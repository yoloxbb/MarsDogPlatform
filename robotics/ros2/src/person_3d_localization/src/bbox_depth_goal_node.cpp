// Copyright 2026 bird
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include <image_geometry/pinhole_camera_model.h>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2/time.h>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.h>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstdint>
#include <deque>
#include <limits>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>

#include <geometry_msgs/msg/point_stamped.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/camera_info.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>

#include "person_3d_localization/bbox_depth_processor.hpp"
#include "person_3d_localization/srv/locate_from_bbox.hpp"

namespace person_3d_localization
{

class BboxDepthGoalNode : public rclcpp::Node
{
public:
  // 声明参数并创建深度缓存、CameraInfo 缓存、TF 和单次定位服务。
  BboxDepthGoalNode()
  : Node("bbox_depth_goal_node")
  {
    depth_topic_ = declare_parameter<std::string>(
      "depth_topic", "/camera/camera/aligned_depth_to_color/image_raw");
    camera_info_topic_ = declare_parameter<std::string>(
      "camera_info_topic", "/camera/camera/color/camera_info");
    service_name_ = declare_parameter<std::string>(
      "service_name", "/person_3d_localization/locate_from_bbox");
    person_point_topic_ = declare_parameter<std::string>(
      "person_point_topic", "/person_3d_localization/person_point");
    navigation_goal_topic_ = declare_parameter<std::string>(
      "navigation_goal_topic", "/person_3d_localization/navigation_goal");
    target_frame_ = declare_parameter<std::string>("target_frame", "map");
    robot_frame_ = declare_parameter<std::string>("robot_frame", "base_footprint");
    default_stand_off_distance_ = declare_parameter<double>(
      "default_stand_off_distance", 1.5);
    arrival_tolerance_ = declare_parameter<double>("arrival_tolerance", 0.15);
    max_timestamp_difference_ = declare_parameter<double>(
      "max_timestamp_difference", 0.05);
    max_latest_depth_age_ = declare_parameter<double>("max_latest_depth_age", 0.5);
    tf_timeout_ = declare_parameter<double>("tf_timeout", 0.3);
    cache_size_ = declare_parameter<int>("cache_size", 60);

    BboxDepthConfig processor_config;
    processor_config.depth_min = declare_parameter<double>("depth_min", 0.3);
    processor_config.depth_max = declare_parameter<double>("depth_max", 6.0);
    processor_config.depth_16u_scale = declare_parameter<double>("depth_16u_scale", 0.001);
    processor_config.bbox_width_scale = declare_parameter<double>("bbox_width_scale", 0.6);
    processor_config.bbox_height_scale = declare_parameter<double>("bbox_height_scale", 0.7);
    processor_config.mad_scale = declare_parameter<double>("mad_scale", 3.0);
    processor_config.min_depth_deviation = declare_parameter<double>(
      "min_depth_deviation", 0.08);
    processor_config.max_depth_deviation = declare_parameter<double>(
      "max_depth_deviation", 0.40);
    processor_config.min_valid_depth_ratio = declare_parameter<double>(
      "min_valid_depth_ratio", 0.20);
    processor_config.min_valid_points = declare_parameter<int>("min_valid_points", 30);
    processor_config.sample_stride = declare_parameter<int>("sample_stride", 2);

    ValidateParameters();
    processor_ = std::make_unique<BboxDepthProcessor>(processor_config);
    tf_buffer_ = std::make_unique<tf2_ros::Buffer>(get_clock());
    tf_listener_ = std::make_shared<tf2_ros::TransformListener>(*tf_buffer_);

    const auto sensor_qos = rclcpp::SensorDataQoS().keep_last(10);
    depth_subscription_ = create_subscription<sensor_msgs::msg::Image>(
      depth_topic_, sensor_qos,
      std::bind(&BboxDepthGoalNode::OnDepth, this, std::placeholders::_1));
    camera_info_subscription_ = create_subscription<sensor_msgs::msg::CameraInfo>(
      camera_info_topic_, sensor_qos,
      std::bind(&BboxDepthGoalNode::OnCameraInfo, this, std::placeholders::_1));

    person_point_publisher_ = create_publisher<geometry_msgs::msg::PointStamped>(
      person_point_topic_, rclcpp::QoS(1).reliable());
    navigation_goal_publisher_ = create_publisher<geometry_msgs::msg::PoseStamped>(
      navigation_goal_topic_, rclcpp::QoS(1).reliable());
    locate_service_ = create_service<person_3d_localization::srv::LocateFromBbox>(
      service_name_,
      std::bind(
        &BboxDepthGoalNode::OnLocate, this, std::placeholders::_1, std::placeholders::_2));

    RCLCPP_INFO(
      get_logger(),
      "单次 bbox 深度定位已启动: depth=%s, camera_info=%s, service=%s",
      depth_topic_.c_str(), camera_info_topic_.c_str(), service_name_.c_str());
  }

private:
  using LocateFromBbox = person_3d_localization::srv::LocateFromBbox;
  using DepthPtr = sensor_msgs::msg::Image::ConstSharedPtr;
  using CameraInfoPtr = sensor_msgs::msg::CameraInfo::ConstSharedPtr;

  // 校验服务、缓存、时间同步和坐标系参数。
  void ValidateParameters() const
  {
    if (depth_topic_.empty() || camera_info_topic_.empty() || service_name_.empty() ||
      target_frame_.empty() || robot_frame_.empty())
    {
      throw std::invalid_argument("话题、服务和坐标系名称不得为空");
    }
    if (!(default_stand_off_distance_ > 0.0) || arrival_tolerance_ < 0.0 ||
      !(max_timestamp_difference_ > 0.0) || !(max_latest_depth_age_ > 0.0) ||
      !(tf_timeout_ > 0.0) || cache_size_ <= 0)
    {
      throw std::invalid_argument("安全距离、时间容差、TF 超时或缓存大小不合法");
    }
  }

  // 缓存最新深度图，并限制队列长度防止长期占用内存。
  void OnDepth(const DepthPtr message)
  {
    std::lock_guard<std::mutex> lock(cache_mutex_);
    depth_cache_.push_back(message);
    while (depth_cache_.size() > static_cast<std::size_t>(cache_size_)) {
      depth_cache_.pop_front();
    }
  }

  // 缓存 CameraInfo，使服务可按深度帧时间戳选择对应内参。
  void OnCameraInfo(const CameraInfoPtr message)
  {
    std::lock_guard<std::mutex> lock(cache_mutex_);
    camera_info_cache_.push_back(message);
    while (camera_info_cache_.size() > static_cast<std::size_t>(cache_size_)) {
      camera_info_cache_.pop_front();
    }
  }

  // 把 ROS 时间戳转换为整数纳秒，避免不同 ClockType 参与直接比较。
  static int64_t StampNanoseconds(const builtin_interfaces::msg::Time & stamp)
  {
    return static_cast<int64_t>(stamp.sec) * 1000000000LL +
           static_cast<int64_t>(stamp.nanosec);
  }

  // 判断上层是否未提供图像时间戳；零时间戳会回退到最新深度帧。
  static bool IsZeroStamp(const builtin_interfaces::msg::Time & stamp)
  {
    return stamp.sec == 0 && stamp.nanosec == 0U;
  }

  // 在已加锁的深度缓存中查找与 bbox 图像时间最接近的帧。
  DepthPtr FindDepthLocked(
    const builtin_interfaces::msg::Time & requested_stamp,
    double & time_difference) const
  {
    time_difference = std::numeric_limits<double>::infinity();
    if (depth_cache_.empty()) {
      return nullptr;
    }
    if (IsZeroStamp(requested_stamp)) {
      time_difference = 0.0;
      return depth_cache_.back();
    }

    const int64_t requested_ns = StampNanoseconds(requested_stamp);
    DepthPtr closest;
    int64_t closest_difference_ns = std::numeric_limits<int64_t>::max();
    for (const auto & depth : depth_cache_) {
      const int64_t difference_ns = std::llabs(
        StampNanoseconds(depth->header.stamp) - requested_ns);
      if (difference_ns < closest_difference_ns) {
        closest_difference_ns = difference_ns;
        closest = depth;
      }
    }
    time_difference = static_cast<double>(closest_difference_ns) * 1e-9;
    return closest;
  }

  // 在已加锁的 CameraInfo 缓存中查找与深度帧最接近的内参。
  CameraInfoPtr FindCameraInfoLocked(
    const builtin_interfaces::msg::Time & depth_stamp,
    double & time_difference) const
  {
    time_difference = std::numeric_limits<double>::infinity();
    if (camera_info_cache_.empty()) {
      return nullptr;
    }

    const int64_t depth_ns = StampNanoseconds(depth_stamp);
    CameraInfoPtr closest;
    int64_t closest_difference_ns = std::numeric_limits<int64_t>::max();
    for (const auto & camera_info : camera_info_cache_) {
      const int64_t difference_ns = std::llabs(
        StampNanoseconds(camera_info->header.stamp) - depth_ns);
      if (difference_ns < closest_difference_ns) {
        closest_difference_ns = difference_ns;
        closest = camera_info;
      }
    }
    time_difference = static_cast<double>(closest_difference_ns) * 1e-9;
    return closest;
  }

  // 统一填写失败响应，确保上层能够区分深度、请求和 TF 错误。
  static void SetFailure(
    const std::shared_ptr<LocateFromBbox::Response> & response,
    uint8_t status,
    const std::string & message)
  {
    response->success = false;
    response->navigation_required = false;
    response->status = status;
    response->message = message;
  }

  // 处理一次 bbox 定位请求并返回人体点和固定 Nav2 目标。
  void OnLocate(
    const std::shared_ptr<LocateFromBbox::Request> request,
    std::shared_ptr<LocateFromBbox::Response> response)
  {
    if (request->bbox.width == 0U || request->bbox.height == 0U) {
      SetFailure(response, LocateFromBbox::Response::STATUS_INVALID_BBOX, "bbox 尺寸为空");
      return;
    }
    const double stand_off_distance = request->stand_off_distance > 0.0F ?
      static_cast<double>(request->stand_off_distance) : default_stand_off_distance_;
    if (!std::isfinite(stand_off_distance) || stand_off_distance <= 0.0) {
      SetFailure(
        response, LocateFromBbox::Response::STATUS_INVALID_REQUEST, "安全距离必须为正数");
      return;
    }

    DepthPtr depth;
    CameraInfoPtr camera_info;
    double depth_time_difference = 0.0;
    double camera_info_time_difference = 0.0;
    {
      std::lock_guard<std::mutex> lock(cache_mutex_);
      depth = FindDepthLocked(request->image_header.stamp, depth_time_difference);
      if (depth) {
        camera_info = FindCameraInfoLocked(
          depth->header.stamp, camera_info_time_difference);
      }
    }

    if (!depth) {
      SetFailure(response, LocateFromBbox::Response::STATUS_NO_DEPTH, "尚未收到深度图");
      return;
    }
    if (!IsZeroStamp(request->image_header.stamp) &&
      depth_time_difference > max_timestamp_difference_)
    {
      SetFailure(
        response, LocateFromBbox::Response::STATUS_NO_DEPTH,
        "缓存中没有与 bbox 时间戳匹配的深度帧");
      return;
    }
    if (IsZeroStamp(request->image_header.stamp)) {
      const double depth_age = static_cast<double>(
        now().nanoseconds() - StampNanoseconds(depth->header.stamp)) * 1e-9;
      if (depth_age > max_latest_depth_age_) {
        SetFailure(
          response, LocateFromBbox::Response::STATUS_NO_DEPTH, "最新深度帧已经过期");
        return;
      }
    }
    if (!camera_info || camera_info_time_difference > max_timestamp_difference_) {
      SetFailure(
        response, LocateFromBbox::Response::STATUS_NO_CAMERA_INFO,
        "缓存中没有与深度帧匹配的 CameraInfo");
      return;
    }
    if (camera_info->width != depth->width || camera_info->height != depth->height) {
      SetFailure(
        response, LocateFromBbox::Response::STATUS_NO_CAMERA_INFO,
        "CameraInfo 与深度图分辨率不一致");
      return;
    }

    image_geometry::PinholeCameraModel camera_model;
    camera_model.fromCameraInfo(*camera_info);
    const BboxDepthResult depth_result = processor_->Process(
      *depth, request->bbox, camera_model);
    response->valid_depth_ratio = static_cast<float>(depth_result.valid_depth_ratio);
    response->mean_depth = static_cast<float>(depth_result.mean_depth);
    response->depth_stddev = static_cast<float>(depth_result.depth_stddev);
    if (!depth_result.success) {
      SetFailure(
        response, LocateFromBbox::Response::STATUS_INVALID_DEPTH, depth_result.message);
      return;
    }

    const std::string source_frame = !depth->header.frame_id.empty() ?
      depth->header.frame_id : camera_info->header.frame_id;
    if (source_frame.empty()) {
      SetFailure(
        response, LocateFromBbox::Response::STATUS_INVALID_REQUEST,
        "深度图和 CameraInfo 均缺少 frame_id");
      return;
    }

    geometry_msgs::msg::PointStamped camera_point;
    camera_point.header.stamp = depth->header.stamp;
    camera_point.header.frame_id = source_frame;
    camera_point.point = depth_result.point;

    geometry_msgs::msg::TransformStamped camera_to_target;
    geometry_msgs::msg::TransformStamped robot_to_target;
    try {
      const rclcpp::Time measurement_time(depth->header.stamp);
      camera_to_target = tf_buffer_->lookupTransform(
        target_frame_, source_frame, measurement_time, tf2::durationFromSec(tf_timeout_));
      robot_to_target = tf_buffer_->lookupTransform(
        target_frame_, robot_frame_, measurement_time, tf2::durationFromSec(tf_timeout_));
    } catch (const tf2::TransformException & exception) {
      SetFailure(
        response, LocateFromBbox::Response::STATUS_TF_UNAVAILABLE,
        std::string("无法取得测量时刻 TF: ") + exception.what());
      return;
    }

    tf2::doTransform(camera_point, response->person_point, camera_to_target);
    const double robot_x = robot_to_target.transform.translation.x;
    const double robot_y = robot_to_target.transform.translation.y;
    const double delta_x = response->person_point.point.x - robot_x;
    const double delta_y = response->person_point.point.y - robot_y;
    const double person_distance = std::hypot(delta_x, delta_y);
    if (!std::isfinite(person_distance) || person_distance < 1e-6) {
      SetFailure(
        response, LocateFromBbox::Response::STATUS_INVALID_DEPTH,
        "人体点与机器人平面位置重合，无法计算目标方向");
      return;
    }

    response->navigation_goal.header.stamp = now();
    response->navigation_goal.header.frame_id = target_frame_;
    response->navigation_goal.pose.position.z = 0.0;
    response->navigation_required = person_distance > stand_off_distance + arrival_tolerance_;
    if (response->navigation_required) {
      const double direction_x = delta_x / person_distance;
      const double direction_y = delta_y / person_distance;
      response->navigation_goal.pose.position.x =
        response->person_point.point.x - stand_off_distance * direction_x;
      response->navigation_goal.pose.position.y =
        response->person_point.point.y - stand_off_distance * direction_y;
    } else {
      response->navigation_goal.pose.position.x = robot_x;
      response->navigation_goal.pose.position.y = robot_y;
    }

    // 目标航向始终面向人体；即使无需平移，上层也可选择是否执行原地转向。
    const double goal_yaw = std::atan2(
      response->person_point.point.y - response->navigation_goal.pose.position.y,
      response->person_point.point.x - response->navigation_goal.pose.position.x);
    tf2::Quaternion orientation;
    orientation.setRPY(0.0, 0.0, goal_yaw);
    response->navigation_goal.pose.orientation = tf2::toMsg(orientation);

    response->success = true;
    response->status = LocateFromBbox::Response::STATUS_OK;
    response->message = response->navigation_required ?
      "成功生成固定导航目标" : "机器人已在安全距离内，无需平移导航";

    person_point_publisher_->publish(response->person_point);
    navigation_goal_publisher_->publish(response->navigation_goal);
    RCLCPP_INFO(
      get_logger(),
      "bbox 定位成功: 人体=(%.3f, %.3f, %.3f), 目标=(%.3f, %.3f), 有效深度=%.1f%%",
      response->person_point.point.x,
      response->person_point.point.y,
      response->person_point.point.z,
      response->navigation_goal.pose.position.x,
      response->navigation_goal.pose.position.y,
      100.0 * response->valid_depth_ratio);
  }

  std::string depth_topic_;
  std::string camera_info_topic_;
  std::string service_name_;
  std::string person_point_topic_;
  std::string navigation_goal_topic_;
  std::string target_frame_;
  std::string robot_frame_;
  double default_stand_off_distance_{1.5};
  double arrival_tolerance_{0.15};
  double max_timestamp_difference_{0.05};
  double max_latest_depth_age_{0.5};
  double tf_timeout_{0.3};
  int cache_size_{60};

  std::mutex cache_mutex_;
  std::deque<DepthPtr> depth_cache_;
  std::deque<CameraInfoPtr> camera_info_cache_;
  std::unique_ptr<BboxDepthProcessor> processor_;
  std::unique_ptr<tf2_ros::Buffer> tf_buffer_;
  std::shared_ptr<tf2_ros::TransformListener> tf_listener_;
  rclcpp::Subscription<sensor_msgs::msg::Image>::SharedPtr depth_subscription_;
  rclcpp::Subscription<sensor_msgs::msg::CameraInfo>::SharedPtr camera_info_subscription_;
  rclcpp::Publisher<geometry_msgs::msg::PointStamped>::SharedPtr person_point_publisher_;
  rclcpp::Publisher<geometry_msgs::msg::PoseStamped>::SharedPtr navigation_goal_publisher_;
  rclcpp::Service<LocateFromBbox>::SharedPtr locate_service_;
};

}  // namespace person_3d_localization

// 初始化 ROS 2 并运行单次 bbox 深度定位节点。
int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<person_3d_localization::BboxDepthGoalNode>());
  rclcpp::shutdown();
  return 0;
}
