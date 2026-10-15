// Copyright 2026 MarsDog contributors
// SPDX-License-Identifier: Apache-2.0
#include <chrono>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <thread>
#include "behaviortree_cpp_v3/bt_factory.h"
#include "geometry_msgs/msg/transform_stamped.hpp"
#include "geometry_msgs/msg/polygon_stamped.hpp"
#include "nav2_msgs/msg/costmap.hpp"
#include "rclcpp/rclcpp.hpp"
#include "sensor_msgs/msg/point_cloud2.hpp"
#include "tf2_ros/buffer.h"

using namespace std::chrono_literals;
namespace
{
void require(bool value, const std::string & text)
{
  if (!value) {throw std::runtime_error(text);}
}
}  // namespace

int main(int argc, char ** argv)
{
  if (argc != 2) {return 2;}
  // Synthetic localhost-only messages; never use a robot's DDS domain.
  setenv("ROS_DOMAIN_ID", "229", 1);
  setenv("ROS_LOCALHOST_ONLY", "1", 1);
  rclcpp::init(argc, argv);
  try {
    auto node = std::make_shared<rclcpp::Node>("fresh_costmap_wait_test");
    node->declare_parameter("recovery_observation_timeout", 0.30);
    node->declare_parameter("recovery_observation_topics",
      std::vector<std::string>{"/test/obstacle", "/test/ground"});
    node->declare_parameter("recovery_fresh_costmap_topic", "/test/costmap");
    node->declare_parameter("recovery_costmap_update_topic", "/test/footprint");
    auto tf = std::make_shared<tf2_ros::Buffer>(node->get_clock());
    geometry_msgs::msg::TransformStamped transform;
    transform.header.frame_id = "odom";
    transform.child_frame_id = "camera";
    transform.header.stamp = node->now();
    transform.transform.rotation.w = 1.0;
    tf->setTransform(transform, "isolated_test", true);
    auto obstacle = node->create_publisher<sensor_msgs::msg::PointCloud2>("/test/obstacle", 10);
    auto ground = node->create_publisher<sensor_msgs::msg::PointCloud2>("/test/ground", 10);
    auto map_pub = node->create_publisher<nav2_msgs::msg::Costmap>(
      "/test/costmap", rclcpp::QoS(1).transient_local().reliable());
    auto update_pub = node->create_publisher<geometry_msgs::msg::PolygonStamped>(
      "/test/footprint", 10);
    BT::BehaviorTreeFactory factory;
    factory.registerFromPlugin(argv[1]);
    auto blackboard = BT::Blackboard::create();
    blackboard->set("node", node);
    blackboard->set("tf_buffer", tf);
    auto tree = factory.createTreeFromText(
      "<root main_tree_to_execute='Main'><BehaviorTree ID='Main'>"
      "<WaitForFreshCostmap/></BehaviorTree></root>", blackboard);
    const auto discovery_end = std::chrono::steady_clock::now() + 3s;
    while (obstacle->get_subscription_count() == 0 || ground->get_subscription_count() == 0 ||
      map_pub->get_subscription_count() == 0 || update_pub->get_subscription_count() == 0)
    {
      require(std::chrono::steady_clock::now() < discovery_end, "DDS discovery timed out");
      std::this_thread::sleep_for(10ms);
    }
    auto tick_for = [&](std::chrono::milliseconds duration) {
        auto status = BT::NodeStatus::RUNNING;
        const auto end = std::chrono::steady_clock::now() + duration;
        do {
          status = tree.tickRoot();
          if (status != BT::NodeStatus::RUNNING) {break;}
          std::this_thread::sleep_for(3ms);
        } while (std::chrono::steady_clock::now() < end);
        return status;
      };
    auto cloud = [&](double age, const std::string & frame, bool send_ground = true) {
        sensor_msgs::msg::PointCloud2 message;
        message.header.stamp = node->now() - rclcpp::Duration::from_seconds(age);
        message.header.frame_id = frame;
        // An empty cloud still represents a fresh observation.
        obstacle->publish(message);
        if (send_ground) {ground->publish(message);}
      };
    auto map = [&](double age = 0.0, bool valid = true, bool updated = true) {
        if (updated) {
          geometry_msgs::msg::PolygonStamped footprint;
          footprint.header.stamp = node->now();
          footprint.header.frame_id = "odom";
          footprint.polygon.points.resize(4);
          update_pub->publish(footprint);
          tick_for(15ms);
        }
        nav2_msgs::msg::Costmap message;
        message.header.stamp = node->now() - rclcpp::Duration::from_seconds(age);
        message.header.frame_id = "odom";
        message.metadata.size_x = message.metadata.size_y = 2;
        message.metadata.resolution = 0.05;
        message.data.resize(valid ? 4 : 3);
        map_pub->publish(message);
      };
    int count = 0;
    auto run = [&](const std::string & name, const std::function<void()> & feed, bool success) {
        tree.haltTree();
        require(tree.tickRoot() == BT::NodeStatus::RUNNING, name + ": did not start");
        feed();
        const auto result = tick_for(400ms);
        require(result == (success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE),
          name + ": wrong result");
        std::cout << name << " PASS\n";
        ++count;
      };
    run("no observations or map", [] {}, false);
    run("map without observations", [&] {map();}, false);
    run("queued old observations", [&] {cloud(1.0, "camera"); tick_for(15ms); map();}, false);
    run("only marking observation, ground category empty", [&] {
        cloud(0.0, "camera", false); tick_for(15ms); map();
      }, true);
    run("only ground observation, obstacle category empty", [&] {
        sensor_msgs::msg::PointCloud2 message;
        message.header.stamp = node->now();
        message.header.frame_id = "camera";
        ground->publish(message); tick_for(15ms); map();
      }, true);
    run("observations without later map", [&] {cloud(0.0, "camera");}, false);
    run("old map after observations", [&] {cloud(0.0, "camera"); tick_for(15ms); map(1.0);}, false);
    run("future observations", [&] {cloud(-10.0, "camera"); tick_for(15ms); map();}, false);
    run("future map", [&] {cloud(0.0, "camera"); tick_for(15ms); map(-10.0);}, false);
    run("republished map without completed update", [&] {
        cloud(0.0, "camera"); tick_for(15ms); map(0.0, true, false);
      }, false);
    run("missing observation TF", [&] {cloud(0.0, "missing_camera"); tick_for(15ms); map();}, false);
    run("malformed map", [&] {cloud(0.0, "camera"); tick_for(15ms); map(0.0, false);}, false);
    run("fresh empty clouds and later full map", [&] {
        cloud(0.0, "camera"); tick_for(15ms); map();
      }, true);
    // Success/latched map and previous observations must not survive a new recovery.
    run("restart cannot reuse previous success", [&] {map();}, false);
    tree.haltTree();
    require(tree.tickRoot() == BT::NodeStatus::RUNNING, "cancel: failed start");
    cloud(0.0, "camera"); tick_for(15ms);
    run("cancel discards incomplete observation set", [&] {map();}, false);
    run("recovery after cancellation", [&] {
        cloud(0.0, "camera"); tick_for(15ms); map();
      }, true);
    tree.haltTree();
    std::cout << count << " fresh-costmap transport cases passed; no hardware or velocity publishers\n";
    rclcpp::shutdown();
    return 0;
  } catch (const std::exception & error) {
    std::cerr << error.what() << '\n';
    rclcpp::shutdown();
    return 1;
  }
}
