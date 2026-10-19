/*
 * OpenVINS: An Open Platform for Visual-Inertial Research
 * Copyright (C) 2018-2023 OpenVINS Contributors
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

#ifndef OV_MSCKF_UPDATER_LEG_VELOCITY_H
#define OV_MSCKF_UPDATER_LEG_VELOCITY_H

#include <Eigen/Eigen>
#include <limits>
#include <memory>
#include <string>
#include <vector>

#include "utils/sensor_data.h"

namespace ov_type {
class Type;
}

namespace ov_msckf {

class State;

/// 足式速度更新结果，供状态机和诊断输出使用。
struct LegVelocityUpdateResult {
  bool accepted = false;
  double chi2 = -1.0;
  double chi2_threshold = -1.0;
  Eigen::VectorXd residual;
  Eigen::Matrix<double, 4, 1> innovation = Eigen::Matrix<double, 4, 1>::Constant(
      std::numeric_limits<double>::quiet_NaN());
  std::string reason = "not_attempted";
};

/// 足式观测的完整四维预测和各状态块雅可比，公开结构用于有限差分测试。
struct LegVelocityLinearization {
  Eigen::Matrix<double, 4, 1> predicted = Eigen::Matrix<double, 4, 1>::Zero();
  std::vector<std::shared_ptr<ov_type::Type>> order;
  std::vector<Eigen::MatrixXd> blocks;
};

/**
 * @brief 使用 base_link 三维速度和偏航角速度约束 OpenVINS IMU 状态。
 */
class UpdaterLegVelocity {
public:
  /// 创建足式速度更新器，所有阈值均来自 VioManagerOptions。
  UpdaterLegVelocity(bool use_vertical, bool use_yaw_rate, double horizontal_variance_floor, double vertical_variance_floor,
                     double yaw_rate_variance_floor, double chi2_multiplier);

  /**
   * @brief 计算四维速度预测与雅可比，不修改状态，供更新器和数学测试共用。
   */
  static bool linearize(std::shared_ptr<State> state, const ov_core::ImuData &imu_measurement,
                        const Eigen::Matrix3d &R_BI, const Eigen::Vector3d &r_IB_in_I,
                        LegVelocityLinearization &linearization, std::string &reason);

  /**
   * @brief 在当前相机状态时刻执行一次足式速度 EKF 更新。
   * @param state OpenVINS 当前状态
   * @param measurement base_link 下的速度观测
   * @param imu_measurement 相机时刻插值得到的原始 IMU 观测
   * @param R_BI 从 IMU 坐标系旋转到 base_link 坐标系
   * @param r_IB_in_I 从 IMU 原点指向 base_link 原点、表达在 IMU 下的杆臂
   */
  LegVelocityUpdateResult update(std::shared_ptr<State> state, const ov_core::LegVelocityData &measurement,
                                 const ov_core::ImuData &imu_measurement, const Eigen::Matrix3d &R_BI,
                                 const Eigen::Vector3d &r_IB_in_I);

private:
  bool use_vertical_ = true;
  bool use_yaw_rate_ = true;
  double horizontal_variance_floor_ = 0.05;
  double vertical_variance_floor_ = 0.10;
  double yaw_rate_variance_floor_ = 0.02;
  double chi2_multiplier_ = 1.0;
};

} // namespace ov_msckf

#endif // OV_MSCKF_UPDATER_LEG_VELOCITY_H
