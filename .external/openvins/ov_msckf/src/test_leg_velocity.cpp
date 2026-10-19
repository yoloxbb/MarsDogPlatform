/*
 * OpenVINS: An Open Platform for Visual-Inertial Research
 * Copyright (C) 2018-2023 OpenVINS Contributors
 */

#include <Eigen/Eigen>
#include <cmath>
#include <iostream>
#include <memory>
#include <string>

#include "cam/CamRadtan.h"
#include "core/VioManager.h"
#include "state/State.h"
#include "state/StateHelper.h"
#include "types/Type.h"
#include "update/UpdaterLegVelocity.h"
#include "utils/quat_ops.h"

using namespace ov_core;
using namespace ov_msckf;

namespace {

class TestVioManager : public VioManager {
public:
  using VioManager::VioManager;
  using VioManager::update_leg_velocity_aiding;
};

/// 检查向量是否在给定绝对误差内一致，并输出便于定位的中文错误。
bool expect_near(const Eigen::Vector4d &actual, const Eigen::Vector4d &expected, double tolerance,
                 const std::string &name) {
  const double error = (actual - expected).cwiseAbs().maxCoeff();
  if (!std::isfinite(error) || error > tolerance) {
    std::cerr << name << " 失败，最大误差=" << error << "\n实际=" << actual.transpose()
              << "\n期望=" << expected.transpose() << std::endl;
    return false;
  }
  return true;
}

/// 设置包含非零姿态、速度、偏置和 IMU 内参的测试状态，避免零值掩盖雅可比错误。
std::shared_ptr<State> make_state(StateOptions::ImuModel model) {
  StateOptions options;
  options.num_cameras = 1;
  options.do_fej = false;
  options.do_calib_imu_intrinsics = true;
  options.do_calib_imu_g_sensitivity = true;
  options.imu_model = model;
  auto state = std::make_shared<State>(options);

  Eigen::Matrix<double, 16, 1> imu_value = Eigen::Matrix<double, 16, 1>::Zero();
  imu_value.head<4>() = rot_2_quat(exp_so3(Eigen::Vector3d(0.12, -0.07, 0.09)));
  imu_value.segment<3>(4) << 0.3, -0.2, 1.1;
  imu_value.segment<3>(7) << 0.8, -0.45, 0.32;
  imu_value.segment<3>(10) << 0.015, -0.012, 0.009;
  imu_value.segment<3>(13) << -0.08, 0.04, 0.03;
  state->_imu->set_value(imu_value);
  state->_imu->set_fej(imu_value);

  Eigen::Matrix<double, 6, 1> dw;
  dw << 1.01, 0.012, -0.008, 0.99, 0.006, 1.02;
  Eigen::Matrix<double, 6, 1> da;
  da << 0.98, -0.009, 0.011, 1.015, -0.007, 1.005;
  Eigen::Matrix<double, 9, 1> tg;
  tg << 0.001, -0.002, 0.0015, 0.0007, -0.0011, 0.0009, -0.0005, 0.0008, -0.0013;
  state->_calib_imu_dw->set_value(dw);
  state->_calib_imu_da->set_value(da);
  state->_calib_imu_tg->set_value(tg);
  state->_calib_imu_GYROtoIMU->set_value(
      rot_2_quat(exp_so3(Eigen::Vector3d(0.025, -0.018, 0.011))));
  state->_calib_imu_ACCtoIMU->set_value(
      rot_2_quat(exp_so3(Eigen::Vector3d(-0.016, 0.013, -0.021))));
  return state;
}

/// 校验零杆臂、平移、垂直运动、原地旋转和 roll/pitch 杆臂速度的物理方向。
bool test_rigid_body_model() {
  StateOptions options;
  options.num_cameras = 1;
  auto state = std::make_shared<State>(options);
  Eigen::Matrix<double, 16, 1> value = Eigen::Matrix<double, 16, 1>::Zero();
  value(3) = 1.0;
  value.segment<3>(7) << 1.0, -2.0, 0.7;
  state->_imu->set_value(value);
  state->_imu->set_fej(value);

  ImuData imu;
  imu.wm << 0.0, 0.0, 1.5;
  imu.am.setZero();
  LegVelocityLinearization linearization;
  std::string reason;
  if (!UpdaterLegVelocity::linearize(state, imu, Eigen::Matrix3d::Identity(), Eigen::Vector3d::Zero(),
                                     linearization, reason)) {
    std::cerr << "零杆臂模型计算失败: " << reason << std::endl;
    return false;
  }
  if (!expect_near(linearization.predicted, Eigen::Vector4d(1.0, -2.0, 0.7, 1.5), 1e-12,
                   "零杆臂三维平移与偏航角速度")) {
    return false;
  }

  value.segment<3>(7).setZero();
  state->_imu->set_value(value);
  state->_imu->set_fej(value);
  if (!UpdaterLegVelocity::linearize(state, imu, Eigen::Matrix3d::Identity(), Eigen::Vector3d(1.0, 0.0, 0.0),
                                     linearization, reason)) {
    return false;
  }
  if (!expect_near(linearization.predicted, Eigen::Vector4d(0.0, 1.5, 0.0, 1.5), 1e-12,
                   "原地偏航旋转杆臂速度")) {
    return false;
  }

  // yaw_rate 是角速度旋转到 base_link 后的 z 分量，不等同于头部 IMU 的原始 wz。
  imu.wm << 0.0, 1.0, 0.0;
  const Eigen::Matrix3d rotated_base = exp_so3(Eigen::Vector3d(0.5 * std::acos(-1.0), 0.0, 0.0));
  if (!UpdaterLegVelocity::linearize(state, imu, rotated_base, Eigen::Vector3d::Zero(), linearization, reason)) {
    return false;
  }
  if (!expect_near(linearization.predicted, Eigen::Vector4d(0.0, 0.0, 0.0, 1.0), 1e-12,
                   "base_link 偏航角速度投影")) {
    return false;
  }

  // 头部绕 IMU x 轴转动、base_link 位于 IMU 下方时，w×r 应产生 +y 速度。
  imu.wm << 2.0, 0.0, 0.0;
  if (!UpdaterLegVelocity::linearize(state, imu, Eigen::Matrix3d::Identity(), Eigen::Vector3d(0.0, 0.0, -0.4),
                                     linearization, reason)) {
    return false;
  }
  return expect_near(linearization.predicted, Eigen::Vector4d(0.0, 0.8, 0.0, 0.0), 1e-12,
                     "roll/pitch 角速度杆臂补偿");
}

/// 对一个 IMU 模型的全部启用状态块执行前向有限差分雅可比校验。
bool test_finite_difference(StateOptions::ImuModel model) {
  auto state = make_state(model);
  ImuData imu;
  imu.wm << 0.72, -0.38, 0.51;
  imu.am << 0.43, -0.27, 9.61;
  const Eigen::Matrix3d R_BI = exp_so3(Eigen::Vector3d(-0.18, 0.11, 0.24));
  const Eigen::Vector3d lever(0.31, -0.06, -0.48);

  LegVelocityLinearization baseline;
  std::string reason;
  if (!UpdaterLegVelocity::linearize(state, imu, R_BI, lever, baseline, reason)) {
    std::cerr << "基准雅可比计算失败: " << reason << std::endl;
    return false;
  }

  constexpr double epsilon = 1e-7;
  constexpr double tolerance = 4e-5;
  for (size_t block_index = 0; block_index < baseline.order.size(); ++block_index) {
    const std::shared_ptr<ov_type::Type> variable = baseline.order.at(block_index);
    const Eigen::MatrixXd original_value = variable->value();
    for (int column = 0; column < variable->size(); ++column) {
      Eigen::VectorXd delta = Eigen::VectorXd::Zero(variable->size());
      delta(column) = epsilon;
      variable->update(delta);

      LegVelocityLinearization perturbed;
      if (!UpdaterLegVelocity::linearize(state, imu, R_BI, lever, perturbed, reason)) {
        std::cerr << "扰动后雅可比计算失败: " << reason << std::endl;
        return false;
      }
      const Eigen::Vector4d numeric = (perturbed.predicted - baseline.predicted) / epsilon;
      variable->set_value(original_value);
      if (!expect_near(numeric, baseline.blocks.at(block_index).col(column), tolerance,
                       "有限差分 block=" + std::to_string(block_index) + " col=" + std::to_string(column))) {
        return false;
      }
    }
  }
  return true;
}

/// 校验非法协方差不会进入 EKF，合法更新后状态协方差仍为半正定。
bool test_covariance_validation() {
  StateOptions options;
  options.num_cameras = 1;
  auto state = std::make_shared<State>(options);
  UpdaterLegVelocity updater(true, true, 0.05, 0.10, 0.02, 1.0);
  ImuData imu;
  imu.wm.setZero();
  imu.am.setZero();
  LegVelocityData measurement;
  measurement.measurement.setZero();
  measurement.covariance = 0.1 * Eigen::Matrix4d::Identity();
  measurement.covariance(0, 0) = -0.1;
  LegVelocityUpdateResult result = updater.update(
      state, measurement, imu, Eigen::Matrix3d::Identity(), Eigen::Vector3d::Zero());
  if (result.reason != "covariance_non_positive_variance") {
    std::cerr << "负方差拒绝失败，reason=" << result.reason << std::endl;
    return false;
  }

  measurement.covariance = 0.1 * Eigen::Matrix4d::Identity();
  measurement.covariance(0, 1) = 1.0;
  measurement.covariance(1, 0) = 1.0;
  result = updater.update(state, measurement, imu, Eigen::Matrix3d::Identity(), Eigen::Vector3d::Zero());
  if (result.reason != "covariance_not_positive_definite") {
    std::cerr << "非正定协方差拒绝失败，reason=" << result.reason << std::endl;
    return false;
  }

  measurement.covariance = 0.1 * Eigen::Matrix4d::Identity();
  measurement.covariance(0, 1) = measurement.covariance(1, 0) = 0.02;
  measurement.covariance(2, 3) = measurement.covariance(3, 2) = -0.01;
  result = updater.update(state, measurement, imu, Eigen::Matrix3d::Identity(), Eigen::Vector3d::Zero());
  if (!result.accepted) {
    std::cerr << "合法协方差未通过更新，reason=" << result.reason << std::endl;
    return false;
  }
  const Eigen::MatrixXd covariance = StateHelper::get_full_covariance(state);
  const Eigen::MatrixXd symmetric_covariance = 0.5 * (covariance + covariance.transpose());
  const Eigen::SelfAdjointEigenSolver<Eigen::MatrixXd> eigen_solver(symmetric_covariance);
  if (eigen_solver.info() != Eigen::Success || eigen_solver.eigenvalues().minCoeff() < -1e-10) {
    std::cerr << "EKF 更新后协方差不是半正定，最小特征值="
              << eigen_solver.eigenvalues().minCoeff() << std::endl;
    return false;
  }
  return true;
}

/// 创建最小单目配置，仅用于不依赖图像数据的足式辅助状态机测试。
VioManagerOptions make_manager_options(bool enabled) {
  VioManagerOptions options;
  options.state_options.num_cameras = 1;
  options.init_options.num_cameras = 1;
  options.leg_velocity_enabled = enabled;
  options.vec_dw << 1.0, 0.0, 0.0, 1.0, 0.0, 1.0;
  options.vec_da = options.vec_dw;
  options.vec_tg.setZero();
  options.q_GYROtoIMU << 0.0, 0.0, 0.0, 1.0;
  options.q_ACCtoIMU = options.q_GYROtoIMU;
  auto camera = std::make_shared<CamRadtan>(640, 480);
  Eigen::VectorXd calibration(8);
  calibration << 400.0, 400.0, 320.0, 240.0, 0.0, 0.0, 0.0, 0.0;
  camera->set_value(calibration);
  options.camera_intrinsics.emplace(0, camera);
  Eigen::VectorXd extrinsics(7);
  extrinsics << 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0;
  options.camera_extrinsics.emplace(0, extrinsics);
  options.init_options.camera_intrinsics = options.camera_intrinsics;
  options.init_options.camera_extrinsics = options.camera_extrinsics;
  return options;
}

/// 覆盖视觉丢失立即接管、恢复迟滞、时间插值、足式不可用和卡方拒绝状态。
bool test_visual_state_machine() {
  const auto initialize_filter_covariance = [](TestVioManager &target) {
    const Eigen::Matrix<double, 15, 15> imu_covariance =
        0.01 * Eigen::Matrix<double, 15, 15>::Identity();
    StateHelper::set_initial_covariance(target.get_state(), imu_covariance, {target.get_state()->_imu});
  };

  VioManagerOptions disabled_options = make_manager_options(false);
  TestVioManager disabled(disabled_options);
  VisualUpdateStats stats;
  stats.timestamp = 1.0;
  stats.active_observations = 100;
  stats.msckf_accepted = 8;
  disabled.update_leg_velocity_aiding(stats);
  if (disabled.get_leg_velocity_status().mode != LegVelocityMode::DISABLED) {
    std::cerr << "默认关闭状态机失败" << std::endl;
    return false;
  }

  VioManagerOptions enabled_options = make_manager_options(true);
  enabled_options.leg_velocity_recovery_time = 0.20;
  enabled_options.leg_velocity_min_active_observations = 50;
  enabled_options.leg_velocity_recovery_accepted = 12;
  TestVioManager manager(enabled_options);
  initialize_filter_covariance(manager);
  if (manager.get_leg_velocity_status().mode != LegVelocityMode::WAITING) {
    std::cerr << "初始化等待状态失败" << std::endl;
    return false;
  }
  manager.set_leg_velocity_extrinsics(Eigen::Matrix3d::Identity(), Eigen::Vector3d::Zero());
  manager.update_leg_velocity_aiding(stats);
  if (manager.get_leg_velocity_status().mode != LegVelocityMode::VISUAL_ONLY) {
    std::cerr << "有视觉约束时进入纯视觉模式失败" << std::endl;
    return false;
  }

  // 第一帧没有视觉约束时必须立即使用同一时刻的足式速度，不能等待累计丢失帧数。
  const auto feed_imu_at = [](TestVioManager &target, double timestamp) {
    target.get_state()->_timestamp = timestamp;
    ImuData imu_before;
    imu_before.timestamp = timestamp - 0.01;
    imu_before.wm.setZero();
    imu_before.am.setZero();
    ImuData imu_after = imu_before;
    imu_after.timestamp = timestamp + 0.01;
    target.feed_measurement_imu(imu_before);
    target.feed_measurement_imu(imu_after);
  };
  const auto feed_leg = [](TestVioManager &target, double timestamp, const Eigen::Vector4d &velocity) {
    LegVelocityData measurement;
    measurement.timestamp = timestamp;
    measurement.measurement = velocity;
    measurement.covariance = 0.1 * Eigen::Matrix4d::Identity();
    target.feed_measurement_leg_velocity(measurement);
  };

  stats.timestamp = 1.05;
  stats.msckf_accepted = 0;
  stats.active_observations = 80;
  feed_imu_at(manager, stats.timestamp);
  feed_leg(manager, stats.timestamp, Eigen::Vector4d::Zero());
  manager.update_leg_velocity_aiding(stats);
  const LegVelocityStatus lost_status = manager.get_leg_velocity_status();
  if (lost_status.mode != LegVelocityMode::LEG_ASSIST || !lost_status.update_accepted) {
    std::cerr << "单帧视觉丢失未立即启用足式速度，reason=" << lost_status.reason << std::endl;
    return false;
  }

  // 视觉刚恢复但活动观测不足时必须继续足式辅助，不能被少量视觉约束抢占。
  stats.timestamp = 1.10;
  stats.msckf_accepted = 4;
  stats.active_observations = 40;
  feed_imu_at(manager, stats.timestamp);
  feed_leg(manager, stats.timestamp, Eigen::Vector4d::Zero());
  manager.update_leg_velocity_aiding(stats);
  const LegVelocityStatus weak_recovery_status = manager.get_leg_velocity_status();
  if (weak_recovery_status.mode != LegVelocityMode::RECOVERING || !weak_recovery_status.update_accepted) {
    std::cerr << "弱视觉恢复错误地停用了足式速度，reason=" << weak_recovery_status.reason << std::endl;
    return false;
  }

  // 活动观测达到阈值后开始连续恢复窗口。
  stats.timestamp = 1.15;
  stats.active_observations = 80;
  feed_imu_at(manager, stats.timestamp);
  feed_leg(manager, stats.timestamp, Eigen::Vector4d::Zero());
  manager.update_leg_velocity_aiding(stats);
  if (manager.get_leg_velocity_status().mode != LegVelocityMode::RECOVERING) {
    std::cerr << "稳定视觉首帧未保持恢复模式" << std::endl;
    return false;
  }

  // 恢复窗口内任何一帧没有视觉更新，都必须立即重新启用足式并清空恢复进度。
  stats.timestamp = 1.20;
  stats.msckf_accepted = 0;
  feed_imu_at(manager, stats.timestamp);
  feed_leg(manager, stats.timestamp, Eigen::Vector4d::Zero());
  manager.update_leg_velocity_aiding(stats);
  if (manager.get_leg_velocity_status().mode != LegVelocityMode::LEG_ASSIST) {
    std::cerr << "视觉恢复中断后未立即回到足式辅助" << std::endl;
    return false;
  }

  // 重新连续恢复：累计约束达到阈值但时间不足时仍不能停用足式。
  stats.msckf_accepted = 6;
  stats.timestamp = 1.25;
  feed_imu_at(manager, stats.timestamp);
  feed_leg(manager, stats.timestamp, Eigen::Vector4d::Zero());
  manager.update_leg_velocity_aiding(stats);
  stats.timestamp = 1.36;
  feed_imu_at(manager, stats.timestamp);
  feed_leg(manager, stats.timestamp, Eigen::Vector4d::Zero());
  manager.update_leg_velocity_aiding(stats);
  if (manager.get_leg_velocity_status().mode != LegVelocityMode::RECOVERING) {
    std::cerr << "视觉恢复时间不足时过早停用了足式" << std::endl;
    return false;
  }

  // 连续时间和累计约束均达标后才回到纯视觉；该帧不得再消费足式消息。
  stats.timestamp = 1.46;
  feed_imu_at(manager, stats.timestamp);
  feed_leg(manager, stats.timestamp, Eigen::Vector4d::Constant(4.9));
  manager.update_leg_velocity_aiding(stats);
  const LegVelocityStatus recovered_status = manager.get_leg_velocity_status();
  if (recovered_status.mode != LegVelocityMode::VISUAL_ONLY || recovered_status.update_accepted ||
      recovered_status.reason != "visual_recovery_stable") {
    std::cerr << "视觉连续稳定后未停用足式速度，reason=" << recovered_status.reason << std::endl;
    return false;
  }

  // 再次出现单帧视觉丢失但没有可用的新足式消息时，应立即报告仅 IMU。
  stats.timestamp = 1.80;
  stats.msckf_accepted = 0;
  manager.update_leg_velocity_aiding(stats);
  const LegVelocityStatus unavailable_status = manager.get_leg_velocity_status();
  if (unavailable_status.mode != LegVelocityMode::IMU_ONLY || unavailable_status.reason != "leg_measurement_unavailable") {
    std::cerr << "单帧视觉丢失或足式不可用状态失败，reason=" << unavailable_status.reason << std::endl;
    return false;
  }

  // 足式消息位于图像时刻两侧时，应插值到图像时刻；正负速度插值后的创新应接近零。
  VioManagerOptions interpolation_options = make_manager_options(true);
  TestVioManager interpolation_manager(interpolation_options);
  initialize_filter_covariance(interpolation_manager);
  interpolation_manager.set_leg_velocity_extrinsics(Eigen::Matrix3d::Identity(), Eigen::Vector3d::Zero());
  VisualUpdateStats interpolation_stats;
  interpolation_stats.timestamp = 2.0;
  interpolation_stats.active_observations = 100;
  interpolation_stats.msckf_accepted = 5;
  interpolation_manager.update_leg_velocity_aiding(interpolation_stats);
  interpolation_stats.timestamp = 2.05;
  interpolation_stats.msckf_accepted = 0;
  feed_imu_at(interpolation_manager, interpolation_stats.timestamp);
  Eigen::Vector4d velocity_before;
  velocity_before << 0.02, -0.02, 0.0, 0.0;
  feed_leg(interpolation_manager, 2.04, velocity_before);
  feed_leg(interpolation_manager, 2.06, -velocity_before);
  interpolation_manager.update_leg_velocity_aiding(interpolation_stats);
  const LegVelocityStatus interpolation_status = interpolation_manager.get_leg_velocity_status();
  if (interpolation_status.mode != LegVelocityMode::LEG_ASSIST || !interpolation_status.update_accepted ||
      std::abs(interpolation_status.measurement_age) > 1e-9 || interpolation_status.innovation.head<2>().norm() > 1e-9) {
    std::cerr << "足式速度未正确插值到图像时刻，age=" << interpolation_status.measurement_age
              << " innovation=" << interpolation_status.innovation.transpose() << std::endl;
    return false;
  }

  // 构造范围合法但与状态严重冲突的观测，确认卡方拒绝后回退 IMU_ONLY。
  manager.get_state()->_timestamp = 2.20;
  ImuData imu_before;
  imu_before.timestamp = 2.19;
  imu_before.wm.setZero();
  imu_before.am.setZero();
  ImuData imu_after = imu_before;
  imu_after.timestamp = 2.21;
  manager.feed_measurement_imu(imu_before);
  manager.feed_measurement_imu(imu_after);
  LegVelocityData rejected_measurement;
  rejected_measurement.timestamp = 2.20;
  rejected_measurement.measurement << 4.9, 0.0, 0.0, 0.0;
  rejected_measurement.covariance = 0.05 * Eigen::Matrix4d::Identity();
  manager.feed_measurement_leg_velocity(rejected_measurement);
  stats.timestamp = 2.20;
  stats.active_observations = 20;
  stats.msckf_accepted = 0;
  manager.update_leg_velocity_aiding(stats);
  const LegVelocityStatus rejected_status = manager.get_leg_velocity_status();
  if (rejected_status.mode != LegVelocityMode::IMU_ONLY || rejected_status.reason != "chi2_rejected") {
    std::cerr << "卡方拒绝回退失败，reason=" << rejected_status.reason << std::endl;
    return false;
  }
  return true;
}

} // namespace

int main() {
  // 该测试直接返回非零退出码，便于 colcon/CTest 和手工运行统一判定。
  if (!test_rigid_body_model() || !test_finite_difference(StateOptions::ImuModel::KALIBR) ||
      !test_finite_difference(StateOptions::ImuModel::RPNG) || !test_covariance_validation() ||
      !test_visual_state_machine()) {
    return 1;
  }
  std::cout << "足式四维速度模型与雅可比测试通过。" << std::endl;
  return 0;
}
