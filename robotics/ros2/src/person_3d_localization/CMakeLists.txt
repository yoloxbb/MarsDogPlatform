cmake_minimum_required(VERSION 3.8)
project(person_3d_localization)

# 使用 C++17，便于实现安全的缓存和数值处理。
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(image_geometry REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)
find_package(tf2_ros REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/LocateFromBbox.srv"
  DEPENDENCIES geometry_msgs sensor_msgs std_msgs
)

add_library(bbox_depth_processor
  src/bbox_depth_processor.cpp
)
target_include_directories(bbox_depth_processor PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)
ament_target_dependencies(bbox_depth_processor
  geometry_msgs
  image_geometry
  sensor_msgs
)

add_executable(bbox_depth_goal_node
  src/bbox_depth_goal_node.cpp
)
target_include_directories(bbox_depth_goal_node PRIVATE
  include
)
ament_target_dependencies(bbox_depth_goal_node
  geometry_msgs
  image_geometry
  rclcpp
  sensor_msgs
  std_msgs
  tf2
  tf2_geometry_msgs
  tf2_ros
)
target_link_libraries(bbox_depth_goal_node bbox_depth_processor)

# 同一包内节点需要显式链接本包生成的服务类型支持库。
rosidl_get_typesupport_target(cpp_typesupport_target
  ${PROJECT_NAME} "rosidl_typesupport_cpp")
target_link_libraries(bbox_depth_goal_node "${cpp_typesupport_target}")

install(TARGETS bbox_depth_processor bbox_depth_goal_node
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY include/
  DESTINATION include
)

install(DIRECTORY config docs launch
  DESTINATION share/${PROJECT_NAME}
)

install(FILES README.md
  DESTINATION share/${PROJECT_NAME}
)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()

  ament_add_gtest(test_bbox_depth_processor
    test/test_bbox_depth_processor.cpp
  )
  if(TARGET test_bbox_depth_processor)
    target_link_libraries(test_bbox_depth_processor bbox_depth_processor)
    ament_target_dependencies(test_bbox_depth_processor
      image_geometry
      sensor_msgs
    )
  endif()
endif()

ament_export_include_directories(include)
ament_export_dependencies(rosidl_default_runtime)
ament_package()
