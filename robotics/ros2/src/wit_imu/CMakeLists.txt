cmake_minimum_required(VERSION 3.8)
project(wit_imu)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)

add_executable(wit_imu_node src/wit_imu_node.cpp)
target_compile_features(wit_imu_node PUBLIC cxx_std_17)
ament_target_dependencies(wit_imu_node rclcpp sensor_msgs)

install(TARGETS wit_imu_node
  DESTINATION lib/${PROJECT_NAME})

# 保留原Python节点，出现兼容性问题时可以手动回退。
install(PROGRAMS wit_imu/wit_imu_node.py
  DESTINATION lib/${PROJECT_NAME}
  RENAME wit_imu_node_py)

install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME})

ament_package()
