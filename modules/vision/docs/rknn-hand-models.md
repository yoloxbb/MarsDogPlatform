# RKNN hand models

The hand observation backend is selected by `hand_landmark_model` suffix. A
`.task` path uses the MediaPipe Tasks adapter as an explicit rollback. A
`.rknn` landmark path requires `hand_detect_model` with a `.rknn` suffix and
uses the shared palm decoder, ROI geometry, tracking and landmark projection.
An unknown suffix is rejected and the backend never silently changes to CPU.

The currently verified FP16 pair is:

| Role | File | SHA-256 |
| --- | --- | --- |
| Palm detector | `hand_detector_fp16.rknn` | `588b2b3749a864766de23caccd12b979305158dad8ea836098529c3f1874c373` |
| Landmarks | `hand_landmarks_detector_fp16.rknn` | `9c973f44a100ebdd9aacbe54e7495fe046b2e94fe900f296d3c7a50189a0e7c4` |

The detector accepts RGB `uint8` NHWC at 192 square and the landmark graph
accepts RGB `uint8` NHWC at 224 square. CPU preprocessing uses OpenCV for the
centered letterbox and color conversion. RGA preprocessing can be selected by
`hand_rknn.preprocessing: rga`; it uses the optional synchronous virtual
address helper, preserves selected-view row strides and reports failures
instead of falling back while claiming RGA. `cpu` remains the explicit
comparison and rollback mode.

Example RKNN configuration:

```yaml
hand_detect_model: ${MARSDOG_VISION_MODEL_DIR}/hand_detector_fp16.rknn
hand_landmark_model: ${MARSDOG_VISION_MODEL_DIR}/hand_landmarks_detector_fp16.rknn
hand_rknn:
  profile: hand_fp16
  preprocessing: rga  # cpu remains the explicit comparison/rollback mode
  detection_interval: 5
  score_threshold: 0.30
  presence_threshold: 0.50
  core_mask: auto
```

The provider keeps at most two hands. Palm detections are decoded to top-left
`xywh`, merged with weighted NMS, and mapped through the exact resize padding.
The landmark ROI is sampled on CPU because it may be rotated; its coordinates
are projected to normalized source-view x/y and MediaPipe-compatible z. A
video call tracks valid ROIs and searches again at the configured interval or
immediately after presence loss. Image mode starts a fresh detection for each
call.

The standalone checker uses the production backend:

```bash
PYTHONPATH=. python tools/check_hand_rknn.py /tmp/woman_hands.jpg \
  --frames 30 --warmup 10 --preprocessing cpu \
  --report /tmp/hand-rknn-business.json
PYTHONPATH=. python tools/check_hand_rknn.py --video /tmp/hand-synthetic-motion.avi \
  --frames 90 --warmup 5 --report /tmp/hand-rknn-video.json
```

Repeated still frames provide a static smoke and warmed timing sample. The
synthetic motion clip checks loss and re-entry scheduling but is not a gesture
accuracy result. On the measured still-frame Provider workload, RKNN CPU
preprocessing was 112.20/138.58 ms median/P95 and RKNN RGA was 113.37/154.54
ms. This does not establish an RGA speedup; keep CPU preprocessing as the
explicit comparison/rollback mode and remeasure on the target camera workload.
