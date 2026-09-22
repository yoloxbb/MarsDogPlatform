cmake_minimum_required(VERSION 3.8)
project(marsdog_vision_interaction)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(rclpy REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)

# RGA is optional.  The Python preprocessor always has a CPU implementation,
# while board builds with librga also install the small virtual-address bridge.
# Keeping this lookup optional preserves workstation and CI builds without the
# Rockchip SDK.
option(MARSDOG_BUILD_HAND_RGA "Build the optional RGA hand preprocessor" ON)
if(MARSDOG_BUILD_HAND_RGA)
  # The bridge includes <rga/im2d.h>; require the parent include directory so
  # SDKs that expose only a flat im2d.h are not selected accidentally.
  find_path(MARSDOG_RGA_INCLUDE_DIR NAMES rga/im2d.h)
  find_library(MARSDOG_RGA_LIBRARY NAMES rga librga)
  if(MARSDOG_RGA_INCLUDE_DIR AND MARSDOG_RGA_LIBRARY)
    # ament normally supplies PYTHON_INSTALL_DIR; query Python explicitly for
    # the fallback so a direct CMake configure does not rely on unset version
    # variables.
    find_package(Python3 COMPONENTS Interpreter QUIET)
    if(PYTHON_INSTALL_DIR)
      set(MARSDOG_PYTHON_INSTALL_DIR "${PYTHON_INSTALL_DIR}")
    elseif(Python3_VERSION_MAJOR AND Python3_VERSION_MINOR)
      set(MARSDOG_PYTHON_INSTALL_DIR
          "lib/python${Python3_VERSION_MAJOR}.${Python3_VERSION_MINOR}/site-packages")
    else()
      # Keep a regular CMake install usable even when no Python interpreter is
      # discoverable; the ament package path remains the normal deployment.
      set(MARSDOG_PYTHON_INSTALL_DIR "lib/python/site-packages")
    endif()
    add_library(marsdog_hand_rga SHARED native/hand_rga.cpp)
    target_include_directories(marsdog_hand_rga PRIVATE ${MARSDOG_RGA_INCLUDE_DIR})
    target_link_libraries(marsdog_hand_rga PRIVATE ${MARSDOG_RGA_LIBRARY})
    set_target_properties(marsdog_hand_rga PROPERTIES OUTPUT_NAME hand_rga)
    install(
      TARGETS marsdog_hand_rga
      LIBRARY DESTINATION ${MARSDOG_PYTHON_INSTALL_DIR}/${PROJECT_NAME}/utils/native
      RUNTIME DESTINATION ${MARSDOG_PYTHON_INSTALL_DIR}/${PROJECT_NAME}/utils/native
    )
    message(STATUS "Building optional hand RGA bridge with ${MARSDOG_RGA_LIBRARY}")
  else()
    message(STATUS "librga headers/library not found; hand RGA bridge is disabled")
  endif()
endif()

# Board-only validation target for the DMA-BUF -> RGA -> RKNN native path.
# This is deliberately opt-in: it requires the RKNN C API header matching the
# deployed librknnrt.so and is not installed or used by the Python provider.
option(MARSDOG_BUILD_HAND_DMABUF_PROBE
       "Build the opt-in Hand DMA-BUF/RGA/RKNN validation probe" OFF)
if(MARSDOG_BUILD_HAND_DMABUF_PROBE)
  if(NOT MARSDOG_RKNN_INCLUDE_DIR OR
     NOT EXISTS "${MARSDOG_RKNN_INCLUDE_DIR}/rknn_api.h" OR
     NOT MARSDOG_RKNN_LIBRARY OR
     NOT EXISTS "${MARSDOG_RKNN_LIBRARY}")
    message(FATAL_ERROR
      "MARSDOG_BUILD_HAND_DMABUF_PROBE requires explicit matching paths: "
      "-DMARSDOG_RKNN_INCLUDE_DIR=/path/to/include and "
      "-DMARSDOG_RKNN_LIBRARY=/path/to/librknnrt.so")
  endif()
  if(NOT MARSDOG_RGA_INCLUDE_DIR OR NOT MARSDOG_RGA_LIBRARY)
    message(FATAL_ERROR
      "MARSDOG_BUILD_HAND_DMABUF_PROBE requires the librga headers and library")
  endif()
  find_package(OpenSSL REQUIRED COMPONENTS Crypto)

  add_executable(hand_dmabuf_rga_rknn_probe
    native/hand_dmabuf_rga_rknn_probe.cpp)
  target_include_directories(hand_dmabuf_rga_rknn_probe PRIVATE
    ${MARSDOG_RGA_INCLUDE_DIR}
    ${MARSDOG_RKNN_INCLUDE_DIR})
  target_link_libraries(hand_dmabuf_rga_rknn_probe PRIVATE
    ${MARSDOG_RGA_LIBRARY}
    ${MARSDOG_RKNN_LIBRARY}
    OpenSSL::Crypto)
  set_target_properties(hand_dmabuf_rga_rknn_probe PROPERTIES
    BUILD_RPATH "$ORIGIN")
  message(STATUS "Building opt-in Hand DMA-BUF/RGA/RKNN probe")
endif()

rosidl_generate_interfaces(
  ${PROJECT_NAME}
  "srv/VisionTask.srv"
)

install(
  DIRECTORY ${PROJECT_NAME}/
  DESTINATION ${PYTHON_INSTALL_DIR}/${PROJECT_NAME}
  PATTERN "srv" EXCLUDE
  PATTERN "__pycache__" EXCLUDE
  PATTERN "*.pyc" EXCLUDE
)

install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME})

install(FILES scripts/fastdds_env.sh DESTINATION share/${PROJECT_NAME})

install(PROGRAMS
  scripts/vision_interaction
  scripts/camera_driver
  scripts/vision_debug_viewer
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
