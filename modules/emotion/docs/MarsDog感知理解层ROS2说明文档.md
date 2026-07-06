MarsDog Perception — ROS2 接口文档
感知系统对外暴露 3 个 Topic + 1 个 Service。下游节点通过订阅这些接口获取视觉观测、语音交互事件和目标决策结果。

目录
1. 节点拓扑
2. Topic 接口
  ○ /camera/image_raw
  ○ /perception/visual_event
  ○ /perception/audio_event
3. Service 接口
  ○ /perception/perception_task
4. 数据 Schema 详解
  ○ active_target
  ○ face
  ○ human
  ○ hand
  ○ tracked_object
  ○ interaction_event
5. 状态机
6. QoS 策略
7. 调试方法

节点拓扑
camera_driver                    perception_bridge
┌──────────────┐                ┌──────────────────────────┐
│ /dev/video0  │   /camera/     │                          │
│ 640x240 MJPG │── image_raw ──→│  vision / audio / intent │
│              │                │                          │
└──────────────┘                │  /perception/visual_event │
                                │── (10Hz JSON) ──────────→│ 下游
                                │                          │
                                │  /perception/            │
                                │── interaction_event      │
                                │   (on event JSON) ──────→│ 下游
                                │                          │
                                │  /perception/perception_task    │
                                │←─ (service) ─────────────│ 下游
                                └──────────────────────────┘
节点名称:
节点	名称	说明
camera_driver	camera_driver	摄像头驱动
perception_bridge	perception_bridge	感知桥接 + HTTP/WS

Topic 接口
/camera/image_raw
摄像头原始图像。
属性	值
类型	sensor_msgs/Image
QoS	BEST_EFFORT, KEEP_LAST, depth=1
频率	可配 (默认 15Hz, config/camera_params.yaml)
编码	bgr8
分辨率	640×240 (双目 side-by-side)
帧 ID	camera_link
双目布局:
┌──────────┬──────────┐
│ 左目     │ 右目     │
│ 320×240  │ 320×240  │
└──────────┴──────────┘
所有 2D 视觉推理只使用左目 (前 320 列)，因此 observation 中坐标 x 范围均在 [0, 0.5]。
订阅示例 (Python):
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
import numpy as np

class MySubscriber(Node):
    def __init__(self):
        super().__init__("my_subscriber")
        self.sub = self.create_subscription(
            Image, "/camera/image_raw", self.callback, 1,
        )

    def callback(self, msg: Image):
        frame = np.frombuffer(msg.data, dtype=np.uint8).reshape(
            msg.height, msg.width, 3,
        )
        # frame[:, :msg.width//2]  = 左目
        # frame[:, msg.width//2:]  = 右目

/perception/visual_event
视觉观测数据，包含人脸、人体、手部、物体检测结果及活跃目标。
属性	值
类型	std_msgs/String (JSON)
QoS	BEST_EFFORT, KEEP_LAST, depth=5
频率	可配 (默认 10Hz, config/perception.yaml)
顶层结构:
{
  "header": { "stamp": 1710000000.123, "frame_id": "camera_link" },
  "active_target": { ... },
  "faces": [ ... ],
  "humans": [ ... ],
  "hands": [ ... ],
  "tracked_objects": [ ... ]
}
订阅示例 (Python):
import json
from std_msgs.msg import String

class ObsSubscriber(Node):
    def __init__(self):
        super().__init__("obs_subscriber")
        self.sub = self.create_subscription(
            String, "/perception/visual_event", self.callback, 5,
        )

    def callback(self, msg: String):
        obs = json.loads(msg.data)
        target = obs.get("active_target", {})
        identity = target.get("identity", "unknown")
        speaker = target.get("speaker_id", "unknown")

        if identity != "unknown":
            self.get_logger().info(f"Recognized: {identity}")

        faces = obs.get("faces", [])
        humans = obs.get("humans", [])
        hands = obs.get("hands", [])
字段说明:
字段	类型	说明
header	object	时间戳 + frame_id
active_target	object	当前活跃交互目标 (单人)
faces	array	所有人脸检测结果
humans	array	所有人体的 bbox + 姿态 + 动作标签 + 关键点
hands	array	手部 21 点关键点 + 手势动作标签
tracked_objects	array	物体检测结果 (仅 service 调用时填充)
events	array	视觉事件列表 — 见下方 视觉事件类型

/perception/audio_event
交互事件推送，包含唤醒 → 声纹 → ASR → 意图分类的完整链路。
属性	值
类型	std_msgs/String (JSON)
QoS	RELIABLE, KEEP_LAST, depth=10
频率	事件驱动 (不定时)
事件类型一览:
event_type	说明	触发时机
EVT_VOICE_CALL_NAME	听到主人呼唤名字	唤醒词检测
EVT_VOICE_MASTER_ID	识别到主人声纹	声纹匹配成功
EVT_VOICE_STRANGER_ID	识别到陌生人声纹	声纹未匹配
EVT_VOICE_PRAISE	听到夸赞/鼓励意图	意图分类→表扬
EVT_VOICE_SCOLD	听到责备/制止意图	意图分类→责备/警告
EVT_VOICE_COMMAND_KNOWN	听到指令（熟悉）	意图分类→已知命令
EVT_VOICE_COMMAND_UNKNOWN	听到指令（陌生）	意图分类→未识别
EVT_VOICE_HAPPY	听到主人开心情绪	意图分类→开心
EVT_VOICE_SAD	听到主人悲伤情绪	意图分类→悲伤
EVT_VOICE_NEUTRAL	听到主人中性情绪	意图分类→中性/兜底

EVT_VOICE_CALL_NAME (唤醒)
{
  "header": { "stamp": 1710000000.0, "frame_id": "base_link" },
  "event_type": "EVT_VOICE_CALL_NAME",
  "wake_word": "你好小狗",
  "wake_angle": 0.0,
  "wake_confidence": 1205.0,
  "state": "attention"
}
字段	类型	说明
wake_word	string	唤醒词文本
wake_angle	float64	声源角度 (度)
wake_confidence	float64	唤醒置信度
state	string	状态机: attention
EVT_VOICE_MASTER_ID / STRANGER_ID (声纹)
{
  "header": { "stamp": 1710000000.3, "frame_id": "base_link" },
  "event_type": "EVT_VOICE_MASTER_ID",
  "speaker_id": "xbb",
  "speaker_confidence": 0.85
}
字段	类型	说明
speaker_id	string	声纹 ID, "unknown" = 未匹配
speaker_confidence	float64	声纹匹配置信度
EVT_VOICE_PRAISE / SCOLD / COMMAND_KNOWN / COMMAND_UNKNOWN (意图)
{
  "header": { "stamp": 1710000000.85, "frame_id": "base_link" },
  "event_type": "EVT_VOICE_COMMAND_KNOWN",
  "command_id": "CMD_SIT",
  "intent_category": "command",
  "intent_source": "rule",
  "intent_confidence": 1.0,
  "slots": [
    { "key": "raw_tag", "value": "C|SIT|N|E" }
  ],
  "asr_text": "坐下",
  "response_text": "",
  "is_executable": true,
  "state": "execution",
  "latency_ms": 0.0
}
字段	类型	说明
event_type	string	EVT_VOICE_PRAISE / EVT_VOICE_SCOLD / EVT_VOICE_COMMAND_KNOWN / EVT_VOICE_COMMAND_UNKNOWN / EVT_VOICE_HAPPY / EVT_VOICE_SAD / EVT_VOICE_NEUTRAL
command_id	string	指令 ID, CMD_UNKNOWN = 未识别
intent_category	string	原始意图大类
intent_source	string	rule / rkllm / fallback
intent_confidence	float64	置信度
slots	array	语义槽位 [{key, value}]
asr_text	string	ASR 识别文本（已去标点）
is_executable	bool	是否为可执行指令
state	string	状态机: execution
command_id 列表:
ID	说明
CMD_SIT	坐下
CMD_COME_HERE	过来
CMD_HAND	握手
CMD_FIVE	击掌
CMD_FOLLOW	随行
CMD_ROLL	翻滚
CMD_SPIN	转圈
CMD_BACK	衔回
CMD_SPIT	吐掉
CMD_DEAD	装死
CMD_STOP	停止
CMD_PRAISE	表扬回应
CMD_ENCOUR	鼓励回应
CMD_COMFORT	安慰
CMD_CHAT	闲聊
CMD_UNKNOWN	未识别
I|A|M|R tag 格式: {意图大类}|{动作}|{模态}|{终止符}
位置	含义	取值示例
I	一级意图	C=命令 P=表扬 B=责备 E=情感 U=未知
A	动作	SIT/COME/HAND/PRAISE/ENCOUR/CHAT...
M	情绪	N=中性 H=开心 S=悲伤 Q=平静 R=严肃
R	响应模式	E=执行 T=终止 P=表扬 C=安慰 L=闲聊
订阅示例 (Python):
class AudioEventSubscriber(Node):
    def __init__(self):
        super().__init__("audio_subscriber")
        self.sub = self.create_subscription(
            String, "/perception/audio_event", self.callback, 10,
        )

    def callback(self, msg: String):
        event = json.loads(msg.data)
        etype = event.get("event_type", "")

        if etype == "EVT_VOICE_CALL_NAME":
            self.on_wakeup(event)
        elif etype in ("EVT_VOICE_MASTER_ID", "EVT_VOICE_STRANGER_ID"):
            self.on_speaker_id(event)
        elif etype.startswith("EVT_VOICE_"):
            self.on_intent(event)

/perception/target_event
融合目标事件，由 target_tracker 节点发布。订阅 visual_event + audio_event 后融合产出。
属性	值
类型	std_msgs/String (JSON)
QoS	BEST_EFFORT, KEEP_LAST, depth=5
频率	10Hz
发布节点	target_tracker
顶层结构:
{
  "header": {...},
  "interaction_state": "interaction",
  "audio_context": {...},
  "active_target": {...},
  "pending_target": {...},
  "persons": [...],
  "emotion_context": {...}
}
适用场景: 云台控制 (gaze_target)、行为决策 (active_target)、多目标管理 (persons)。

Service 接口
/perception/perception_task
按需感知任务服务。
属性	值
类型	marsdog_perception/srv/PerceptionTask
QoS	RELIABLE (默认)
srv 定义:
string task_id         # 调用方生成的唯一标识
string task_type       # 任务类型
string params_json     # JSON 数组参数
---
bool   success         # 是否成功
string task_id         # 回传 task_id
string task_type       # 回传 task_type
string result_json     # JSON 格式结果
string error_message   # 错误描述 (成功时为空)
float64 latency_ms     # 耗时 (毫秒)
任务类型:
task_type	说明	params_json	result_json 示例
check_person	检查是否有人	[]	[{"key":"present","value":"true"},{"key":"count","value":"1"}]
detect_objects	检测物体	[{"key":"confidence","value":"0.5"}]	[{"key":"objects","value":"[{\"label\":\"dog toy ball\",\"x\":0.3,...}]"}]
enroll_face	注册人脸	[]	[{"key":"user_id","value":"alice"}]
recognize_face	识别人脸	[]	[{"key":"user_id","value":"alice"},{"key":"confidence","value":"0.92"},{"key":"matched","value":"true"}]
enroll_speaker	注册声纹	[]	[{"key":"speaker_id","value":"spk_001"}]
verify_speaker	验证声纹	[]	[{"key":"speaker_id","value":"bob"},{"key":"confidence","value":"0.85"},{"key":"matched","value":"true"}]
调用示例 (Python):
from marsdog_perception.srv import PerceptionTask

class TaskClient(Node):
    def __init__(self):
        super().__init__("task_client")
        self.client = self.create_client(PerceptionTask, "/perception/perception_task")
        self.client.wait_for_service()

    def check_person(self) -> dict:
        req = PerceptionTask.Request()
        req.task_id = "my_task_001"
        req.task_type = "check_person"
        req.params_json = "[]"

        future = self.client.call_async(req)
        rclpy.spin_until_future_complete(self, future)

        resp = future.result()
        if resp.success:
            return json.loads(resp.result_json)
        return {}

    def detect_objects(self, threshold: float = 0.5) -> list:
        req = PerceptionTask.Request()
        req.task_id = "my_task_002"
        req.task_type = "detect_objects"
        req.params_json = json.dumps([{"key": "confidence", "value": str(threshold)}])

        future = self.client.call_async(req)
        rclpy.spin_until_future_complete(self, future)

        resp = future.result()
        if resp.success:
            result = json.loads(resp.result_json)
            for item in result:
                if item["key"] == "objects":
                    return json.loads(item["value"])
        return []
调用示例 (命令行):
source /opt/ros/humble/setup.bash

# 检测人物
ros2 service call /perception/perception_task marsdog_perception/srv/PerceptionTask \
  "{task_id: 't1', task_type: 'check_person', params_json: '[]'}"

# 检测物体 (低阈值)
ros2 service call /perception/perception_task marsdog_perception/srv/PerceptionTask \
  "{task_id: 't2', task_type: 'detect_objects', params_json: '[{\"key\":\"confidence\",\"value\":\"0.3\"}]'}"

# 注册人脸
ros2 service call /perception/perception_task marsdog_perception/srv/PerceptionTask \
  "{task_id: 't3', task_type: 'enroll_face', params_json: '[]'}"

# 识别人脸
ros2 service call /perception/perception_task marsdog_perception/srv/PerceptionTask \
  "{task_id: 't4', task_type: 'recognize_face', params_json: '[]'}"

# 验证声纹
ros2 service call /perception/perception_task marsdog_perception/srv/PerceptionTask \
  "{task_id: 't5', task_type: 'verify_speaker', params_json: '[]'}"

数据 Schema 详解
active_target
当前活跃交互目标。系统始终保持单人约束 — 任意时刻只有一个 active_target。
{
  "track_id": 1,
  "identity": "alice",
  "speaker_id": "spk_001",
  "is_speaking": true,
  "is_registered": true,
  "bbox": [0.15, 0.53, 0.20, 0.68],
  "face_bbox": [0.17, 0.55, 0.06, 0.08],
  "face_center": [0.20, 0.59],
  "body_center": [0.25, 0.87],
  "pose_state": "standing",
  "confidence": 0.85,
  "face_confidence": 0.92,
  "speaker_confidence": 0.0,
  "selection_reason": "currently speaking"
}
字段	类型	说明
track_id	int	跟踪 ID (同一个人保持不变)
identity	string	SFace 人脸识别结果, "unknown" = 未识别/未注册
speaker_id	string	声纹识别结果, "unknown" = 未识别/未注册
is_speaking	bool	当前是否正在说话
is_registered	bool	此人是否已注册
bbox	[float×4]	人体包围盒 [x, y, w, h] 归一化 [0,1]
face_bbox	[float×4]	人脸包围盒, 无脸时全 0
face_center	[float×2]	人脸中心, 供云台追踪
body_center	[float×2]	人体中心
pose_state	string	standing / sitting / lying / unknown
confidence	float	人体检测置信度
face_confidence	float	人脸检测置信度
speaker_confidence	float	声纹匹配置信度
selection_reason	string	为什么选中此目标
selection_reason 取值:
● "currently speaking" — 正在说话 (最高优先级)
● "identity (alice)" — 已注册人脸匹配
● "proximity (largest bbox)" — 最近/最大目标
● "speech detected" — 语音触发
目标选择优先级:
优先级	条件	说明
P_SPEECH (最高)	当前正在说话	VAD 检测到语音
P_IDENTITY	已注册人脸	SFace 匹配成功
P_PROXIMITY	最大包围盒	距离最近的人
P_PERSISTENCE	上一个活跃目标	3 秒内保持
INTERACTION 和 EXECUTION 状态下禁止目标切换。
face
{
  "track_id": 3,
  "x": 0.17, "y": 0.55, "w": 0.06, "h": 0.08,
  "confidence": 0.92,
  "recognized_user": "alice",
  "identity_confidence": 0.81,
  "identity_state": "confirmed_known",
  "quality": 0.76
}
字段	类型	说明
track_id	int	ByteTrack 短期跟踪 ID, -1=未跟踪
x, y, w, h	float	包围盒 [0,1] 归一化
confidence	float	YuNet 检测置信度
recognized_user	string	SFace 识别结果, "" = 未识别
identity_confidence	float	身份匹配置信度 (cosine)
identity_state	string	unverified / candidate_known / confirmed_known / unknown_candidate / confirmed_unknown
quality	float	人脸质量分 (综合分数+尺寸)
SFace 按 track_id 节流识别: 新 track 立即识别, 已知 track 3-8 秒复核一次, 连续 2 次匹配才确认身份。
human
{
  "x": 0.15, "y": 0.53, "w": 0.20, "h": 0.68,
  "confidence": 0.85,
  "pose_state": "standing",
  "pose_action": "arm_raise_wave",
  "pose_action_label": "手臂高举/挥舞",
  "keypoints": [
    {"id": 0,  "x": 0.20, "y": 0.58, "confidence": 0.9},
    {"id": 11, "x": 0.18, "y": 0.62, "confidence": 0.8}
  ],
  "track_id": 1
}
字段	类型	说明
x, y, w, h	float	MediaPipe 33 点 landmark 计算的包围盒
confidence	float	平均关键点可见度
pose_state	string	姿态分类 (standing/sitting/lying/unknown)
pose_action	string	肢体动作标签 key（预留，当前 mock 随机触发）
pose_action_label	string	肢体动作中文标签
keypoints	array	MediaPipe Pose 33 个关键点
track_id	int	TargetManager 分配的跟踪 ID
关键点索引 (MediaPipe Pose):
索引	部位	索引	部位
0	鼻子	11-12	左右肩
1-4	左眼周	13-14	左右肘
5-8	右眼周	15-16	左右腕
9-10	嘴角	23-24	左右髋
17-22	手指/脚趾 (lite 模型可能不全)	25-26	左右膝
		27-32	脚踝/脚尖
hand
{
  "handedness": "Right",
  "hand_action": "thumbs_up",
  "hand_action_label": "点赞手势",
  "landmarks": [
    {"id": 0, "x": 0.32, "y": 0.55},
    {"id": 4, "x": 0.38, "y": 0.50}
  ]
}
字段	类型	说明
handedness	string	Left / Right
hand_action	string	手势动作标签 key（预留，当前 mock 随机触发）
hand_action_label	string	手势动作中文标签
landmarks	array	21 个手部关键点 [{id, x, y}]
pose_action / hand_action 标签列表
当前为 mock 随机触发（~60秒一次，持续2-4秒），后续接入基于关键点的动作识别后改为真实输出。
动作 key	中文标签	类型	情绪分组
arm_raise_wave	手臂高举/挥舞	pose	happy
jump	跳跃	pose	happy
lean_forward_arms_open	身体前倾/张开双臂	pose	happy
nodding	快速点头	pose	happy
clapping	双手鼓掌	hand	happy
thumbs_up	点赞手势	hand	happy
hands_on_hips	双手叉腰	pose	angry
rapid_wave_slap	快速挥手/拍打	hand	angry
finger_pointing	用手指点	hand	angry
stomping	急促跺脚	pose	angry
arms_crossed	双臂交叉于胸前	pose	angry
head_down_slumped	低头/肩膀下垂	pose	sad
hands_covering_face	双手掩面或抱头	hand	sad
body_curled_up	身体蜷缩	pose	sad
hunched_back	驼背/弓着背走路	pose	sad
neutral_stand_sit	自然站立/端坐	pose	neutral
stop_gesture	停止/别动手势	hand	alert
fallen_down	跌倒姿态	pose	alert
tracked_object
{
  "label": "dog toy ball",
  "x": 0.3, "y": 0.45, "w": 0.12, "h": 0.12,
  "confidence": 0.88,
  "center_x": 0.36, "center_y": 0.51
}
字段	类型	说明
label	string	物体类别名
x, y, w, h	float	包围盒 [0,1]
confidence	float	YOLOE-seg 置信度
center_x, center_y	float	中心点
仅当通过 service 调用 detect_objects 时填充，连续 observation 中为空数组。

视觉事件类型
/perception/visual_event JSON 中的 events 字段为 string[]，包含当前帧触发的视觉事件标签。
event_type	说明	触发逻辑
EVT_VISION_MASTER	识别到主人脸	SFace 匹配注册库
EVT_VISION_STRANGER	识别到陌生人脸	人脸存在但未匹配注册库
EVT_VISION_MASTER_HAPPY	识别到主人开心情绪	主人 + happy 组动作(挥舞/跳跃/点头/鼓掌/点赞)
EVT_VISION_MASTER_SAD	识别到主人悲伤情绪	主人 + sad 组动作(低头/蜷缩/驼背/掩面)
EVT_VISION_MASTER_NEUTRAL	识别到主人中性情绪	主人 + neutral 动作(自然站立/端坐)
EVT_VISION_FALL	人跌倒姿态	pose_action = fallen_down
EVT_VISION_STOP_GESTURE	停止/别动手势	hand_action = stop_gesture
EVT_VISION_TOY	识别到玩具	物体检测命中玩具类别(dog toy ball/frisbee/tug ring)
EVT_VISION_FOOD	识别到食物	物体检测命中食物类别(dog bowl/food can/treat bag)
EVT_VISION_ANIMAL_CALM	猫/狗-平静互动	service 请求 animal_type=calm + 检测到 cat/dog
EVT_VISION_ANIMAL_GREET	猫/狗-社交问候	service 请求 animal_type=greet + 检测到 cat/dog
EVT_VISION_ANIMAL_PLAY	猫/狗-邀请玩耍	service 请求 animal_type=play + 检测到 cat/dog
EVT_VISION_ANIMAL_BOUNDARY	猫/狗-边界试探	service 请求 animal_type=boundary + 检测到 cat/dog
注意: EVT_VISION_ANIMAL_* 事件仅在下游通过 /perception/perception_task service 明确请求动物行为识别时触发，不在连续 observation 中自动推送。
interaction_event
完整 schema 包含以下字段 (根据 event_type 仅部分有效):
字段	类型	wakeup	speech	intent
header	object	✅	✅	✅
event_type	string	✅	✅	✅
state	string	✅	✅	✅
previous_state	string	✅	✅	✅
state_reason	string	✅	✅	✅
wake_word	string	✅		
wake_angle	float64	✅		
wake_confidence	float64	✅		
asr_text	string		✅	
speaker_id	string		✅	
speaker_confidence	float64		✅	
emotion	string		✅	
language	string		✅	
command_id	string			✅
intent_category	string			✅
intent_source	string			✅
intent_confidence	float64			✅
slots	array			✅
response_text	string			✅ (始终为空)
is_executable	bool			✅
latency_ms	float64		✅	✅

状态机
IDLE ──(wakeup / person detected)──→ ATTENTION
ATTENTION ──(speech start)──→ INTERACTION  ← 目标锁定
INTERACTION ──(intent parsed)──→ EXECUTION
任意状态 ──(timeout)──→ IDLE
状态	说明	目标切换
IDLE	等待唤醒	允许
ATTENTION	已唤醒, 等待语音	允许
INTERACTION	语音交互中	禁止
EXECUTION	指令执行中	禁止

QoS 策略
接口	可靠性	持久性	Depth	说明
/camera/image_raw	BEST_EFFORT	KEEP_LAST	1	低延迟, 丢帧可接受
/perception/visual_event	BEST_EFFORT	KEEP_LAST	5	持续流, 容忍丢帧
/perception/audio_event	RELIABLE	KEEP_LAST	10	事件不能丢
/perception/perception_task	RELIABLE (默认)	—	—	请求/响应

调试方法
命令行验证
source /opt/ros/humble/setup.bash

# 查看 observation (单次)
ros2 topic echo /perception/visual_event --once

# 持续监听事件
ros2 topic echo /perception/audio_event

# 统计 observation 频率
ros2 topic hz /perception/visual_event

# 检查 QoS 兼容性
ros2 topic info /perception/visual_event --verbose

# 调用 service
ros2 service call /perception/perception_task marsdog_perception/srv/PerceptionTask \
  "{task_id: 'debug_1', task_type: 'check_person', params_json: '[]'}"
Python 一行检查
# 人/脸/手数量
ros2 topic echo /perception/visual_event --once --field data 2>/dev/null \
  | python3 -c "
import sys,json
d=json.loads(sys.stdin.read())
at=d.get('active_target',{})
print(f'track_id={at.get(\"track_id\",0)} identity={at.get(\"identity\",\"?\")} speaker={at.get(\"speaker_id\",\"?\")}')
print(f'faces={len(d.get(\"faces\",[]))} humans={len(d.get(\"humans\",[]))} hands={len(d.get(\"hands\",[]))} objects={len(d.get(\"tracked_objects\",[]))}')
"

# 监听事件类型
ros2 topic echo /perception/audio_event --field data 2>/dev/null \
  | python3 -c "
import sys,json
for line in sys.stdin:
    d=json.loads(line.strip())
    print(f'{d.get(\"event_type\",\"?\")}: {d.get(\"asr_text\") or d.get(\"wake_word\") or d.get(\"command_id\",\"?\")} [state={d.get(\"state\",\"?\")}]')
"