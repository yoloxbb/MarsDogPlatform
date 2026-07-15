#include <fcntl.h>
#include <poll.h>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <termios.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

class WitImuNode : public rclcpp::Node
{
public:
  WitImuNode()
  : Node("wit_imu_node")
  {
    port_ = declare_parameter<std::string>("port", "/dev/ttyUSB0");
    baud_ = declare_parameter<int>("baud", 115200);
    frame_id_ = declare_parameter<std::string>("frame_id", "imu_link");
    topic_ = declare_parameter<std::string>("topic", "imu/data_raw");
    expected_rate_hz_ = declare_parameter<double>("expected_rate_hz", 200.0);
    qos_depth_ = declare_parameter<int>("qos_depth", 5);
    poll_timeout_ms_ = declare_parameter<int>("poll_timeout_ms", 500);
    serial_data_timeout_ms_ = declare_parameter<int>("serial_data_timeout_ms", 2000);
    reconnect_delay_ms_ = declare_parameter<int>("reconnect_delay_ms", 1000);
    timestamp_resync_threshold_ms_ =
      declare_parameter<double>("timestamp_resync_threshold_ms", 20.0);
    angular_velocity_covariance_ =
      declare_parameter<double>("angular_velocity_covariance", 0.0);
    linear_acceleration_covariance_ =
      declare_parameter<double>("linear_acceleration_covariance", 0.0);

    ExecuteValidateParameters();
    sample_period_ns_ = static_cast<int64_t>(
      std::llround(1000000000.0 / expected_rate_hz_));
    timestamp_resync_threshold_ns_ = static_cast<int64_t>(
      std::llround(timestamp_resync_threshold_ms_ * 1000000.0));

    const auto qos = rclcpp::SensorDataQoS().keep_last(qos_depth_);
    publisher_ = create_publisher<sensor_msgs::msg::Imu>(topic_, qos);

    running_.store(true);
    read_thread_ = std::thread(&WitImuNode::ExecuteReadLoop, this);
  }

  ~WitImuNode() override
  {
    running_.store(false);
    if (read_thread_.joinable()) {
      read_thread_.join();
    }
    ExecuteCloseSerial();
  }

private:
  static constexpr double kGravity = 9.80665;
  static constexpr double kDegreesToRadians = M_PI / 180.0;
  static constexpr std::size_t kFrameSize = 11;

  struct ImuSample
  {
    std::array<double, 3> acceleration{};
    std::array<double, 3> angular_velocity{};
    uint32_t missing_samples_before{0};
  };

  void ExecuteValidateParameters()
  {
    // 提前拒绝无效参数，避免采集线程反复失败重连。
    if (port_.empty() || frame_id_.empty() || topic_.empty()) {
      throw std::invalid_argument("port, frame_id and topic must not be empty");
    }
    if (expected_rate_hz_ <= 0.0 || qos_depth_ <= 0 || poll_timeout_ms_ <= 0 ||
      serial_data_timeout_ms_ < poll_timeout_ms_ || reconnect_delay_ms_ <= 0)
    {
      throw std::invalid_argument(
              "rate and queue depth must be positive; serial timeout must cover poll timeout");
    }
    if (angular_velocity_covariance_ < 0.0 || linear_acceleration_covariance_ < 0.0) {
      throw std::invalid_argument("covariance values must not be negative");
    }
    if (!std::isfinite(timestamp_resync_threshold_ms_) ||
      timestamp_resync_threshold_ms_ <= 0.0 || timestamp_resync_threshold_ms_ > 1000.0)
    {
      throw std::invalid_argument(
              "timestamp_resync_threshold_ms must be finite and within (0, 1000]");
    }
  }

  speed_t GetBaudRateValue(int baud) const
  {
    // 只接受系统termios明确支持的波特率。
    switch (baud) {
      case 9600:
        return B9600;
      case 19200:
        return B19200;
      case 38400:
        return B38400;
      case 57600:
        return B57600;
      case 115200:
        return B115200;
#ifdef B230400
      case 230400:
        return B230400;
#endif
#ifdef B460800
      case 460800:
        return B460800;
#endif
      default:
        throw std::invalid_argument("unsupported baud rate: " + std::to_string(baud));
    }
  }

  bool ExecuteOpenSerial()
  {
    ExecuteCloseSerial();
    fd_ = open(port_.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC);
    if (fd_ < 0) {
      RCLCPP_WARN(get_logger(), "Cannot open %s: %s", port_.c_str(), std::strerror(errno));
      return false;
    }

    termios options{};
    if (tcgetattr(fd_, &options) < 0) {
      RCLCPP_ERROR(get_logger(), "tcgetattr failed: %s", std::strerror(errno));
      ExecuteCloseSerial();
      return false;
    }

    cfmakeraw(&options);
    const speed_t speed = GetBaudRateValue(baud_);
    cfsetispeed(&options, speed);
    cfsetospeed(&options, speed);
    options.c_cflag &= ~(PARENB | CSTOPB | CSIZE | CRTSCTS);
    options.c_cflag |= CS8 | CLOCAL | CREAD;
    options.c_cc[VMIN] = 0;
    options.c_cc[VTIME] = 0;
    if (tcsetattr(fd_, TCSANOW, &options) < 0) {
      RCLCPP_ERROR(get_logger(), "tcsetattr failed: %s", std::strerror(errno));
      ExecuteCloseSerial();
      return false;
    }
    tcflush(fd_, TCIFLUSH);

    receive_buffer_.clear();
    receive_offset_ = 0;
    has_acceleration_ = false;
    current_cycle_missing_counted_ = false;
    pending_missing_samples_ = 0;
    timestamp_valid_ = false;
    report_start_ = std::chrono::steady_clock::now();
    samples_since_report_ = 0;
    checksum_errors_since_report_ = 0;
    discarded_bytes_since_report_ = 0;
    incomplete_pairs_since_report_ = 0;
    missing_samples_since_report_ = 0;
    timestamp_resyncs_since_report_ = 0;
    RCLCPP_INFO(
      get_logger(), "Opened %s @ %d baud, publishing %s at %.1f Hz",
      port_.c_str(), baud_, topic_.c_str(), expected_rate_hz_);
    return true;
  }

  void ExecuteCloseSerial()
  {
    if (fd_ >= 0) {
      close(fd_);
      fd_ = -1;
    }
  }

  static int16_t GetSigned16Value(uint8_t low, uint8_t high)
  {
    const uint16_t raw = static_cast<uint16_t>(low) |
      (static_cast<uint16_t>(high) << 8U);
    return static_cast<int16_t>(raw);
  }

  static bool IsFrameChecksumValid(const uint8_t * frame)
  {
    uint8_t checksum = 0;
    for (std::size_t index = 0; index < kFrameSize - 1; ++index) {
      checksum = static_cast<uint8_t>(checksum + frame[index]);
    }
    return checksum == frame[kFrameSize - 1];
  }

  void ExecuteHandleInvalidFrame(const uint8_t * frame)
  {
    // 已对齐但校验失败时记录当前采样缺口，让下一条消息立即体现丢帧间隔。
    if (frame[1] == 0x51) {
      if (has_acceleration_) {
        ++pending_missing_samples_;
        ++missing_samples_since_report_;
        ++incomplete_pairs_since_report_;
      }
      has_acceleration_ = false;
      ++pending_missing_samples_;
      ++missing_samples_since_report_;
      current_cycle_missing_counted_ = true;
    } else if (frame[1] == 0x52) {
      if (has_acceleration_ || !current_cycle_missing_counted_) {
        ++pending_missing_samples_;
        ++missing_samples_since_report_;
        ++incomplete_pairs_since_report_;
      }
      has_acceleration_ = false;
      current_cycle_missing_counted_ = true;
    }
  }

  void ExecuteHandleFrame(const uint8_t * frame, std::vector<ImuSample> & samples)
  {
    const int16_t x = GetSigned16Value(frame[2], frame[3]);
    const int16_t y = GetSigned16Value(frame[4], frame[5]);
    const int16_t z = GetSigned16Value(frame[6], frame[7]);

    if (frame[1] == 0x51) {
      // WIT加速度量程为±16g，统一转换为m/s²。
      if (has_acceleration_) {
        ++pending_missing_samples_;
        ++missing_samples_since_report_;
        ++incomplete_pairs_since_report_;
      }
      constexpr double scale = 16.0 / 32768.0 * kGravity;
      latest_acceleration_ = {x * scale, y * scale, z * scale};
      has_acceleration_ = true;
      current_cycle_missing_counted_ = false;
      return;
    }

    if (frame[1] == 0x52) {
      // WIT角速度量程为±4000°/s，统一转换为rad/s。
      constexpr double scale = 4000.0 / 32768.0 * kDegreesToRadians;
      if (!has_acceleration_) {
        if (!current_cycle_missing_counted_) {
          ++pending_missing_samples_;
          ++missing_samples_since_report_;
          ++incomplete_pairs_since_report_;
        }
        current_cycle_missing_counted_ = true;
        return;
      }
      ImuSample sample;
      sample.acceleration = latest_acceleration_;
      sample.angular_velocity = {x * scale, y * scale, z * scale};
      sample.missing_samples_before = pending_missing_samples_;
      pending_missing_samples_ = 0;
      samples.push_back(sample);
      has_acceleration_ = false;
      current_cycle_missing_counted_ = false;
    }
    // 0x53是设备融合角度，data_raw模式下有意忽略。
  }

  void ExecuteParseBuffer(std::vector<ImuSample> & samples)
  {
    // 滑动查找帧头；校验失败只移动一字节，避免破坏下一帧。
    while (receive_buffer_.size() - receive_offset_ >= kFrameSize) {
      const uint8_t * frame = receive_buffer_.data() + receive_offset_;
      if (frame[0] != 0x55) {
        ++receive_offset_;
        ++discarded_bytes_since_report_;
        continue;
      }
      if (!IsFrameChecksumValid(frame)) {
        ++checksum_errors_since_report_;
        if (frame[1] >= 0x50 && frame[1] <= 0x59) {
          ExecuteHandleInvalidFrame(frame);
          receive_offset_ += kFrameSize;
        } else {
          ++receive_offset_;
        }
        continue;
      }
      ExecuteHandleFrame(frame, samples);
      receive_offset_ += kFrameSize;
    }

    if (receive_offset_ > 0 &&
      (receive_offset_ >= 4096 || receive_offset_ * 2 >= receive_buffer_.size()))
    {
      receive_buffer_.erase(
        receive_buffer_.begin(), receive_buffer_.begin() +
        static_cast<std::ptrdiff_t>(receive_offset_));
      receive_offset_ = 0;
    }
  }

  std::vector<int64_t> GetSampleTimestampsValue(const std::vector<ImuSample> & samples)
  {
    const std::size_t sample_count = samples.size();
    std::vector<int64_t> timestamps(sample_count);
    if (sample_count == 0) {
      return timestamps;
    }

    // 一次read可能包含多组数据；最后一组靠近读取时刻，其余样本按设备周期向前展开。
    const int64_t now_ns = get_clock()->now().nanoseconds();
    const auto anchor_to_now = [&]() {
      int64_t span_ns = 0;
      for (std::size_t index = 1; index < sample_count; ++index) {
        span_ns += static_cast<int64_t>(1 + samples[index].missing_samples_before) *
          sample_period_ns_;
      }
      timestamps[0] = now_ns - span_ns;
      for (std::size_t index = 1; index < sample_count; ++index) {
        timestamps[index] = timestamps[index - 1] +
          static_cast<int64_t>(1 + samples[index].missing_samples_before) * sample_period_ns_;
      }
      if (timestamp_valid_ && timestamps.front() <= last_timestamp_ns_) {
        // 极端调度抖动下仍保证时间戳严格单调。
        const int64_t shift_ns = last_timestamp_ns_ + 1 - timestamps.front();
        for (auto & timestamp : timestamps) {
          timestamp += shift_ns;
        }
      }
    };

    if (!timestamp_valid_) {
      anchor_to_now();
    } else {
      int64_t predicted_last_ns = last_timestamp_ns_;
      for (const auto & sample : samples) {
        predicted_last_ns += static_cast<int64_t>(1 + sample.missing_samples_before) *
          sample_period_ns_;
      }
      const int64_t phase_error_ns = now_ns - predicted_last_ns;
      if (std::abs(phase_error_ns) > timestamp_resync_threshold_ns_) {
        // CPU短时抢占后快速回到当前时钟，避免OpenVINS因IMU时间落后而持续丢图。
        anchor_to_now();
        ++timestamp_resyncs_since_report_;
      } else {
        const int64_t correction_divisor =
          std::max<int64_t>(20 * static_cast<int64_t>(sample_count), 1);
        const int64_t correction_ns = std::clamp<int64_t>(
          phase_error_ns / correction_divisor, -250000LL, 250000LL);
        int64_t timestamp_ns = last_timestamp_ns_;
        for (std::size_t index = 0; index < sample_count; ++index) {
          timestamp_ns += static_cast<int64_t>(1 + samples[index].missing_samples_before) *
            sample_period_ns_ + correction_ns;
          timestamps[index] = timestamp_ns;
        }
      }
    }
    last_timestamp_ns_ = timestamps.back();
    timestamp_valid_ = true;
    return timestamps;
  }

  void ExecutePublishSamples(const std::vector<ImuSample> & samples)
  {
    const auto timestamps = GetSampleTimestampsValue(samples);
    for (std::size_t index = 0; index < samples.size(); ++index) {
      sensor_msgs::msg::Imu message;
      message.header.stamp = static_cast<builtin_interfaces::msg::Time>(
        rclcpp::Time(timestamps[index], get_clock()->get_clock_type()));
      message.header.frame_id = frame_id_;

      // 原始IMU没有可靠姿态，按sensor_msgs约定将orientation标记为不可用。
      message.orientation.w = 1.0;
      message.orientation_covariance[0] = -1.0;
      message.angular_velocity.x = samples[index].angular_velocity[0];
      message.angular_velocity.y = samples[index].angular_velocity[1];
      message.angular_velocity.z = samples[index].angular_velocity[2];
      message.linear_acceleration.x = samples[index].acceleration[0];
      message.linear_acceleration.y = samples[index].acceleration[1];
      message.linear_acceleration.z = samples[index].acceleration[2];

      if (angular_velocity_covariance_ > 0.0) {
        message.angular_velocity_covariance[0] = angular_velocity_covariance_;
        message.angular_velocity_covariance[4] = angular_velocity_covariance_;
        message.angular_velocity_covariance[8] = angular_velocity_covariance_;
      }
      if (linear_acceleration_covariance_ > 0.0) {
        message.linear_acceleration_covariance[0] = linear_acceleration_covariance_;
        message.linear_acceleration_covariance[4] = linear_acceleration_covariance_;
        message.linear_acceleration_covariance[8] = linear_acceleration_covariance_;
      }

      publisher_->publish(message);
      ++samples_since_report_;
    }
  }

  void ExecuteReportStatistics()
  {
    const auto now = std::chrono::steady_clock::now();
    const double elapsed = std::chrono::duration<double>(now - report_start_).count();
    if (elapsed < 5.0) {
      return;
    }
    RCLCPP_INFO(
      get_logger(),
      "IMU: %.2f Hz, checksum errors=%lu, discarded bytes=%lu, incomplete pairs=%lu, "
      "missing samples=%lu, timestamp resyncs=%lu, timestamp phase error=%.3f ms",
      static_cast<double>(samples_since_report_) / elapsed,
      static_cast<unsigned long>(checksum_errors_since_report_),
      static_cast<unsigned long>(discarded_bytes_since_report_),
      static_cast<unsigned long>(incomplete_pairs_since_report_),
      static_cast<unsigned long>(missing_samples_since_report_),
      static_cast<unsigned long>(timestamp_resyncs_since_report_),
      timestamp_valid_ ?
      static_cast<double>(get_clock()->now().nanoseconds() - last_timestamp_ns_) / 1000000.0 :
      0.0);
    report_start_ = now;
    samples_since_report_ = 0;
    checksum_errors_since_report_ = 0;
    discarded_bytes_since_report_ = 0;
    incomplete_pairs_since_report_ = 0;
    missing_samples_since_report_ = 0;
    timestamp_resyncs_since_report_ = 0;
  }

  void ExecuteReadLoop()
  {
    // 串口异常后自动关闭重开，USB短暂断连无需重启ROS节点。
    std::array<uint8_t, 2048> read_buffer{};
    while (running_.load()) {
      if (!ExecuteOpenSerial()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(reconnect_delay_ms_));
        continue;
      }

      bool reconnect_required = false;
      auto last_data_time = std::chrono::steady_clock::now();
      while (running_.load() && !reconnect_required) {
        pollfd descriptor{};
        descriptor.fd = fd_;
        descriptor.events = POLLIN;
        const int poll_result = poll(&descriptor, 1, poll_timeout_ms_);
        if (poll_result < 0) {
          if (errno == EINTR) {
            continue;
          }
          RCLCPP_WARN(get_logger(), "Serial poll failed: %s", std::strerror(errno));
          reconnect_required = true;
          continue;
        }
        if (poll_result == 0) {
          const auto silence_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - last_data_time).count();
          if (silence_ms >= serial_data_timeout_ms_) {
            RCLCPP_WARN(
              get_logger(), "No IMU data for %ld ms, reopening serial port", silence_ms);
            reconnect_required = true;
          }
          continue;
        }
        if ((descriptor.revents & (POLLERR | POLLHUP | POLLNVAL)) != 0) {
          RCLCPP_WARN(get_logger(), "Serial device disconnected, reopening");
          reconnect_required = true;
          continue;
        }

        const ssize_t bytes_read = read(fd_, read_buffer.data(), read_buffer.size());
        if (bytes_read < 0) {
          if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) {
            continue;
          }
          RCLCPP_WARN(get_logger(), "Serial read failed: %s", std::strerror(errno));
          reconnect_required = true;
          continue;
        }
        if (bytes_read == 0) {
          continue;
        }
        last_data_time = std::chrono::steady_clock::now();

        receive_buffer_.insert(
          receive_buffer_.end(), read_buffer.begin(), read_buffer.begin() + bytes_read);
        std::vector<ImuSample> samples;
        samples.reserve(8);
        ExecuteParseBuffer(samples);
        ExecutePublishSamples(samples);
        ExecuteReportStatistics();
      }

      ExecuteCloseSerial();
      if (running_.load()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(reconnect_delay_ms_));
      }
    }
    ExecuteCloseSerial();
  }

  std::string port_;
  int baud_{115200};
  std::string frame_id_;
  std::string topic_;
  double expected_rate_hz_{200.0};
  int qos_depth_{5};
  int poll_timeout_ms_{500};
  int serial_data_timeout_ms_{2000};
  int reconnect_delay_ms_{1000};
  double timestamp_resync_threshold_ms_{20.0};
  double angular_velocity_covariance_{0.0};
  double linear_acceleration_covariance_{0.0};
  int64_t sample_period_ns_{5000000};
  int64_t timestamp_resync_threshold_ns_{20000000};

  int fd_{-1};
  std::atomic<bool> running_{false};
  std::thread read_thread_;
  std::vector<uint8_t> receive_buffer_;
  std::size_t receive_offset_{0};
  std::array<double, 3> latest_acceleration_{};
  bool has_acceleration_{false};
  bool current_cycle_missing_counted_{false};
  uint32_t pending_missing_samples_{0};
  bool timestamp_valid_{false};
  int64_t last_timestamp_ns_{0};

  std::chrono::steady_clock::time_point report_start_{};
  uint64_t samples_since_report_{0};
  uint64_t checksum_errors_since_report_{0};
  uint64_t discarded_bytes_since_report_{0};
  uint64_t incomplete_pairs_since_report_{0};
  uint64_t missing_samples_since_report_{0};
  uint64_t timestamp_resyncs_since_report_{0};

  rclcpp::Publisher<sensor_msgs::msg::Imu>::SharedPtr publisher_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<WitImuNode>());
  rclcpp::shutdown();
  return 0;
}
