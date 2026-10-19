/*
 * OpenVINS: An Open Platform for Visual-Inertial Research
 * Copyright (C) 2018-2023 OpenVINS Contributors
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

#include "UpdaterLegVelocity.h"

#include <algorithm>
#include <cmath>
#include <vector>

#include "state/Propagator.h"
#include "state/State.h"
#include "state/StateHelper.h"
#include "types/IMU.h"
#include "types/Type.h"
#include "utils/quat_ops.h"

using namespace ov_core;
using namespace ov_type;
using namespace ov_msckf;

UpdaterLegVelocity::UpdaterLegVelocity(bool use_vertical, bool use_yaw_rate, double horizontal_variance_floor,
                                       double vertical_variance_floor, double yaw_rate_variance_floor, double chi2_multiplier)
    : use_vertical_(use_vertical), use_yaw_rate_(use_yaw_rate),
      horizontal_variance_floor_(horizontal_variance_floor), vertical_variance_floor_(vertical_variance_floor),
      yaw_rate_variance_floor_(yaw_rate_variance_floor), chi2_multiplier_(chi2_multiplier) {}

bool UpdaterLegVelocity::linearize(std::shared_ptr<State> state, const ov_core::ImuData &imu_measurement,
                                   const Eigen::Matrix3d &R_BI, const Eigen::Vector3d &r_IB_in_I,
                                   LegVelocityLinearization &linearization, std::string &reason) {
  // 此函数只计算观测模型和雅可比，不能修改状态，保证有限差分测试与实际 EKF 使用同一套数学实现。
  linearization = LegVelocityLinearization();
  if (state == nullptr || !imu_measurement.wm.allFinite() || !imu_measurement.am.allFinite() || !R_BI.allFinite() ||
      !r_IB_in_I.allFinite()) {
    reason = "non_finite_linearization_input";
    return false;
  }

  // 使用与 Propagator 完全相同的 IMU 内参、重力敏感度和坐标旋转模型修正角速度。
  const Eigen::Matrix3d Dw = State::Dm(state->_options.imu_model, state->_calib_imu_dw->value());
  const Eigen::Matrix3d Da = State::Dm(state->_options.imu_model, state->_calib_imu_da->value());
  const Eigen::Matrix3d Tg = State::Tg(state->_calib_imu_tg->value());
  const Eigen::Matrix3d R_ACCtoI = state->_calib_imu_ACCtoIMU->Rot();
  const Eigen::Matrix3d R_GYROtoI = state->_calib_imu_GYROtoIMU->Rot();
  const Eigen::Vector3d a_uncorrected = imu_measurement.am - state->_imu->bias_a();
  const Eigen::Vector3d a_in_I = R_ACCtoI * Da * a_uncorrected;
  const Eigen::Vector3d w_uncorrected = imu_measurement.wm - state->_imu->bias_g() - Tg * a_in_I;
  const Eigen::Vector3d w_in_I = R_GYROtoI * Dw * w_uncorrected;

  // 头部 IMU 到 base_link 的刚体速度变换：完整角速度参与叉乘，不能只使用 yaw_rate。
  const Eigen::Matrix3d R_GI = state->_imu->Rot();
  const Eigen::Vector3d v_I_in_I = R_GI * state->_imu->vel();
  linearization.predicted.head<3>() = R_BI * (v_I_in_I + w_in_I.cross(r_IB_in_I));
  linearization.predicted(3) = Eigen::Vector3d::UnitZ().dot(R_BI * w_in_I);

  // H_omega 把角速度误差同时映射到杆臂线速度和 base_link 偏航角速度。
  Eigen::Matrix<double, 4, 3> H_omega_full = Eigen::Matrix<double, 4, 3>::Zero();
  H_omega_full.block<3, 3>(0, 0) = -R_BI * skew_x(r_IB_in_I);
  H_omega_full.block<1, 3>(3, 0) = Eigen::Vector3d::UnitZ().transpose() * R_BI;

  Eigen::Matrix<double, 4, 15> H_imu_full = Eigen::Matrix<double, 4, 15>::Zero();
  const Eigen::Matrix3d R_GI_jacobian = state->_options.do_fej ? state->_imu->Rot_fej() : R_GI;
  H_imu_full.block<3, 3>(0, 0) = R_BI * skew_x(R_GI_jacobian * state->_imu->vel());
  H_imu_full.block<3, 3>(0, 6) = R_BI * R_GI_jacobian;
  const Eigen::Matrix3d J_w_bg = -R_GYROtoI * Dw;
  const Eigen::Matrix3d J_w_ba = R_GYROtoI * Dw * Tg * R_ACCtoI * Da;
  H_imu_full.block<4, 3>(0, 9) = H_omega_full * J_w_bg;
  H_imu_full.block<4, 3>(0, 12) = H_omega_full * J_w_ba;

  linearization.order.push_back(state->_imu);
  linearization.blocks.emplace_back(H_imu_full);

  if (state->_options.do_calib_imu_intrinsics) {
    const Eigen::MatrixXd J_w_Dw = R_GYROtoI * Propagator::compute_H_Dw(state, w_uncorrected);
    const Eigen::MatrixXd J_w_Da =
        -R_GYROtoI * Dw * Tg * R_ACCtoI * Propagator::compute_H_Da(state, a_uncorrected);
    linearization.order.push_back(state->_calib_imu_dw);
    linearization.blocks.emplace_back(H_omega_full * J_w_Dw);
    linearization.order.push_back(state->_calib_imu_da);
    linearization.blocks.emplace_back(H_omega_full * J_w_Da);

    if (state->_options.do_calib_imu_g_sensitivity) {
      const Eigen::MatrixXd J_w_Tg = -R_GYROtoI * Dw * Propagator::compute_H_Tg(state, a_in_I);
      linearization.order.push_back(state->_calib_imu_tg);
      linearization.blocks.emplace_back(H_omega_full * J_w_Tg);
    }

    if (state->_options.imu_model == StateOptions::ImuModel::KALIBR) {
      linearization.order.push_back(state->_calib_imu_GYROtoIMU);
      linearization.blocks.emplace_back(H_omega_full * skew_x(w_in_I));
    } else {
      const Eigen::Matrix3d J_w_ACCtoI = -R_GYROtoI * Dw * Tg * skew_x(a_in_I);
      linearization.order.push_back(state->_calib_imu_ACCtoIMU);
      linearization.blocks.emplace_back(H_omega_full * J_w_ACCtoI);
    }
  }

  if (!linearization.predicted.allFinite()) {
    reason = "non_finite_prediction";
    return false;
  }
  reason = "ok";
  return true;
}

LegVelocityUpdateResult UpdaterLegVelocity::update(std::shared_ptr<State> state, const ov_core::LegVelocityData &measurement,
                                                   const ov_core::ImuData &imu_measurement, const Eigen::Matrix3d &R_BI,
                                                   const Eigen::Vector3d &r_IB_in_I) {
  LegVelocityUpdateResult result;
  if (!measurement.measurement.allFinite() || !measurement.covariance.allFinite()) {
    result.reason = "non_finite_input";
    return result;
  }

  LegVelocityLinearization linearization;
  if (!linearize(state, imu_measurement, R_BI, r_IB_in_I, linearization, result.reason)) {
    return result;
  }

  std::vector<int> selected_rows = {0, 1};
  if (use_vertical_) {
    selected_rows.push_back(2);
  }
  if (use_yaw_rate_) {
    selected_rows.push_back(3);
  }
  const int measurement_size = static_cast<int>(selected_rows.size());

  Eigen::VectorXd residual = Eigen::VectorXd::Zero(measurement_size);
  Eigen::MatrixXd covariance = Eigen::MatrixXd::Zero(measurement_size, measurement_size);
  Eigen::Matrix<double, 4, 4> covariance_full = 0.5 * (measurement.covariance + measurement.covariance.transpose());
  for (const int selected_row : selected_rows) {
    if (covariance_full(selected_row, selected_row) <= 0.0) {
      result.reason = "covariance_non_positive_variance";
      return result;
    }
  }
  // 先保留输入的完整交叉协方差，再只抬高各观测方差下限并检查所用子矩阵正定性。
  covariance_full(0, 0) = std::max(covariance_full(0, 0), horizontal_variance_floor_);
  covariance_full(1, 1) = std::max(covariance_full(1, 1), horizontal_variance_floor_);
  covariance_full(2, 2) = std::max(covariance_full(2, 2), vertical_variance_floor_);
  covariance_full(3, 3) = std::max(covariance_full(3, 3), yaw_rate_variance_floor_);
  for (int row = 0; row < measurement_size; ++row) {
    residual(row) = measurement.measurement(selected_rows.at(row)) - linearization.predicted(selected_rows.at(row));
    result.innovation(selected_rows.at(row)) = residual(row);
    for (int col = 0; col < measurement_size; ++col) {
      covariance(row, col) = covariance_full(selected_rows.at(row), selected_rows.at(col));
    }
  }
  result.residual = residual;
  if (Eigen::LLT<Eigen::MatrixXd>(covariance).info() != Eigen::Success) {
    result.reason = "covariance_not_positive_definite";
    return result;
  }

  int total_columns = 0;
  for (const auto &block : linearization.blocks) {
    total_columns += block.cols();
  }
  Eigen::MatrixXd H = Eigen::MatrixXd::Zero(measurement_size, total_columns);
  int column = 0;
  for (const auto &block : linearization.blocks) {
    for (int row = 0; row < measurement_size; ++row) {
      H.block(row, column, 1, block.cols()) = block.row(selected_rows.at(row));
    }
    column += block.cols();
  }

  const Eigen::MatrixXd P_marginal = StateHelper::get_marginal_covariance(state, linearization.order);
  const Eigen::MatrixXd innovation_covariance = H * P_marginal * H.transpose() + covariance;
  Eigen::LLT<Eigen::MatrixXd> innovation_llt(innovation_covariance);
  if (innovation_llt.info() != Eigen::Success) {
    result.reason = "innovation_not_positive_definite";
    return result;
  }
  result.chi2 = residual.dot(innovation_llt.solve(residual));
  const double chi2_95[] = {0.0, 3.8414588207, 5.9914645471, 7.8147279033, 9.4877290368};
  result.chi2_threshold = chi2_multiplier_ * chi2_95[measurement_size];
  if (!std::isfinite(result.chi2) || result.chi2 > result.chi2_threshold) {
    result.reason = "chi2_rejected";
    return result;
  }

  StateHelper::EKFUpdate(state, linearization.order, H, residual, covariance);
  result.accepted = true;
  result.reason = "accepted";
  return result;
}
