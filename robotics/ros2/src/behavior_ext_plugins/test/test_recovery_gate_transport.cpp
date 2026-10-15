// Copyright 2026 MarsDog contributors
// SPDX-License-Identifier: Apache-2.0
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <thread>
#include "behaviortree_cpp_v3/bt_factory.h"
#include "nav2_msgs/msg/costmap.hpp"
#include "rclcpp/rclcpp.hpp"
#include "tf2_ros/buffer.h"
#include "geometry_msgs/msg/transform_stamped.hpp"

int main(int argc, char ** argv)
{
  if (argc != 2) {return 2;}
  setenv("ROS_DOMAIN_ID", "226", 1);
  setenv("ROS_LOCALHOST_ONLY", "1", 1);
  rclcpp::init(argc, argv);
  int result = 0;
  try {
    auto node = std::make_shared<rclcpp::Node>("occupied_start_transport_test");
    node->declare_parameter("robot_base_frame", "probe_base");
    // Synthetic TF is injected synchronously; never wait for an absent TF listener.
    node->declare_parameter("transform_tolerance", 0.0);
    node->declare_parameter("recovery_search_costmap_topic", "probe_costmap");
    node->declare_parameter("recovery_costmap_max_age", 5.0);
    auto tf = std::make_shared<tf2_ros::Buffer>(node->get_clock());
    geometry_msgs::msg::TransformStamped transform;
    transform.header.frame_id = "map";
    transform.child_frame_id = "probe_base";
    transform.transform.translation.x = 0.25;
    transform.transform.translation.y = 0.25;
    transform.transform.rotation.w = 1.0;
    tf->setTransform(transform, "test", true);
    auto blackboard = BT::Blackboard::create();
    blackboard->set("node", node);
    blackboard->set("tf_buffer", tf);
    BT::BehaviorTreeFactory factory;
    factory.registerFromPlugin(argv[1]);
    auto tree = factory.createTreeFromText(
      "<root><BehaviorTree ID='Main'><IsStartOccupied/></BehaviorTree></root>", blackboard);
    if (tree.tickRoot() != BT::NodeStatus::FAILURE) {
      throw std::runtime_error("Missing costmap must deny escape");
    }
    auto publisher = node->create_publisher<nav2_msgs::msg::Costmap>(
      "probe_costmap", rclcpp::QoS(1).transient_local().reliable());
    nav2_msgs::msg::Costmap map;
    map.header.frame_id = "map";
    map.metadata.size_x = 3;
    map.metadata.size_y = 3;
    map.metadata.resolution = 1.0;
    map.data.assign(9, 0);

    auto expect = [&](int cost, bool occupied, bool stale = false) {
        std::cout << "expect cost=" << cost << " occupied=" << occupied <<
          " stale=" << stale << std::endl;
        map.header.stamp = node->now();
        if (stale) {map.header.stamp.sec -= 6;}
        map.data[0] = cost;
        publisher->publish(map);
        for (int i = 0; i < 200; ++i) {
          const auto state = tree.tickRoot();
          if ((state == BT::NodeStatus::SUCCESS) == occupied) {return;}
          std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        throw std::runtime_error("Unexpected live gate result for cost " + std::to_string(cost));
      };
    expect(254, true);
    expect(0, false);
    expect(253, true);
    expect(255, false);
    expect(254, true);
    expect(254, false, true);
    expect(254, true);
    // Static transforms survive Buffer::clear(); break the required map/base chain.
    transform.header.frame_id = "disconnected_map";
    tf->setTransform(transform, "test", true);
    expect(254, false);
    transform.header.frame_id = "map";
    tf->setTransform(transform, "test", true);
    expect(254, true);
    transform.transform.translation.x = 50.0;
    tf->setTransform(transform, "test", true);
    expect(254, false);
    std::cout << "11 isolated costmap/TF cases passed; no motion publishers\n";
  } catch (const std::exception & error) {
    std::cerr << error.what() << '\n'; result = 1;
  }
  rclcpp::shutdown();
  return result;
}
