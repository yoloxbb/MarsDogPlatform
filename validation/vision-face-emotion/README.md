# Vision facial emotion software validation — 2026-10-08 / 2026-10-09

The feature integrates the existing `enet_b0_8_va_mtl` RKNN artifact into current
face crops. Successful `GET /api/v1/faces/emotion` responses contain exactly
`emotion` and `intensity`; all eight expression classes participate in softmax,
while valence/arousal do not. Source aging and per-face association apply to API,
optional visual metadata, dashboard JSON, and cached MJPEG emotion overlays.

The implementation and independent review are scoped to Vision. Robot emotion
state, needs settlement, existing required ROS contracts and behavior policy
remain unchanged. Deployment/API/rollback details are in
[the model guide](../../modules/vision/docs/rknn-emotion-models.md).

## Software checks

| Check | Result | Evidence / scope |
| --- | --- | --- |
| `python3 tools/dev.py check` | PASS | Architecture and identifiers: no new errors; 122 platform tool and 13 observability tests pass. Existing identifier gaps remain documented. |
| `python3 tools/dev.py test vision` | 467 passed, 3 skipped, 0 failed | 470 collected; report `out/dev/vision/result.json`, JUnit and log alongside it. Isolated CPU/fake-model unit tests on existing Humble host, localhost domain 208. |
| `python3 tools/check_visual_contracts.py` | PASS | 8 Vision observations and 34 downstream scenarios per consumer; frozen baseline preserved, no skips. |
| `uv lock --project modules/vision --check --offline` | PASS | Only Pillow direct-dependency metadata added at the already locked 12.3.0 version; no runtime/dependency version upgrades. |
| Python compilation and `git diff --check` | PASS | Changed module sources compile; no whitespace errors. No separate configured static type checker. |
| Extracted dashboard JavaScript, `node --check` | PASS | JavaScript syntax only; does not establish browser/camera acceptance. |
| Current wheel build and supplemental import/resource probe | PASS | Offline wheel build; all 61 packaged Python files match current sources, config/dashboard resources match, imported from extracted wheel using existing Vision dependencies. Eight-class decoder and exact OpenAPI success schema verified. Report `out/vision-face-emotion/wheel-import-probe.json`. No model weights included. |

New regressions cover benchmark preprocessing parity, all class winners,
auxiliary exclusion, malformed output/hash/runtime failure, clipped face crops,
unknown identities, multi-face/default/explicit selection, source expiration,
failed frames, retained target association, shutdown/repeated startup,
HTTP/OpenAPI contracts, OSD labels, cached JSON deadlines and actual isolated
localhost MJPEG fallback when camera input stops. The stream fallback uses the
same source frame without expression fields; render/encode time does not extend
its deadline. Additional rendering cost is documented in the model guide.

The three skipped cases are existing RGA image-parity tests requiring explicit
`MARSDOG_HAND_RGA_TEST_LIBRARY`. They are not counted as passes.

## Installation gate: blocked, not passed

`python3 tools/check_vision_install.py --uv uv` first timed out while syncing the
disposable dependency environment. An offline retry built and installed the
wheel and completed locked dependency sync, but `uv pip check` rejected
`nvidia-cusparselt-cu13` as built for a different platform on this aarch64 host.
That Torch dependency is already present in the baseline lock and source
Virtualenv; this feature does not change it. Reports are preserved separately:
`out/vision-install/result.json` and `out/vision-install-offline/result.json`, with
command logs in those directories. The supplemental wheel probe above verifies
this feature's packaging/imports and does not substitute for this failed clean
installation gate. No Torch/CUDA/ROS/runtime upgrades were made to bypass it.

## Hardware and transport acceptance

During the initial software validation, no new camera, RKNN/NPU, expression-quality,
motion-hardware, or real ROS transport trial was performed. Unit/contract checks and localhost HTTP tests are distinct
from real DDS transport acceptance. The user's earlier benchmark result is a
prerequisite report, not evidence that this new runtime integration is accepted
on hardware. Follow the separate board-trial procedure in the model guide and
record model hash/runtime, API/OSD association, face loss/failure, performance and
accuracy separately. Viewer lifetime starts on receipt; network/scheduling
latency is not measured and no cross-host clock synchronization is introduced.

## Follow-up: actual debug installation refresh

The user reported no expressions after restarting the existing debug command.
The selected live prefix was `modules/vision/install/marsdog_vision_interaction`;
its installed YAML lacked `face_emotion` and installed backend/web copies were
old. Source-cwd Python imports could still expose the new API/UI, so the precise
runtime gap was mixed new source and old installed configuration (API503).
Isolated wheel/ROS checks under `out/` did not refresh that user's install.

The owning package was rebuilt in place with the existing CMake copy-install
mode; no generated directory, source repository, model or user data was removed.
After the October8 rebuild, backend/API/OSD/config/dashboard installation hashes
matched the then-current source:
`out/vision-face-emotion/live-install-parity.json`. Only the user's vision debug
launch was restarted; the existing webcam process remained running. Startup
instructions now name the owning module prefix and distinguish Python import
origin from selected share/config paths.

This follow-up is live operational diagnosis requested by the user, not an
automated test on hardware or a production ROS domain. The newly running RKNN
model initialized with runtime2.3.2/driver0.9.8, and successful expression-inference
stages were recorded. Read-only API/web sampling now returns404 for no current
fresh face, rather than the earlier capability-unavailable503; webcam input is
about30fps and sampled face arrays are empty. These observations establish
startup/config integration, not expression accuracy, complete end-to-end OSD
acceptance, or a formal real-DDS/board-performance acceptance report. Runtime
logs and sampled readback are in `out/vision-face-emotion/live-debug/`.

## 2026-10-09: minimum source-crop dimensions

The completed child task adds `face_emotion.min_face_size_px` (default and
production value80). Both dimensions of the clipped source-frame face crop must
meet that threshold before224×224 preprocessing and model inference. Smaller
faces retain identity/detection results and omit facial-expression data; no
class mapping, confidence, event policy, or robot emotion semantics change.
Invalid thresholds are rejected as non-positive/non-integer configuration.

The reviewed child validation is59 expression tests passed and full Vision
467 passed /3 explicit RGA skips /0 failures (470 collected). Platform checks
and whitespace checks passed. This records software checks only, not new
camera/model-quality acceptance. Original October8 runtime-inspection evidence
and installation-gate limitations above remain unchanged. The current feature
and this gate are submitted together because their implementation/docs/tests
share the same formerly uncommitted files.

The October9 combined feature/gate wheel was rebuilt and its source/config/web
parity and import/schema probe passed. The October8 live install/readback above
is historical pre-gate evidence; this commit step does not redeploy or restart
the user's live Vision session.
