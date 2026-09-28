cmake_minimum_required(VERSION 3.8)
project(marsdog_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(
  ${PROJECT_NAME}
  "action/ExecuteBehavior.action"
  "msg/BehaviorExecutionEvent.msg"
  "msg/BehaviorResultEvent.msg"
)

ament_package()
