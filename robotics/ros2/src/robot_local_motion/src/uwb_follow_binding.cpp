// Thin ABI adapter to the existing public UWB control core; no control algorithm here.
#include <cmath>
#include <new>
#include "go2_uwb_local_follow/follow_control_core.hpp"

namespace core = go2_uwb_local_follow;
namespace
{
struct Session
{
  core::FollowConfig config;
  int direction{0};
  bool braking{false};
};
}

extern "C" void * marsdog_uwb_follow_create(const double * values, int count)
{
  if (values == nullptr || count != 19) {return nullptr;}
  auto * session = new (std::nothrow) Session;
  if (session == nullptr) {return nullptr;}
  auto & c = session->config;
  c.follow_distance = values[0]; c.distance_deadband = values[1];
  c.angle_deadband = values[2]; c.angle_reengage = values[3];
  c.turn_response_delay = values[4]; c.angular_braking_accel = values[5];
  c.angular_brake_release_speed = values[6]; c.angular_reverse_speed_threshold = values[7];
  c.linear_kp = values[8]; c.angular_kp = values[9];
  c.min_linear_speed = values[10]; c.max_linear_speed = values[11];
  c.max_angular_speed = values[12]; c.heading_slowdown_start = values[13];
  c.heading_stop_angle = values[14]; c.blind_rotation_max_speed = values[15];
  c.max_linear_accel = values[16]; c.max_linear_decel = values[17];
  c.max_angular_accel = values[18];
  if (!core::validateFollowConfig(c)) {delete session; return nullptr;}
  return session;
}

extern "C" void marsdog_uwb_follow_destroy(void * handle)
{
  delete static_cast<Session *>(handle);
}

extern "C" void marsdog_uwb_follow_reset(void * handle)
{
  if (handle != nullptr) {
    auto * session = static_cast<Session *>(handle);
    session->direction = 0; session->braking = false;
  }
}

extern "C" int marsdog_uwb_follow_step(
  void * handle, double x, double y, double actual_w, double * output, int count)
{
  if (handle == nullptr || output == nullptr || count != 5 ||
    !std::isfinite(x) || !std::isfinite(y) || !std::isfinite(actual_w)) {return 0;}
  auto & session = *static_cast<Session *>(handle);
  const auto target = core::computeFollowTarget(x, y, session.config);
  const auto brake = core::applyDynamicAngularBrake(
    target.heading, target.target_velocity.angular_z, actual_w,
    session.config, session.direction, session.braking);
  session.direction = brake.turn_direction; session.braking = brake.brake_latched;
  output[0] = target.target_velocity.linear_x;
  output[1] = brake.angular_z;
  output[2] = target.distance;
  output[3] = target.heading;
  output[4] = brake.dynamic_stop_angle;
  return 1;
}
