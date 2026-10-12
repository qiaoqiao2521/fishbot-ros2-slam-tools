// Execute the complete derived XML with installed Nav2 control/condition nodes.
// Only ROS actions, selectors and path/goal observations are substitutes.
#include <behaviortree_cpp/bt_factory.h>
#include <deque>
#include <chrono>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>

namespace {
using Status = BT::NodeStatus;
void require(bool value, const std::string &reason) {
  if (!value) throw std::runtime_error(reason);
}
struct Scenario {
  std::deque<uint16_t> planners, controllers;
  uint16_t planner_default = 0, controller_default = 0;
  int planner_calls = 0, controller_calls = 0, waits = 0, ordinary_waits = 0;
  int local_clears = 0, global_clears = 0, spins = 0, backups = 0, wait_halts = 0;
  bool valid_path = false, complete_wait = true, goal_updated = false;
};
uint16_t next(std::deque<uint16_t> &values, uint16_t fallback) {
  if (values.empty()) return fallback;
  const auto result = values.front(); values.pop_front(); return result;
}
class Wait : public BT::StatefulActionNode {
 public:
  Wait(const std::string &name, const BT::NodeConfig &config, std::shared_ptr<Scenario> scenario)
      : BT::StatefulActionNode(name,config), state_(std::move(scenario)) {}
  static BT::PortsList providedPorts() {return {BT::InputPort<double>("wait_duration")};}
  Status onStart() override {
    const double duration = getInput<double>("wait_duration").value();
    require(duration == 1. || duration == 5.,"Unexpected wait duration");
    if (duration == 1.) ++state_->waits; else ++state_->ordinary_waits;
    return state_->complete_wait ? Status::SUCCESS : Status::RUNNING;
  }
  Status onRunning() override {return state_->complete_wait ? Status::SUCCESS : Status::RUNNING;}
  void onHalted() override {++state_->wait_halts;}
 private:
  std::shared_ptr<Scenario> state_;
};
class Fixture {
 public:
  Fixture(const std::string &xml,std::shared_ptr<Scenario> state) : state_(std::move(state)) {
    for (const auto *plugin : {"recovery_node","pipeline_sequence","rate_controller",
        "round_robin_node","are_error_codes_active_condition",
        "would_a_controller_recovery_help_condition","would_a_planner_recovery_help_condition"}) {
      factory_.registerFromPlugin(std::string("/opt/ros/jazzy/lib/libnav2_")+plugin+"_bt_node.so");
    }
    factory_.registerSimpleAction("ComputePathToPose",[s=state_](BT::TreeNode &node) {
      ++s->planner_calls;
      const auto code = next(s->planners,s->planner_default);
      if (code != 65535) node.setOutput("error_code_id",code);
      s->valid_path = code == 0;
      node.setOutput("path",std::string(code == 0 ? "actual-substitute-path" : ""));
      return code == 0 ? Status::SUCCESS : Status::FAILURE;
    },{BT::InputPort<std::string>("goal"),BT::InputPort<std::string>("planner_id"),
       BT::OutputPort<std::string>("path"),BT::OutputPort<uint16_t>("error_code_id")});
    factory_.registerSimpleAction("FollowPath",[s=state_](BT::TreeNode &node) {
      ++s->controller_calls;
      const auto code = next(s->controllers,s->controller_default);
      // A failed action with no result must not inherit an earlier TF code.
      if (code != 65535) node.setOutput("error_code_id",code);
      return code == 0 ? Status::SUCCESS : Status::FAILURE;
    },{BT::InputPort<std::string>("path"),BT::InputPort<std::string>("controller_id"),
       BT::OutputPort<uint16_t>("error_code_id")});
    factory_.registerSimpleAction("ControllerSelector",[](BT::TreeNode &node) {
      node.setOutput("selected_controller",std::string("FollowPath")); return Status::SUCCESS;
    },{BT::OutputPort<std::string>("selected_controller"),BT::InputPort<std::string>("default_controller"),BT::InputPort<std::string>("topic_name")});
    factory_.registerSimpleAction("PlannerSelector",[](BT::TreeNode &node) {
      node.setOutput("selected_planner",std::string("GridBased")); return Status::SUCCESS;
    },{BT::OutputPort<std::string>("selected_planner"),BT::InputPort<std::string>("default_planner"),BT::InputPort<std::string>("topic_name")});
    factory_.registerSimpleAction("ClearEntireCostmap",[s=state_](BT::TreeNode &node) {
      const auto name = node.getInput<std::string>("service_name").value();
      if (name == "local_costmap/clear_entirely_local_costmap") ++s->local_clears;
      else if (name == "global_costmap/clear_entirely_global_costmap") ++s->global_clears;
      else throw std::runtime_error("Unexpected costmap service");
      return Status::SUCCESS;
    },{BT::InputPort<std::string>("service_name")});
    factory_.registerSimpleAction("Spin",[s=state_](BT::TreeNode &node) {
      ++s->spins; node.setOutput("error_code_id",uint16_t(0)); return Status::SUCCESS;
    },{BT::InputPort<double>("spin_dist"),BT::OutputPort<uint16_t>("error_code_id")});
    factory_.registerSimpleAction("BackUp",[s=state_](BT::TreeNode &node) {
      ++s->backups; node.setOutput("error_code_id",uint16_t(0)); return Status::SUCCESS;
    },{BT::InputPort<double>("backup_dist"),BT::InputPort<double>("backup_speed"),BT::OutputPort<uint16_t>("error_code_id")});
    factory_.registerNodeType<Wait>("Wait",state_);
    factory_.registerSimpleCondition("IsPathValid",[s=state_](BT::TreeNode &) {
      return s->valid_path ? Status::SUCCESS : Status::FAILURE;
    },{BT::InputPort<std::string>("path")});
    factory_.registerSimpleCondition("GlobalUpdatedGoal",[](BT::TreeNode &) {return Status::FAILURE;});
    factory_.registerSimpleCondition("GoalUpdated",[s=state_](BT::TreeNode &) {
      const bool updated = s->goal_updated; s->goal_updated = false;
      return updated ? Status::SUCCESS : Status::FAILURE;
    });
    auto board=BT::Blackboard::create(); board->set("goal",std::string("same-navigation-goal"));
    board->set("compute_path_error_code",uint16_t(0)); board->set("follow_path_error_code",uint16_t(0));
    tree_=factory_.createTreeFromFile(xml,board);
  }
  Status tick() {return tree_.tickExactlyOnce();}
  Status finish() {
    for (int i=0;i<256;++i) {const auto status=tick(); if(status!=Status::RUNNING)return status;}
    throw std::runtime_error("Derived tree did not terminate in bounded offline ticks");
  }
  void halt() {tree_.haltTree();}
 private:
  std::shared_ptr<Scenario> state_;
  BT::BehaviorTreeFactory factory_;
  BT::Tree tree_;
};
}
int main(int argc,char **argv) {
  try {
    require(argc==3,"Require actual derived and validity-only XML paths");
    const std::string derived=argv[1],baseline=argv[2]; int passed=0;
    auto run=[&](std::deque<uint16_t> planners,std::deque<uint16_t> controllers,
                 Status expected,int waits) {
      auto state=std::make_shared<Scenario>(); state->planners=std::move(planners); state->controllers=std::move(controllers);
      Fixture fixture(derived,state); require(fixture.finish()==expected,"Wrong final status");
      require(state->waits==waits,"Wrong shared timing budget");
      require(state->planners.empty()&&state->controllers.empty(),"Skipped expected action outcome");
      ++passed; return state;
    };
    run({},{102,0},Status::SUCCESS,1);
    run({202,0},{0},Status::SUCCESS,1);
    run({},{107,0},Status::SUCCESS,1);
    run({},{102,102,102,102,102,102},Status::FAILURE,5);
    run({202,202,0},{102,102,102,0},Status::SUCCESS,5);
    run({202,202,202,0},{102,102,102},Status::FAILURE,5);
    run({},{102,65535},Status::FAILURE,1);
    run({202,65535},{},Status::FAILURE,1);
    {
      const auto state=run({},{102,105,105,102,102,102,102,102},Status::FAILURE,5);
      require(state->local_clears==2&&state->global_clears==1,
              "Shared timing budget was reset across the original outer geometric recovery");
    }
    // A stale controller TF code cannot authorize retrying a new invalid planner goal.
    {
      auto state=std::make_shared<Scenario>(); state->controllers={102,0}; state->planners={0,206};
      state->complete_wait=false; Fixture fixture(derived,state);
      require(fixture.tick()==Status::RUNNING&&state->waits==1,"Did not enter TF wait");
      state->valid_path=false; state->complete_wait=true;
      // The real RateController retains its one-second wall-clock schedule.
      std::this_thread::sleep_for(std::chrono::milliseconds(1100));
      require(fixture.finish()==Status::FAILURE&&state->waits==1&&state->planner_calls==2,
              "Old TF error leaked into invalid planner retry"); ++passed;
    }
    // The complete original geometric recovery budget remains unchanged after a TF wait.
    {
      auto ordinary=std::make_shared<Scenario>(); ordinary->controller_default=105;
      Fixture before(baseline,ordinary); require(before.finish()==Status::FAILURE,"Baseline ordinary error succeeded");
      auto mixed=std::make_shared<Scenario>(); mixed->controllers={102}; mixed->controller_default=105;
      Fixture after(derived,mixed); require(after.finish()==Status::FAILURE&&mixed->waits==1,"Ordinary error borrowed timing retries");
      require(mixed->controller_calls==ordinary->controller_calls+1&&mixed->local_clears==ordinary->local_clears
          &&mixed->global_clears==ordinary->global_clears&&mixed->spins==ordinary->spins
          &&mixed->backups==ordinary->backups&&mixed->ordinary_waits==ordinary->ordinary_waits,
          "TF wait reset or expanded the official geometric recovery budget"); ++passed;
    }
    {
      auto state=std::make_shared<Scenario>(); state->controllers={102,0}; state->complete_wait=false;
      Fixture fixture(derived,state); require(fixture.tick()==Status::RUNNING&&state->waits==1,"Halt did not reach wait");
      fixture.halt(); require(state->wait_halts==1&&state->controller_calls==1,"Halt restarted a controller"); ++passed;
    }
    {
      auto state=std::make_shared<Scenario>(); state->controllers={102,0}; state->complete_wait=false;
      Fixture fixture(derived,state); require(fixture.tick()==Status::RUNNING&&state->waits==1,"Update did not reach wait");
      state->goal_updated=true;
      require(fixture.finish()==Status::SUCCESS&&state->wait_halts==1&&state->waits==1&&state->controller_calls==2,
              "GoalUpdated failed to halt the one owned wait"); ++passed;
    }
    std::cout<<passed<<" complete localization timing scenarios passed; no ROS context initialized\n";
    return 0;
  } catch(const std::exception &error) {std::cerr<<"FAIL "<<error.what()<<'\n';return 1;}
}
