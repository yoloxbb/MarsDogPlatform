cmake_minimum_required(VERSION 3.8)
project(stereo_v4l2_camera)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(ament_index_cpp REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(yaml-cpp REQUIRED)

add_executable(stereo_v4l2_direct_node src/stereo_v4l2_direct_node.cpp)
target_compile_features(stereo_v4l2_direct_node PUBLIC cxx_std_17)
ament_target_dependencies(
  stereo_v4l2_direct_node
  ament_index_cpp
  rclcpp
  sensor_msgs
)
target_link_libraries(stereo_v4l2_direct_node ${YAML_CPP_LIBRARIES})

install(
  TARGETS stereo_v4l2_direct_node
  DESTINATION lib/${PROJECT_NAME}
)
install(
  DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()
