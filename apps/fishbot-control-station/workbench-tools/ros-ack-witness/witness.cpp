// Read-only ROS receipt evidence. No application publishers or control APIs are added.
#include <chrono>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <nlohmann/json.hpp>
#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/string.hpp>
#include <traj_utils/msg/bspline.hpp>
#include <quadrotor_msgs/msg/position_command.hpp>

using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;

class ReceiptWitness : public rclcpp::Node {
public:
  ReceiptWitness() : Node("drone_ros_receipt_witness") {
    const auto prefix = declare_parameter<std::string>("prefix", "/drone_ack_probe");
    ack_ = create_subscription<std_msgs::msg::String>(prefix+"/ack", 50,
      [this](std_msgs::msg::String::ConstSharedPtr message, const rclcpp::MessageInfo & info) {
        emit("ack", {{"data", message->data}}, info);
      });
    curve_ = create_subscription<traj_utils::msg::Bspline>(prefix+"/bspline", 50,
      [this](traj_utils::msg::Bspline::ConstSharedPtr message, const rclcpp::MessageInfo & info) {
        Json points = Json::array();
        for (const auto & point : message->pos_pts)
          points.push_back({point.x, point.y, point.z});
        emit("bspline", {{"traj_id", message->traj_id}, {"order", message->order},
             {"knots", message->knots}, {"control_points", points},
             {"start_sim_s", message->start_time.sec+message->start_time.nanosec*1e-9}}, info);
      });
    command_ = create_subscription<quadrotor_msgs::msg::PositionCommand>(prefix+"/position", 50,
      [this](quadrotor_msgs::msg::PositionCommand::ConstSharedPtr message, const rclcpp::MessageInfo & info) {
        emit("position", {{"trajectory_id", message->trajectory_id},
             {"stamp_sim_s", message->header.stamp.sec+message->header.stamp.nanosec*1e-9},
             {"position", {message->position.x,message->position.y,message->position.z}},
             {"velocity", {message->velocity.x,message->velocity.y,message->velocity.z}},
             {"acceleration", {message->acceleration.x,message->acceleration.y,message->acceleration.z}},
             {"yaw", message->yaw}}, info);
      });
  }
private:
  void emit(const std::string & kind, const Json & body, const rclcpp::MessageInfo & info) {
    const auto & raw = info.get_rmw_message_info();
    std::ostringstream gid;
    for (auto value : raw.publisher_gid.data)
      gid << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned>(value);
    const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count();
    const Json event = {{"kind",kind}, {"host_monotonic_ns",ns}, {"message",body},
      {"publisher_gid",gid.str()}, {"source_timestamp",raw.source_timestamp},
      {"received_timestamp",raw.received_timestamp},
      {"publication_sequence_number",raw.publication_sequence_number},
      {"reception_sequence_number",raw.reception_sequence_number}};
    std::cout << event.dump() << std::endl;
  }
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr ack_;
  rclcpp::Subscription<traj_utils::msg::Bspline>::SharedPtr curve_;
  rclcpp::Subscription<quadrotor_msgs::msg::PositionCommand>::SharedPtr command_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc,argv);
  rclcpp::spin(std::make_shared<ReceiptWitness>());
  rclcpp::shutdown();
  return 0;
}
