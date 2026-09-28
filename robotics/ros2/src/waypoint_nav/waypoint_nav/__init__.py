"""waypoint_nav: 预设点位导航包。

分两层：
- matcher: 纯 Python 的 waypoints.yaml 加载与地点名匹配，不依赖 ROS；
- waypoint_nav_dispatcher: ROS 2 节点，接 VoiceTask service，对着 /map
  校验点位后下发 Nav2 NavigateToPose。
"""
