"""Real CPU runtime smoke for supplied face/MediaPipe assets, without cameras or ROS."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import numpy as np

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"status": "FAIL", "device": "cpu", "cases": [],
              "scope": "Face detection/features and MediaPipe runtime smoke; no identity accuracy, gesture semantics, RKNN parity, camera or ROS acceptance"}
    try:
        import cv2
        import mediapipe as mp
        import ultralytics
        from mediapipe.tasks.python import vision
        from marsdog_vision_interaction.providers.face_backends.factory import create_face_detector, create_face_recognizer
        models = args.assets / "archive/models/vision"
        # Visually checked before inference: two visible faces, upper bodies and a hand.
        fixture = Path(ultralytics.__file__).parent / "assets/zidane.jpg"
        report["fixture"] = {"path": str(fixture), "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
                             "annotation": "At least one face and person; independently visually inspected"}
        frame = cv2.imread(str(fixture))
        detector = create_face_detector(models / "face_detection_yunet_2023mar.onnx",
                                         input_size=(frame.shape[1], frame.shape[0]))
        recognizer = None
        try:
            _, faces = detector.detect(frame)
            if faces is None or len(faces) < 1:
                raise RuntimeError("Known face fixture produced no face")
            recognizer = create_face_recognizer(models / "face_recognition_sface_2021dec.onnx")
            feature = recognizer.feature(recognizer.alignCrop(frame, faces[0]))
            if feature.size != 128 or not np.isfinite(feature).all() or np.linalg.norm(feature) <= 0:
                raise RuntimeError("SFace feature contract failed")
            report["cases"].append({"id": "yunet-sface", "status": "PASS", "faces": len(faces), "feature_values": int(feature.size)})
        finally:
            detector.close()
            if recognizer is not None:
                recognizer.close()
        rgb = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        pose_fixture = Path(ultralytics.__file__).parent / "assets/bus.jpg"
        report["pose_fixture"] = {"path": str(pose_fixture), "sha256": hashlib.sha256(pose_fixture.read_bytes()).hexdigest(),
                                  "annotation": "Visually inspected full standing people; at least one pose expected"}
        pose_rgb = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(cv2.imread(str(pose_fixture)), cv2.COLOR_BGR2RGB))
        for name in ("pose_landmarker_lite.task", "pose_landmarker_full.task"):
            options = vision.PoseLandmarkerOptions(base_options=mp.tasks.BaseOptions(
                model_asset_path=str(models / name), delegate=mp.tasks.BaseOptions.Delegate.CPU),
                running_mode=vision.RunningMode.IMAGE)
            with vision.PoseLandmarker.create_from_options(options) as landmarker:
                result = landmarker.detect(pose_rgb)
                if not result.pose_landmarks or any(len(points) != 33 for points in result.pose_landmarks):
                    raise RuntimeError("Expected at least one 33-landmark pose")
                report["cases"].append({"id": name, "status": "PASS", "poses": len(result.pose_landmarks)})
        options = vision.HandLandmarkerOptions(base_options=mp.tasks.BaseOptions(
            model_asset_path=str(models / "hand_landmarker.task"), delegate=mp.tasks.BaseOptions.Delegate.CPU),
            running_mode=vision.RunningMode.IMAGE)
        with vision.HandLandmarker.create_from_options(options) as landmarker:
            result = landmarker.detect(rgb)
            if any(len(points) != 21 for points in result.hand_landmarks):
                raise RuntimeError("Hand landmark shape mismatch")
            blank = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.zeros((256, 256, 3), np.uint8))
            negative = landmarker.detect(blank)
            if negative.hand_landmarks:
                raise RuntimeError("Blank frame yielded hand landmarks")
            report["cases"].append({"id": "hand_landmarker.task", "status": "PASS",
                                    "hands_in_photo": len(result.hand_landmarks),
                                    "assertion": "Runtime/shape and blank-negative; positive hand recall not asserted"})
        report.update(status="PASS", versions={k: importlib.metadata.version(k) for k in ("opencv-contrib-python", "mediapipe", "numpy", "ultralytics")})
    except Exception as exc:
        report["error"] = str(exc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["status"] == "PASS" else 1

if __name__ == "__main__":
    raise SystemExit(main())
