// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// Offline adapter to GCOPTER MINCO_S4NU (MIT, Zhepei Wang and Fei Gao).
// The upstream solver and its license remain in the external GCOPTER checkout.
#include <gcopter/minco.hpp>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <iostream>
#include <numeric>
#include <stdexcept>
#include <vector>

using Json = nlohmann::json;

Eigen::MatrixXd matrix(const Json &value) {
  if (!value.is_array() || value.empty() || !value.at(0).is_array())
    throw std::invalid_argument("Expected a nonempty matrix");
  Eigen::MatrixXd result(value.size(), value.at(0).size());
  for (int i=0;i<result.rows();++i) {
    if (value.at(i).size()!=static_cast<size_t>(result.cols()))
      throw std::invalid_argument("Expected equal matrix row sizes");
    for (int j=0;j<result.cols();++j) result(i,j)=value.at(i).at(j).get<double>();
  }
  return result;
}

std::vector<double> numbers(const Json &value) {
  if (!value.is_array()) throw std::invalid_argument("Expected a numeric array");
  auto values=value.get<std::vector<double>>();
  for (double v:values) if (!std::isfinite(v)) throw std::invalid_argument("Expected finite values");
  return values;
}

Json generate(const Json &input) {
  if (input.at("mode")!="axis_stop") throw std::invalid_argument("Expected axis_stop mode");
  const Eigen::MatrixXd initial=matrix(input.at("initial_pva"));
  const auto stops=numbers(input.at("axis_stop_durations_xyz"));
  const auto positions=numbers(input.at("stop_positions"));
  const auto jerk=numbers(input.value("initial_jerk",Json::array({0.,0.,0.})));
  if (initial.rows()!=3 || initial.cols()!=3 || !initial.allFinite() ||
      stops.size()!=3 || positions.size()!=3 || jerk.size()!=3)
    throw std::invalid_argument("Expected finite 3x3 PVA, three stops/positions/jerks");
  const Json inner=input.value("axis_inner_positions_xyz",Json::array({Json::array(),Json::array(),Json::array()}));
  const Json times=input.value("axis_segment_durations_xyz",Json::array({Json::array({stops[0]}),Json::array({stops[1]}),Json::array({stops[2]})}));
  if (!inner.is_array() || !times.is_array() || inner.size()!=3 || times.size()!=3)
    throw std::invalid_argument("Expected one inner-position/duration array per axis");
  std::vector<Trajectory<7>> axes(3);
  std::vector<std::vector<double>> axisKnots(3,std::vector<double>{0.});
  std::vector<double> actualStops(3),knots={0.};
  Json counts=Json::array();
  for (int axis=0;axis<3;++axis) {
    const auto durations=numbers(times.at(axis)),points=numbers(inner.at(axis));
    if (durations.empty() || points.size()+1!=durations.size() || stops[axis]<=0.)
      throw std::invalid_argument("Expected N positive durations and N-1 inner positions");
    double total=0.;
    for (double duration:durations) {
      if (duration<=0.) throw std::invalid_argument("Piece durations must be positive");
      const double next=total+duration;
      if (!std::isfinite(next) || next<=total)
        throw std::invalid_argument("Axis cumulative time did not strictly advance");
      total=next; knots.push_back(total);axisKnots[axis].push_back(total);
    }
    if (!std::isfinite(total) || std::abs(total-stops[axis])>1e-9)
      throw std::invalid_argument("Axis durations do not sum to its stopping time; no rescaling");
    actualStops[axis]=total; counts.push_back(durations.size());
    Eigen::Matrix<double,3,4> head=Eigen::Matrix<double,3,4>::Zero(),tail=head;
    head.col(0)=initial.col(0);tail.col(0)=initial.col(0);
    head.block<1,3>(axis,0)=initial.row(axis);head(axis,3)=jerk[axis];tail(axis,0)=positions[axis];
    Eigen::Matrix3Xd waypoints(3,points.size());
    for (int i=0;i<waypoints.cols();++i) { waypoints.col(i)=initial.col(0);waypoints(axis,i)=points[i]; }
    Eigen::VectorXd durationsVector(durations.size());
    for (int i=0;i<durationsVector.size();++i) durationsVector[i]=durations[i];
    minco::MINCO_S4NU solver;solver.setConditions(head,tail,durations.size());
    solver.setParameters(waypoints,durationsVector);solver.getTrajectory(axes[axis]);
  }
  auto stateAt=[&](double t) {
    Eigen::Matrix<double,3,4> state=Eigen::Matrix<double,3,4>::Zero();
    for (int axis=0;axis<3;++axis) {
      if (t>=actualStops[axis]) state(axis,0)=positions[axis];
      else {
        state(axis,0)=axes[axis].getPos(t)[axis];state(axis,1)=axes[axis].getVel(t)[axis];
        state(axis,2)=axes[axis].getAcc(t)[axis];state(axis,3)=axes[axis].getJer(t)[axis];
      }
    }
    return state;
  };
  std::sort(knots.begin(),knots.end());knots.erase(std::unique(knots.begin(),knots.end()),knots.end());
  Json pieces=Json::array();
  double boundaryError=0.;
  for (size_t i=1;i<knots.size();++i) {
    const double duration=knots[i]-knots[i-1];
    const auto head=stateAt(knots[i-1]),tail=stateAt(knots[i]);
    Eigen::Matrix<double,3,8> coeff=Eigen::Matrix<double,3,8>::Zero();
    for (int axis=0;axis<3;++axis) {
      if (knots[i-1]>=actualStops[axis]) {coeff(axis,7)=positions[axis];continue;}
      size_t source=0;
      while (source+2<axisKnots[axis].size() && knots[i-1]>=axisKnots[axis][source+1]) ++source;
      const long double offset=static_cast<long double>(knots[i-1])-axisKnots[axis][source];
      const auto &original=axes[axis][source].getCoeffMat();
      // Translate the existing polynomial p(t+offset), without a new endpoint
      // solve. Near-coincident axis knots otherwise amplify endpoint roundoff.
      for (int power=0;power<8;++power) {
        long double value=0.;
        for (int sourcePower=power;sourcePower<8;++sourcePower) {
          unsigned choose=1;
          for (int k=1;k<=power;++k) choose=choose*(sourcePower-k+1)/k;
          value+=static_cast<long double>(original(axis,7-sourcePower))*choose*std::pow(offset,sourcePower-power);
        }
        coeff(axis,7-power)=static_cast<double>(value);
      }
    }
    Trajectory<7> segment;segment.emplace_back(duration,coeff);
    if (!coeff.allFinite()) throw std::runtime_error("Nonfinite coefficients at unified breakpoints");
    for (int end=0;end<2;++end) {
      const double t=end ? duration : 0.;
      Eigen::Matrix<double,3,4> reconstructed;
      reconstructed.col(0)=segment.getPos(t);reconstructed.col(1)=segment.getVel(t);
      reconstructed.col(2)=segment.getAcc(t);reconstructed.col(3)=segment.getJer(t);
      boundaryError=std::max(boundaryError,(reconstructed-(end ? tail : head)).cwiseAbs().maxCoeff());
      if (!reconstructed.allFinite() || boundaryError>1e-8)
        throw std::runtime_error("Unified piece did not reconstruct source endpoint PVAJ");
    }
    Json rows=Json::array();
    for (int axis=0;axis<3;++axis) {
      Json row=Json::array();for (int k=0;k<8;++k) row.push_back(coeff(axis,k));rows.push_back(row);
    }
    pieces.push_back({{"duration",duration},{"coefficients_descending",rows}});
  }
  return {{"native_success",!pieces.empty()},{"setup_ok",true},{"cost",0.},
    {"generator","official_MINCO_S4NU_axis_inner_points"},{"polynomial_degree",7},
    {"unified_piece_method","source_polynomial_time_translation_no_refit"},
    {"axis_piece_counts",counts},{"axis_stop_actual_durations_xyz",actualStops},{"pieces",pieces},
    {"reconstruction_boundary_error",boundaryError},
    {"initial_jerk_source",input.contains("initial_jerk") ? "explicit" : "assumed_zero_not_measured"},
    {"execution_admission","not_performed"}};
}

int main() {
  std::string line;
  while (std::getline(std::cin,line)) {
    Json output;
    const auto started=std::chrono::steady_clock::now();
    try { const auto input=Json::parse(line);output=generate(input);output["id"]=input.value("id",std::string("offline-s4-knots")); }
    catch (const std::exception &error) { output={{"native_success",false},{"error",error.what()},{"execution_admission","not_performed"}}; }
    output["elapsed_ms"]=std::chrono::duration<double,std::milli>(std::chrono::steady_clock::now()-started).count();
    std::cout<<"MincoResult "<<output.dump()<<std::endl;
  }
}
