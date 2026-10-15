cmake_minimum_required(VERSION 3.8)
project(robot_local_motion)
find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter)
find_package(go2_uwb_local_follow REQUIRED)
# Call the existing public C++ follow core from the Python task coordinator.
# The control functions remain owned by go2_uwb_local_follow.
add_library(uwb_follow_binding SHARED src/uwb_follow_binding.cpp)
target_compile_features(uwb_follow_binding PRIVATE cxx_std_17)
ament_target_dependencies(uwb_follow_binding go2_uwb_local_follow)
install(TARGETS uwb_follow_binding LIBRARY DESTINATION lib)
rosidl_generate_interfaces(${PROJECT_NAME}
  "action/ExecuteLocalMotion.action" "msg/TargetObservation.msg" "srv/ReleaseRecovery.srv"
  DEPENDENCIES geometry_msgs std_msgs)
# Separate implementation module avoids ament_python_install_package/rosidl target collision.
install(DIRECTORY robot_local_motion/ DESTINATION
  lib/python${Python3_VERSION_MAJOR}.${Python3_VERSION_MINOR}/site-packages/robot_local_motion_runtime
  FILES_MATCHING PATTERN "*.py")
# Register the implementation path independently of rosidl's interface path.
# This also survives direct CMake installs that regenerate ament setup metadata.
ament_environment_hooks(
  "${CMAKE_CURRENT_SOURCE_DIR}/env-hooks/robot_local_motion_runtime.sh.in"
  "${CMAKE_CURRENT_SOURCE_DIR}/env-hooks/robot_local_motion_runtime.dsv.in")
install(PROGRAMS scripts/local_motion_server scripts/uwb_observation_bridge scripts/uwb_multitag_input scripts/uwb_roundtrip_demo
  scripts/target_follow_input scripts/behavior_odom_input
  DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch config DESTINATION share/${PROJECT_NAME})
install(FILES README.md DESTINATION share/${PROJECT_NAME})
if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(test_core test/test_core.py)
  ament_add_pytest_test(test_uwb_follow_backend test/test_uwb_follow_backend.py)
  ament_add_pytest_test(test_guard test/test_guard.py)
  ament_add_pytest_test(test_roundtrip_core test/test_roundtrip_core.py)
  ament_add_pytest_test(test_roundtrip_transport test/test_roundtrip_transport.py TIMEOUT 300
    ENV "ROS_DOMAIN_ID=227" "ROS_LOCALHOST_ONLY=1")
  ament_add_pytest_test(test_native_roundtrip_transport test/test_native_roundtrip_transport.py TIMEOUT 180
    ENV "ROS_DOMAIN_ID=226" "ROS_LOCALHOST_ONLY=1")
  ament_add_pytest_test(test_target_geometry test/test_target_geometry.py)
  ament_add_pytest_test(test_follow_input_transport test/test_follow_input_transport.py TIMEOUT 120
    ENV "ROS_DOMAIN_ID=224" "ROS_LOCALHOST_ONLY=1")
  ament_add_pytest_test(test_uwb_protocol test/test_uwb_protocol.py)
  ament_add_pytest_test(test_uwb_tracking test/test_uwb_tracking.py)
  ament_add_pytest_test(test_uwb_stability test/test_uwb_stability.py)
  ament_add_pytest_test(test_uwb_transport test/test_uwb_transport.py TIMEOUT 45
    ENV "ROS_DOMAIN_ID=225" "ROS_LOCALHOST_ONLY=1")
  ament_add_pytest_test(test_task_transport test/test_task_transport.py TIMEOUT 90
    ENV "ROS_DOMAIN_ID=220" "ROS_LOCALHOST_ONLY=1")
endif()
ament_export_dependencies(rosidl_default_runtime)
ament_package()
