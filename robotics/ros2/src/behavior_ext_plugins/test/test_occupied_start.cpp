// Copyright 2026 MarsDog contributors
// SPDX-License-Identifier: Apache-2.0
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <iostream>
#include <limits>
#include "behavior_ext_plugins/occupied_start.hpp"

int main()
{
  nav2_msgs::msg::Costmap map;
  map.header.frame_id = "map";
  map.header.stamp.sec = 100;
  map.metadata.size_x = 3;
  map.metadata.size_y = 2;
  map.metadata.resolution = 0.5;
  map.metadata.origin.position.x = -1.0;
  map.metadata.origin.position.y = 2.0;
  map.data = {0, 252, 253, 254, 255, 20};
  using behavior_ext_plugins::occupiedStart;
  // Centre-cell costs: free/inflation are rejected; only 253/254 authorize motion.
  assert(!occupiedStart(map, -0.75, 2.25, 101.0, 5.0));
  assert(!occupiedStart(map, -0.25, 2.25, 101.0, 5.0));
  assert(occupiedStart(map, 0.25, 2.25, 101.0, 5.0));
  assert(occupiedStart(map, -0.75, 2.75, 101.0, 5.0));
  assert(!occupiedStart(map, -0.25, 2.75, 101.0, 5.0));
  assert(!occupiedStart(map, 0.25, 2.75, 101.0, 5.0));
  // Map boundaries and metadata origin must be applied before indexing.
  assert(!occupiedStart(map, -1.01, 2.25, 101.0, 5.0));
  assert(!occupiedStart(map, 0.50, 2.25, 101.0, 5.0));
  assert(!occupiedStart(map, -0.75, 3.00, 101.0, 5.0));
  assert(!occupiedStart(map, -0.75, 1.99, 101.0, 5.0));
  // Missing, stale and future data must not be interpreted as occupied.
  assert(!occupiedStart(map, 0.25, 2.25, 106.0, 5.0));
  assert(occupiedStart(map, 0.25, 2.25, 105.0, 5.0));
  assert(!occupiedStart(map, 0.25, 2.25, 99.0, 5.0));
  assert(!occupiedStart(map, 0.25, 2.25, 101.0, 0.0));
  assert(!occupiedStart(map, 0.25, 2.25, 101.0, 5.0, 252));
  assert(!occupiedStart(map, 0.25, 2.25, 101.0, 5.0, 255));
  assert(!occupiedStart(map, 0.25, 2.25, 101.0, 5.0, 254));
  assert(!occupiedStart(map, std::numeric_limits<double>::quiet_NaN(), 2.25, 101.0, 5.0));
  map.header.frame_id.clear();
  assert(!occupiedStart(map, 0.25, 2.25, 101.0, 5.0));
  map.header.frame_id = "map";
  map.header.stamp.sec = 0;
  assert(!occupiedStart(map, 0.25, 2.25, 1.0, 5.0));
  map.header.stamp.sec = 100;
  map.metadata.resolution = 0.0;
  assert(!occupiedStart(map, 0.25, 2.25, 101.0, 5.0));
  map.metadata.resolution = 0.5;
  map.data.pop_back();
  assert(!occupiedStart(map, 0.25, 2.25, 101.0, 5.0));
  std::cout << "22 occupied-start assertions passed\n";
}
