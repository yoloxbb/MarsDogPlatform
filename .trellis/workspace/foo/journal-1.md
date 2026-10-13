# Journal - foo (Part 1)

> AI development session journal
> Started: 2026-10-08

---



## Session 1: Merge VisionInteraction into main
<!-- trellis-session: v=2 fp=c038a961e99d023b -->

**Date**: 2026-10-08
**Task**: Merge VisionInteraction into main
**Branch**: `main`

### Summary

Imported all six upstream VisionInteraction commits in sequence, added platform fail-closed handling for visual-only locate responses, and fast-forwarded local main to the integration branch. GitHub push and remote branch deletion remain pending because no HTTPS or SSH credentials are available.

### Main Changes

- Integrated upstream commits 1904258 and c8f73d2 plus four posture recognition fixes.
- Added Action handling and tests for visual-only locate_person_once responses.

### Git Commits

| Hash | Message |
|------|---------|
| `a385880` | refactor: make locate_person_once visual-only |
| `6e35dae` | feat: 上报确认陌生人的姿态事件 |
| `f9978bc` | fix: 优化掩面持续识别与结束判定 |
| `e61a6c8` | fix: 优化抱头触发 |
| `9822a16` | fix: 优化驼背方向与躺卧判定 |
| `a6895d5` | fix: 优化蜷缩姿势识别 |
| `2908109` | integration: adapt platform to visual-only person locate |
| `91bd4cc` | feat: add gitignore config |

### Testing

- [OK] Vision 405 passed, 3 RGA skips; Behavior 538 passed; Emotion 374 passed; Action 462 passed, 31 environment skips.
- [OK] Visual contract and installed Humble Vision mock transport passed; task contract gate unavailable on aarch64 due amd64-only pinned dependencies.

### Status

[OK] **Completed**

### Next Steps

- After GitHub authentication, push main and delete origin/codex/merge-visioninteraction-20261008.


## Session 2: Commit Vision RKNN facial emotion and crop-size gate
<!-- trellis-session: v=2 fp=3745387434618a6c -->

**Date**: 2026-10-09
**Task**: Commit Vision RKNN facial emotion and crop-size gate
**Branch**: `codex/vision-face-emotion`

### Summary

Committed eight-class RKNN face-crop emotion, exact read API, OSD/cache expiration, deployment docs and approved 80px source-crop gate. Source checks pass with explicit environment/hardware limits; related tasks archived locally.

### Main Changes

- Eight-class expression/softmax confidence API and debug OSD with source expiry
- Minimum clipped source crop80px and actual ROS installation refresh guidance

### Git Commits

| Hash | Message |
|------|---------|
| `64dd0102e9ac7599824578b1a48edbb23c19cdda` | feat(vision): integrate eight-class RKNN facial emotion recognition |

### Testing

- [OK] Vision467passed/3explicit RGA skips; platform/visual contracts and current wheel/source/resource probe passed
- [OK] Clean installation gate remains blocked by pre-existing NVIDIA platform mismatch; no model-quality acceptance claimed

### Status

[OK] **Completed**

### Next Steps

- User-controlled board quality/performance validation and ordinary branch review


## Session 3: Vision facial emotion NHWC input optimization
<!-- trellis-session: v=2 fp=444cfc6e0171a36b -->

**Date**: 2026-10-09
**Task**: Vision facial emotion NHWC input optimization
**Branch**: `codex/vision-face-emotion`

### Summary

Pass the selected facial-expression RKNN model contiguous NHWC input to avoid its runtime NCHW-to-NHWC reorder. Keep preprocessing values and result behavior unchanged; update model benchmark, tests, and runbook. Commit 50994c8.

### Main Changes

- Changed selected emotion input from [1,3,224,224] NCHW to [1,224,224,3] NHWC.
- Updated benchmark profile, regression tests, and runbook; kept other model layouts unchanged.

### Git Commits

| Hash | Message |
|------|---------|
| `50994c8` | fix(vision): pass facial emotion input as NHWC |

### Testing

- [OK] Vision: 467 passed, 3 explicit RGA hardware skips; tools/dev.py check passed; diff check passed.

### Status

[OK] **Completed**

### Next Steps

- On RK3588, verify this model no longer emits the NCHW warning and record NPU behavior separately.


## Session 4: 区分人脸表情与 MarsDog 情绪
<!-- trellis-session: v=2 fp=c874f16c8d96a6cd -->

**Date**: 2026-10-10
**Task**: 区分人脸表情与 MarsDog 情绪
**Branch**: `codex/vision-face-emotion`

### Summary

将 Vision 人脸结果统一重命名为 facial_expression，类别字段 expression、概率字段 confidence；保留 MarsDog 自身 emotion 契约，并补充跨层验证与 wheel 旧模块残留检查。

### Main Changes

- 替换人脸 API、视觉事件、消息、配置、后端包、调试界面与文档中的旧情绪命名。
- 增加生产者 facial_expression 字段和 Emotion 消费不变的视觉契约探针；wheel guard 拒绝旧模块路径。

### Git Commits

| Hash | Message |
|------|---------|
| `0355cc7` | refactor(vision): distinguish facial expression from emotion |

### Testing

- [OK] tools/dev.py check 通过；Vision 472 passed，3 个 RGA helper 显式跳过。
- [OK] 视觉契约和状态契约均通过，各 34 场景、0 跳过；状态探针确认 MarsDog 情绪输出不变。
- [OK] uv lock 检查、py_compile、git diff --check、Trellis manifest 校验通过；uv sync 安装门禁两次超时，未宣称通过。

### Status

[OK] **Completed**

### Next Steps

- 完整 uv sync 安装门禁仍未通过，需在具备可用网络/依赖源的环境重试。


## Session 5: Owner facial-expression events
<!-- trellis-session: v=2 fp=7ae3a8886014906b -->

**Date**: 2026-10-10
**Task**: Owner facial-expression events
**Branch**: `codex/vision-face-emotion`

### Summary

Implemented owner happy/sad events with the approved 1 s entry, 0.5 s release, and raw confidence >= 0.70 policy.

### Main Changes

- Added owner-only temporal expression events and merged them with existing pose/hand events.
- Updated Vision config, ROS contract, tester guide, and expression documentation.

### Git Commits

| Hash | Message |
|------|---------|
| `30ca3e5` | feat(vision): trigger owner expression events |

### Testing

- [OK] Vision suite: 509 passed, 3 skipped (RGA helper unavailable); project check passed.
- [OK] Visual contracts: 34 scenarios passed; wheel built, isolated dependency sync timed out after 300 s.

### Status

[OK] **Completed**

### Next Steps

- Retry the isolated locked dependency sync when the environment can complete dependency synchronization.


## Session 6: Add confirmed owner presence visual event
<!-- trellis-session: v=2 fp=1f2c4d85aac5fdb2 -->

**Date**: 2026-10-12
**Task**: Add confirmed owner presence visual event
**Branch**: `codex/vision-face-emotion`

### Summary

Implemented and archived the confirmed-owner visual-direct state event; event routes to owner_greet candidate through existing BehaviorTree arbitration. Action template remains unsupported.

### Main Changes

- Vision emits EVT_VISION_OWNER_PRESENT with distinct-observation ENTER/HOLD/EXIT and 3.0s retrigger cooldown; invalid inference cannot masquerade as owner absence.
- BehaviorTree deduplicates active event instances and validates fresh same-epoch owner target context before L2 arbitration.
- Updated visual-event v1, naming, Vision, Behavior, and Action contract documentation; preserved frozen visual baseline.

### Git Commits

| Hash | Message |
|------|---------|
| `5cb7d7b` | feat(vision): add owner presence visual event |

### Testing

- [OK] tools/dev.py check: PASS (122 platform tests, 13 runtime log tests).
- [OK] Vision: 536 passed, 0 failed, 3 optional RGA skips; Behavior: 555 passed, 0 skipped; Action: 432 passed, 31 dependency skips.
- [OK] check_visual_contracts.py: 34 scenarios PASS, 0 skips; naming: 4 passed; git diff --check PASS.

### Status

[OK] **Completed**

### Next Steps

- No Action template currently implements the combined owner greeting intent; add only after product defines the actual existing Action stages.


## Session 7: Family and stranger presence events
<!-- trellis-session: v=2 fp=ac8e8e21ccb3ca71 -->

**Date**: 2026-10-12
**Task**: Family and stranger presence events
**Branch**: `codex/vision-face-emotion`

### Summary

Implemented Vision family/stranger presence state events and BT candidates; added identity evidence validation, per-enter deduplication, and pre-dispatch revalidation. Added Trellis contracts and task records. Verified tools/dev.py check, Vision 567 passed with 3 explicit RGA parity skips, Behavior 575 passed, visual contract 34 scenarios passed. Action templates remain unimplemented per approved scope; ROS transport tests were not run because the Humble runner was unavailable.

### Main Changes

- Added family and stranger presence events in Vision with active-state tracking and enter/exit/retrigger thresholds.
- Added Behavior routing/candidate mapping with fresh identity/snapshot checks, HOLD deduplication, and pre-dispatch revalidation.
- Recorded local Trellis task archive and implementation contract.

### Git Commits

| Hash | Message |
|------|---------|
| `4ce1a9a` | feat(vision): add family and stranger presence events |

### Testing

- [OK] tools/dev.py check: passed.
- [OK] Vision suite: 567 passed; 3 explicit RGA parity skips.
- [OK] Behavior suite: 575 passed.
- [OK] Visual contract: 34 scenarios passed, 0 skipped; v1 baseline unchanged.
- [OK] ROS transport tests not run; Humble runner unavailable.

### Status

[OK] **Completed**


## Session 8: Add pet-attention bend and squat postures
<!-- trellis-session: v=2 fp=3957c523ee652276 -->

**Date**: 2026-10-13
**Task**: Add pet-attention bend and squat postures
**Branch**: `codex/vision-face-emotion`

### Summary

Added temporally stabilized bend_over and squat_down GesturePose actions with keypoint scoring, conflict handling, public pose fields, no event mapping, regression coverage, and Vision contract guidance.

### Main Changes

- Added signed torso-lean scoring for bend_over; knee-bracing is optional support.
- Added lowered-hip and knee-flexion scoring for half/deep squat_down with chair-sit and mild-flexion boundaries.
- Added rolling 10-update posture smoothing, posture-history conflict clearing, exact public labels, and no-derived-event contract tests.

### Git Commits

| Hash | Message |
|------|---------|
| `0595dd2` | feat(vision): detect pet-attention bend and squat postures |

### Testing

- [OK] python3 tools/dev.py check: pass; 122 platform + 13 observability/runtime tests.
- [OK] python3 tools/dev.py test vision: 585 passed, 3 skipped (RGA parity helper unavailable), 0 failures.
- [OK] python3 tools/check_visual_contracts.py: 34 scenarios passed, 0 skipped.
- [OK] git diff --check: pass.

### Status

[OK] **Completed**

### Next Steps

- No follow-up work remains for this feature; existing Bootstrap Guidelines task remains active.


## Session 9: Owner bend squat visual event
<!-- trellis-session: v=2 fp=3aac011b5562dbcf -->

**Date**: 2026-10-13
**Task**: Owner bend squat visual event
**Branch**: `codex/vision-face-emotion`

### Summary

Implemented owner-only bend/squat visual event with distinct-observation entry stability, posture-release rearming, validity and epoch safeguards, BehaviorTree/L2 candidate mapping, contract coverage, and Vision/Behavior/application documentation. Verified dev check, Vision and Behavior suites, and visual contract checks; no real ROS transport was run.

### Git Commits

| Hash | Message |
|------|---------|
| `cd57886` | feat(vision): add owner bend squat interaction event |

### Status

[OK] **Completed**
