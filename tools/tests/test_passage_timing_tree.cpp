// Offline execution of the production XML with real Nav2 control plugins.
// Action substitutes return scripted results; no ROS context or hardware exists.
#include <behaviortree_cpp/bt_factory.h>

#include <deque>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Status = BT::NodeStatus;

void require(bool condition, const std::string &message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

struct Scenario {
  std::deque<uint16_t> planner_results;
  std::deque<uint16_t> controller_results;
  int planner_calls = 0;
  int controller_calls = 0;
  int local_clears = 0;
  int global_clears = 0;
  int waits = 0;
  int wait_halts = 0;
  bool complete_wait = true;
  bool goal_updated = false;
};

uint16_t next_result(std::deque<uint16_t> &results) {
  if (results.empty()) {
    return 0;
  }
  const auto result = results.front();
  results.pop_front();
  return result;
}

class WaitSubstitute : public BT::StatefulActionNode {
 public:
  WaitSubstitute(const std::string &name, const BT::NodeConfig &config,
                 std::shared_ptr<Scenario> scenario)
      : BT::StatefulActionNode(name, config), scenario_(std::move(scenario)) {}

  static BT::PortsList providedPorts() {
    return {BT::InputPort<double>("wait_duration")};
  }

  Status onStart() override {
    const auto duration = getInput<double>("wait_duration");
    require(duration && duration.value() == 1.0, "Wait must request one second");
    ++scenario_->waits;
    return scenario_->complete_wait ? Status::SUCCESS : Status::RUNNING;
  }

  Status onRunning() override {
    return scenario_->complete_wait ? Status::SUCCESS : Status::RUNNING;
  }

  void onHalted() override { ++scenario_->wait_halts; }

 private:
  std::shared_ptr<Scenario> scenario_;
};

class Fixture {
 public:
  explicit Fixture(const std::string &xml, std::shared_ptr<Scenario> scenario)
      : scenario_(std::move(scenario)) {
    // These are the installed implementations, including their retry counters,
    // halt propagation, rate scheduling, and error-code membership conditions.
    for (const auto *plugin : {"recovery_node", "pipeline_sequence", "rate_controller",
                              "are_error_codes_active_condition"}) {
      factory_.registerFromPlugin(std::string("/opt/ros/jazzy/lib/libnav2_") +
                                  plugin + "_bt_node.so");
    }
    factory_.registerSimpleAction(
        "ComputePathToPose",
        [state = scenario_](BT::TreeNode &node) {
          ++state->planner_calls;
          const auto code = next_result(state->planner_results);
          node.setOutput("error_code_id", code);
          node.setOutput("path", std::string(code == 0 ? "synthetic-path" : ""));
          return code == 0 ? Status::SUCCESS : Status::FAILURE;
        },
        {BT::InputPort<std::string>("goal"), BT::InputPort<std::string>("planner_id"),
         BT::OutputPort<std::string>("path"), BT::OutputPort<uint16_t>("error_code_id")});
    factory_.registerSimpleAction(
        "FollowPath",
        [state = scenario_](BT::TreeNode &node) {
          ++state->controller_calls;
          const auto code = next_result(state->controller_results);
          node.setOutput("error_code_id", code);
          return code == 0 ? Status::SUCCESS : Status::FAILURE;
        },
        {BT::InputPort<std::string>("path"), BT::InputPort<std::string>("controller_id"),
         BT::InputPort<std::string>("goal_checker_id"),
         BT::OutputPort<uint16_t>("error_code_id")});
    factory_.registerSimpleAction(
        "ClearEntireCostmap",
        [state = scenario_](BT::TreeNode &node) {
          const auto service = node.getInput<std::string>("service_name");
          require(static_cast<bool>(service), "Clear must identify its service");
          if (service.value() == "local_costmap/clear_entirely_local_costmap") {
            ++state->local_clears;
          } else if (service.value() == "global_costmap/clear_entirely_global_costmap") {
            ++state->global_clears;
          } else {
            throw std::runtime_error("Unexpected clear service: " + service.value());
          }
          return Status::SUCCESS;
        },
        {BT::InputPort<std::string>("service_name")});
    factory_.registerNodeType<WaitSubstitute>("Wait", scenario_);
    factory_.registerSimpleCondition("GoalUpdated", [state = scenario_](BT::TreeNode &) {
      const bool updated = state->goal_updated;
      state->goal_updated = false;
      return updated ? Status::SUCCESS : Status::FAILURE;
    });
    auto blackboard = BT::Blackboard::create();
    blackboard->set("goal", std::string("synthetic-goal"));
    tree_ = factory_.createTreeFromFile(xml, blackboard);
  }

  Status tick() { return tree_.tickExactlyOnce(); }

  Status finish() {
    for (int i = 0; i < 64; ++i) {
      const auto status = tick();
      if (status != Status::RUNNING) {
        return status;
      }
    }
    throw std::runtime_error("Offline scenario did not terminate in 64 ticks");
  }

  void halt() { tree_.haltTree(); }

 private:
  std::shared_ptr<Scenario> scenario_;
  BT::BehaviorTreeFactory factory_;
  BT::Tree tree_;
};

struct Case {
  const char *name;
  std::vector<uint16_t> planners;
  std::vector<uint16_t> controllers;
  Status expected;
  int waits;
  int clears;
};
}  // namespace

int main(int argc, char **argv) {
  try {
    require(argc == 2, "Usage: test_passage_timing_tree PATH_TO_PRODUCTION_XML");
    const std::string xml = argv[1];
    const std::vector<Case> cases = {
        {"controller TF recovery", {}, {102, 0}, Status::SUCCESS, 1, 0},
        {"planner TF recovery", {202, 0}, {0}, Status::SUCCESS, 1, 0},
        {"costmap timeout recovery", {}, {107, 0}, Status::SUCCESS, 1, 0},
        {"six TF failures exhaust five waits", {}, {102, 102, 102, 102, 102, 102},
         Status::FAILURE, 5, 0},
        {"repeated progress failure clears once", {}, {105, 105}, Status::FAILURE, 0, 1},
        {"repeated no path clears once", {208, 208}, {}, Status::FAILURE, 0, 1},
        {"stale controller TF cannot hide invalid planner goal", {0, 206}, {102},
         Status::FAILURE, 1, 0},
        {"mixed faults preserve one clear budget", {}, {105, 102, 105},
         Status::FAILURE, 1, 1},
        {"ordinary fault after TF cannot inherit TF retry", {}, {102, 105, 105},
         Status::FAILURE, 1, 1},
    };
    int passed = 0;
    for (const auto &test : cases) {
      auto state = std::make_shared<Scenario>();
      state->planner_results.assign(test.planners.begin(), test.planners.end());
      state->controller_results.assign(test.controllers.begin(), test.controllers.end());
      Fixture fixture(xml, state);
      require(fixture.finish() == test.expected, std::string(test.name) + ": wrong result");
      require(state->waits == test.waits, std::string(test.name) + ": wrong wait count");
      require(state->local_clears == test.clears && state->global_clears == test.clears,
              std::string(test.name) + ": clear budget exceeded or omitted");
      require(state->planner_results.empty() && state->controller_results.empty(),
              std::string(test.name) + ": returned before consuming expected failures");
      std::cout << "PASS " << test.name << '\n';
      ++passed;
    }
    {
      auto state = std::make_shared<Scenario>();
      state->controller_results = {102, 0};
      state->complete_wait = false;
      Fixture fixture(xml, state);
      require(fixture.tick() == Status::RUNNING && state->waits == 1,
              "halt: did not enter waiting");
      fixture.halt();
      require(state->wait_halts == 1 && state->controller_calls == 1,
              "halt: wait not cancelled, or another controller command attempted");
      std::cout << "PASS halt interrupts waiting without another action\n";
      ++passed;
    }
    {
      auto state = std::make_shared<Scenario>();
      state->controller_results = {102, 0};
      state->complete_wait = false;
      Fixture fixture(xml, state);
      require(fixture.tick() == Status::RUNNING && state->waits == 1,
              "updated goal: did not enter waiting");
      state->goal_updated = true;
      require(fixture.finish() == Status::SUCCESS && state->wait_halts == 1 &&
                  state->waits == 1 && state->controller_calls == 2,
              "updated goal: did not interrupt wait and attempt the current goal");
      std::cout << "PASS updated goal interrupts waiting\n";
      ++passed;
    }
    std::cout << passed << " offline behavior scenarios passed; no ROS context initialized\n";
    return 0;
  } catch (const std::exception &error) {
    std::cerr << "FAIL " << error.what() << '\n';
    return 1;
  }
}
