// Copyright 2026 MarsDog contributors
// SPDX-License-Identifier: Apache-2.0
#include <memory>
#include <string>
#include "behaviortree_cpp_v3/bt_factory.h"
#include "behavior_ext_plugins/occupied_start.hpp"
#include "behavior_ext_plugins/fresh_costmap_wait.hpp"
#include "nav_msgs/msg/path.hpp"
#include "nav2_util/robot_utils.hpp"
#include "rclcpp/rclcpp.hpp"
#include "tf2_ros/buffer.h"

namespace behavior_ext_plugins
{

class HasValidPath : public BT::ConditionNode
{
public:
  HasValidPath(const std::string & name, const BT::NodeConfiguration & config)
  : BT::ConditionNode(name, config) {}

  static BT::PortsList providedPorts()
  {
    return {BT::InputPort<nav_msgs::msg::Path>("path", "Path to follow")};
  }

  BT::NodeStatus tick() override
  {
    nav_msgs::msg::Path path;
    return getInput("path", path) && !path.poses.empty() ?
           BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
  }
};

class IsStartOccupied : public BT::ConditionNode
{
public:
  IsStartOccupied(const std::string & name, const BT::NodeConfiguration & config)
  : BT::ConditionNode(name, config)
  {
    node_ = config.blackboard->get<rclcpp::Node::SharedPtr>("node");
    tf_ = config.blackboard->get<std::shared_ptr<tf2_ros::Buffer>>("tf_buffer");
    node_->get_parameter_or("robot_base_frame", base_frame_, std::string("base_link"));
    node_->get_parameter_or("transform_tolerance", transform_tolerance_, 0.2);
    node_->get_parameter_or("recovery_search_costmap_topic", topic_,
      std::string("global_costmap/costmap_raw"));
    node_->get_parameter_or("recovery_start_occupied_cost", occupied_cost_, 253);
    node_->get_parameter_or("recovery_costmap_max_age", max_age_, 5.0);

    callback_group_ = node_->create_callback_group(
      rclcpp::CallbackGroupType::MutuallyExclusive, false);
    executor_.add_callback_group(callback_group_, node_->get_node_base_interface());
    rclcpp::SubscriptionOptions options;
    options.callback_group = callback_group_;
    subscription_ = node_->create_subscription<nav2_msgs::msg::Costmap>(
      topic_, rclcpp::QoS(1).transient_local().reliable(),
      [this](nav2_msgs::msg::Costmap::SharedPtr map) {
        std::atomic_store(&map_, map);
      }, options);
  }

  static BT::PortsList providedPorts() {return {};}

  BT::NodeStatus tick() override
  {
    executor_.spin_some();
    const auto map = std::atomic_load(&map_);
    if (!map || map->header.frame_id.empty()) {
      return BT::NodeStatus::FAILURE;
    }
    geometry_msgs::msg::PoseStamped pose;
    if (!nav2_util::getCurrentPose(
        pose, *tf_, map->header.frame_id, base_frame_, transform_tolerance_))
    {
      return BT::NodeStatus::FAILURE;
    }
    return occupiedStart(*map, pose.pose.position.x, pose.pose.position.y,
      node_->now().seconds(), max_age_, occupied_cost_) ?
           BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
  }

private:
  rclcpp::Node::SharedPtr node_;
  std::shared_ptr<tf2_ros::Buffer> tf_;
  rclcpp::CallbackGroup::SharedPtr callback_group_;
  rclcpp::executors::SingleThreadedExecutor executor_;
  rclcpp::Subscription<nav2_msgs::msg::Costmap>::SharedPtr subscription_;
  nav2_msgs::msg::Costmap::SharedPtr map_;
  std::string base_frame_, topic_;
  int occupied_cost_{253};
  double max_age_{5.0}, transform_tolerance_{0.2};
};

}  // namespace behavior_ext_plugins

BT_REGISTER_NODES(factory)
{
  factory.registerNodeType<behavior_ext_plugins::IsStartOccupied>("IsStartOccupied");
  factory.registerNodeType<behavior_ext_plugins::HasValidPath>("HasValidPath");
  factory.registerNodeType<behavior_ext_plugins::WaitForFreshCostmap>("WaitForFreshCostmap");
}
