/*
 * OpenVINS: An Open Platform for Visual-Inertial Research
 * Copyright (C) 2018-2023 Patrick Geneva
 * Copyright (C) 2018-2023 Guoquan Huang
 * Copyright (C) 2018-2023 OpenVINS Contributors
 * Copyright (C) 2018-2019 Kevin Eckenhoff
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <https://www.gnu.org/licenses/>.
 */

#include "VioManager.h"

#include "feat/Feature.h"
#include "feat/FeatureDatabase.h"
#include "feat/FeatureInitializer.h"
#include "track/TrackAruco.h"
#include "track/TrackDescriptor.h"
#include "track/TrackKLT.h"
#include "track/TrackSIM.h"
#include "types/Landmark.h"
#include "types/LandmarkRepresentation.h"
#include "utils/opencv_lambda_body.h"
#include "utils/print.h"
#include "utils/sensor_data.h"

#include "init/InertialInitializer.h"

#include "state/Propagator.h"
#include "state/State.h"
#include "state/StateHelper.h"
#include "update/UpdaterMSCKF.h"
#include "update/UpdaterLegVelocity.h"
#include "update/UpdaterSLAM.h"
#include "update/UpdaterZeroVelocity.h"

using namespace ov_core;
using namespace ov_type;
using namespace ov_msckf;

namespace {

/// 将足式辅助枚举转换为稳定的诊断字符串。
const char *leg_velocity_mode_name(LegVelocityMode mode) {
  switch (mode) {
  case LegVelocityMode::DISABLED:
    return "DISABLED";
  case LegVelocityMode::WAITING:
    return "WAITING";
  case LegVelocityMode::VISUAL_ONLY:
    return "VISUAL_ONLY";
  case LegVelocityMode::LEG_ASSIST:
    return "LEG_ASSIST";
  case LegVelocityMode::IMU_ONLY:
    return "IMU_ONLY";
  case LegVelocityMode::RECOVERING:
    return "RECOVERING";
  }
  return "UNKNOWN";
}

} // namespace

VioManager::VioManager(VioManagerOptions &params_) : thread_init_running(false), thread_init_success(false) {

  // Nice startup message
  PRINT_DEBUG("=======================================\n");
  PRINT_DEBUG("OPENVINS ON-MANIFOLD EKF IS STARTING\n");
  PRINT_DEBUG("=======================================\n");

  // Nice debug
  this->params = params_;
  params.print_and_load_estimator();
  params.print_and_load_noise();
  params.print_and_load_state();
  params.print_and_load_trackers();

  // This will globally set the thread count we will use
  // -1 will reset to the system default threading (usually the num of cores)
  cv::setNumThreads(params.num_opencv_threads);
  cv::setRNGSeed(0);

  // Create the state!!
  state = std::make_shared<State>(params.state_options);

  // Set the IMU intrinsics
  state->_calib_imu_dw->set_value(params.vec_dw);
  state->_calib_imu_dw->set_fej(params.vec_dw);
  state->_calib_imu_da->set_value(params.vec_da);
  state->_calib_imu_da->set_fej(params.vec_da);
  state->_calib_imu_tg->set_value(params.vec_tg);
  state->_calib_imu_tg->set_fej(params.vec_tg);
  state->_calib_imu_GYROtoIMU->set_value(params.q_GYROtoIMU);
  state->_calib_imu_GYROtoIMU->set_fej(params.q_GYROtoIMU);
  state->_calib_imu_ACCtoIMU->set_value(params.q_ACCtoIMU);
  state->_calib_imu_ACCtoIMU->set_fej(params.q_ACCtoIMU);

  // Timeoffset from camera to IMU
  Eigen::VectorXd temp_camimu_dt;
  temp_camimu_dt.resize(1);
  temp_camimu_dt(0) = params.calib_camimu_dt;
  state->_calib_dt_CAMtoIMU->set_value(temp_camimu_dt);
  state->_calib_dt_CAMtoIMU->set_fej(temp_camimu_dt);

  // Loop through and load each of the cameras
  state->_cam_intrinsics_cameras = params.camera_intrinsics;
  for (int i = 0; i < state->_options.num_cameras; i++) {
    state->_cam_intrinsics.at(i)->set_value(params.camera_intrinsics.at(i)->get_value());
    state->_cam_intrinsics.at(i)->set_fej(params.camera_intrinsics.at(i)->get_value());
    state->_calib_IMUtoCAM.at(i)->set_value(params.camera_extrinsics.at(i));
    state->_calib_IMUtoCAM.at(i)->set_fej(params.camera_extrinsics.at(i));
  }

  //===================================================================================
  //===================================================================================
  //===================================================================================

  // If we are recording statistics, then open our file
  if (params.record_timing_information) {
    // If the file exists, then delete it
    if (boost::filesystem::exists(params.record_timing_filepath)) {
      boost::filesystem::remove(params.record_timing_filepath);
      PRINT_INFO(YELLOW "[STATS]: found old file found, deleted...\n" RESET);
    }
    // Create the directory that we will open the file in
    boost::filesystem::path p(params.record_timing_filepath);
    boost::filesystem::create_directories(p.parent_path());
    // Open our statistics file!
    of_statistics.open(params.record_timing_filepath, std::ofstream::out | std::ofstream::app);
    // Write the header information into it
    of_statistics << "# timestamp (sec),tracking,propagation,msckf update,";
    if (state->_options.max_slam_features > 0) {
      of_statistics << "slam update,slam delayed,";
    }
    of_statistics << "re-tri & marg,total" << std::endl;
  }

  //===================================================================================
  //===================================================================================
  //===================================================================================

  // Let's make a feature extractor
  // NOTE: after we initialize we will increase the total number of feature tracks
  // NOTE: we will split the total number of features over all cameras uniformly
  int init_max_features = std::floor((double)params.init_options.init_max_features / (double)params.state_options.num_cameras);
  if (params.use_klt) {
    trackFEATS = std::shared_ptr<TrackBase>(new TrackKLT(state->_cam_intrinsics_cameras, init_max_features,
                                                         state->_options.max_aruco_features, params.use_stereo, params.histogram_method,
                                                         params.fast_threshold, params.grid_x, params.grid_y, params.min_px_dist));
  } else {
    trackFEATS = std::shared_ptr<TrackBase>(new TrackDescriptor(
        state->_cam_intrinsics_cameras, init_max_features, state->_options.max_aruco_features, params.use_stereo, params.histogram_method,
        params.fast_threshold, params.grid_x, params.grid_y, params.min_px_dist, params.knn_ratio));
  }

  // Initialize our aruco tag extractor
  if (params.use_aruco) {
    trackARUCO = std::shared_ptr<TrackBase>(new TrackAruco(state->_cam_intrinsics_cameras, state->_options.max_aruco_features,
                                                           params.use_stereo, params.histogram_method, params.downsize_aruco));
  }

  // Initialize our state propagator
  propagator = std::make_shared<Propagator>(params.imu_noises, params.gravity_mag);

  // Our state initialize
  initializer = std::make_shared<ov_init::InertialInitializer>(params.init_options, trackFEATS->get_feature_database());

  // Make the updater!
  updaterMSCKF = std::make_shared<UpdaterMSCKF>(params.msckf_options, params.featinit_options);
  updaterSLAM = std::make_shared<UpdaterSLAM>(params.slam_options, params.aruco_options, params.featinit_options);

  // If we are using zero velocity updates, then create the updater
  if (params.try_zupt) {
    updaterZUPT = std::make_shared<UpdaterZeroVelocity>(params.zupt_options, params.imu_noises, trackFEATS->get_feature_database(),
                                                        propagator, params.gravity_mag, params.zupt_max_velocity,
                                                        params.zupt_noise_multiplier, params.zupt_max_disparity);
  }

  leg_velocity_mode = params.leg_velocity_enabled ? LegVelocityMode::WAITING : LegVelocityMode::DISABLED;
  leg_velocity_status.mode = leg_velocity_mode;
  leg_velocity_status.reason = params.leg_velocity_enabled ? "waiting_for_vio" : "disabled";
  if (params.leg_velocity_enabled) {
    updaterLegVelocity = std::make_shared<UpdaterLegVelocity>(
        params.leg_velocity_use_vertical, params.leg_velocity_use_yaw_rate, params.leg_velocity_horizontal_variance_floor,
        params.leg_velocity_vertical_variance_floor, params.leg_velocity_yaw_rate_variance_floor, params.leg_velocity_chi2_multiplier);
  }
}

void VioManager::feed_measurement_imu(const ov_core::ImuData &message) {

  // The oldest time we need IMU with is the last clone
  // We shouldn't really need the whole window, but if we go backwards in time we will
  double oldest_time = state->margtimestep();
  if (oldest_time > state->_timestamp) {
    oldest_time = -1;
  }
  if (!is_initialized_vio) {
    oldest_time = message.timestamp - params.init_options.init_window_time + state->_calib_dt_CAMtoIMU->value()(0) - 0.10;
  }
  propagator->feed_imu(message, oldest_time);

  // Push back to our initializer
  if (!is_initialized_vio) {
    initializer->feed_imu(message, oldest_time);
  }

  // Push back to the zero velocity updater if it is enabled
  // No need to push back if we are just doing the zv-update at the begining and we have moved
  if (is_initialized_vio && updaterZUPT != nullptr && (!params.zupt_only_at_beginning || !has_moved_since_zupt)) {
    updaterZUPT->feed_imu(message, oldest_time);
  }
}

void VioManager::feed_measurement_leg_velocity(const ov_core::LegVelocityData &message) {
  if (!params.leg_velocity_enabled) {
    return;
  }
  std::lock_guard<std::mutex> lock(leg_velocity_mutex);
  leg_velocity_queue.push_back(message);
  std::sort(leg_velocity_queue.begin(), leg_velocity_queue.end());
  while (leg_velocity_queue.size() > 200) {
    leg_velocity_queue.pop_front();
  }
}

void VioManager::set_leg_velocity_extrinsics(const Eigen::Matrix3d &R_BI, const Eigen::Vector3d &r_IB_in_I) {
  std::lock_guard<std::mutex> lock(leg_velocity_mutex);
  leg_R_BI = R_BI;
  leg_r_IB_in_I = r_IB_in_I;
  leg_extrinsics_valid = R_BI.allFinite() && r_IB_in_I.allFinite() && std::abs(R_BI.determinant() - 1.0) < 1e-3 &&
                         (R_BI.transpose() * R_BI).isApprox(Eigen::Matrix3d::Identity(), 1e-6);
  leg_velocity_status.lever_arm = r_IB_in_I;
  if (!leg_extrinsics_valid) {
    leg_extrinsics_reason = "invalid_extrinsics";
    leg_velocity_status.reason = leg_extrinsics_reason;
  } else {
    leg_extrinsics_reason.clear();
    PRINT_INFO("[OV-LEG] R_BI=[%.6f %.6f %.6f; %.6f %.6f %.6f; %.6f %.6f %.6f] r_IB_I=[%.4f %.4f %.4f]\n",
               R_BI(0, 0), R_BI(0, 1), R_BI(0, 2), R_BI(1, 0), R_BI(1, 1), R_BI(1, 2), R_BI(2, 0), R_BI(2, 1),
               R_BI(2, 2), r_IB_in_I(0), r_IB_in_I(1), r_IB_in_I(2));
  }
}

void VioManager::disable_leg_velocity_extrinsics(const std::string &reason) {
  // 外参一旦在运行中失效就不自动恢复，避免使用跳变后的 TF 污染滤波状态。
  std::lock_guard<std::mutex> lock(leg_velocity_mutex);
  leg_extrinsics_valid = false;
  leg_extrinsics_reason = reason.empty() ? "invalid_extrinsics" : reason;
  leg_velocity_status.reason = leg_extrinsics_reason;
  PRINT_WARNING(YELLOW "[OV-LEG] disabling leg velocity aiding: %s\n" RESET, reason.c_str());
}

LegVelocityStatus VioManager::get_leg_velocity_status() const {
  std::lock_guard<std::mutex> lock(leg_velocity_mutex);
  return leg_velocity_status;
}

void VioManager::update_leg_velocity_aiding(const VisualUpdateStats &visual_stats) {
  if (!params.leg_velocity_enabled || updaterLegVelocity == nullptr) {
    return;
  }

  std::string mode_reason;
  const auto change_mode = [&](LegVelocityMode new_mode, const std::string &reason) {
    if (leg_velocity_mode != new_mode) {
      PRINT_INFO("[OV-LEG] t=%.6f mode=%s->%s active=%zu accepted=%zu reason=%s\n", visual_stats.timestamp,
                 leg_velocity_mode_name(leg_velocity_mode), leg_velocity_mode_name(new_mode), visual_stats.active_observations,
                 visual_stats.accepted_total(), reason.c_str());
    }
    leg_velocity_mode = new_mode;
    mode_reason = reason;
  };

  const size_t accepted = visual_stats.accepted_total();
  const auto reset_visual_recovery = [&]() {
    visual_recovery_start_time = -1.0;
    visual_recovery_accepted = 0;
  };
  const size_t minimum_active = static_cast<size_t>(std::max(0, params.leg_velocity_min_active_observations));
  const size_t minimum_accepted = static_cast<size_t>(std::max(0, params.leg_velocity_recovery_accepted));
  const bool recovery_sample_stable = accepted > 0 && visual_stats.active_observations >= minimum_active;
  const auto extend_visual_recovery = [&]() {
    if (!recovery_sample_stable) {
      reset_visual_recovery();
      return false;
    }
    if (visual_recovery_start_time < 0.0 || visual_stats.timestamp < visual_recovery_start_time) {
      visual_recovery_start_time = visual_stats.timestamp;
      visual_recovery_accepted = accepted;
    } else {
      visual_recovery_accepted += accepted;
    }
    const double recovery_duration = visual_stats.timestamp - visual_recovery_start_time;
    return recovery_duration >= std::max(0.0, params.leg_velocity_recovery_time) &&
           visual_recovery_accepted >= minimum_accepted;
  };

  // 非对称迟滞：视觉首次没有实际 EKF 更新时立即启用足式；进入足式辅助后，
  // 即使视觉重新出现也继续联合约束，直到连续恢复时间、活动观测数和累计接受数全部达标。
  switch (leg_velocity_mode) {
  case LegVelocityMode::WAITING:
    reset_visual_recovery();
    change_mode(accepted > 0 ? LegVelocityMode::VISUAL_ONLY : LegVelocityMode::IMU_ONLY,
                accepted > 0 ? "vio_initialized_with_visual" : "visual_update_missing");
    break;
  case LegVelocityMode::VISUAL_ONLY:
    if (accepted == 0) {
      reset_visual_recovery();
      change_mode(LegVelocityMode::IMU_ONLY, "visual_update_missing");
    }
    break;
  case LegVelocityMode::LEG_ASSIST:
  case LegVelocityMode::IMU_ONLY:
    if (accepted > 0) {
      change_mode(LegVelocityMode::RECOVERING, "visual_recovery_started");
      if (extend_visual_recovery()) {
        reset_visual_recovery();
        change_mode(LegVelocityMode::VISUAL_ONLY, "visual_recovery_stable");
      }
    } else {
      reset_visual_recovery();
    }
    break;
  case LegVelocityMode::RECOVERING:
    if (accepted == 0) {
      reset_visual_recovery();
      change_mode(LegVelocityMode::IMU_ONLY, "visual_recovery_interrupted");
    } else if (extend_visual_recovery()) {
      reset_visual_recovery();
      change_mode(LegVelocityMode::VISUAL_ONLY, "visual_recovery_stable");
    }
    break;
  case LegVelocityMode::DISABLED:
    return;
  }

  const bool should_use_leg = leg_velocity_mode == LegVelocityMode::LEG_ASSIST ||
                              leg_velocity_mode == LegVelocityMode::IMU_ONLY ||
                              leg_velocity_mode == LegVelocityMode::RECOVERING;

  {
    std::lock_guard<std::mutex> lock(leg_velocity_mutex);
    leg_velocity_status.mode = leg_velocity_mode;
    leg_velocity_status.timestamp = visual_stats.timestamp;
    leg_velocity_status.measurement_age = -1.0;
    leg_velocity_status.active_observations = visual_stats.active_observations;
    leg_velocity_status.visual_accepted = accepted;
    leg_velocity_status.msckf_candidates = visual_stats.msckf_candidates;
    leg_velocity_status.msckf_selected = visual_stats.msckf_selected;
    leg_velocity_status.msckf_accepted = visual_stats.msckf_accepted;
    leg_velocity_status.slam_update_candidates = visual_stats.slam_update_candidates;
    leg_velocity_status.slam_update_accepted = visual_stats.slam_update_accepted;
    leg_velocity_status.slam_init_candidates = visual_stats.slam_init_candidates;
    leg_velocity_status.slam_init_accepted = visual_stats.slam_init_accepted;
    leg_velocity_status.update_accepted = false;
    leg_velocity_status.chi2 = -1.0;
    leg_velocity_status.chi2_threshold = -1.0;
    leg_velocity_status.innovation.setConstant(std::numeric_limits<double>::quiet_NaN());
    if (should_use_leg) {
      leg_velocity_status.reason = leg_velocity_mode == LegVelocityMode::RECOVERING ? "visual_recovery_pending"
                                                                                    : "leg_measurement_pending";
    } else {
      leg_velocity_status.reason = mode_reason.empty() ? "visual_update_accepted" : mode_reason;
    }
  }

  if (!should_use_leg) {
    return;
  }

  ov_core::LegVelocityData selected;
  bool has_measurement = false;
  double consumed_through_timestamp = -1.0;
  bool extrinsics_valid = false;
  std::string extrinsics_reason;
  Eigen::Matrix3d R_BI;
  Eigen::Vector3d r_IB_in_I;
  {
    std::lock_guard<std::mutex> lock(leg_velocity_mutex);
    extrinsics_valid = leg_extrinsics_valid;
    extrinsics_reason = leg_extrinsics_reason;
    R_BI = leg_R_BI;
    r_IB_in_I = leg_r_IB_in_I;
    while (!leg_velocity_queue.empty() &&
           leg_velocity_queue.front().timestamp + params.leg_velocity_time_offset < visual_stats.timestamp - params.leg_velocity_max_age) {
      leg_velocity_queue.pop_front();
    }
    auto before = leg_velocity_queue.end();
    auto after = leg_velocity_queue.end();
    for (auto candidate = leg_velocity_queue.begin(); candidate != leg_velocity_queue.end(); ++candidate) {
      const double effective_time = candidate->timestamp + params.leg_velocity_time_offset;
      if (effective_time <= visual_stats.timestamp && candidate->timestamp > last_consumed_leg_timestamp) {
        before = candidate;
      } else if (effective_time > visual_stats.timestamp) {
        after = candidate;
        break;
      }
    }

    if (before != leg_velocity_queue.end()) {
      selected = *before;
      consumed_through_timestamp = before->timestamp;
      has_measurement = true;

      // 图像处理有传输延迟时，队列通常已经包含图像时刻之后的足式消息。
      // 用前后两条观测线性插值，使送入 EKF 的速度对应当前图像的时间戳。
      if (after != leg_velocity_queue.end() &&
          after->timestamp + params.leg_velocity_time_offset - visual_stats.timestamp <= params.leg_velocity_max_age) {
        const double before_time = before->timestamp + params.leg_velocity_time_offset;
        const double after_time = after->timestamp + params.leg_velocity_time_offset;
        const double interval = after_time - before_time;
        if (interval > 1e-9) {
          const double alpha = (visual_stats.timestamp - before_time) / interval;
          selected.timestamp = visual_stats.timestamp - params.leg_velocity_time_offset;
          selected.measurement = (1.0 - alpha) * before->measurement + alpha * after->measurement;
          // 使用凸组合保持协方差半正定，同时避免把高频相邻消息误当成独立观测而过度收紧方差。
          selected.covariance = (1.0 - alpha) * before->covariance + alpha * after->covariance;
        }
      }

      last_consumed_leg_timestamp = consumed_through_timestamp;
      while (!leg_velocity_queue.empty() && leg_velocity_queue.front().timestamp <= consumed_through_timestamp) {
        leg_velocity_queue.pop_front();
      }
      leg_velocity_status.measurement_age = visual_stats.timestamp - (selected.timestamp + params.leg_velocity_time_offset);
    }
  }

  if (!extrinsics_valid || !has_measurement) {
    reset_visual_recovery();
    if (leg_velocity_mode != LegVelocityMode::IMU_ONLY) {
      change_mode(LegVelocityMode::IMU_ONLY, extrinsics_valid ? "leg_measurement_unavailable" : extrinsics_reason);
    }
    std::lock_guard<std::mutex> lock(leg_velocity_mutex);
    leg_velocity_status.mode = leg_velocity_mode;
    leg_velocity_status.reason = extrinsics_valid ? "leg_measurement_unavailable" : extrinsics_reason;
    return;
  }

  const Eigen::Vector3d linear_velocity = selected.measurement.head<3>();
  const double selected_linear_speed = params.leg_velocity_use_vertical ? linear_velocity.norm() : linear_velocity.head<2>().norm();
  if (!selected.measurement.allFinite() || selected_linear_speed > params.leg_velocity_max_linear_speed ||
      (params.leg_velocity_use_vertical && std::abs(selected.measurement(2)) > params.leg_velocity_max_vertical_speed) ||
      (params.leg_velocity_use_yaw_rate && std::abs(selected.measurement(3)) > params.leg_velocity_max_yaw_rate)) {
    reset_visual_recovery();
    if (leg_velocity_mode != LegVelocityMode::IMU_ONLY) {
      change_mode(LegVelocityMode::IMU_ONLY, "leg_measurement_out_of_range");
    }
    std::lock_guard<std::mutex> lock(leg_velocity_mutex);
    leg_velocity_status.mode = leg_velocity_mode;
    leg_velocity_status.reason = "leg_measurement_out_of_range";
    return;
  }

  ov_core::ImuData interpolated_imu;
  const double imu_timestamp = visual_stats.timestamp + state->_calib_dt_CAMtoIMU->value()(0);
  if (!propagator->get_interpolated_imu(imu_timestamp, interpolated_imu)) {
    reset_visual_recovery();
    if (leg_velocity_mode != LegVelocityMode::IMU_ONLY) {
      change_mode(LegVelocityMode::IMU_ONLY, "imu_interpolation_unavailable");
    }
    std::lock_guard<std::mutex> lock(leg_velocity_mutex);
    leg_velocity_status.mode = leg_velocity_mode;
    leg_velocity_status.reason = "imu_interpolation_unavailable";
    return;
  }

  const LegVelocityUpdateResult update_result = updaterLegVelocity->update(state, selected, interpolated_imu, R_BI, r_IB_in_I);
  if (update_result.accepted) {
    propagator->invalidate_cache();
    if (leg_velocity_mode == LegVelocityMode::IMU_ONLY) {
      change_mode(LegVelocityMode::LEG_ASSIST, "leg_update_accepted");
    }
  } else {
    reset_visual_recovery();
    if (leg_velocity_mode != LegVelocityMode::IMU_ONLY) {
      change_mode(LegVelocityMode::IMU_ONLY, update_result.reason);
    }
  }
  {
    std::lock_guard<std::mutex> lock(leg_velocity_mutex);
    leg_velocity_status.mode = leg_velocity_mode;
    leg_velocity_status.update_accepted = update_result.accepted;
    leg_velocity_status.chi2 = update_result.chi2;
    leg_velocity_status.chi2_threshold = update_result.chi2_threshold;
    leg_velocity_status.innovation = update_result.innovation;
    leg_velocity_status.reason = update_result.reason;
  }
  PRINT_INFO(
      "[OV-LEG] t=%.6f mode=%s active=%zu visual_accepted=%zu age=%.3f accepted=%d "
      "innovation=[%.4f %.4f %.4f %.4f] chi2=%.3f/%.3f lever=[%.4f %.4f %.4f] reason=%s\n",
      visual_stats.timestamp, leg_velocity_mode_name(leg_velocity_mode), visual_stats.active_observations,
      visual_stats.accepted_total(), visual_stats.timestamp - selected.timestamp - params.leg_velocity_time_offset,
      update_result.accepted, update_result.innovation(0), update_result.innovation(1), update_result.innovation(2),
      update_result.innovation(3), update_result.chi2, update_result.chi2_threshold, r_IB_in_I(0), r_IB_in_I(1),
      r_IB_in_I(2), update_result.reason.c_str());
}

void VioManager::feed_measurement_simulation(double timestamp, const std::vector<int> &camids,
                                             const std::vector<std::vector<std::pair<size_t, Eigen::VectorXf>>> &feats) {

  // Start timing
  rT1 = boost::posix_time::microsec_clock::local_time();

  // Check if we actually have a simulated tracker
  // If not, recreate and re-cast the tracker to our simulation tracker
  std::shared_ptr<TrackSIM> trackSIM = std::dynamic_pointer_cast<TrackSIM>(trackFEATS);
  if (trackSIM == nullptr) {
    // Replace with the simulated tracker
    trackSIM = std::make_shared<TrackSIM>(state->_cam_intrinsics_cameras, state->_options.max_aruco_features);
    trackFEATS = trackSIM;
    // Need to also replace it in init and zv-upt since it points to the trackFEATS db pointer
    initializer = std::make_shared<ov_init::InertialInitializer>(params.init_options, trackFEATS->get_feature_database());
    if (params.try_zupt) {
      updaterZUPT = std::make_shared<UpdaterZeroVelocity>(params.zupt_options, params.imu_noises, trackFEATS->get_feature_database(),
                                                          propagator, params.gravity_mag, params.zupt_max_velocity,
                                                          params.zupt_noise_multiplier, params.zupt_max_disparity);
    }
    PRINT_WARNING(RED "[SIM]: casting our tracker to a TrackSIM object!\n" RESET);
  }

  // Feed our simulation tracker
  trackSIM->feed_measurement_simulation(timestamp, camids, feats);
  rT2 = boost::posix_time::microsec_clock::local_time();

  // Check if we should do zero-velocity, if so update the state with it
  // Note that in the case that we only use in the beginning initialization phase
  // If we have since moved, then we should never try to do a zero velocity update!
  if (is_initialized_vio && updaterZUPT != nullptr && (!params.zupt_only_at_beginning || !has_moved_since_zupt)) {
    // If the same state time, use the previous timestep decision
    if (state->_timestamp != timestamp) {
      did_zupt_update = updaterZUPT->try_update(state, timestamp);
    }
    if (did_zupt_update) {
      assert(state->_timestamp == timestamp);
      propagator->clean_old_imu_measurements(timestamp + state->_calib_dt_CAMtoIMU->value()(0) - 0.10);
      updaterZUPT->clean_old_imu_measurements(timestamp + state->_calib_dt_CAMtoIMU->value()(0) - 0.10);
      propagator->invalidate_cache();
      return;
    }
  }

  // If we do not have VIO initialization, then return an error
  if (!is_initialized_vio) {
    PRINT_ERROR(RED "[SIM]: your vio system should already be initialized before simulating features!!!\n" RESET);
    PRINT_ERROR(RED "[SIM]: initialize your system first before calling feed_measurement_simulation()!!!!\n" RESET);
    std::exit(EXIT_FAILURE);
  }

  // Call on our propagate and update function
  // Simulation is either all sync, or single camera...
  ov_core::CameraData message;
  message.timestamp = timestamp;
  for (auto const &camid : camids) {
    int width = state->_cam_intrinsics_cameras.at(camid)->w();
    int height = state->_cam_intrinsics_cameras.at(camid)->h();
    message.sensor_ids.push_back(camid);
    message.images.push_back(cv::Mat::zeros(cv::Size(width, height), CV_8UC1));
    message.masks.push_back(cv::Mat::zeros(cv::Size(width, height), CV_8UC1));
  }
  do_feature_propagate_update(message);
}

void VioManager::track_image_and_update(const ov_core::CameraData &message_const) {

  // Start timing
  rT1 = boost::posix_time::microsec_clock::local_time();

  // Assert we have valid measurement data and ids
  assert(!message_const.sensor_ids.empty());
  assert(message_const.sensor_ids.size() == message_const.images.size());
  for (size_t i = 0; i < message_const.sensor_ids.size() - 1; i++) {
    assert(message_const.sensor_ids.at(i) != message_const.sensor_ids.at(i + 1));
  }

  // Downsample if we are downsampling
  ov_core::CameraData message = message_const;
  for (size_t i = 0; i < message.sensor_ids.size() && params.downsample_cameras; i++) {
    cv::Mat img = message.images.at(i);
    cv::Mat mask = message.masks.at(i);
    cv::Mat img_temp, mask_temp;
    cv::pyrDown(img, img_temp, cv::Size(img.cols / 2.0, img.rows / 2.0));
    message.images.at(i) = img_temp;
    cv::pyrDown(mask, mask_temp, cv::Size(mask.cols / 2.0, mask.rows / 2.0));
    message.masks.at(i) = mask_temp;
  }

  // Perform our feature tracking!
  trackFEATS->feed_new_camera(message);

  // If the aruco tracker is available, the also pass to it
  // NOTE: binocular tracking for aruco doesn't make sense as we by default have the ids
  // NOTE: thus we just call the stereo tracking if we are doing binocular!
  if (is_initialized_vio && trackARUCO != nullptr) {
    trackARUCO->feed_new_camera(message);
  }
  rT2 = boost::posix_time::microsec_clock::local_time();

  // Check if we should do zero-velocity, if so update the state with it
  // Note that in the case that we only use in the beginning initialization phase
  // If we have since moved, then we should never try to do a zero velocity update!
  if (is_initialized_vio && updaterZUPT != nullptr && (!params.zupt_only_at_beginning || !has_moved_since_zupt)) {
    // If the same state time, use the previous timestep decision
    if (state->_timestamp != message.timestamp) {
      did_zupt_update = updaterZUPT->try_update(state, message.timestamp);
    }
    if (did_zupt_update) {
      assert(state->_timestamp == message.timestamp);
      propagator->clean_old_imu_measurements(message.timestamp + state->_calib_dt_CAMtoIMU->value()(0) - 0.10);
      updaterZUPT->clean_old_imu_measurements(message.timestamp + state->_calib_dt_CAMtoIMU->value()(0) - 0.10);
      propagator->invalidate_cache();
      return;
    }
  }

  // If we do not have VIO initialization, then try to initialize
  // TODO: Or if we are trying to reset the system, then do that here!
  if (!is_initialized_vio) {
    is_initialized_vio = try_to_initialize(message);
    if (!is_initialized_vio) {
      double time_track = (rT2 - rT1).total_microseconds() * 1e-6;
      PRINT_DEBUG(BLUE "[TIME]: %.4f seconds for tracking\n" RESET, time_track);
      return;
    }
  }

  // Call on our propagate and update function
  do_feature_propagate_update(message);
}

void VioManager::do_feature_propagate_update(const ov_core::CameraData &message) {

  //===================================================================================
  // State propagation, and clone augmentation
  //===================================================================================

  // Return if the camera measurement is out of order
  if (state->_timestamp > message.timestamp) {
    PRINT_WARNING(YELLOW "image received out of order, unable to do anything (prop dt = %3f)\n" RESET,
                  (message.timestamp - state->_timestamp));
    return;
  }

  // Propagate the state forward to the current update time
  // Also augment it with a new clone!
  // NOTE: if the state is already at the given time (can happen in sim)
  // NOTE: then no need to prop since we already are at the desired timestep
  if (state->_timestamp != message.timestamp) {
    propagator->propagate_and_clone(state, message.timestamp);
  }
  rT3 = boost::posix_time::microsec_clock::local_time();

  // If we have not reached max clones, we should just return...
  // This isn't super ideal, but it keeps the logic after this easier...
  // We can start processing things when we have at least 5 clones since we can start triangulating things...
  if ((int)state->_clones_IMU.size() < std::min(state->_options.max_clone_size, 5)) {
    PRINT_DEBUG("waiting for enough clone states (%d of %d)....\n", (int)state->_clones_IMU.size(),
                std::min(state->_options.max_clone_size, 5));
    return;
  }

  // Return if we where unable to propagate
  if (state->_timestamp != message.timestamp) {
    PRINT_WARNING(RED "[PROP]: Propagator unable to propagate the state forward in time!\n" RESET);
    PRINT_WARNING(RED "[PROP]: It has been %.3f since last time we propagated\n" RESET, message.timestamp - state->_timestamp);
    return;
  }
  has_moved_since_zupt = true;

  //===================================================================================
  // MSCKF features and KLT tracks that are SLAM features
  //===================================================================================

  // Now, lets get all features that should be used for an update that are lost in the newest frame
  // We explicitly request features that have not been deleted (used) in another update step
  std::vector<std::shared_ptr<Feature>> feats_lost, feats_marg, feats_slam;
  feats_lost = trackFEATS->get_feature_database()->features_not_containing_newer(state->_timestamp, false, true);

  // Don't need to get the oldest features until we reach our max number of clones
  if ((int)state->_clones_IMU.size() > state->_options.max_clone_size || (int)state->_clones_IMU.size() > 5) {
    feats_marg = trackFEATS->get_feature_database()->features_containing(state->margtimestep(), false, true);
    if (trackARUCO != nullptr && message.timestamp - startup_time >= params.dt_slam_delay) {
      feats_slam = trackARUCO->get_feature_database()->features_containing(state->margtimestep(), false, true);
    }
  }

  // Remove any lost features that were from other image streams
  // E.g: if we are cam1 and cam0 has not processed yet, we don't want to try to use those in the update yet
  // E.g: thus we wait until cam0 process its newest image to remove features which were seen from that camera
  auto it1 = feats_lost.begin();
  while (it1 != feats_lost.end()) {
    bool found_current_message_camid = false;
    for (const auto &camuvpair : (*it1)->uvs) {
      if (std::find(message.sensor_ids.begin(), message.sensor_ids.end(), camuvpair.first) != message.sensor_ids.end()) {
        found_current_message_camid = true;
        break;
      }
    }
    if (found_current_message_camid) {
      it1++;
    } else {
      it1 = feats_lost.erase(it1);
    }
  }

  // We also need to make sure that the max tracks does not contain any lost features
  // This could happen if the feature was lost in the last frame, but has a measurement at the marg timestep
  it1 = feats_lost.begin();
  while (it1 != feats_lost.end()) {
    if (std::find(feats_marg.begin(), feats_marg.end(), (*it1)) != feats_marg.end()) {
      // PRINT_WARNING(YELLOW "FOUND FEATURE THAT WAS IN BOTH feats_lost and feats_marg!!!!!!\n" RESET);
      it1 = feats_lost.erase(it1);
    } else {
      it1++;
    }
  }

  // Find tracks that have reached max length, these can be made into SLAM features
  std::vector<std::shared_ptr<Feature>> feats_maxtracks;
  auto it2 = feats_marg.begin();
  while (it2 != feats_marg.end()) {
    // See if any of our camera's reached max track
    bool reached_max = false;
    for (const auto &cams : (*it2)->timestamps) {
      if ((int)cams.second.size() > state->_options.max_clone_size) {
        reached_max = true;
        break;
      }
    }
    // If max track, then add it to our possible slam feature list
    if (reached_max) {
      feats_maxtracks.push_back(*it2);
      it2 = feats_marg.erase(it2);
    } else {
      it2++;
    }
  }

  // Count how many aruco tags we have in our state
  int curr_aruco_tags = 0;
  auto it0 = state->_features_SLAM.begin();
  while (it0 != state->_features_SLAM.end()) {
    if ((int)(*it0).second->_featid <= 4 * state->_options.max_aruco_features)
      curr_aruco_tags++;
    it0++;
  }

  // Append a new SLAM feature if we have the room to do so
  // Also check that we have waited our delay amount (normally prevents bad first set of slam points)
  if (state->_options.max_slam_features > 0 && message.timestamp - startup_time >= params.dt_slam_delay &&
      (int)state->_features_SLAM.size() < state->_options.max_slam_features + curr_aruco_tags) {
    // Get the total amount to add, then the max amount that we can add given our marginalize feature array
    int amount_to_add = (state->_options.max_slam_features + curr_aruco_tags) - (int)state->_features_SLAM.size();
    int valid_amount = (amount_to_add > (int)feats_maxtracks.size()) ? (int)feats_maxtracks.size() : amount_to_add;
    // If we have at least 1 that we can add, lets add it!
    // Note: we remove them from the feat_marg array since we don't want to reuse information...
    if (valid_amount > 0) {
      feats_slam.insert(feats_slam.end(), feats_maxtracks.end() - valid_amount, feats_maxtracks.end());
      feats_maxtracks.erase(feats_maxtracks.end() - valid_amount, feats_maxtracks.end());
    }
  }

  // Loop through current SLAM features, we have tracks of them, grab them for this update!
  // NOTE: if we have a slam feature that has lost tracking, then we should marginalize it out
  // NOTE: we only enforce this if the current camera message is where the feature was seen from
  // NOTE: if you do not use FEJ, these types of slam features *degrade* the estimator performance....
  // NOTE: we will also marginalize SLAM features if they have failed their update a couple times in a row
  for (std::pair<const size_t, std::shared_ptr<Landmark>> &landmark : state->_features_SLAM) {
    if (trackARUCO != nullptr) {
      std::shared_ptr<Feature> feat1 = trackARUCO->get_feature_database()->get_feature(landmark.second->_featid);
      if (feat1 != nullptr)
        feats_slam.push_back(feat1);
    }
    std::shared_ptr<Feature> feat2 = trackFEATS->get_feature_database()->get_feature(landmark.second->_featid);
    if (feat2 != nullptr)
      feats_slam.push_back(feat2);
    assert(landmark.second->_unique_camera_id != -1);
    bool current_unique_cam =
        std::find(message.sensor_ids.begin(), message.sensor_ids.end(), landmark.second->_unique_camera_id) != message.sensor_ids.end();
    if (feat2 == nullptr && current_unique_cam)
      landmark.second->should_marg = true;
    if (landmark.second->update_fail_count > 1)
      landmark.second->should_marg = true;
  }

  // Lets marginalize out all old SLAM features here
  // These are ones that where not successfully tracked into the current frame
  // We do *NOT* marginalize out our aruco tags landmarks
  StateHelper::marginalize_slam(state);

  // Separate our SLAM features into new ones, and old ones
  std::vector<std::shared_ptr<Feature>> feats_slam_DELAYED, feats_slam_UPDATE;
  for (size_t i = 0; i < feats_slam.size(); i++) {
    if (state->_features_SLAM.find(feats_slam.at(i)->featid) != state->_features_SLAM.end()) {
      feats_slam_UPDATE.push_back(feats_slam.at(i));
      // PRINT_DEBUG("[UPDATE-SLAM]: found old feature %d (%d
      // measurements)\n",(int)feats_slam.at(i)->featid,(int)feats_slam.at(i)->timestamps_left.size());
    } else {
      feats_slam_DELAYED.push_back(feats_slam.at(i));
      // PRINT_DEBUG("[UPDATE-SLAM]: new feature ready %d (%d
      // measurements)\n",(int)feats_slam.at(i)->featid,(int)feats_slam.at(i)->timestamps_left.size());
    }
  }

  // Concatenate our MSCKF feature arrays (i.e., ones not being used for slam updates)
  std::vector<std::shared_ptr<Feature>> featsup_MSCKF = feats_lost;
  featsup_MSCKF.insert(featsup_MSCKF.end(), feats_marg.begin(), feats_marg.end());
  featsup_MSCKF.insert(featsup_MSCKF.end(), feats_maxtracks.begin(), feats_maxtracks.end());

  //===================================================================================
  // Now that we have a list of features, lets do the EKF update for MSCKF and SLAM!
  //===================================================================================

  // Sort based on track length
  // TODO: we should have better selection logic here (i.e. even feature distribution in the FOV etc..)
  // TODO: right now features that are "lost" are at the front of this vector, while ones at the end are long-tracks
  auto compare_feat = [](const std::shared_ptr<Feature> &a, const std::shared_ptr<Feature> &b) -> bool {
    size_t asize = 0;
    size_t bsize = 0;
    for (const auto &pair : a->timestamps)
      asize += pair.second.size();
    for (const auto &pair : b->timestamps)
      bsize += pair.second.size();
    return asize < bsize;
  };
  std::sort(featsup_MSCKF.begin(), featsup_MSCKF.end(), compare_feat);

  // Pass them to our MSCKF updater
  // NOTE: if we have more then the max, we select the "best" ones (i.e. max tracks) for this update
  // NOTE: this should only really be used if you want to track a lot of features, or have limited computational resources
  const size_t msckf_candidates = featsup_MSCKF.size();
  if ((int)featsup_MSCKF.size() > state->_options.max_msckf_in_update)
    featsup_MSCKF.erase(featsup_MSCKF.begin(), featsup_MSCKF.end() - state->_options.max_msckf_in_update);
  const size_t msckf_selected = featsup_MSCKF.size();
  updaterMSCKF->update(state, featsup_MSCKF);
  // Updater 会原地移除清理、三角化或卡方检验失败的特征，剩余数量即实际参与更新的数量。
  const size_t msckf_accepted = featsup_MSCKF.size();
  propagator->invalidate_cache();
  rT4 = boost::posix_time::microsec_clock::local_time();

  // Perform SLAM delay init and update
  // NOTE: that we provide the option here to do a *sequential* update
  // NOTE: this will be a lot faster but won't be as accurate.
  const size_t slam_update_candidates = feats_slam_UPDATE.size();
  const size_t slam_init_candidates = feats_slam_DELAYED.size();
  std::vector<std::shared_ptr<Feature>> feats_slam_UPDATE_TEMP;
  while (!feats_slam_UPDATE.empty()) {
    // Get sub vector of the features we will update with
    std::vector<std::shared_ptr<Feature>> featsup_TEMP;
    featsup_TEMP.insert(featsup_TEMP.begin(), feats_slam_UPDATE.begin(),
                        feats_slam_UPDATE.begin() + std::min(state->_options.max_slam_in_update, (int)feats_slam_UPDATE.size()));
    feats_slam_UPDATE.erase(feats_slam_UPDATE.begin(),
                            feats_slam_UPDATE.begin() + std::min(state->_options.max_slam_in_update, (int)feats_slam_UPDATE.size()));
    // Do the update
    updaterSLAM->update(state, featsup_TEMP);
    feats_slam_UPDATE_TEMP.insert(feats_slam_UPDATE_TEMP.end(), featsup_TEMP.begin(), featsup_TEMP.end());
    propagator->invalidate_cache();
  }
  feats_slam_UPDATE = feats_slam_UPDATE_TEMP;
  const size_t slam_update_accepted = feats_slam_UPDATE.size();
  rT5 = boost::posix_time::microsec_clock::local_time();
  updaterSLAM->delayed_init(state, feats_slam_DELAYED);
  const size_t slam_init_accepted = feats_slam_DELAYED.size();
  rT6 = boost::posix_time::microsec_clock::local_time();

  // 只使用本帧真正进入 EKF 的视觉约束判断是否切换足式辅助，避免“仍有跟踪线但没有约束”的假健康状态。
  VisualUpdateStats visual_stats;
  visual_stats.timestamp = message.timestamp;
  visual_stats.msckf_candidates = msckf_candidates;
  visual_stats.msckf_selected = msckf_selected;
  visual_stats.msckf_accepted = msckf_accepted;
  visual_stats.slam_update_candidates = slam_update_candidates;
  visual_stats.slam_init_candidates = slam_init_candidates;
  visual_stats.slam_update_accepted = slam_update_accepted;
  visual_stats.slam_init_accepted = slam_init_accepted;
  const auto active_tracks_for_stats = trackFEATS->get_last_obs();
  for (const auto &camera_tracks : active_tracks_for_stats) {
    visual_stats.active_observations += camera_tracks.second.size();
  }
  update_leg_velocity_aiding(visual_stats);

  //===================================================================================
  // Update our visualization feature set, and clean up the old features
  //===================================================================================

  // Re-triangulate all current tracks in the current frame
  if (message.sensor_ids.at(0) == 0) {

    // Re-triangulate features
    retriangulate_active_tracks(message);

    // Clear the MSCKF features only on the base camera
    // Thus we should be able to visualize the other unique camera stream
    // MSCKF features as they will also be appended to the vector
    good_features_MSCKF.clear();
  }

  // Save all the MSCKF features used in the update
  for (auto const &feat : featsup_MSCKF) {
    good_features_MSCKF.push_back(feat->p_FinG);
    feat->to_delete = true;
  }

  //===================================================================================
  // Cleanup, marginalize out what we don't need any more...
  //===================================================================================

  // Remove features that where used for the update from our extractors at the last timestep
  // This allows for measurements to be used in the future if they failed to be used this time
  // Note we need to do this before we feed a new image, as we want all new measurements to NOT be deleted
  trackFEATS->get_feature_database()->cleanup();
  if (trackARUCO != nullptr) {
    trackARUCO->get_feature_database()->cleanup();
  }

  // First do anchor change if we are about to lose an anchor pose
  updaterSLAM->change_anchors(state);

  // Cleanup any features older than the marginalization time
  if ((int)state->_clones_IMU.size() > state->_options.max_clone_size) {
    trackFEATS->get_feature_database()->cleanup_measurements(state->margtimestep());
    if (trackARUCO != nullptr) {
      trackARUCO->get_feature_database()->cleanup_measurements(state->margtimestep());
    }
  }

  // Finally marginalize the oldest clone if needed
  StateHelper::marginalize_old_clone(state);
  rT7 = boost::posix_time::microsec_clock::local_time();

  //===================================================================================
  // Debug info, and stats tracking
  //===================================================================================

  // Get timing statitics information
  double time_track = (rT2 - rT1).total_microseconds() * 1e-6;
  double time_prop = (rT3 - rT2).total_microseconds() * 1e-6;
  double time_msckf = (rT4 - rT3).total_microseconds() * 1e-6;
  double time_slam_update = (rT5 - rT4).total_microseconds() * 1e-6;
  double time_slam_delay = (rT6 - rT5).total_microseconds() * 1e-6;
  double time_marg = (rT7 - rT6).total_microseconds() * 1e-6;
  double time_total = (rT7 - rT1).total_microseconds() * 1e-6;

  // Timing information
  PRINT_DEBUG(BLUE "[TIME]: %.4f seconds for tracking\n" RESET, time_track);
  PRINT_DEBUG(BLUE "[TIME]: %.4f seconds for propagation\n" RESET, time_prop);
  PRINT_DEBUG(BLUE "[TIME]: %.4f seconds for MSCKF update (%d feats)\n" RESET, time_msckf, (int)featsup_MSCKF.size());
  if (state->_options.max_slam_features > 0) {
    PRINT_DEBUG(BLUE "[TIME]: %.4f seconds for SLAM update (%d feats)\n" RESET, time_slam_update, (int)state->_features_SLAM.size());
    PRINT_DEBUG(BLUE "[TIME]: %.4f seconds for SLAM delayed init (%d feats)\n" RESET, time_slam_delay, (int)feats_slam_DELAYED.size());
  }
  PRINT_DEBUG(BLUE "[TIME]: %.4f seconds for re-tri & marg (%d clones in state)\n" RESET, time_marg, (int)state->_clones_IMU.size());

  std::stringstream ss;
  ss << "[TIME]: " << std::setprecision(4) << time_total << " seconds for total (camera";
  for (const auto &id : message.sensor_ids) {
    ss << " " << id;
  }
  ss << ")" << std::endl;
  PRINT_DEBUG(BLUE "%s" RESET, ss.str().c_str());

  // 汇总视觉观测漏斗；一行对应一个相机时间戳，便于和 IMU 冲击及轨迹漂移对齐。
  PRINT_INFO(
      "[OV-VIO] t=%.6f active_obs=%zu msckf_candidates=%zu msckf_selected=%zu msckf_accepted=%zu "
      "slam_update=%zu/%zu slam_init=%zu/%zu slam_state=%zu clones=%zu\n",
      message.timestamp, visual_stats.active_observations, msckf_candidates, msckf_selected, msckf_accepted, slam_update_accepted,
      slam_update_candidates, slam_init_accepted, slam_init_candidates, state->_features_SLAM.size(), state->_clones_IMU.size());

  // Finally if we are saving stats to file, lets save it to file
  if (params.record_timing_information && of_statistics.is_open()) {
    // We want to publish in the IMU clock frame
    // The timestamp in the state will be the last camera time
    double t_ItoC = state->_calib_dt_CAMtoIMU->value()(0);
    double timestamp_inI = state->_timestamp + t_ItoC;
    // Append to the file
    of_statistics << std::fixed << std::setprecision(15) << timestamp_inI << "," << std::fixed << std::setprecision(5) << time_track << ","
                  << time_prop << "," << time_msckf << ",";
    if (state->_options.max_slam_features > 0) {
      of_statistics << time_slam_update << "," << time_slam_delay << ",";
    }
    of_statistics << time_marg << "," << time_total << std::endl;
    of_statistics.flush();
  }

  // Update our distance traveled
  if (timelastupdate != -1 && state->_clones_IMU.find(timelastupdate) != state->_clones_IMU.end()) {
    Eigen::Matrix<double, 3, 1> dx = state->_imu->pos() - state->_clones_IMU.at(timelastupdate)->pos();
    distance += dx.norm();
  }
  timelastupdate = message.timestamp;

  // 单行记录核心状态，避免原有多行输出难以按时间戳关联。
  PRINT_INFO(
      "[OV-STATE] t=%.6f q=%.5f,%.5f,%.5f,%.5f p=%.5f,%.5f,%.5f v=%.5f,%.5f,%.5f "
      "bg=%.6f,%.6f,%.6f ba=%.6f,%.6f,%.6f camimu_dt=%.6f dist=%.3f\n",
      message.timestamp, state->_imu->quat()(0), state->_imu->quat()(1), state->_imu->quat()(2), state->_imu->quat()(3),
      state->_imu->pos()(0), state->_imu->pos()(1), state->_imu->pos()(2), state->_imu->vel()(0), state->_imu->vel()(1),
      state->_imu->vel()(2), state->_imu->bias_g()(0), state->_imu->bias_g()(1), state->_imu->bias_g()(2), state->_imu->bias_a()(0),
      state->_imu->bias_a()(1), state->_imu->bias_a()(2), state->_calib_dt_CAMtoIMU->value()(0), distance);

  // Debug for camera intrinsics
  if (state->_options.do_calib_camera_intrinsics) {
    for (int i = 0; i < state->_options.num_cameras; i++) {
      std::shared_ptr<Vec> calib = state->_cam_intrinsics.at(i);
      PRINT_INFO("cam%d intrinsics = %.3f,%.3f,%.3f,%.3f | %.3f,%.3f,%.3f,%.3f\n", (int)i, calib->value()(0), calib->value()(1),
                 calib->value()(2), calib->value()(3), calib->value()(4), calib->value()(5), calib->value()(6), calib->value()(7));
    }
  }

  // Debug for camera extrinsics
  if (state->_options.do_calib_camera_pose) {
    for (int i = 0; i < state->_options.num_cameras; i++) {
      std::shared_ptr<PoseJPL> calib = state->_calib_IMUtoCAM.at(i);
      PRINT_INFO("cam%d extrinsics = %.3f,%.3f,%.3f,%.3f | %.3f,%.3f,%.3f\n", (int)i, calib->quat()(0), calib->quat()(1), calib->quat()(2),
                 calib->quat()(3), calib->pos()(0), calib->pos()(1), calib->pos()(2));
    }
  }

  // Debug for imu intrinsics
  if (state->_options.do_calib_imu_intrinsics && state->_options.imu_model == StateOptions::ImuModel::KALIBR) {
    PRINT_INFO("q_GYROtoI = %.3f,%.3f,%.3f,%.3f\n", state->_calib_imu_GYROtoIMU->value()(0), state->_calib_imu_GYROtoIMU->value()(1),
               state->_calib_imu_GYROtoIMU->value()(2), state->_calib_imu_GYROtoIMU->value()(3));
  }
  if (state->_options.do_calib_imu_intrinsics && state->_options.imu_model == StateOptions::ImuModel::RPNG) {
    PRINT_INFO("q_ACCtoI = %.3f,%.3f,%.3f,%.3f\n", state->_calib_imu_ACCtoIMU->value()(0), state->_calib_imu_ACCtoIMU->value()(1),
               state->_calib_imu_ACCtoIMU->value()(2), state->_calib_imu_ACCtoIMU->value()(3));
  }
  if (state->_options.do_calib_imu_intrinsics && state->_options.imu_model == StateOptions::ImuModel::KALIBR) {
    PRINT_INFO("Dw = | %.4f,%.4f,%.4f | %.4f,%.4f | %.4f |\n", state->_calib_imu_dw->value()(0), state->_calib_imu_dw->value()(1),
               state->_calib_imu_dw->value()(2), state->_calib_imu_dw->value()(3), state->_calib_imu_dw->value()(4),
               state->_calib_imu_dw->value()(5));
    PRINT_INFO("Da = | %.4f,%.4f,%.4f | %.4f,%.4f | %.4f |\n", state->_calib_imu_da->value()(0), state->_calib_imu_da->value()(1),
               state->_calib_imu_da->value()(2), state->_calib_imu_da->value()(3), state->_calib_imu_da->value()(4),
               state->_calib_imu_da->value()(5));
  }
  if (state->_options.do_calib_imu_intrinsics && state->_options.imu_model == StateOptions::ImuModel::RPNG) {
    PRINT_INFO("Dw = | %.4f | %.4f,%.4f | %.4f,%.4f,%.4f |\n", state->_calib_imu_dw->value()(0), state->_calib_imu_dw->value()(1),
               state->_calib_imu_dw->value()(2), state->_calib_imu_dw->value()(3), state->_calib_imu_dw->value()(4),
               state->_calib_imu_dw->value()(5));
    PRINT_INFO("Da = | %.4f | %.4f,%.4f | %.4f,%.4f,%.4f |\n", state->_calib_imu_da->value()(0), state->_calib_imu_da->value()(1),
               state->_calib_imu_da->value()(2), state->_calib_imu_da->value()(3), state->_calib_imu_da->value()(4),
               state->_calib_imu_da->value()(5));
  }
  if (state->_options.do_calib_imu_intrinsics && state->_options.do_calib_imu_g_sensitivity) {
    PRINT_INFO("Tg = | %.4f,%.4f,%.4f |  %.4f,%.4f,%.4f | %.4f,%.4f,%.4f |\n", state->_calib_imu_tg->value()(0),
               state->_calib_imu_tg->value()(1), state->_calib_imu_tg->value()(2), state->_calib_imu_tg->value()(3),
               state->_calib_imu_tg->value()(4), state->_calib_imu_tg->value()(5), state->_calib_imu_tg->value()(6),
               state->_calib_imu_tg->value()(7), state->_calib_imu_tg->value()(8));
  }
}
