// Actual native contact/actuator probe. No ROS, no base state writes.
#include <mujoco/mujoco.h>
#include <array>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
  if (argc != 3) return 2;
  char error[2048]{};
  mjModel* model = mj_loadXML(argv[1], nullptr, error, sizeof(error));
  if (!model) { std::cerr << error << '\n'; return 3; }
  mjData* data = mj_makeData(model);
  const std::array<std::string, 4> names = {"front_left", "rear_left", "front_right", "rear_right"};
  std::array<int, 4> actuators{}, joints{}, wheel_geoms{}, contact_steps{};
  for (int i = 0; i < 4; ++i) {
    actuators[i] = mj_name2id(model, mjOBJ_ACTUATOR, (names[i]+"_wheel_joint").c_str());
    joints[i] = mj_name2id(model, mjOBJ_JOINT, (names[i]+"_wheel_joint").c_str());
    wheel_geoms[i] = mj_name2id(model, mjOBJ_GEOM, (names[i]+"_wheel_collision").c_str());
    if (actuators[i] < 0 || joints[i] < 0 || wheel_geoms[i] < 0) return 4;
  }
  const int base = mj_name2id(model, mjOBJ_BODY, "base_footprint");
  const int floor = mj_name2id(model, mjOBJ_GEOM, "floor");
  double peak_force = 0.;
  bool turning = false;
  std::array<double,4> turn_speed_sum{}, turn_force_sum{}, turn_force_peak{};
  auto step = [&](int steps) {
    for (int t = 0; t < steps; ++t) {
      mj_step(model, data);
      if (turning) for (int w = 0; w < 4; ++w) {
        turn_speed_sum[w] += data->qvel[model->jnt_dofadr[joints[w]]];
        turn_force_sum[w] += data->actuator_force[actuators[w]];
        turn_force_peak[w] = std::max(turn_force_peak[w], std::abs(double(data->actuator_force[actuators[w]])));
      }
      for (int c = 0; c < data->ncon; ++c) {
        const auto& contact = data->contact[c];
        mjtNum force[6]; mj_contactForce(model, data, c, force);
        if (force[0] <= 0) continue;
        for (int w = 0; w < 4; ++w) {
          if ((contact.geom1 == floor && contact.geom2 == wheel_geoms[w]) ||
              (contact.geom2 == floor && contact.geom1 == wheel_geoms[w])) {
            ++contact_steps[w]; peak_force = std::max(peak_force, double(force[0]));
          }
        }
      }
    }
  };
  auto yaw = [&]() { const auto* m = data->xmat+base*9; return std::atan2(m[3],m[0]); };
  auto position = [&]() { return std::array<double,3>{data->xpos[3*base],data->xpos[3*base+1],data->xpos[3*base+2]}; };
  step(500);
  auto start = position();
  std::array<double,4> start_angles{};
  for (int i = 0; i < 4; ++i) { start_angles[i] = data->qpos[model->jnt_qposadr[joints[i]]]; data->ctrl[actuators[i]] = .15/.098; }
  step(1000);
  auto end = position(); const double straight_yaw = yaw();
  std::array<double,4> angle_changes{};
  for (int i = 0; i < 4; ++i) { angle_changes[i] = data->qpos[model->jnt_qposadr[joints[i]]]-start_angles[i]; data->ctrl[actuators[i]] = 0.; }
  step(500);
  const double before_turn = yaw();
  std::array<double,4> turn_start_angles{}, turn_changes{};
  for (int i = 0; i < 4; ++i) turn_start_angles[i] = data->qpos[model->jnt_qposadr[joints[i]]];
  for (int i = 0; i < 4; ++i) data->ctrl[actuators[i]] = i < 2 ? -1. : 1.;
  turning = true;
  step(1000);
  turning = false;
  const double turn = std::remainder(yaw()-before_turn, 2*3.141592653589793);
  for (int i = 0; i < 4; ++i) turn_changes[i] = data->qpos[model->jnt_qposadr[joints[i]]]-turn_start_angles[i];
  for (int i = 0; i < 4; ++i) data->ctrl[actuators[i]] = 0.;
  step(500);
  const int base_joint = mj_name2id(model,mjOBJ_JOINT,"base_free_joint");
  const int dof = model->jnt_dofadr[base_joint];
  const double final_linear = std::hypot(data->qvel[dof],data->qvel[dof+1]);
  const double final_angular = std::abs(data->qvel[dof+5]);
  bool contacts = true, wheels = true;
  for (int i=0;i<4;++i) { contacts &= contact_steps[i]>0; wheels &= angle_changes[i]>1.; }
  bool passed = contacts && wheels && end[0]-start[0]>.20 && end[0]-start[0]<.40 &&
                std::abs(end[1]-start[1])<.03 && std::abs(straight_yaw)<.06 && turn>.15 &&
                final_linear<.01 && final_angular<.02;
  std::ofstream out(argv[2]); out << std::setprecision(12)
    << "{\n  \"passed\": " << (passed?"true":"false") << ",\n  \"native_version\": \"" << mj_versionString()
    << "\",\n  \"sim_time_s\": " << data->time << ",\n  \"straight_displacement_xy_m\": [" << end[0]-start[0] << "," << end[1]-start[1]
    << "],\n  \"straight_yaw_rad\": " << straight_yaw << ",\n  \"turn_rad\": " << turn
    << ",\n  \"final_linear_m_s\": " << final_linear << ",\n  \"final_angular_rad_s\": " << final_angular
    << ",\n  \"peak_floor_normal_force_n\": " << peak_force << ",\n  \"positive_wheel_floor_contacts\": [";
  for (int i=0;i<4;++i) out << (i?",":"") << contact_steps[i];
  out << "],\n  \"straight_wheel_angle_changes_rad\": [";
  for (int i=0;i<4;++i) out << (i?",":"") << angle_changes[i];
  out << "],\n  \"turn_wheel_angle_changes_rad\": [";
  for (int i=0;i<4;++i) out << (i?",":"") << turn_changes[i];
  out << "],\n  \"turn_wheel_mean_speed_rad_s\": [";
  for (int i=0;i<4;++i) out << (i?",":"") << turn_speed_sum[i]/1000.;
  out << "],\n  \"turn_wheel_mean_torque_nm\": [";
  for (int i=0;i<4;++i) out << (i?",":"") << turn_force_sum[i]/1000.;
  out << "],\n  \"turn_wheel_peak_torque_nm\": [";
  for (int i=0;i<4;++i) out << (i?",":"") << turn_force_peak[i];
  out << "],\n  \"base_state_writes\": 0,\n  \"scope\": \"native contact/actuator probe; not ROS navigation or calibrated tire dynamics\"\n}\n";
  mj_deleteData(data); mj_deleteModel(model);
  return passed?0:1;
}
