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

#include "person_3d_localization/bbox_depth_processor.hpp"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <utility>
#include <vector>

#include <sensor_msgs/image_encodings.hpp>

namespace person_3d_localization
{
namespace
{

struct DepthPixel
{
  double u{0.0};
  double v{0.0};
  double depth{0.0};
};

// 判断当前主机是否使用大端字节序。
bool IsHostBigEndian()
{
  const uint16_t value = 0x0102;
  const auto * bytes = reinterpret_cast<const uint8_t *>(&value);
  return bytes[0] == 0x01;
}

// 对 16 位无符号整数执行字节序翻转。
uint16_t ByteSwap16(uint16_t value)
{
  return static_cast<uint16_t>((value >> 8U) | (value << 8U));
}

// 对 32 位无符号整数执行字节序翻转。
uint32_t ByteSwap32(uint32_t value)
{
  return ((value & 0x000000FFU) << 24U) |
         ((value & 0x0000FF00U) << 8U) |
         ((value & 0x00FF0000U) >> 8U) |
         ((value & 0xFF000000U) >> 24U);
}

// 使用 nth_element 计算数值中位数，避免对全部样本完整排序。
double Median(std::vector<double> values)
{
  if (values.empty()) {
    return std::numeric_limits<double>::quiet_NaN();
  }

  const std::size_t middle = values.size() / 2U;
  std::nth_element(values.begin(), values.begin() + middle, values.end());
  const double upper = values[middle];
  if (values.size() % 2U != 0U) {
    return upper;
  }

  const auto lower_it = std::max_element(values.begin(), values.begin() + middle);
  return (*lower_it + upper) * 0.5;
}

}  // namespace

// 保存并校验 bbox 深度提取参数。
BboxDepthProcessor::BboxDepthProcessor(BboxDepthConfig config)
: config_(std::move(config))
{
  if (!(config_.depth_min > 0.0 && config_.depth_max > config_.depth_min) ||
    !(config_.depth_16u_scale > 0.0) ||
    !(config_.bbox_width_scale > 0.0 && config_.bbox_width_scale <= 1.0) ||
    !(config_.bbox_height_scale > 0.0 && config_.bbox_height_scale <= 1.0) ||
    !(config_.mad_scale > 0.0) ||
    !(config_.min_depth_deviation > 0.0) ||
    !(config_.max_depth_deviation >= config_.min_depth_deviation) ||
    !(config_.min_valid_depth_ratio > 0.0 && config_.min_valid_depth_ratio <= 1.0) ||
    config_.min_valid_points <= 0 || config_.sample_stride <= 0)
  {
    throw std::invalid_argument("bbox 深度提取参数不合法");
  }
}

// 在 bbox 中过滤深度离群点，并对剩余像素的三维反投影结果求均值。
BboxDepthResult BboxDepthProcessor::Process(
  const sensor_msgs::msg::Image & depth_image,
  const sensor_msgs::msg::RegionOfInterest & bbox,
  const image_geometry::PinholeCameraModel & camera_model) const
{
  BboxDepthResult result;
  if (!camera_model.initialized()) {
    result.message = "CameraInfo 尚未初始化";
    return result;
  }
  if (depth_image.width == 0U || depth_image.height == 0U || bbox.width == 0U ||
    bbox.height == 0U)
  {
    result.message = "深度图或 bbox 尺寸为空";
    return result;
  }
  if (depth_image.encoding != sensor_msgs::image_encodings::TYPE_16UC1 &&
    depth_image.encoding != sensor_msgs::image_encodings::TYPE_32FC1)
  {
    result.message = "仅支持 16UC1 和 32FC1 深度图";
    return result;
  }

  const uint64_t bbox_right_raw =
    static_cast<uint64_t>(bbox.x_offset) + static_cast<uint64_t>(bbox.width);
  const uint64_t bbox_bottom_raw =
    static_cast<uint64_t>(bbox.y_offset) + static_cast<uint64_t>(bbox.height);
  const std::size_t left = std::min<std::size_t>(bbox.x_offset, depth_image.width);
  const std::size_t top = std::min<std::size_t>(bbox.y_offset, depth_image.height);
  const std::size_t right = std::min<uint64_t>(bbox_right_raw, depth_image.width);
  const std::size_t bottom = std::min<uint64_t>(bbox_bottom_raw, depth_image.height);
  if (left >= right || top >= bottom) {
    result.message = "bbox 位于深度图范围外";
    return result;
  }

  const double center_x = 0.5 * static_cast<double>(left + right);
  const double center_y = 0.5 * static_cast<double>(top + bottom);
  const double crop_width = static_cast<double>(right - left) * config_.bbox_width_scale;
  const double crop_height = static_cast<double>(bottom - top) * config_.bbox_height_scale;
  const std::size_t crop_left = std::max<std::size_t>(
    left, static_cast<std::size_t>(std::floor(center_x - crop_width * 0.5)));
  const std::size_t crop_top = std::max<std::size_t>(
    top, static_cast<std::size_t>(std::floor(center_y - crop_height * 0.5)));
  const std::size_t crop_right = std::min<std::size_t>(
    right, static_cast<std::size_t>(std::ceil(center_x + crop_width * 0.5)));
  const std::size_t crop_bottom = std::min<std::size_t>(
    bottom, static_cast<std::size_t>(std::ceil(center_y + crop_height * 0.5)));

  std::vector<DepthPixel> valid_pixels;
  std::vector<double> valid_depths;
  const std::size_t stride = static_cast<std::size_t>(config_.sample_stride);
  for (std::size_t v = crop_top; v < crop_bottom; v += stride) {
    for (std::size_t u = crop_left; u < crop_right; u += stride) {
      ++result.sampled_points;
      double depth = 0.0;
      if (!DecodeDepthMeters(depth_image, u, v, depth) ||
        !std::isfinite(depth) || depth < config_.depth_min || depth > config_.depth_max)
      {
        continue;
      }
      valid_pixels.push_back({static_cast<double>(u), static_cast<double>(v), depth});
      valid_depths.push_back(depth);
    }
  }

  if (result.sampled_points == 0U) {
    result.message = "bbox 中没有可采样像素";
    return result;
  }
  const double raw_valid_ratio =
    static_cast<double>(valid_pixels.size()) / static_cast<double>(result.sampled_points);
  if (valid_pixels.size() < static_cast<std::size_t>(config_.min_valid_points) ||
    raw_valid_ratio < config_.min_valid_depth_ratio)
  {
    result.valid_depth_ratio = raw_valid_ratio;
    result.message = "bbox 中有效深度点数量或比例不足";
    return result;
  }

  const double median_depth = Median(valid_depths);
  std::vector<double> deviations;
  deviations.reserve(valid_depths.size());
  for (const double depth : valid_depths) {
    deviations.push_back(std::abs(depth - median_depth));
  }
  const double mad = Median(std::move(deviations));
  const double robust_sigma = 1.4826 * mad;
  const double depth_deviation = std::clamp(
    config_.mad_scale * robust_sigma,
    config_.min_depth_deviation,
    config_.max_depth_deviation);

  // 先用深度主簇去掉人体后方背景，再对每个内点反投影，避免“均值深度+中心像素”偏置。
  double sum_x = 0.0;
  double sum_y = 0.0;
  double sum_z = 0.0;
  std::vector<double> inlier_depths;
  inlier_depths.reserve(valid_pixels.size());
  for (const auto & pixel : valid_pixels) {
    if (std::abs(pixel.depth - median_depth) > depth_deviation) {
      continue;
    }
    const cv::Point3d ray = camera_model.projectPixelTo3dRay(cv::Point2d(pixel.u, pixel.v));
    if (!std::isfinite(ray.x) || !std::isfinite(ray.y) || !std::isfinite(ray.z) ||
      std::abs(ray.z) < 1e-9)
    {
      continue;
    }
    const double scale = pixel.depth / ray.z;
    sum_x += ray.x * scale;
    sum_y += ray.y * scale;
    sum_z += pixel.depth;
    inlier_depths.push_back(pixel.depth);
  }

  result.inlier_points = inlier_depths.size();
  result.valid_depth_ratio =
    static_cast<double>(result.inlier_points) / static_cast<double>(result.sampled_points);
  if (result.inlier_points < static_cast<std::size_t>(config_.min_valid_points) ||
    result.valid_depth_ratio < config_.min_valid_depth_ratio)
  {
    result.message = "深度离群点过滤后剩余点不足";
    return result;
  }

  const double point_count = static_cast<double>(result.inlier_points);
  result.point.x = sum_x / point_count;
  result.point.y = sum_y / point_count;
  result.point.z = sum_z / point_count;
  result.mean_depth = result.point.z;

  double squared_error_sum = 0.0;
  for (const double depth : inlier_depths) {
    const double error = depth - result.mean_depth;
    squared_error_sum += error * error;
  }
  result.depth_stddev = std::sqrt(squared_error_sum / point_count);
  result.success = true;
  result.message = "成功";
  return result;
}

// 解码单个深度像素并统一转换为米。
bool BboxDepthProcessor::DecodeDepthMeters(
  const sensor_msgs::msg::Image & image,
  std::size_t x,
  std::size_t y,
  double & depth) const
{
  const bool image_big_endian = image.is_bigendian != 0U;
  if (image.encoding == sensor_msgs::image_encodings::TYPE_16UC1) {
    const std::size_t offset = y * image.step + x * sizeof(uint16_t);
    if (offset + sizeof(uint16_t) > image.data.size()) {
      return false;
    }
    uint16_t raw = 0U;
    std::memcpy(&raw, image.data.data() + offset, sizeof(raw));
    if (image_big_endian != IsHostBigEndian()) {
      raw = ByteSwap16(raw);
    }
    depth = static_cast<double>(raw) * config_.depth_16u_scale;
    return raw != 0U;
  }

  if (image.encoding == sensor_msgs::image_encodings::TYPE_32FC1) {
    const std::size_t offset = y * image.step + x * sizeof(float);
    if (offset + sizeof(float) > image.data.size()) {
      return false;
    }
    uint32_t raw_bits = 0U;
    std::memcpy(&raw_bits, image.data.data() + offset, sizeof(raw_bits));
    if (image_big_endian != IsHostBigEndian()) {
      raw_bits = ByteSwap32(raw_bits);
    }
    float raw = 0.0F;
    std::memcpy(&raw, &raw_bits, sizeof(raw));
    depth = static_cast<double>(raw);
    return std::isfinite(depth) && depth > 0.0;
  }

  return false;
}

}  // namespace person_3d_localization
