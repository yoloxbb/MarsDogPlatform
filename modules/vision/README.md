# MarsDog Vision Interaction

> 项目交接请先阅读 [docs/HANDOFF.md](docs/HANDOFF.md)。四项目总览、统一接口清单
> 和联调手册位于 [docs/integration/README.md](docs/integration/README.md)。测试工程师请
> 使用 [视觉测试工程师验收说明](docs/TEST_ENGINEER_GUIDE.md)，其中包含逐模块测试表、
> 日志字段、通过标准和证据模板。

独立的 MarsDog 视觉交互 Python/ROS2 项目，负责相机、视觉推理、人脸注册和
`/perception/visual_event`。本项目不导入语音项目，也不维护 VAD、声纹或语音会话状态。

## 环境

- Python 3.10
- uv
- ROS2 Humble

### Fast DDS 项目配置

项目使用 [config/fastdds.xml](config/fastdds.xml) 作为所有 ROS2 参与者的统一传输
配置。本项目的 `vision.launch.py` 和 `vision_debug.launch.py` 会自动为其子进程加载
该配置；独立启动 RealSense 或 `camera_driver` 前，先在对应终端执行：

```bash
source scripts/fastdds_env.sh
```

如果需要替换配置，可设置 `MARSDOG_FASTDDS_PROFILE` 后再 source。配置使用本机 SHM
传输的 8MiB 单条消息上限；Humble 自带 Fast DDS 2.6.x 的 UDP 上限为 65500 bytes，
跨主机 UDP 会使用 RTPS 分片。这里只配置传输层，不打开
`RMW_FASTRTPS_USE_QOS_FROM_XML`。

`rknn-toolkit-lite2` 只在 Linux AArch64（RK3588）环境安装；其他平台仍可安装、
运行单元测试和 Mock 联调，但不能执行 RKNN 模型。

模型目录按以下顺序解析：`MARSDOG_VISION_MODEL_DIR` 环境变量、仓库内
`models/vision`、仓库同级的 `models/vision`。因此既可以让单项目自包含，也可以
让多个项目共享一份大模型而不写死开发机目录。运行数据默认写入仓库内 `data`，
可通过 `MARSDOG_VISION_DATA_DIR` 覆盖。
人脸注册表和人脸样本是运行时生成的生物识别数据，仅保存在本机 `data/`
目录，不进入 Git，也不打进源码发布包；新设备需单独完成人脸注册或安全迁移数据。

以下命令均假定当前目录为仓库根目录，并且已经按本机 ROS2 安装方式加载环境：

```bash
uv sync --extra models --extra dev
uv run pytest
```

直接运行源码节点：

```bash
uv run marsdog-vision-interaction \
  --ros-args -p config_path:=config/vision.yaml
```

ROS2 构建：

```bash
colcon build --base-paths . --packages-select marsdog_vision_interaction
source install/setup.bash
ros2 launch marsdog_vision_interaction vision.launch.py
```

该 launch 只启动视觉节点，并订阅已经存在的 RealSense 彩色图、对齐深度与
CameraInfo；相机驱动需单独启动且启用 `enable_depth` 与 `align_depth.enable`。

将 `providers.vision.type` 设置为 `mock` 可以在没有模型和相机的环境中做下游联调。
真实配置不会在模型、相机或 RKNN 不可用时自动伪造人体/物体；对应 Topic
字段为空或 Service 明确返回失败。

YuNet / SFace 根据模型扩展名自动选择 OpenCV（`.onnx`）或 RKNN（`.rknn`），
无需配置 backend。当前支持已验证的 RK3588 FP16 模型；生产配置使用 RKNN。
切换步骤、模型指纹和板端验证命令见 [人脸 RKNN 适配说明](docs/rknn-face-models.md)。

姿态与手势使用 MediaPipe 索引的 33 槽时序规则引擎；RKNN 的 COCO 17 点在动作
引擎入口映射到对应槽位。每个稳定目标独立保存
动作历史；跌倒必须经过“稳定直立、快速转变、持续躺卧”才产生事件，静态躺卧
只属于姿态，不触发跌倒告警。生产配置使用 `inference_frame_stride: 2`，即
相机第 1、3、5…帧执行完整人脸/姿态/手部推理；30 Hz 输入时推理上限约 15 Hz，
但相机新鲜度仍按每个原始帧更新。相机回调只替换一个最新待处理帧，完整模型
流水线由独立单线程工作器执行；算力不足时丢弃旧候选帧而不积压延迟，10 Hz
事件发布和 VisionTask Service 不再等待关键点推理完成。正式配置的 Pose 使用
RKNN YOLOv8 NPU 模型，Hand 使用 RKNN 检测与关键点模型；切换到 MediaPipe `.task`
时，`VIDEO` 模式通过严格递增的单调时间戳复用帧间跟踪。
正式配置每帧最多请求 5 个 Pose 并输出独立 `human_candidates[]`；兼容
`active_target` 仍只选一个人。Hand 在未发现手部时每两个关键点推理帧探测一次，
发现手部后连续逐帧推理至少 8 次，在降低空场景负载的同时保留手势响应。

### Pose RKNN / Lite / Full A/B

生产配置使用 `yolov8n-pose-fp16.rknn`，发布原生 COCO 17 点并附带
`keypoint_format: coco_17`。需要回退到 MediaPipe CPU 链路时，可以直接切换：

```bash
ros2 launch marsdog_vision_interaction vision.launch.py pose_model_variant:=lite
ros2 launch marsdog_vision_interaction vision.launch.py pose_model_variant:=full
```

RKNN 模型、输出契约和板端检查命令见
[docs/rknn-pose-models.md](docs/rknn-pose-models.md)。RKNN 路径没有测量 Pose Z，
动作引擎会跳过深度证据。

MediaPipe Lite 和 Full 模型统一放在共享模型目录。Full 模型可用以下命令安装：

```bash
export MARSDOG_VISION_MODEL_DIR="${MARSDOG_VISION_MODEL_DIR:-$PWD/models/vision}"
mkdir -p "$MARSDOG_VISION_MODEL_DIR"
curl --fail --location \
  --output "$MARSDOG_VISION_MODEL_DIR/pose_landmarker_full.task" \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task
```

不修改 YAML 即可分别启动两组 MediaPipe 实验：

```bash
ros2 launch marsdog_vision_interaction vision.launch.py \
  pose_model_variant:=lite

ros2 launch marsdog_vision_interaction vision.launch.py \
  pose_model_variant:=full
```

每组在相同站位、光照和动作下保持至少150个推理帧。Web Viewer 的“关键点模型
A/B”面板显示有效推理FPS、平均/P95耗时、人体检测率、当前点数有效率及动作关键点
有效率，并显示接收帧、推理候选、实际完成和被新帧替换的数量。画面无人时的
检测率没有比较意义；选择 Full 前应确认有效推理频率满足实际动作时序要求。

## ROS2 接口

- 订阅：`/camera/camera/color/image_raw`
- 订阅：`/camera/camera/aligned_depth_to_color/image_raw`
- 订阅：`/camera/camera/color/camera_info`
- 发布：`/perception/visual_event`
- 发布：`/perception/vision/object_detections`（按需物体检测数据流）
- Service：`/perception/vision/task`（单次查询及物体流控制）

外部相机流超过 0.5 秒未更新时，视觉节点停止发布缓存场景事实，并让目标自然
进入丢失状态。人体米制距离只有在对齐深度、内参、frame、时间同步和躯干 ROI
都有效时才设置 `range_valid=true`；否则 fail closed，不使用框高度估距。

## 按需物体检测

正式配置启动时不运行物体模型。动作系统开始寻物任务后，通过
`VisionTask.set_object_detection` 开启数据流，订阅
`/perception/vision/object_detections` 取得二维检测结果，并在完成、取消或异常
路径中关闭。视觉节点不控制底盘、不调用 Nav2、不判断是否已经靠近物体。

开启一个 2 Hz、3 秒租约的数据流：

```bash
ros2 service call /perception/vision/task \
  marsdog_vision_interaction/srv/VisionTask \
  "{task_id: 'find-object-001-start', task_type: 'set_object_detection', \
    params_json: '{\"enabled\":true,\"session_id\":\"find-object-001\",\
\"rate_hz\":2.0,\"confidence\":0.25,\"target_labels\":[\"dog toy ball\"],\
\"lease_sec\":3.0}'}"
```

动作系统应在 3 秒到期前使用相同 `session_id` 重复调用完成续租。结束时关闭：

```bash
ros2 service call /perception/vision/task \
  marsdog_vision_interaction/srv/VisionTask \
  "{task_id: 'find-object-001-stop', task_type: 'set_object_detection', \
    params_json: '{\"enabled\":false,\"session_id\":\"find-object-001\"}'}"
```

`detect_objects` 仍是单帧同步查询，不会开启数据流。Topic 使用 schema v2，包含
`stream.session_id`、租约剩余时间、请求标签、时间戳、推理耗时和停止原因；完整
格式见 [docs/ROS2_CONTRACT.md](docs/ROS2_CONTRACT.md)。

## 陌生人情绪细分事件

视觉节点订阅情绪系统的 `/emotion/state` JSON v2，并在识别到陌生人脸时
读取 `emotions.<name>.triggered`：

- `Anxiety` 或 `Fear` 已触发：`EVT_VISION_STRANGER_ALERT`；
- 否则 `Joy`、`Excite` 或 `Calm` 已触发：`EVT_VISION_STRANGER_FRIEND`；
- 情绪状态未收到、超过 2.5 秒、格式非法或仅 `Curious` 触发：
  回退 `EVT_VISION_STRANGER`。

Alert 优先于 Friend，细分事件替换通用 Stranger，同包不双发。已知人脸
仍走 `EVT_VISION_MASTER*`。情绪系统不应再把两个细分事件配置为情绪增量
输入，否则可能形成 Vision → Emotion → Vision 的反馈环。

## 统一视觉调试页面

人脸、人体/Pose、手势、视觉事件和物体识别统一使用
`vision_debug.launch.py`，不再要求测试人员切换到单独的物体调试命令。该入口默认
同时启动正式 `vision_interaction` 节点和 Web Viewer；RealSense 驱动仍需提前发布
彩色图、对齐深度和 CameraInfo。

物体 Provider 使用 `ultralytics.YOLOE` 完成图像预处理、模型调用、NMS 和
`Results.boxes` 解码。当前 `object_model` 指向 RKNN 导出目录，因此最终仍由
Ultralytics 的 RKNNBackend 通过 `rknn-toolkit-lite2` 在 RK3588 NPU 上执行；
Provider 只对 RKNN 模型已有类别做不区分大小写的精确标签过滤。

正式配置仍以 `inference_rate_hz=0` 启动；当视觉正在跟踪人物时，会启用可让路的
`vision-human-holding` 内部流，以2 Hz检查玩具/狗粮。物体框必须接近当前人物的
有效 Pose/Hand 手腕；置信度至少0.35，并在1.5秒内得到两个不同阳性物体结果后，
才把当前人物写为 `pose_action=holding_toy`（手持玩具）
或 `holding_dog_food`（手持狗粮）。人物离开2秒后停止自动推理，显式 Action 或
Debug session 始终优先。两个阳性结果之间允许一次短暂漏检；物体可随伸出的手部分
超出人物框，但远离手腕的地面或桌面物体仍不会成为手持证据。

`EVT_VISION_TOY/FOOD` 现在只由上述已确认手持姿态产生，并继续遵守固定人脸库
`confirmed_known + tracking` 门控。地面、桌面或其他人附近仅出现对应物体，只保留
`tracked_objects[]`，不再发布 TOY/FOOD 事件。跌倒姿态优先，不会被手持结果覆盖。

重新构建并 source 工作区后，只需执行一个调试命令：

```bash
export VISION_REPO="$PWD"
export ROS2_WS="${ROS2_WS:-$HOME/ros2_ws}"
cd "$ROS2_WS"
colcon build --symlink-install \
  --packages-select marsdog_vision_interaction
source install/setup.bash

ros2 launch marsdog_vision_interaction vision_debug.launch.py \
  web_host:=0.0.0.0
```

打开 `http://<机器狗IP>:8765`。默认 `start_vision_node:=true`，因此不要同时运行
普通 `vision.launch.py`，否则会产生同名节点和重复 Topic。如果设备上已经有正式
视觉节点，只附加 Viewer：

```bash
ros2 launch marsdog_vision_interaction vision_debug.launch.py \
  web_host:=0.0.0.0 start_vision_node:=false
```

“手势与物体”面板支持“单次物体识别”“启动持续识别”“停止持续识别”。持续识别
使用固定 `vision-debug-web` session，并每10秒续租30秒；关闭页面后最多30秒自动
停止。若 Action 已持有其他 session，页面会显示占用错误且不会抢占。物体模型保持
懒加载，首次点击可能明显较慢。

也可以绕过 ROS2，用单张图片做 RKNN 硬件冒烟测试；模型路径默认复用
`vision.yaml` 的解析结果：

```bash
uv run python tests/test_rknn.py path/to/input.jpg
```

## 调试页面功能

在同一局域网的电脑或手机打开
`http://<机器狗局域网IP>:8765`。例如机器狗 IP 为
`192.168.1.50` 时，访问
`http://192.168.1.50:8765`。页面显示人体框与姿态骨架（绿）、人脸框与
身份（蓝）、物体框（紫）、手部骨架与手势（橙）、当前目标（红），并列出
相机/视觉消息年龄、FPS、动作、置信度、事件以及原始 JSON。GesturePose 面板
显示精确的内部标签（例如 `waving`、`victory`）、P0–P4 优先级、原始候选分数
和经过时序平滑后真正命中的动作，便于区分粗粒度 `standing/lying` 与动作规则。
快速点头区域还显示头部垂直运动能量、方向反转次数和归一化位移幅度；
`fast_nod` 必须同时满足三项条件，避免鼻尖关键点的小幅抖动被误判为点头。

“Vision 已发布事件记录”面板直接在 Viewer 的 ROS Topic 回调中记录
`/perception/visual_event.events[]`，不会因网页 350 ms 轮询漏掉短事件。相同事件的
10 Hz 重复状态流会压缩成 `ENTER`（开始）、`ACTIVE`（持续）和 `EXIT`（结束），
同时保留接收时间、`vision_epoch/sequence`、目标身份、姿态和手势证据。测试人员可
复制、导出或清空本次 Viewer 进程内最多200条记录；可通过
`event_history_limit:=500` 调整为20～1000条。该面板只证明 Vision 已发布事件，
不表示行为树已选中候选，也不表示 Action 已执行；后两段链路必须查看各自日志。
桌面端会把事件记录排在右栏首位，并在滚动右侧诊断信息时固定左侧实时画面；窗口
宽度小于1050像素时自动恢复上下排列，避免手机或窄屏被固定画面遮挡。

页面的“在线人脸录入”可直接管理设备本地人脸库。身份固定为 `owner`（主人）和
`family_member_1`～`family_member_4`（家人1～4），不接受自由姓名。选择身份后，只需自然面对
摄像头并保持稳定；系统通过单人脸、检测置信度、人脸尺寸、清晰度和光照检查后，
默认自动连续保存三张，不需要转头、抬头或做其他动作。每个身份最多保存5张，
剩余槽位不足3张时页面只补满剩余槽位。完成后可在
同一页面现场验证识别、刷新名单或删除录入。统一的 `vision_debug.launch.py` 默认
已经启动正式视觉节点；只有传入 `start_vision_node:=false` 时，才要求设备上已有
可用的 `/perception/vision/task` Service。

录入质量配置位于 `config/vision.yaml` 的 `face_enrollment`：上传 API、WebUI 和连续
录入共用 `quality`，连续采集使用独立的 `continuous`。修改后需要重启节点。
当前 YAML 的 `min_detection_confidence: 0.70` 是待样本验证的值；省略该配置时使用
原有 `0.85`。它是 YuNet 检测置信度，不是 SFace 相似度或综合质量分数。
亮度和 Laplacian 清晰度在检测到的人脸区域计算，不能直接对比整图评分。
默认 `require_single_face: true`，上传多人照片也会拒绝；设为 `false` 时两种入口
均选择最大人脸。有效关键点缺失的检测结果会拒绝录入。

`continuous.stable_frames` 表示连续合格帧数，不检查位置或身份是否稳定；
`continuous.required_shots` 是默认采集张数（1～5），未传张数时后端自动限制到剩余槽位。
显式指定 `required_shots` 会覆盖默认值，超过剩余容量时返回错误。
质量拒绝时 HTTP API 保留字符串 `detail`，并新增 `quality`，包含 `reason`、
`metrics` 和 `thresholds`；连续录入通过 `enrollment_event` 返回相同诊断。

每张样本会分别生成 SFace 模板，识别时对同一固定身份的所有模板取最高相似度。
所有姿态/手势事件只在当前主目标属于固定人脸库（`owner` 或
`family_member_1`～`family_member_4`），目标仍为 `tracking`，且身份状态达到 `confirmed_known` 后
发布。第一次匹配形成的 `candidate_known`、陌生人或未检测到人脸时，页面仍可
看到结构化姿态调试结果，但不会上报普通姿态、跌倒或 Stop 手势事件。

正式节点会在视觉状态发生变化时输出一条 `Visual state changed` 日志，包含
`track`、`identity`、`identity_state`、`pose`、`hands`、
`pose_event_gate` 和最终发布的 `events`。人脸识别状态发生变化时还会输出
`Face identity changed`。这些日志按状态变化去重，不会随 10 Hz Topic 重复刷屏。
人脸图片及 `face_registry.json` 是设备本地生物数据，位于配置的数据目录，
不得提交 Git。页面默认只监听 `127.0.0.1`；当前 Debug Web 和人脸管理接口暂不
鉴权，设置 `web_host:=0.0.0.0` 后局域网内任何客户端都可操作，因此只允许在
可信隔离网络中使用，并优先考虑下方 SSH 端口转发。

## 人脸样本 CRUD API

正式视觉节点默认在 `http://127.0.0.1:8092` 提供 FastAPI，OpenAPI/Swagger 页面为
`http://127.0.0.1:8092/docs`。接口固定提供5个身份槽位，每个身份最多5张图片：

| 身份 | 显示名称 | 角色 |
|---|---|---|
| `owner` | 主人 | `owner` |
| `family_member_1`～`family_member_4` | 家人1～家人4 | `family` |

| 方法和路径 | 用途 |
|---|---|
| `POST /api/v1/faces/{name}/samples` | 上传 JPG/JPEG/PNG，检测并新增最大人脸 |
| `GET /api/v1/faces` | 列出人员、样本数、固定上限和可用身份 |
| `GET /api/v1/faces/{name}/samples` | 列出该人员每张图片的稳定 `sample_id` 和状态 |
| `GET /api/v1/faces/{name}/samples/{sample_id}` | 查询单张样本元数据 |
| `GET /api/v1/faces/{name}/samples/{sample_id}/image` | 查看或下载裁剪后的人脸 JPG |
| `PUT /api/v1/faces/{name}/samples/{sample_id}` | 校验新图片并原位替换，编号不变 |
| `DELETE /api/v1/faces/{name}/samples/{sample_id}` | 只删除指定样本；最后一张删除后释放身份槽位 |

`sample_id` 范围固定为1～5。删除 `002.jpg` 后不会重编号 `003.jpg`；下一次新增会
复用最小空闲编号。POST/PUT 请求使用 `multipart/form-data` 的 `image` 文件字段，
默认单文件上限10 MiB。系统会对同一身份的规范化人脸 JPG 做精确去重；重复新增或
替换其它样本返回 HTTP 409 和 `code=face_sample_duplicate`，并给出已存在的
`duplicate_sample_id`。替换当前样本自身仍可幂等成功。上传成功后会同步当前进程的
人脸识别模板。

本机示例：

```bash
curl -X POST http://127.0.0.1:8092/api/v1/faces/owner/samples \
  -F "image=@./owner.jpg"
```

每次响应都带 `X-Request-ID`；新增、替换、删除的 JSON 成功响应以及业务错误响应也
包含相同的 `request_id`，可用它在视觉日志中定位调用。重复上传示例：

```bash
curl -i -X POST http://127.0.0.1:8092/api/v1/faces/owner/samples \
  -F "image=@./owner.jpg"
```

如果 `owner.jpg` 已经存在于主人样本中，返回 HTTP 409，响应形如：

```json
{
  "detail": "该身份已存在相同人脸样本",
  "code": "face_sample_duplicate",
  "request_id": "...",
  "name": "owner",
  "duplicate_sample_id": 1,
  "duplicate_sample_key": "001",
  "shots": 1,
  "max_samples_per_face": 5
}
```

服务端会记录 `request_id`、HTTP 方法、路径、状态码和耗时，不记录图片二进制、人脸
特征或请求体。

需要局域网访问时：

```bash
ros2 launch marsdog_vision_interaction vision.launch.py \
  face_api_host:=0.0.0.0
```

当前人脸 FastAPI 暂不鉴权，不需要请求头或 URL token。默认仅监听回环地址；绑定
`0.0.0.0` 时只应接入可信隔离局域网，仍推荐通过 SSH 转发 `8092`，不要把设备
本地生物数据管理接口暴露到不可信网络。

跌倒区域显示是否已完成直立基线布防、躺卧分数、转换分数和报警保持状态；
Stop 调试显示左右手四指伸直数量、掌面朝向分数及手部运动能量，可直接判断
是姿态条件未满足，还是仍在等待时序稳定。
针对安装在狗头高位并向下俯视的相机，Stop 允许“手掌明显朝前/靠近镜头”或
“手臂接近伸直”任一几何证据成立，不再要求两者同时满足；四根非拇指伸直、
掌心朝镜头、手部稳定、Pose/Hand 手腕关联以及 3/5 帧时序确认仍是硬条件。手腕
还必须离开髋部自然下垂区并举到躯干指令区域；单纯手臂伸直不再足以触发 Stop。
跳跃优先使用髋部和双脚共同向上的全身证据，连续两帧即可确认。脚踝因近距离构图
不可见、但肩部和髋部仍可靠时，会切换到半身兜底：先取得约0.2秒稳定基线，再结合
肩髋上升速度与相对基线的整体抬升量，确认一个强起跳帧或两个普通起跳帧，并在约
1.1秒内观察共同回落或回到基线；脚踝可见但仍着地时
不会绕过全身条件，因此
普通起身不按跳跃处理。确认后保持约0.65秒供时序输出。页面显示识别模式、阶段、
缺失关键点、全身/半身/回落证据、肩髋脚踝速度和躯干尺度变化。
跺脚优先使用脚踝相对髋部的“抬起—落下”轨迹；脚踝被裁掉但膝部仍可见时，自动
改用膝部相对髋部的垂直速度、运动幅度和换向次数。身体中心必须基本稳定且保持直立，
整个人共同上下移动的跳跃不会作为跺脚证据。
正式视觉节点默认不运行物体检测。页面“手势与物体”面板可设置置信度和持续频率，
并通过按钮执行单次识别、启动持续识别或停止持续识别。单次调用不会创建 session；
持续调试固定使用 `vision-debug-web` session，且不会抢占 Action 已持有的 session。
首次识别需要懒加载模型，等待时间可能较长。

为避免调试页面反过来拖慢识别，Web Viewer 默认限制为 8 FPS、按 0.75 比例
渲染、JPEG 质量 75，并关闭完整 BGR 调试 Topic 的重复发布。需要原分辨率或
`/perception/vision/debug_image` 时可显式打开：

```bash
ros2 launch marsdog_vision_interaction vision_debug.launch.py \
  max_render_fps:=10 render_scale:=1.0 publish_debug_image:=true
```

页面默认只监听本机回环地址。远程查看推荐使用 SSH 端口转发：

```bash
ssh -L 8765:127.0.0.1:8765 <user>@<robot-ip>
```

启用 `publish_debug_image:=true` 后会发布 `/perception/vision/debug_image`，可以
使用 `rqt_image_view` 查看。需要保留原 OpenCV 窗口时传入 `show_window:=true`。

视觉与调试节点默认订阅 RealSense 彩色流
`/camera/camera/color/image_raw`，并按普通单目画面处理。
- 发布：`/perception/vision/enrollment_event`
- 调试：`/perception/vision/gesture_debug`
- Service：`/perception/vision/task`

视觉任务：`check_person`、`query_targets`、`detect_objects`、`set_object_detection`、
`get_object_detection_state`、`recognize_face`、
`start_face_enrollment`、`cancel_face_enrollment`、`upload_face`、
`list_faces`、`list_face_records`、`list_face_samples`、`get_face_sample`、
`replace_face_sample`、`delete_face_sample`、`delete_face`。

完整字段约定见 [docs/ROS2_CONTRACT.md](docs/ROS2_CONTRACT.md)。
