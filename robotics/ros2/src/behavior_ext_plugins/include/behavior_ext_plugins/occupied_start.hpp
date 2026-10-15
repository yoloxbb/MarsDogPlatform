// Copyright 2026 MarsDog contributors
// SPDX-License-Identifier: Apache-2.0
#ifndef BEHAVIOR_EXT_PLUGINS__OCCUPIED_START_HPP_
#define BEHAVIOR_EXT_PLUGINS__OCCUPIED_START_HPP_

#include <cmath>
#include <cstddef>
#include "nav2_msgs/msg/costmap.hpp"

namespace behavior_ext_plugins
{

// Unknown, missing, malformed and stale maps do not authorize recovery motion.
inline bool occupiedStart(
  const nav2_msgs::msg::Costmap & map, double x, double y,
  double now_seconds, double max_age_seconds, int occupied_cost = 253)
{
  const auto & metadata = map.metadata;
  const double stamp = map.header.stamp.sec + map.header.stamp.nanosec * 1e-9;
  const double age = now_seconds - stamp;
  if (map.header.frame_id.empty() || stamp <= 0.0 ||
    !std::isfinite(age) || !std::isfinite(max_age_seconds) ||
    max_age_seconds <= 0.0 || age < 0.0 || age > max_age_seconds ||
    occupied_cost < 253 || occupied_cost > 254 ||
    !std::isfinite(x) || !std::isfinite(y) ||
    !std::isfinite(metadata.resolution) || metadata.resolution <= 0.0 ||
    metadata.size_x == 0 || metadata.size_y == 0 ||
    map.data.size() != static_cast<std::size_t>(metadata.size_x) * metadata.size_y)
  {
    return false;
  }

  const double mx = std::floor((x - metadata.origin.position.x) / metadata.resolution);
  const double my = std::floor((y - metadata.origin.position.y) / metadata.resolution);
  if (!std::isfinite(mx) || !std::isfinite(my) || mx < 0.0 || my < 0.0 ||
    mx >= metadata.size_x || my >= metadata.size_y)
  {
    return false;
  }
  const auto index = static_cast<std::size_t>(my) * metadata.size_x +
    static_cast<std::size_t>(mx);
  const int cost = map.data[index];
  return cost >= occupied_cost && cost < 255;
}

}  // namespace behavior_ext_plugins
#endif  // BEHAVIOR_EXT_PLUGINS__OCCUPIED_START_HPP_
