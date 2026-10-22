// Read-only DDS witness. No command publisher, action client, or truth input.
#include <ctime>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include "nav_msgs/msg/path.hpp"
#include "rclcpp/rclcpp.hpp"

double monotonic_seconds()
{
  timespec stamp{};
  clock_gettime(CLOCK_MONOTONIC, &stamp);
  return stamp.tv_sec + stamp.tv_nsec / 1e9;
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<rclcpp::Node>("cooperation_plan_witness");
  size_t count = 0;
  auto subscription = node->create_subscription<nav_msgs::msg::Path>(
    "/received_global_plan", rclcpp::QoS(100).reliable().durability_volatile(),
    [&count](nav_msgs::msg::Path::ConstSharedPtr path, const rclcpp::MessageInfo & info) {
      const double received = monotonic_seconds();
      if (++count > 20000) {
        if (count == 20001) {std::cout << "{\"kind\":\"overflow\"}" << std::endl;}
        return;
      }
      const auto & metadata = info.get_rmw_message_info();
      std::ostringstream gid;
      for (const auto value : metadata.publisher_gid.data) {
        gid << std::hex << std::setw(2) << std::setfill('0') << static_cast<unsigned>(value);
      }
      std::cout << std::setprecision(17)
                << "{\"kind\":\"plan\",\"receive_monotonic\":" << received
                << ",\"publisher_gid\":\"" << gid.str()
                << "\",\"source_stamp\":" << path->header.stamp.sec + path->header.stamp.nanosec / 1e9
                << ",\"poses\":" << path->poses.size() << "}" << std::endl;
    });
  bool ready = false;
  auto timer = node->create_wall_timer(std::chrono::milliseconds(100), [&]() {
      if (!ready && subscription->get_publisher_count() >= 2) {
        ready = true;
        std::cout << "{\"kind\":\"ready\",\"publishers\":"
                  << subscription->get_publisher_count() << "}" << std::endl;
      }
    });
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
