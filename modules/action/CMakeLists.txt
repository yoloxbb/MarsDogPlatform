cmake_minimum_required(VERSION 3.8)
project(marsdog_action_executor)

# Find dependencies
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclpy REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(action_msgs REQUIRED)
find_package(nav2_msgs REQUIRED)

# The public ROS types are provided by marsdog_interfaces.
ament_python_install_package(${PROJECT_NAME})

# Install launcher scripts
install(
  PROGRAMS
    scripts/action_executor_node
    scripts/emotion_display
  DESTINATION lib/${PROJECT_NAME}
)

# Install launch files
install(
  DIRECTORY launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

# Install config files
install(
  DIRECTORY config/
  DESTINATION share/${PROJECT_NAME}/config
)

ament_package()
