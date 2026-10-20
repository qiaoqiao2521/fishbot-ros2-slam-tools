// SPDX-License-Identifier: Apache-2.0
// Read-only physics evidence. This plugin never changes commands or model state.
#include <atomic>
#include <cstdint>
#include <string>
#include <vector>

#include <diagnostic_msgs/msg/diagnostic_array.hpp>
#include <pluginlib/class_list_macros.hpp>
#include <mujoco_ros2_control_plugins/mujoco_ros2_control_plugins_base.hpp>

namespace fishbot_mujoco
{
class ContactAudit : public mujoco_ros2_control_plugins::MuJoCoROS2ControlPluginBase
{
public:
  bool init(rclcpp::Node::SharedPtr node, const mjModel * model, mjData *) override
  {
    node_ = node;
    model_ = model;
    // Parameter types are explicit to remain compatible with the installed wrapper.
    const std::string root_key = "mujoco_plugins.contact_audit.robot_body";
    if (!node_->has_parameter(root_key)) node_->declare_parameter(root_key, "base_footprint");
    const std::string floor_key = "mujoco_plugins.contact_audit.floor_geoms";
    if (!node_->has_parameter(floor_key)) node_->declare_parameter(floor_key, std::vector<std::string>{"floor"});
    const auto root = node_->get_parameter(root_key).as_string();
    const int root_id = mj_name2id(model_, mjOBJ_BODY, root.c_str());
    available_ = root_id >= 0;
    robot_geom_.assign(model_->ngeom, false);
    floor_geom_.assign(model_->ngeom, false);
    for (int geom = 0; geom < model_->ngeom; ++geom) {
      for (int body = model_->geom_bodyid[geom]; body > 0; body = model_->body_parentid[body]) {
        if (body == root_id) {robot_geom_[geom] = true; break;}
      }
    }
    const auto floor_geoms = node_->get_parameter(floor_key).as_string_array();
    for (const auto & name : floor_geoms) {
      const int id = mj_name2id(model_, mjOBJ_GEOM, name.c_str());
      if (id >= 0) floor_geom_[id] = true;
      else RCLCPP_WARN(node_->get_logger(), "Contact audit: optional floor geom '%s' absent", name.c_str());
    }
    if (!available_) RCLCPP_WARN(node_->get_logger(), "Contact audit unavailable: robot body '%s' absent", root.c_str());
    publisher_ = node_->create_publisher<diagnostic_msgs::msg::DiagnosticArray>(
      "/scene_validation/contact_audit", rclcpp::SensorDataQoS());
    return true;
  }

  void pre_step(mjData * data) override
  {
    ++steps_;
    if (!available_) return;
    bool collided = false;
    for (int index = 0; index < data->ncon; ++index) {
      const auto & contact = data->contact[index];
      const int first = contact.geom[0], second = contact.geom[1];
      if (first < 0 || second < 0 || robot_geom_[first] == robot_geom_[second]) continue;
      const int other = robot_geom_[first] ? second : first;
      if (floor_geom_[other]) continue;
      mjtNum force[6] = {};
      mj_contactForce(model_, data, index, force);
      if (contact.dist <= 0.0 && force[0] > 0.0) {
        collided = true;
        auto peak = peak_force_.load(std::memory_order_relaxed);
        while (peak < force[0] && !peak_force_.compare_exchange_weak(peak, force[0])) {}
      }
    }
    if (collided) {
      ++collision_steps_;
      last_collision_time_.store(data->time, std::memory_order_relaxed);
    }
  }

  void update(const mjModel *, mjData * data) override
  {
    if (data->time < last_publish_ + 0.05) return;
    last_publish_ = data->time;
    diagnostic_msgs::msg::DiagnosticArray message;
    message.header.stamp = rclcpp::Time(static_cast<int64_t>(data->time * 1e9));
    message.header.frame_id = "world";
    diagnostic_msgs::msg::DiagnosticStatus status;
    status.name = "scene_validation/contact_audit";
    status.hardware_id = "mujoco_physics_contacts";
    status.level = available_ ? diagnostic_msgs::msg::DiagnosticStatus::OK : diagnostic_msgs::msg::DiagnosticStatus::WARN;
    status.message = available_ ? "Read-only cumulative physics-step contacts; floor excluded" : "Robot body unavailable";
    const auto add = [&](const std::string & key, const std::string & value) {
      diagnostic_msgs::msg::KeyValue field; field.key = key; field.value = value; status.values.push_back(field);
    };
    add("available", available_ ? "true" : "false");
    add("physics_steps_total", std::to_string(steps_.load()));
    add("collision_steps_total", std::to_string(collision_steps_.load()));
    add("peak_normal_force_n", std::to_string(peak_force_.load()));
    add("last_collision_source_s", std::to_string(last_collision_time_.load()));
    message.status.push_back(status);
    publisher_->publish(message);
  }

  void cleanup() override {publisher_.reset(); node_.reset();}

private:
  const mjModel * model_ = nullptr;
  rclcpp::Node::SharedPtr node_;
  rclcpp::Publisher<diagnostic_msgs::msg::DiagnosticArray>::SharedPtr publisher_;
  std::vector<bool> robot_geom_, floor_geom_;
  bool available_ = false;
  double last_publish_ = -1.0;
  std::atomic<uint64_t> steps_{0}, collision_steps_{0};
  std::atomic<double> peak_force_{0.0}, last_collision_time_{-1.0};
};
}  // namespace fishbot_mujoco

PLUGINLIB_EXPORT_CLASS(fishbot_mujoco::ContactAudit,
  mujoco_ros2_control_plugins::MuJoCoROS2ControlPluginBase)
