# RK3588 facial expressions

Vision analyzes each current detected face crop, including unknown identities,
with EmotiEffLib `enet_b0_8_va_mtl`. This is human expression evidence; it does
not update robot `/emotion/state`, needs settlement, stranger policy or actions.

The real observation configuration enables `providers.vision.config.face_emotion`:

```yaml
face_emotion:
  enabled: true
  min_face_size_px: 80
  model: ${MARSDOG_VISION_MODEL_DIR}/emotion/enet_b0_8_va_mtl_rk3588_fp.rknn
  profile: enet_b0_8_va_mtl
  core_mask: auto
  max_age_sec: 0.5
```

Configurations without this block default to disabled. Mock and object-only
profiles do not load this model. Disable the block to restore previous inference
work. The external model is not included in the wheel or source delivery. Its
reviewed SHA-256 is
`e260bee2a207a14256db37d5b313bfa46d1f3fc344818ca3108a7d6fffcfd4f0`;
unreviewed assets/profiles fail closed. Paths follow the existing Vision model
root; see the platform `config/models/README.md`.

Before expression inference, Vision clips each detected face box to the source
frame and checks its pixel width and height. Both dimensions must be at least
`min_face_size_px` (80 px by default); smaller crops keep their face detection
and identity data but are omitted from expression inference and output. This is
checked before resizing the crop to 224×224, so the threshold measures source
image detail and does not estimate physical distance.

Preprocessing matches `tools/benchmark_emotion_rknn.py`: clipped BGR uint8 face
ROI, RGB, Pillow bilinear 224×224, float32/255, ImageNet mean
[0.485,0.456,0.406] and std [0.229,0.224,0.225], contiguous NHWC
[1,224,224,3]. The selected model expects NHWC, so the input is passed in that
layout, avoiding the previous NCHW-to-NHWC reorder. Other benchmark profiles
retain their own declared layouts. RKNN returns one finite floating-point
[1,10] tensor. Only its first eight logits participate in a stable softmax, in order:
`angry / contempt / disgust / fear / happy / neutral / sad / surprise`.
Valence/arousal are ignored. Intensity is the winning class's original eight-way
probability, without class grouping, thresholding or further renormalization;
it is confidence, not psychological strength.

## Build and select the current ROS installation

After source/config/dashboard changes, stop the old Vision launch and rebuild
only the owning package from the main repository's `modules/vision` directory.
The locked module environment must already be prepared with
`python3 tools/dev.py setup vision` from the platform root. In a new terminal:

```bash
cd /absolute/path/to/MarsDogPlatform/modules/vision
source /opt/ros/humble/setup.bash
colcon build --base-paths . --packages-select marsdog_vision_interaction
source install/local_setup.bash
ros2 pkg prefix marsdog_vision_interaction
ros2 launch marsdog_vision_interaction vision_debug.launch.py web_host:=0.0.0.0
```

The prefix must be this checkout's
`modules/vision/install/marsdog_vision_interaction`. This package's CMake
`install(DIRECTORY ...)` rules install Python, YAML and dashboard resources;
`--symlink-install` does not guarantee that every installed resource tracks
source edits. Keep the existing install mode when refreshing code. A restart
or another `source` does not update old copied files.
Rebuild the actual selected install, source it, then restart. A successful wheel
check or an isolated ROS test build under `out/` also does not refresh this live
ROS installation. Original repositories and other modules are not rebuilt by
these commands.

Before launching, these read-only checks distinguish a stale installation from
an unavailable expression model; they do not execute RKNN inference:

```bash
ros2 pkg prefix --share marsdog_vision_interaction
VISION_RUNTIME_PYTHON="$PWD/.venv/bin/python"
(
  cd /tmp
  "$VISION_RUNTIME_PYTHON" -c 'import marsdog_vision_interaction.providers.emotion_backends as backend; print(backend.__file__)'
)
```

Run the import check outside the source directory so that Python does not
select the checkout merely because it is the current directory. It uses the
already prepared module environment and sourced ROS overlay without changing
the node's interpreter settings. This checks the installed copy specifically:
the installed entrypoints may re-execute `python -m`, whose import selection also
depends on the launch working directory and `PYTHONPATH`. A launch from the
source directory can therefore run new Python code with an old default YAML
from the selected ROS share directory. The printed backend path must belong to the
same selected Vision install, and its `share/marsdog_vision_interaction/config/vision.yaml` must contain the enabled
`face_emotion` block above. If a custom `config_path` is supplied, inspect that
file instead. Once the current package is running, query
`http://127.0.0.1:8092/api/v1/faces/emotion`: HTTP 404 means no fresh selected
result, while HTTP 503 means the capability is unavailable. A stale Face API
without the new route can also return HTTP 404; verify the installed backend
and configuration first.

## Read API and debug display

`GET /api/v1/faces/emotion` on the existing Face API port (8092) returns exactly:

```json
{"emotion":"happy","intensity":0.85}
```

Without a query, choose the current active face if it has same-frame matching
face evidence; otherwise choose a single current detected face. Use
`?track_id=2` to select a current nonnegative face track ID. Unknown identities
are eligible. Untracked faces can be read as a single default face; multiple
untracked faces cannot be selected reliably by track ID.

| Condition | HTTP status |
| --- | --- |
| Fresh selected face with valid expression | 200 |
| No face, absent track, missing result, or expired source | 404 |
| Multiple faces without active selection | 409 |
| Invalid track query | 422 |
| Disabled/unavailable model/provider | 503 |

Errors follow the existing `detail`/`request_id` API convention. HTTP performs
no inference and starts no task/session. Existing face sample CRUD is unchanged.

Visual schema v1 has additive optional `facial_emotion: {emotion, intensity}`
on `faces` and `debug_faces`. Invalid/unavailable/expired expression fields are
omitted. Shared OSD shows the canonical category and probability beside its
face; the dashboard face table shows the same evidence. Optional event metadata
`facial_emotion_valid_for_sec` carries remaining source lifetime to the viewer.
Repeated publications of the same image (epoch/header stamp/frame ID) keep the
earliest local expiry, independently of publication sequence; both OSD and web
JSON age cached expressions. Viewer aging starts on local receipt; it does not
measure network transport delay or synchronize clocks across hosts.

When an OSD frame contains expression evidence, the viewer also renders and
encodes the same source frame with only expression fields removed. The MJPEG
cache switches once to this fallback at the original local expiry, including
when camera messages stop; a no-expression visual packet invalidates it early.
Rendering/encoding time is subtracted from the lifetime. This adds one overlay
render and JPEG encode per expression-bearing web frame; frames without
expression metadata keep the existing cost. The stream waits until the expiry
or its existing one-second wake interval, whichever is earlier. Scheduling and
HTTP delivery may add latency; this is not a hard real-time deadline.

The worker records monotonic frame receipt, not cache publication/read time.
Fresh camera traffic cannot revive old inference evidence. No-face/failed
frames, mismatched tracks, model failures, disabled face tasks and stop suppress
old results. A runtime failure disables expression work until provider restart
while keeping existing face/pose/hand capabilities operational. Model release
waits for the existing inference worker to stop.

## Validation limits and board trial

Synthetic/fake tests verify benchmark parity, eight-class decoding, associations,
API errors, source aging, debug rendering and shutdown. They do not establish
NPU performance or expression accuracy. For a board trial, record the model hash,
RKNN runtime library/version, provider status/logged
`facial_emotion_inference` timings, current and explicit-track API responses,
OSD association, face loss/failure/expiry behavior and end-to-end latency. Keep
hardware/quality evidence separate from software and ROS transport reports.
