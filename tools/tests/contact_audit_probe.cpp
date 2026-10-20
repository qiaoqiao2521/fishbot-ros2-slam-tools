// SPDX-License-Identifier: Apache-2.0
// Bounded real MuJoCo / installed pluginlib probe. No navigation or command publisher.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include <diagnostic_msgs/msg/diagnostic_array.hpp>
#include <mujoco/mujoco.h>
#include <mujoco_ros2_control_plugins/mujoco_ros2_control_plugins_base.hpp>
#include <pluginlib/class_loader.hpp>
#include <rclcpp/rclcpp.hpp>

using Plugin = mujoco_ros2_control_plugins::MuJoCoROS2ControlPluginBase;
using Clock = std::chrono::steady_clock;

struct CaseResult {
  std::string id;
  bool passed = false;
  std::string reason;
  std::map<std::string, std::string> fields;
  std::size_t messages = 0;
  std::size_t contacts_with_positive_force = 0;
  std::size_t wall_contacts_with_positive_force = 0;
  double independently_observed_peak_force_n = 0.0;
  bool state_untouched = true;
};

std::string quote(const std::string & value)
{
  std::string escaped = "\"";
  for (const auto character : value) {
    switch (character) {
      case '\\': escaped += "\\\\"; break;
      case '"': escaped += "\\\""; break;
      case '\n': escaped += "\\n"; break;
      case '\r': escaped += "\\r"; break;
      case '\t': escaped += "\\t"; break;
      default: escaped += character;
    }
  }
  return escaped + "\"";
}

std::string model_xml(bool wall)
{
  return std::string(R"(<mujoco model="contact_probe">
  <option timestep="0.002" gravity="0 0 -9.81"/>
  <worldbody>
    <geom name="floor" type="plane" size="2 2 .1" friction=".05 .005 .001"/>)") +
    (wall ? R"(<geom name="wall" type="box" pos="0 0 .5" size=".03 1 .5"/>)" : "") +
    R"(<body name="base_footprint" pos="-.4 0 .3"><freejoint/>
      <geom name="robot_cube" type="box" size=".08 .08 .08" mass="1" friction=".05 .005 .001"/>
    </body>
  </worldbody>
</mujoco>)";
}

bool same_physical_state(
  const mjModel * model, const mjData * data, const std::vector<mjtNum> & qpos,
  const std::vector<mjtNum> & qvel, double time)
{
  return data->time == time &&
         std::equal(qpos.begin(), qpos.end(), data->qpos) &&
         std::equal(qvel.begin(), qvel.end(), data->qvel) &&
         qpos.size() == static_cast<std::size_t>(model->nq) &&
         qvel.size() == static_cast<std::size_t>(model->nv);
}

CaseResult run_case(
  pluginlib::ClassLoader<Plugin> & loader, const std::filesystem::path & output,
  const std::string & id, bool wall, bool missing_body)
{
  CaseResult result;
  result.id = id;
  const auto xml_path = output / (id + ".xml");
  {std::ofstream file(xml_path); file << model_xml(wall);}
  char error[1024] = {};
  std::unique_ptr<mjModel, decltype(&mj_deleteModel)> model(
    mj_loadXML(xml_path.c_str(), nullptr, error, sizeof(error)), &mj_deleteModel);
  if (!model) {result.reason = error; return result;}
  std::unique_ptr<mjData, decltype(&mj_deleteData)> data(mj_makeData(model.get()), &mj_deleteData);
  if (wall) data->qvel[0] = 2.0;
  mj_forward(model.get(), data.get());
  std::cerr << id << ": MuJoCo " << mj_versionString() << ", body="
            << mj_name2id(model.get(), mjOBJ_BODY, "base_footprint") << '\n';

  auto node = std::make_shared<rclcpp::Node>("contact_probe_" + id);
  node->declare_parameter("mujoco_plugins.contact_audit.robot_body", missing_body ? "missing_robot" : "base_footprint");
  auto plugin = loader.createSharedInstance("fishbot_mujoco/ContactAudit");
  if (!plugin->init(node, model.get(), data.get())) {
    result.reason = "Installed plugin init returned false";
    return result;
  }
  auto subscription = node->create_subscription<diagnostic_msgs::msg::DiagnosticArray>(
    "/scene_validation/contact_audit", rclcpp::SensorDataQoS(),
    [&result](const diagnostic_msgs::msg::DiagnosticArray & message) {
      for (const auto & status : message.status) {
        if (status.name != "scene_validation/contact_audit") continue;
        ++result.messages;
        for (const auto & value : status.values) result.fields[value.key] = value.value;
      }
    });
  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(node);
  const auto discovery_deadline = Clock::now() + std::chrono::seconds(3);
  while (subscription->get_publisher_count() == 0 && Clock::now() < discovery_deadline) {
    executor.spin_some();
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }

  const int wall_id = mj_name2id(model.get(), mjOBJ_GEOM, "wall");
  for (int step = 0; step < 1100; ++step) {
    std::vector<mjtNum> qpos(data->qpos, data->qpos + model->nq);
    std::vector<mjtNum> qvel(data->qvel, data->qvel + model->nv);
    const double time = data->time;
    plugin->pre_step(data.get());
    result.state_untouched &= same_physical_state(model.get(), data.get(), qpos, qvel, time);
    mj_step(model.get(), data.get());
    for (int index = 0; index < data->ncon; ++index) {
      const auto & contact = data->contact[index];
      mjtNum force[6] = {};
      mj_contactForce(model.get(), data.get(), index, force);
      if (contact.dist <= 0 && force[0] > 0) {
        ++result.contacts_with_positive_force;
        result.independently_observed_peak_force_n = std::max(
          result.independently_observed_peak_force_n, static_cast<double>(force[0]));
        if (wall_id >= 0 && (contact.geom[0] == wall_id || contact.geom[1] == wall_id)) {
          ++result.wall_contacts_with_positive_force;
        }
      }
    }
    qpos.assign(data->qpos, data->qpos + model->nq);
    qvel.assign(data->qvel, data->qvel + model->nv);
    const double update_time = data->time;
    plugin->update(model.get(), data.get());
    result.state_untouched &= same_physical_state(model.get(), data.get(), qpos, qvel, update_time);
    if (step % 10 == 0) {
      executor.spin_some();
      std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
  }
  const auto delivery_deadline = Clock::now() + std::chrono::milliseconds(200);
  while (Clock::now() < delivery_deadline) {
    executor.spin_some();
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
  plugin->cleanup();
  executor.remove_node(node);
  executor.cancel();
  subscription.reset();
  plugin.reset();
  node.reset();

  const auto field = [&result](const std::string & key) {
    const auto found = result.fields.find(key);
    return found == result.fields.end() ? std::string() : found->second;
  };
  const bool observed = result.messages > 0 && !field("physics_steps_total").empty();
  if (!observed) {result.reason = "No diagnostic message received from installed plugin"; return result;}
  const auto physics_steps = std::stoull(field("physics_steps_total"));
  const auto collision_steps = std::stoull(field("collision_steps_total"));
  const auto peak = std::stod(field("peak_normal_force_n"));
  if (missing_body) {
    result.passed = field("available") == "false" && physics_steps > 0 &&
      collision_steps == 0 && result.state_untouched;
    result.reason = result.passed ? "Missing body reported unavailable; plugin remained operational" : "Missing-body diagnostic mismatch";
  } else if (wall) {
    result.passed = field("available") == "true" && physics_steps > 0 &&
      collision_steps > 0 && peak > 0 && result.wall_contacts_with_positive_force > 0 && result.state_untouched;
    result.reason = result.passed ? "Actual positive-force wall contact recorded by original plugin" : "Wall contact or diagnostic evidence missing";
  } else {
    result.passed = field("available") == "true" && physics_steps > 0 && collision_steps == 0 &&
      peak == 0 && result.contacts_with_positive_force > 0 && result.state_untouched;
    result.reason = result.passed ? "Actual positive-force floor contacts excluded from collision count" : "Floor exclusion or contact evidence mismatch";
  }
  return result;
}

int main(int argc, char ** argv)
{
  const std::filesystem::path output = argc > 1 ? argv[1] : ".";
  std::filesystem::create_directories(output);
  setenv("ROS_DOMAIN_ID", "131", 1);
  setenv("ROS_AUTOMATIC_DISCOVERY_RANGE", "LOCALHOST", 1);
  setenv("ROS_LOCALHOST_ONLY", "1", 1);
  rclcpp::init(argc, argv);
  std::vector<CaseResult> results;
  std::string library;
  try {
    pluginlib::ClassLoader<Plugin> loader(
      "mujoco_ros2_control_plugins", "mujoco_ros2_control_plugins::MuJoCoROS2ControlPluginBase");
    library = loader.getClassLibraryPath("fishbot_mujoco/ContactAudit");
    for (const auto & id : {"floor_only", "wall_collision", "missing_body"}) {
      try {
        results.push_back(run_case(loader, output, id, std::string(id) == "wall_collision", std::string(id) == "missing_body"));
      } catch (const std::exception & error) {
        CaseResult result; result.id = id; result.reason = error.what(); results.push_back(result);
      }
    }
  } catch (const std::exception & error) {
    CaseResult result; result.id = "plugin_loading"; result.reason = error.what(); results.push_back(result);
  }
  rclcpp::shutdown();
  const bool passed = results.size() == 3 && std::all_of(results.begin(), results.end(), [](const auto & result) {return result.passed;});
  std::ofstream report(output / "result.json");
  report << "{\n  \"passed\":" << (passed ? "true" : "false") << ",\n  \"ros_domain_id\":131,\n  \"plugin_library\":" << quote(library) << ",\n  \"cases\":[";
  for (std::size_t index = 0; index < results.size(); ++index) {
    if (index) report << ',';
    const auto & result = results[index];
    report << "\n    {\"id\":" << quote(result.id) << ",\"passed\":" << (result.passed ? "true" : "false") << ",\"reason\":" << quote(result.reason)
           << ",\"messages\":" << result.messages << ",\"positive_force_contacts\":" << result.contacts_with_positive_force
           << ",\"positive_force_wall_contacts\":" << result.wall_contacts_with_positive_force
           << ",\"independent_peak_force_n\":" << result.independently_observed_peak_force_n
           << ",\"physical_state_untouched\":" << (result.state_untouched ? "true" : "false") << ",\"diagnostics\":{";
    bool first = true;
    for (const auto & [key, value] : result.fields) {
      if (!first) report << ',';
      first = false;
      report << quote(key) << ':' << quote(value);
    }
    report << "}}";
  }
  report << "\n  ]\n}\n";
  report.close();
  std::cout << (passed ? "PASS" : "FAIL") << " installed contact audit probe; " << (output / "result.json") << '\n';
  return passed ? 0 : 1;
}
