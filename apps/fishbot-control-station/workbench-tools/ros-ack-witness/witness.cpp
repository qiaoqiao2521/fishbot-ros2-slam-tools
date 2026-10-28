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
             {"start_sim_s", message->start_time.sec+message->start_time.nanosec*1e-9}}, info,
             static_cast<int64_t>(message->start_time.sec)*1000000000LL+message->start_time.nanosec);
      });
    command_ = create_subscription<quadrotor_msgs::msg::PositionCommand>(prefix+"/position", 50,
      [this](quadrotor_msgs::msg::PositionCommand::ConstSharedPtr message, const rclcpp::MessageInfo & info) {
        emit("position", {{"trajectory_id", message->trajectory_id},
             {"stamp_sim_s", message->header.stamp.sec+message->header.stamp.nanosec*1e-9},
             {"position", {message->position.x,message->position.y,message->position.z}},
             {"velocity", {message->velocity.x,message->velocity.y,message->velocity.z}},
             {"acceleration", {message->acceleration.x,message->acceleration.y,message->acceleration.z}},
             {"yaw", message->yaw}}, info,
             static_cast<int64_t>(message->header.stamp.sec)*1000000000LL+message->header.stamp.nanosec);
      });
    if (declare_parameter<bool>("emit_heartbeat", false))
      heartbeat_ = create_wall_timer(std::chrono::milliseconds(100), [this]() {
        const Json event = {{"kind","heartbeat"}, {"host_monotonic_ns", steady_ns()},
          {"publisher_counts", {{"ack",ack_->get_publisher_count()},
            {"bspline",curve_->get_publisher_count()}, {"position",command_->get_publisher_count()}}}};
        std::cout << event.dump() << std::endl;
      });
  }
private:
  static int64_t steady_ns() {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now().time_since_epoch()).count();
  }
  void emit(const std::string & kind, const Json & body, const rclcpp::MessageInfo & info,
            int64_t source_stamp_ns = 0) {
    const auto & raw = info.get_rmw_message_info();
    std::ostringstream gid;
    for (auto value : raw.publisher_gid.data)
      gid << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned>(value);
    const Json event = {{"kind",kind}, {"host_monotonic_ns",steady_ns()}, {"message",body},
      {"source_stamp_ns",source_stamp_ns},
      {"publisher_gid",gid.str()}, {"source_timestamp",raw.source_timestamp},
      {"received_timestamp",raw.received_timestamp},
      {"publication_sequence_number",raw.publication_sequence_number},
      {"reception_sequence_number",raw.reception_sequence_number}};
    std::cout << event.dump() << std::endl;
  }
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr ack_;
  rclcpp::Subscription<traj_utils::msg::Bspline>::SharedPtr curve_;
  rclcpp::Subscription<quadrotor_msgs::msg::PositionCommand>::SharedPtr command_;
  rclcpp::TimerBase::SharedPtr heartbeat_;
};

int main(int argc, char ** argv) {
  rclcpp::init(argc,argv);
  rclcpp::spin(std::make_shared<ReceiptWitness>());
  rclcpp::shutdown();
  return 0;
}
