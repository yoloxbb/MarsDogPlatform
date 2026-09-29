"""Offline CPU object replay using the maintained ObjectDetectorProvider."""
from __future__ import annotations
import argparse
import importlib.metadata
import json
import math
import os
from pathlib import Path
import time


def evaluate(objects: list[dict], sample: dict) -> list[str]:
    errors = []
    for obj in objects:
        for key in ("x", "y", "w", "h", "confidence", "center_x", "center_y"):
            value = obj.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                errors.append("Invalid normalized detection field: " + key)
        if obj.get("w", 0) <= 0 or obj.get("h", 0) <= 0:
            errors.append("Empty detection box")
    labels = {str(obj.get("label", "")).casefold() for obj in objects}
    if sample["expected_empty"]:
        if objects:
            errors.append("Expected no objects")
    else:
        missing = [label for label in sample["expected_labels"] if label.casefold() not in labels]
        if missing:
            errors.append("Missing expected labels: " + ", ".join(missing))
    return errors


def replay(request: dict) -> dict:
    # Set before importing Ultralytics/Torch. Local model files only; no auto-install.
    os.environ.update(CUDA_VISIBLE_DEVICES="", YOLO_AUTOINSTALL="false", YOLO_OFFLINE="true")
    import cv2
    from marsdog_vision_interaction.providers.object_detector import ObjectDetectorProvider
    model = Path(request["model"])
    if not model.is_file() or model.suffix.lower() not in (".onnx", ".pt"):
        raise ValueError("A local CPU-compatible YOLOE .pt or .onnx model is required")
    settings = request["settings"]
    provider = ObjectDetectorProvider({
        "object_model": str(model), "device": "cpu", "mock_mode": False,
        "image_size": settings["image_size"], "det_threshold": settings["confidence"],
        "nms_threshold": settings["iou"], "max_detections": settings["max_detections"],
    })
    cases = []
    try:
        provider.start()
        if not provider.is_available():
            raise RuntimeError(provider.last_error or "Object detector unavailable")
        for sample in request["samples"]:
            path = Path(sample["image"])
            if path.stat().st_size > 20 * 1024 * 1024:
                raise ValueError("Image exceeds 20 MiB")
            frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if frame is None or not frame.size:
                raise ValueError("Cannot decode image: " + str(path))
            started = time.perf_counter()
            objects = provider.detect_objects(frame)
            if provider.last_error or not provider.is_available():
                raise RuntimeError(provider.last_error or "Object detector became unavailable")
            errors = evaluate(objects, sample)
            cases.append({"id": sample["id"], "status": "FAIL" if errors else "PASS",
                          "objects": objects, "errors": errors,
                          "elapsed_ms": round((time.perf_counter()-started)*1000, 3)})
    finally:
        provider.stop()
    return {"status": "PASS" if cases and all(c["status"] == "PASS" for c in cases) else "FAIL",
            "device": "cpu", "real_model_inference": bool(cases), "cases": cases,
            "module_file": __file__,
            "versions": {k: importlib.metadata.version(k) for k in ("ultralytics", "torch", "numpy", "opencv-contrib-python")},
            "scope": "YOLOE object detection and normalized boxes; no face/pose/hand/ROS/hardware acceptance"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = replay(json.loads(args.request.read_text()))
    except Exception as exc:
        report = {"status": "FAIL", "device": "cpu", "real_model_inference": False, "cases": [], "error": str(exc)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
