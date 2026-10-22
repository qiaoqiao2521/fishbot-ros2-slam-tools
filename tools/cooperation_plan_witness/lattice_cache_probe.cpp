// Exercise installed native collision code; no actions, controller or simulation.
#include <algorithm>
#include <fstream>
#include <iostream>
#include <set>
#include <string>
#include "rclcpp/rclcpp.hpp"
#include "nav2_costmap_2d/costmap_2d_ros.hpp"
#include "nav2_smac_planner/node_lattice.hpp"

int main(int argc, char ** argv)
{
  if (argc != 3) {return 2;}
  const std::string file = argv[1], expected = argv[2];
  rclcpp::init(0, nullptr);
  bool matches = false;
  {
    auto map = std::make_shared<nav2_costmap_2d::Costmap2DROS>("lattice_cache_probe");
    map->set_parameters({rclcpp::Parameter("plugins", std::vector<std::string>{})});
    map->configure();
    auto grid = map->getCostmap();
    grid->resizeMap(120, 120, .02, 0., 0.);
    std::fill_n(grid->getCharMap(), 120 * 120, nav2_costmap_2d::FREE_SPACE);
    for (unsigned x = 50; x <= 60; ++x) {
      for (unsigned y = 45; y <= 55; ++y) {
        grid->setCost(x, y, nav2_costmap_2d::LETHAL_OBSTACLE);
      }
    }
    nav2_smac_planner::GridCollisionChecker checker(map, 72, map);
    nav2_costmap_2d::Footprint footprint;
    for (auto xy : {std::pair<double, double>{-.04, -.04}, {.04, -.04},
                   {.04, .04}, {-.04, .04}}) {
      geometry_msgs::msg::Point point;
      point.x = xy.first; point.y = xy.second; footprint.push_back(point);
    }
    checker.setFootprint(footprint, false, -1.);
    using namespace nav2_smac_planner;
    NodeLattice::motion_table.lattice_metadata = LatticeMotionTable::getLatticeMetadata(file);
    MotionPrimitive primitive;
    primitive.start_angle = primitive.end_angle = 0;
    primitive.trajectory_length = primitive.straight_length = 1.6;
    primitive.arc_length = 0.;
    for (int i = 0; i <= 80; ++i) {
      primitive.poses.emplace_back(i * .02f, 0.f, 0.f, TurnDirection::FORWARD);
    }
    NodeLattice cold(0), warm(1);
    cold.setPose({95.f, 50.f, 0.f}); warm.setPose({95.f, 50.f, 0.f});
    const bool cold_edge = cold.isNodeValid(false, &checker, &primitive);
    const bool endpoint = warm.isNodeValid(false, &checker);
    const bool warm_edge = warm.isNodeValid(false, &checker, &primitive);
    matches = endpoint && !cold_edge && (expected == "cached" ? warm_edge : !warm_edge);
    std::set<std::string> libraries;
    std::ifstream maps("/proc/self/maps"); std::string line;
    while (std::getline(maps, line)) {
      if (line.find("libnav2_smac_planner") != std::string::npos) {
        libraries.insert(line.substr(line.find('/')));
      }
    }
    nlohmann::json result = {{"clear_endpoint_valid", endpoint},
      {"blocked_edge_without_endpoint_cache_valid", cold_edge},
      {"blocked_edge_after_endpoint_cache_valid", warm_edge},
      {"native_cache_issue_reproduced", endpoint && !cold_edge && warm_edge},
      {"expected", expected}, {"expectation_matched", matches},
      {"native_libraries", libraries}, {"navigation_goals", 0}};
    std::cout << result.dump() << std::endl;
    map->cleanup();
  }
  rclcpp::shutdown();
  return matches ? 0 : 1;
}
