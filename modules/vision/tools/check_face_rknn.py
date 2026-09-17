"""Manual RK3588 parity/stability check; never modifies enrolled images.

Run from the project root with the project interpreter. The report contains
metrics and image basenames only, never images or face embeddings.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time

import cv2
import numpy as np

# Permit `python tools/check_face_rknn.py` from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from marsdog_vision_interaction.providers.face_backends import (
    create_face_detector,
    create_face_recognizer,
)
from marsdog_vision_interaction.utils.config_loader import load_config


def cosine(a, b):
    a, b = a.ravel().astype(np.float64), b.ravel().astype(np.float64)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def fit(image, width, height):
    h, w = image.shape[:2]
    scale = min(width / w, height / h)
    rw, rh = round(w * scale), round(h * scale)
    result = np.zeros((height, width, 3), np.uint8)
    result[:rh, :rw] = cv2.resize(image, (rw, rh))
    return result


def iou(a, b):
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[0]+a[2], b[0]+b[2]), min(a[1]+a[3], b[1]+b[3])
    intersection = max(0, right-left) * max(0, bottom-top)
    return float(intersection / max(1e-8, a[2]*a[3]+b[2]*b[3]-intersection))


def measure(operation, iterations):
    operation()  # warm up
    elapsed = []
    for _ in range(iterations):
        start = time.perf_counter()
        operation()
        elapsed.append((time.perf_counter()-start)*1000)
    return {'iterations': iterations, 'mean_ms': float(np.mean(elapsed)),
            'p95_ms': float(np.percentile(elapsed, 95)), 'max_ms': max(elapsed)}


def pipeline_smoke(config, model_dir, image, iterations):
    """Run actual observation provider while YOLOE executes on another thread."""
    from marsdog_vision_interaction.providers.object_detector import ObjectDetectorProvider
    from marsdog_vision_interaction.providers.vision_observation import VisionObservationProvider

    vc = dict(config['providers']['vision']['config'])
    vc.update(face_detect_model=str(model_dir/'face_detection_yunet_2023mar_fp16.rknn'),
              face_recogn_model=str(model_dir/'face_recognition_sface_2021dec_fp16.rknn'))
    vision = VisionObservationProvider(vc)
    objects = ObjectDetectorProvider(config['providers']['object']['config'])
    frame = fit(image, 640, 480)
    try:
        vision.start()
        objects.start()
        assert vision.available and all(s['ready'] for s in vision.face_model_status.values())
        assert vision._pose_landmarker is not None and vision._hand_landmarker is not None
        vision.sync_enrolled_to_throttle()
        # Serialize all direct calls with the existing observation/model lock.
        def run_vision():
            observation = vision.run_inference_exclusive(lambda: vision._process_frame_impl(frame))
            assert observation['faces'], 'Face disappeared during pipeline smoke'
        def run_objects():
            objects.detect_objects(frame)
            assert not objects.last_error, objects.last_error
        run_vision()
        run_objects()
        with ThreadPoolExecutor(max_workers=2) as executor:
            object_future = executor.submit(measure, run_objects, iterations)
            vision_future = executor.submit(measure, run_vision, iterations)
            return {'vision': vision_future.result(), 'yoloe': object_future.result(),
                    'face_models': vision.face_model_status.copy(),
                    'note': 'Repeated still frame, object inference unthrottled; not a live camera or soak test.'}
    finally:
        vision.stop()
        objects.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path('config/vision.yaml'))
    parser.add_argument('--model-dir', type=Path)
    parser.add_argument('--images', type=Path, default=Path('data/faces'))
    parser.add_argument('--iterations', type=int, default=50)
    parser.add_argument('--with-pipeline', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error('--iterations must be positive')
    config = load_config(args.config)
    md = args.model_dir or Path(config['providers']['vision']['config']['face_detect_model']).parent
    paths = sorted(args.images.rglob('*.jpg')) if args.images.is_dir() else [args.images]
    assert paths, 'No test images found'
    report = {'opencv': cv2.__version__, 'samples': [], 'failures': []}
    resources = []
    try:
        for factory, filename in [
            (create_face_detector, 'face_detection_yunet_2023mar.onnx'),
            (create_face_detector, 'face_detection_yunet_2023mar_fp16.rknn'),
            (create_face_recognizer, 'face_recognition_sface_2021dec.onnx'),
            (create_face_recognizer, 'face_recognition_sface_2021dec_fp16.rknn'),
        ]:
            resources.append(factory(str(md/filename)))
        od, rd, oc, rc = resources
        features = []
        for index, path in enumerate(paths):
            source = cv2.imread(str(path))
            assert source is not None, f'Cannot read {path}'
            # Native camera dimensions; reference receives the same zero padding.
            frame = fit(source, 640, 480)
            canvas = np.zeros((640, 640, 3), np.uint8)
            canvas[:480] = frame
            od.setInputSize((640, 640))
            rd.setInputSize((640, 480))
            _, onnx_faces = od.detect(canvas)
            _, rknn_faces = rd.detect(frame)
            assert onnx_faces is not None and rknn_faces is not None, f'No face in sample {index}'
            a = max(onnx_faces, key=lambda row: row[2]*row[3])
            b = max(rknn_faces, key=lambda row: row[2]*row[3])
            # RKNN's public contract clips boxes to the original source area;
            # native FaceDetectorYN may retain negative / padded coordinates.
            # Compare the same valid image region, retaining the raw IoU too.
            bounded_a = a.copy()
            x1, y1 = np.clip(a[:2], [0, 0], [640, 480])
            x2, y2 = np.clip(a[:2]+a[2:4], [0, 0], [640, 480])
            bounded_a[:4] = (x1, y1, x2-x1, y2-y1)
            aligned = oc.alignCrop(frame, a)
            rknn_aligned = rc.alignCrop(frame, a)
            af, bf = oc.feature(aligned), rc.feature(aligned)
            end_to_end = rc.feature(rc.alignCrop(frame, b))
            direct_af, direct_bf = oc.feature(source), rc.feature(source)
            features.append((index, direct_af, direct_bf))
            sample = {
                'sample': index, 'onnx_faces': len(onnx_faces), 'rknn_faces': len(rknn_faces),
                'box_iou': iou(bounded_a, b), 'raw_box_iou': iou(a, b),
                'score_delta': abs(float(a[-1]-b[-1])),
                'landmark_max_error_px': float(np.max(np.abs(a[4:14]-b[4:14]))),
                'alignment_pixel_max_delta': int(np.max(np.abs(aligned.astype(int)-rknn_aligned.astype(int)))),
                'sface_same_crop_cosine': cosine(af, bf),
                'sface_saved_crop_cosine': cosine(direct_af, direct_bf),
                'sface_end_to_end_cosine': cosine(af, end_to_end),
            }
            report['samples'].append(sample)
            # Engineering parity checks, not recognition accuracy acceptance.
            if (sample['box_iou'] < .95 or sample['score_delta'] > .02
                    or sample['landmark_max_error_px'] > 3
                    or sample['sface_same_crop_cosine'] < .999
                    or sample['sface_saved_crop_cosine'] < .999
                    or sample['alignment_pixel_max_delta'] > 1):
                report['failures'].append(f'Parity failed for sample {index}')
        report['pairwise'] = [
            {'samples': [i, j], 'onnx_cosine': cosine(a, c), 'rknn_cosine': cosine(b, d)}
            for pos, (i, a, b) in enumerate(features)
            for j, c, d in features[pos+1:]
        ]
        report['timing'] = {
            'onnx_yunet': measure(lambda: od.detect(canvas), args.iterations),
            'rknn_yunet': measure(lambda: rd.detect(frame), args.iterations),
            'onnx_sface': measure(lambda: oc.feature(aligned), args.iterations),
            'rknn_sface': measure(lambda: rc.feature(aligned), args.iterations),
        }
        rd.setInputSize((640, 480))
        _, blank_faces = rd.detect(np.zeros((480, 640, 3), np.uint8))
        assert blank_faces is None or len(blank_faces) == 0
    finally:
        for resource in resources:
            resource.close()
    if args.with_pipeline:
        report['pipeline'] = pipeline_smoke(config, md, source, args.iterations)
    report['passed'] = not report['failures']
    output = json.dumps(report, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output+'\n')
    print(output)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
