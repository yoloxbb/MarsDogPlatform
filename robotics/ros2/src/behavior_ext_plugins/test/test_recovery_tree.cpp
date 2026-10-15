// Copyright 2026 MarsDog contributors
// SPDX-License-Identifier: Apache-2.0
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include "behaviortree_cpp_v3/bt_factory.h"
#include "nav_msgs/msg/path.hpp"
#include "geometry_msgs/msg/pose_stamped.hpp"

namespace
{
struct Scenario
{
  bool occupied;
  bool reachable_after_move;
  bool planning_succeeds;
  bool follow_fails;
  bool first_goal_tick{true};
  bool fresh{true};
  int plans{0}, follows{0}, moves{0}, clears{0}, waits{0};
};
Scenario * scenario;

class Compute : public BT::SyncActionNode
{
public:
  Compute(const std::string & name, const BT::NodeConfiguration & config)
  : BT::SyncActionNode(name, config) {}
  static BT::PortsList providedPorts()
  {
    return {
      BT::InputPort<geometry_msgs::msg::PoseStamped>("goal"),
      BT::InputPort<std::vector<geometry_msgs::msg::PoseStamped>>("goals"),
      BT::InputPort<std::string>("planner_id"),
      BT::OutputPort<nav_msgs::msg::Path>("path")};
  }
  BT::NodeStatus tick() override
  {
    ++scenario->plans;
    nav_msgs::msg::Path path;
    const bool success = scenario->planning_succeeds ||
      (scenario->moves > 0 && scenario->reachable_after_move);
    if (success) {path.poses.resize(2);}
    // Match Nav2: failed planning clears the output path.
    setOutput("path", path);
    return success ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
  }
};

class Follow : public BT::SyncActionNode
{
public:
  Follow(const std::string & name, const BT::NodeConfiguration & config)
  : BT::SyncActionNode(name, config) {}
  static BT::PortsList providedPorts()
  {
    return {BT::InputPort<nav_msgs::msg::Path>("path"),
      BT::InputPort<std::string>("controller_id"), BT::InputPort<std::string>("goal_checker_id")};
  }
  BT::NodeStatus tick() override
  {
    nav_msgs::msg::Path path;
    if (!getInput("path", path) || path.poses.empty()) {
      throw std::runtime_error("Empty path reached FollowPath");
    }
    ++scenario->follows;
    return scenario->follow_fails ? BT::NodeStatus::FAILURE : BT::NodeStatus::SUCCESS;
  }
};

class Move : public BT::SyncActionNode
{
public:
  Move(const std::string & name, const BT::NodeConfiguration & config)
  : BT::SyncActionNode(name, config) {}
  static BT::PortsList providedPorts()
  {
    return {BT::InputPort<double>("backup_dist"), BT::InputPort<double>("backup_speed"),
      BT::InputPort<double>("time_allowance")};
  }
  BT::NodeStatus tick() override
  {
    if (!scenario->occupied) {throw std::runtime_error("Moving from a free start");}
    ++scenario->moves;
    scenario->occupied = false;
    return BT::NodeStatus::SUCCESS;
  }
};

class Smooth : public BT::SyncActionNode
{
public:
  Smooth(const std::string & name, const BT::NodeConfiguration & config)
  : BT::SyncActionNode(name, config) {}
  static BT::PortsList providedPorts()
  {
    return {BT::InputPort<nav_msgs::msg::Path>("unsmoothed_path"),
      BT::OutputPort<nav_msgs::msg::Path>("smoothed_path"),
      BT::InputPort<std::string>("smoother_id"), BT::InputPort<double>("max_smoothing_duration"),
      BT::InputPort<bool>("check_for_collisions")};
  }
  BT::NodeStatus tick() override
  {
    nav_msgs::msg::Path path;
    if (!getInput("unsmoothed_path", path) || path.poses.empty()) {
      throw std::runtime_error("Empty path reached smoothing");
    }
    setOutput("smoothed_path", path);
    return BT::NodeStatus::SUCCESS;
  }
};

void require(bool value, const std::string & description)
{
  if (!value) {throw std::runtime_error(description);}
}
}  // namespace

int main(int argc, char ** argv)
{
  if (argc != 7) {return 2;}
  try {
    BT::BehaviorTreeFactory factory;
    for (int i = 1; i <= 4; ++i) {factory.registerFromPlugin(argv[i]);}
    require(factory.unregisterBuilder("IsStartOccupied"), "Missing actual recovery gate plugin");
    // Substitute only costmap/TF input; exercise installed control nodes and actual XML.
    factory.registerSimpleCondition("IsStartOccupied", [](BT::TreeNode &) {
        return scenario->occupied ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
      });
    factory.registerSimpleCondition("GlobalUpdatedGoal", [](BT::TreeNode &) {
        const bool first = scenario->first_goal_tick;
        scenario->first_goal_tick = false;
        return first ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
      });
    factory.registerSimpleCondition("GoalUpdated", [](BT::TreeNode &) {
        return BT::NodeStatus::FAILURE;
      });
    factory.registerNodeType<Compute>("ComputePathToPose");
    factory.registerNodeType<Compute>("ComputePathThroughPoses");
    factory.registerNodeType<Follow>("FollowPath");
    factory.registerNodeType<Move>("BackUp");
    factory.registerNodeType<Smooth>("SmoothPath");
    factory.registerSimpleAction("ClearEntireCostmap", [](BT::TreeNode &) {
        ++scenario->clears; return BT::NodeStatus::SUCCESS;
      }, {BT::InputPort<std::string>("service_name")});
    require(factory.unregisterBuilder("WaitForFreshCostmap"), "Missing fresh-costmap wait plugin");
    factory.registerSimpleAction("WaitForFreshCostmap", [](BT::TreeNode &) {
        ++scenario->waits; return scenario->fresh ? BT::NodeStatus::SUCCESS : BT::NodeStatus::FAILURE;
      });
    factory.registerSimpleAction("RemovePassedGoals", [](BT::TreeNode &) {
        return BT::NodeStatus::SUCCESS;
      }, {BT::InputPort<std::vector<geometry_msgs::msg::PoseStamped>>("input_goals"),
        BT::OutputPort<std::vector<geometry_msgs::msg::PoseStamped>>("output_goals"),
        BT::InputPort<double>("radius")});

    int cases = 0;
    for (int file = 5; file <= 6; ++file) {
      std::ifstream input(argv[file]);
      std::string xml((std::istreambuf_iterator<char>(input)), std::istreambuf_iterator<char>());
      require(!xml.empty(), "Missing installed behavior tree");
      // GoalUpdater is unrelated to the recovery policy and has ROS subscriptions.
      const auto updater = xml.find("<GoalUpdater input_goal=");
      if (updater != std::string::npos) {
        xml.erase(updater, xml.find('>', updater) - updater + 1);
        const auto close = xml.find("</GoalUpdater>");
        xml.erase(close, std::string("</GoalUpdater>").size());
      }
      for (int test = 0; test < 6; ++test) {
        Scenario current{test == 1 || test == 2 || test == 5, test == 1, test == 3, test == 3};
        current.fresh = test < 4;
        scenario = &current;
        auto blackboard = BT::Blackboard::create();
        auto tree = factory.createTreeFromText(xml, blackboard);
        auto status = tree.tickRoot();
        while (status == BT::NodeStatus::RUNNING) {status = tree.tickRoot();}
        if (test == 0) {
          require(status == BT::NodeStatus::FAILURE && current.moves == 0 &&
            current.follows == 0 && current.plans == 2 && current.clears == 1,
            "Free start/unreachable goal must fail without moving or following an empty path");
        } else if (test == 1) {
          require(status == BT::NodeStatus::SUCCESS && current.moves == 1 && current.follows == 1,
            "Occupied start must retain the custom escape behavior");
        } else if (test == 2) {
          require(status == BT::NodeStatus::FAILURE && current.moves == 1 && current.follows == 0,
            "Unreachable goal after leaving occupancy must stop further escape moves");
        } else if (test >= 4) {
          require(status == BT::NodeStatus::FAILURE && current.moves == 0 &&
            current.plans == 1 && current.clears == 1 && current.waits == 1,
            "Fresh-data timeout must abort without replanning or trying escape, even if occupied");
        } else {
          require(status == BT::NodeStatus::FAILURE && current.moves == 0 && current.follows == 7,
            "Controller failure from free space must not authorize escape motion");
        }
        ++cases;
        std::cout << "tree=" << file - 5 << " case=" << test << " plans=" << current.plans <<
          " moves=" << current.moves << " follows=" << current.follows << " PASS\n";
      }
    }
    std::cout << cases << " recovery-policy cases passed; no ROS nodes or velocity publishers\n";
  } catch (const std::exception & error) {
    std::cerr << error.what() << '\n'; return 1;
  }
}
