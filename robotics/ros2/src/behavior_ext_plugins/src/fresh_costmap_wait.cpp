// Copyright 2026 MarsDog contributors
// SPDX-License-Identifier: Apache-2.0
#include <cmath>
#include "behavior_ext_plugins/fresh_costmap_wait.hpp"

namespace behavior_ext_plugins
{
WaitForFreshCostmap::WaitForFreshCostmap(
  const std::string & name, const BT::NodeConfiguration & config)
: BT::StatefulActionNode(name, config)
{
  node_ = config.blackboard->get<rclcpp::Node::SharedPtr>("node");
  tf_ = config.blackboard->get<std::shared_ptr<tf2_ros::Buffer>>("tf_buffer");
  node_->get_parameter_or("recovery_observation_timeout", timeout_, 5.0);
  node_->get_parameter_or("recovery_fresh_costmap_topic", map_topic_,
    std::string("local_costmap/costmap_raw"));
  node_->get_parameter_or("recovery_costmap_update_topic", update_topic_,
    std::string("local_costmap/published_footprint"));
  node_->get_parameter_or("recovery_observation_topics", topics_,
    std::vector<std::string>{"/local_grid_obstacle", "/local_grid_ground"});
  observations_.resize(topics_.size());
  group_ = node_->create_callback_group(rclcpp::CallbackGroupType::MutuallyExclusive, false);
  executor_.add_callback_group(group_, node_->get_node_base_interface());
  rclcpp::SubscriptionOptions options;
  options.callback_group = group_;
  for (size_t index = 0; index < topics_.size(); ++index) {
    subscriptions_.push_back(node_->create_subscription<sensor_msgs::msg::PointCloud2>(
      topics_[index], rclcpp::SensorDataQoS(),
      [this, index](sensor_msgs::msg::PointCloud2::ConstSharedPtr cloud) {
        if (!active_ || observations_[index].received) {return;}
        const auto stamp = rclcpp::Time(cloud->header.stamp).nanoseconds();
        const auto now = node_->now().nanoseconds();
        // Receipt alone is insufficient: reject queued/pre-clear and future data.
        // Empty clouds are valid observations of an obstacle-free view.
        if (cloud->header.frame_id.empty() || stamp <= start_ros_ || stamp > now) {return;}
        observations_[index] = {cloud->header.frame_id, cloud->header.stamp, true};
        // RTAB-Map suppresses empty categories, so requiring BOTH marking and
        // ground topics would falsely time out in a completely free view.
        if (observations_received_ros_ == 0) {
          observations_received_ros_ = now;
        }
      }, options));
  }
  // Humble publishes a footprint only after updateMap successfully obtains the
  // robot pose and completes the layered costmap update. A raw snapshot alone
  // can also be republished when updateMap skipped an update due to missing TF.
  update_subscription_ = node_->create_subscription<geometry_msgs::msg::PolygonStamped>(
    update_topic_, rclcpp::QoS(10),
    [this](geometry_msgs::msg::PolygonStamped::ConstSharedPtr footprint) {
      if (!active_ || observations_received_ros_ == 0) {return;}
      const auto stamp = rclcpp::Time(footprint->header.stamp).nanoseconds();
      const auto now = node_->now().nanoseconds();
      if (stamp <= observations_received_ros_ || stamp > now ||
        footprint->header.frame_id.empty() || footprint->polygon.points.size() < 3)
      {
        return;
      }
      // Keep the first completed update, rather than moving the barrier on
      // every 12 Hz update and starving the slower costmap publication.
      if (update_received_ros_ == 0) {
        update_received_ros_ = now;
        update_frame_ = footprint->header.frame_id;
      }
    }, options);
  map_subscription_ = node_->create_subscription<nav2_msgs::msg::Costmap>(
    map_topic_, rclcpp::QoS(1).transient_local().reliable(),
    [this](nav2_msgs::msg::Costmap::ConstSharedPtr map) {
      if (!active_ || update_received_ros_ == 0) {return;}
      const auto stamp = rclcpp::Time(map->header.stamp).nanoseconds();
      const auto & meta = map->metadata;
      // Humble costmap_raw is a full snapshot on every publication, even when
      // always_send_full_costmap=false; metadata.update_time is left zero.
      if (stamp <= update_received_ros_ || stamp > node_->now().nanoseconds() ||
        map->header.frame_id != update_frame_ ||
        map->header.frame_id.empty() || meta.size_x == 0 || meta.size_y == 0 ||
        !std::isfinite(meta.resolution) || meta.resolution <= 0 ||
        !std::isfinite(meta.origin.position.x) || !std::isfinite(meta.origin.position.y) ||
        map->data.size() != static_cast<size_t>(meta.size_x) * meta.size_y)
      {
        return;
      }
      for (const auto & observation : observations_) {
        // Query BufferCore directly: this is a non-blocking availability check,
        // with no dedicated-listener-thread requirement from Buffer's wait API.
        if (observation.received && !tf_->tf2::BufferCore::canTransform(
            map->header.frame_id, observation.frame, tf2_ros::fromMsg(observation.stamp)))
        {
          return;
        }
      }
      ready_ = true;
    }, options);
}

BT::NodeStatus WaitForFreshCostmap::onStart()
{
  active_ = false;
  executor_.spin_some();  // Discard queued snapshots from an earlier recovery.
  observations_.clear();
  observations_.resize(topics_.size());
  ready_ = false;
  observations_received_ros_ = 0;
  update_received_ros_ = 0;
  update_frame_.clear();
  start_ros_ = node_->now().nanoseconds();
  if (!std::isfinite(timeout_) || timeout_ <= 0.0 || topics_.empty() || start_ros_ <= 0) {
    RCLCPP_ERROR(node_->get_logger(), "Invalid fresh-costmap wait configuration or ROS clock");
    return BT::NodeStatus::FAILURE;
  }
  deadline_ = std::chrono::steady_clock::now() +
    std::chrono::duration_cast<std::chrono::steady_clock::duration>(
    std::chrono::duration<double>(timeout_));
  active_ = true;
  RCLCPP_INFO(node_->get_logger(), "Waiting up to %.2f s for new observations and %s",
    timeout_, map_topic_.c_str());
  return BT::NodeStatus::RUNNING;
}

BT::NodeStatus WaitForFreshCostmap::onRunning()
{
  if (std::chrono::steady_clock::now() >= deadline_ ||
    node_->now().nanoseconds() < start_ros_)
  {
    active_ = false;
    RCLCPP_WARN(node_->get_logger(),
      "Recovery stopped: fresh observations/costmap timed out or ROS clock moved backwards");
    RCLCPP_WARN(node_->get_logger(), "  completed local costmap update observed: %s",
      update_received_ros_ != 0 ? "yes" : "no");
    for (size_t index = 0; index < topics_.size(); ++index) {
      RCLCPP_WARN(node_->get_logger(), "  %s: %s", topics_[index].c_str(),
        observations_[index].received ? "new observation received" : "waiting for new observation");
    }
    return BT::NodeStatus::FAILURE;
  }
  executor_.spin_some();
  if (ready_) {
    active_ = false;
    RCLCPP_INFO(node_->get_logger(), "New observations and subsequent local costmap received");
    return BT::NodeStatus::SUCCESS;
  }
  return BT::NodeStatus::RUNNING;
}

void WaitForFreshCostmap::onHalted()
{
  active_ = false;
  ready_ = false;
  observations_received_ros_ = 0;
  update_received_ros_ = 0;
}
}  // namespace behavior_ext_plugins
