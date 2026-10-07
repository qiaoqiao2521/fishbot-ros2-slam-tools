// Exercise the shipped fallback with native BT controls, without ROS nodes.
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include "behaviortree_cpp/bt_factory.h"
#include "nav2_behavior_tree/plugins/condition/are_error_codes_present_condition.hpp"

struct Scenario
{
  BT::NodeStatus rpp = BT::NodeStatus::FAILURE;
  BT::NodeStatus mppi = BT::NodeStatus::RUNNING;
  int error = -1;  // No result: rejected goal or acknowledgement timeout.
  int rpp_starts = 0, mppi_starts = 0, rpp_halts = 0, mppi_halts = 0;
};

class FollowPathStub : public BT::StatefulActionNode
{
public:
  FollowPathStub(const std::string & name, const BT::NodeConfig & config, Scenario & scenario)
  : BT::StatefulActionNode(name, config), scenario_(scenario) {}

  static BT::PortsList providedPorts()
  {
    return {BT::InputPort<std::string>("path"), BT::InputPort<std::string>("controller_id"),
      BT::InputPort<std::string>("goal_checker_id"), BT::InputPort<std::string>("progress_checker_id"),
      BT::OutputPort<uint16_t>("error_code_id")};
  }

  BT::NodeStatus onStart() override
  {
    mppi_ = getInput<std::string>("controller_id").value() == "NarrowPassage";
    (mppi_ ? scenario_.mppi_starts : scenario_.rpp_starts)++;
    if (!mppi_ && scenario_.error >= 0) {
      setOutput("error_code_id", static_cast<uint16_t>(scenario_.error));
    }
    return mppi_ ? scenario_.mppi : scenario_.rpp;
  }

  BT::NodeStatus onRunning() override { return mppi_ ? scenario_.mppi : scenario_.rpp; }
  void onHalted() override { (mppi_ ? scenario_.mppi_halts : scenario_.rpp_halts)++; }

private:
  Scenario & scenario_;
  bool mppi_ = false;
};

void require(bool condition, const std::string & message)
{
  if (!condition) { throw std::runtime_error(message); }
}

int main(int argc, char ** argv)
{
  if (argc != 2) { return 2; }
  Scenario scenario;
  BT::BehaviorTreeFactory factory;
  factory.registerNodeType<nav2_behavior_tree::AreErrorCodesPresent>("AreErrorCodesPresent");
  factory.registerBuilder<FollowPathStub>("FollowPath",
    [&](const std::string & name, const BT::NodeConfig & config) {
      return std::make_unique<FollowPathStub>(name, config, scenario);
    });

  auto make_tree = [&]() {
      auto blackboard = BT::Blackboard::create();
      blackboard->set("path", std::string("fixture_path"));
      // A previous narrow-passage failure must not survive an ACK timeout.
      blackboard->set("follow_path_error_code", static_cast<uint16_t>(106));
      return factory.createTreeFromFile(argv[1], blackboard);
    };

  for (int code : {104, 105, 106}) {
    scenario = Scenario{};
    scenario.error = code;
    auto tree = make_tree();
    require(tree.tickExactlyOnce() == BT::NodeStatus::RUNNING, "allowed failure must start MPPI");
    require(scenario.rpp_starts == 1 && scenario.mppi_starts == 1, "exactly one handoff");
    require(tree.tickExactlyOnce() == BT::NodeStatus::RUNNING, "MPPI remains running");
    require(scenario.rpp_starts == 1, "running MPPI must not restart RPP");
    tree.haltTree();
    require(scenario.mppi_halts == 1, "tree cancellation must halt active MPPI");
    scenario.rpp = BT::NodeStatus::SUCCESS;
    require(tree.tickExactlyOnce() == BT::NodeStatus::SUCCESS, "next goal restarts RPP");
    require(scenario.rpp_starts == 2 && scenario.mppi_starts == 1, "no sticky MPPI selection");
  }
  for (int code : {-1, 0, 100, 101, 102, 103, 107}) {
    scenario = Scenario{};
    scenario.error = code;
    auto tree = make_tree();
    require(tree.tickExactlyOnce() == BT::NodeStatus::FAILURE, "non-control error must fail");
    require(scenario.mppi_starts == 0, "non-control error must not enter MPPI");
  }
  scenario = Scenario{};
  scenario.rpp = BT::NodeStatus::RUNNING;
  auto tree = make_tree();
  require(tree.tickExactlyOnce() == BT::NodeStatus::RUNNING, "normal RPP remains active");
  tree.haltTree();
  require(scenario.rpp_halts == 1 && scenario.mppi_starts == 0, "cancel RPP without fallback");
  std::cout << "11 native BT lifecycle scenarios passed; no ROS graph or actions started\n";
}
