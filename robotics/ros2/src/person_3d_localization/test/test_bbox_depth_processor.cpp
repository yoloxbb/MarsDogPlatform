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

#include <gtest/gtest.h>

#include <cstdint>
#include <cstring>
#include <vector>

#include <sensor_msgs/image_encodings.hpp>

#include "person_3d_localization/bbox_depth_processor.hpp"

namespace person_3d_localization
{
namespace
{

// 创建用于反投影测试的针孔 CameraInfo。
image_geometry::PinholeCameraModel MakeCameraModel(uint32_t width, uint32_t height)
{
  sensor_msgs::msg::CameraInfo info;
  info.width = width;
  info.height = height;
  info.k = {100.0, 0.0, 5.0, 0.0, 100.0, 5.0, 0.0, 0.0, 1.0};
  info.r = {1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0};
  info.p = {100.0, 0.0, 5.0, 0.0, 0.0, 100.0, 5.0, 0.0, 0.0, 0.0, 1.0, 0.0};
  image_geometry::PinholeCameraModel model;
  model.fromCameraInfo(info);
  return model;
}

// 按毫米值创建小端 16UC1 深度图。
sensor_msgs::msg::Image MakeDepthImage(
  uint32_t width,
  uint32_t height,
  const std::vector<uint16_t> & depth_mm)
{
  sensor_msgs::msg::Image image;
  image.width = width;
  image.height = height;
  image.encoding = sensor_msgs::image_encodings::TYPE_16UC1;
  image.is_bigendian = false;
  image.step = width * sizeof(uint16_t);
  image.data.resize(depth_mm.size() * sizeof(uint16_t));
  std::memcpy(image.data.data(), depth_mm.data(), image.data.size());
  return image;
}

// 创建覆盖整幅测试图像的 bbox。
sensor_msgs::msg::RegionOfInterest MakeFullBbox(uint32_t width, uint32_t height)
{
  sensor_msgs::msg::RegionOfInterest bbox;
  bbox.width = width;
  bbox.height = height;
  return bbox;
}

TEST(BboxDepthProcessorTest, ComputesMeanPointFromUniformDepth)
{
  BboxDepthConfig config;
  config.bbox_width_scale = 1.0;
  config.bbox_height_scale = 1.0;
  config.sample_stride = 1;
  config.min_valid_points = 10;
  const BboxDepthProcessor processor(config);
  const auto image = MakeDepthImage(10, 10, std::vector<uint16_t>(100, 2000U));

  const auto result = processor.Process(image, MakeFullBbox(10, 10), MakeCameraModel(10, 10));

  ASSERT_TRUE(result.success) << result.message;
  EXPECT_NEAR(result.point.x, -0.01, 1e-6);
  EXPECT_NEAR(result.point.y, -0.01, 1e-6);
  EXPECT_NEAR(result.point.z, 2.0, 1e-6);
  EXPECT_NEAR(result.valid_depth_ratio, 1.0, 1e-6);
}

TEST(BboxDepthProcessorTest, RejectsBackgroundDepthOutliers)
{
  BboxDepthConfig config;
  config.bbox_width_scale = 1.0;
  config.bbox_height_scale = 1.0;
  config.sample_stride = 1;
  config.min_valid_points = 10;
  const BboxDepthProcessor processor(config);
  std::vector<uint16_t> depths(100, 2000U);
  for (std::size_t index = 0; index < 20U; ++index) {
    depths[index] = 5000U;
  }
  const auto image = MakeDepthImage(10, 10, depths);

  const auto result = processor.Process(image, MakeFullBbox(10, 10), MakeCameraModel(10, 10));

  ASSERT_TRUE(result.success) << result.message;
  EXPECT_NEAR(result.mean_depth, 2.0, 1e-6);
  EXPECT_EQ(result.inlier_points, 80U);
}

TEST(BboxDepthProcessorTest, FailsWhenValidDepthRatioIsTooLow)
{
  BboxDepthConfig config;
  config.bbox_width_scale = 1.0;
  config.bbox_height_scale = 1.0;
  config.sample_stride = 1;
  config.min_valid_points = 10;
  config.min_valid_depth_ratio = 0.5;
  const BboxDepthProcessor processor(config);
  std::vector<uint16_t> depths(100, 0U);
  for (std::size_t index = 0; index < 20U; ++index) {
    depths[index] = 2000U;
  }
  const auto image = MakeDepthImage(10, 10, depths);

  const auto result = processor.Process(image, MakeFullBbox(10, 10), MakeCameraModel(10, 10));

  EXPECT_FALSE(result.success);
  EXPECT_NEAR(result.valid_depth_ratio, 0.2, 1e-6);
}

}  // namespace
}  // namespace person_3d_localization
