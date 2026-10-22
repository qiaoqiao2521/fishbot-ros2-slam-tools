// Installed native AMCL models, zero-noise diagnostic. No ROS or physics loop.
#include <cmath>
#include <iomanip>
#include <iostream>
#include "nav2_amcl/motion_model/differential_motion_model.hpp"
#include "nav2_amcl/motion_model/omni_motion_model.hpp"

template<class Model>
double run(const char * name, double offset, bool rotate)
{
  Model model;
  model.initialize(0., 0., 0., 0., 0.);
  pf_t * pf = pf_alloc(1, 1, 0., 0., nullptr);
  pf->sets[pf->current_set].sample_count = 1;
  auto & sample = pf->sets[pf->current_set].samples[0];
  sample.pose = pf_vector_t{};
  pf_vector_t previous{};
  for (int i = 1; i <= 100; i++) {
    const double angle = rotate ? std::acos(-1.) * i / 100. : 0.;
    pf_vector_t pose{};
    pose.v[0] = rotate ? offset * (std::cos(angle) - 1.) : .25 * i / 100.;
    pose.v[1] = offset * std::sin(angle);
    pose.v[2] = angle;
    pf_vector_t delta{};
    for (int j = 0; j < 3; j++) {delta.v[j] = pose.v[j] - previous.v[j];}
    model.odometryUpdate(pf, pose, delta);
    previous = pose;
  }
  const double error = std::hypot(sample.pose.v[0] - previous.v[0],
                                  sample.pose.v[1] - previous.v[1]);
  std::cout << std::setprecision(17) << "{\"model\":\"" << name
            << "\",\"offset_m\":" << offset << ",\"rotate\":" << (rotate ? "true" : "false")
            << ",\"expected_xy\":[" << previous.v[0] << "," << previous.v[1]
            << "],\"predicted_xy\":[" << sample.pose.v[0] << "," << sample.pose.v[1]
            << "],\"xy_error_m\":" << error << "}" << std::endl;
  pf_free(pf);
  return error;
}

int main()
{
  run<nav2_amcl::DifferentialMotionModel>("differential", .02, true);
  double error = run<nav2_amcl::OmniMotionModel>("omni", .02, true);
  error += run<nav2_amcl::DifferentialMotionModel>("differential", 0., true);
  error += run<nav2_amcl::OmniMotionModel>("omni", 0., true);
  error += run<nav2_amcl::DifferentialMotionModel>("differential", .02, false);
  error += run<nav2_amcl::OmniMotionModel>("omni", .02, false);
  return error < 1e-10 ? 0 : 1;
}
