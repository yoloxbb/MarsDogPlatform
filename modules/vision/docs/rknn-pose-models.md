# YOLOv8 Pose RKNN

The production `config/vision.yaml` selects
`yolov8n-pose-fp16.rknn` through `pose_model_variant: rknn`. The verified
profile is `yolov8n_pose_fp16` with SHA-256
`74e0a714e3565c491b724787f7419b343d4e1451e56a8103c5b524c482fc1ce2`.
The graph accepts a 640 square RGB uint8 NHWC tensor with the RKNN runtime
normalization and returns one `(1,56,8400)` output tensor.

Pose results on this path use native COCO 0–16 IDs and carry
`keypoint_format: coco_17`. MediaPipe `.task` variants remain selectable with
`pose_model_variant:=lite` or `pose_model_variant:=full` and publish
`mediapipe_33` IDs. A failed RKNN load or inference marks pose unavailable and
does not silently start a CPU fallback; face and hand processing continue.

Run a board smoke check with a still image or representative clip:

```bash
uv run python tools/check_pose_rknn.py /path/to/frame.jpg
uv run python tools/check_pose_rknn.py --video /path/to/clip.mp4
```

The still-image report verifies load, output decoding, NMS, source-frame
geometry and timing. Motion accuracy requires representative video.
