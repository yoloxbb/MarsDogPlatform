// Copyright 2026 MarsDog contributors
// SPDX-License-Identifier: Apache-2.0
#ifndef BEHAVIOR_EXT_PLUGINS__FRESH_COSTMAP_WAIT_HPP_
#define BEHAVIOR_EXT_PLUGINS__FRESH_COSTMAP_WAIT_HPP_

#include <chrono>
#include <memory>
#include <string>
#include <vector>
#include "behaviortree_cpp_v3/action_node.h"
#include "nav2_msgs/msg/costmap.hpp"
#include "geometry_msgs/msg/polygon_stamped.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/point_cloud2.hpp"
#include "tf2_ros/buffer.h"

namespace behavior_ext_plugins
{
// A receipt/publication fence, not an acknowledgement of individual STVL voxels.
// Runs after the clear service replies (and after successful escape movement).
class WaitForFreshCostmap : public BT::StatefulActionNode
{
public:
  WaitForFreshCostmap(const std::string & name, const BT::NodeConfiguration & config);
  static BT::PortsList providedPorts() {return {};}
  BT::NodeStatus onStart() override;
  BT::NodeStatus onRunning() override;
  void onHalted() override;

private:
  struct Observation
  {
    std::string frame;
    builtin_interfaces::msg::Time stamp;
    bool received{false};
  };
  rclcpp::Node::SharedPtr node_;
  std::shared_ptr<tf2_ros::Buffer> tf_;
  rclcpp::CallbackGroup::SharedPtr group_;
  rclcpp::executors::SingleThreadedExecutor executor_;
  std::vector<rclcpp::Subscription<sensor_msgs::msg::PointCloud2>::SharedPtr> subscriptions_;
  rclcpp::Subscription<nav2_msgs::msg::Costmap>::SharedPtr map_subscription_;
  rclcpp::Subscription<geometry_msgs::msg::PolygonStamped>::SharedPtr update_subscription_;
  std::vector<std::string> topics_;
  std::vector<Observation> observations_;
  std::string map_topic_, update_topic_, update_frame_;
  double timeout_{5.0};
  bool active_{false}, ready_{false};
  int64_t start_ros_{0}, observations_received_ros_{0};
  int64_t update_received_ros_{0};
  std::chrono::steady_clock::time_point deadline_;
};
}  // namespace behavior_ext_plugins
#endif  // BEHAVIOR_EXT_PLUGINS__FRESH_COSTMAP_WAIT_HPP_
