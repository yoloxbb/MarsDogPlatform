// Copyright 2026 bird
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#ifndef PERSON_3D_LOCALIZATION__BBOX_DEPTH_PROCESSOR_HPP_
#define PERSON_3D_LOCALIZATION__BBOX_DEPTH_PROCESSOR_HPP_

#include <image_geometry/pinhole_camera_model.h>

#include <cstddef>
#include <string>

#include <geometry_msgs/msg/point.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <sensor_msgs/msg/region_of_interest.hpp>

namespace person_3d_localization
{

struct BboxDepthConfig
{
  double depth_min{0.3};
  double depth_max{6.0};
  double depth_16u_scale{0.001};
  double bbox_width_scale{0.6};
  double bbox_height_scale{0.7};
  double mad_scale{3.0};
  double min_depth_deviation{0.08};
  double max_depth_deviation{0.40};
  double min_valid_depth_ratio{0.20};
  int min_valid_points{30};
  int sample_stride{2};
};

struct BboxDepthResult
{
  bool success{false};
  std::string message;
  geometry_msgs::msg::Point point;
  double valid_depth_ratio{0.0};
  double mean_depth{0.0};
  double depth_stddev{0.0};
  std::size_t sampled_points{0};
  std::size_t inlier_points{0};
};

class BboxDepthProcessor
{
public:
  // 保存并校验 bbox 深度提取参数。
  explicit BboxDepthProcessor(BboxDepthConfig config);

  // 在 bbox 中过滤深度离群点，并对剩余像素的三维反投影结果求均值。
  BboxDepthResult Process(
    const sensor_msgs::msg::Image & depth_image,
    const sensor_msgs::msg::RegionOfInterest & bbox,
    const image_geometry::PinholeCameraModel & camera_model) const;

private:
  // 解码单个深度像素并统一转换为米。
  bool DecodeDepthMeters(
    const sensor_msgs::msg::Image & image,
    std::size_t x,
    std::size_t y,
    double & depth) const;

  BboxDepthConfig config_;
};

}  // namespace person_3d_localization

#endif  // PERSON_3D_LOCALIZATION__BBOX_DEPTH_PROCESSOR_HPP_
