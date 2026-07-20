#include <ament_index_cpp/get_package_share_directory.hpp>
#include <fcntl.h>
#include <linux/videodev2.h>
#include <opencv2/core.hpp>
#include <opencv2/imgcodecs.hpp>
#include <poll.h>
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/camera_info.hpp>
#include <sensor_msgs/msg/image.hpp>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <yaml-cpp/yaml.h>

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <cctype>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

class StereoV4l2DirectNode : public rclcpp::Node
{
public:
  StereoV4l2DirectNode()
  : Node("stereo_v4l2_direct_node")
  {
    const std::string package_share =
      ament_index_cpp::get_package_share_directory("stereo_v4l2_camera");

    device_ = declare_parameter<std::string>(
      "video_device",
      "/dev/v4l/by-id/usb-USB_Camera_USB_Camera_01.00.00-video-index0");
    width_ = declare_parameter<int>("image_width", 1280);
    height_ = declare_parameter<int>("image_height", 480);
    pixel_format_name_ = declare_parameter<std::string>("pixel_format", "YUYV");
    fps_ = declare_parameter<int>("framerate", 15);
    publish_fps_ = declare_parameter<int>("publish_framerate", 0);
    qos_depth_ = declare_parameter<int>("qos_depth", 4);
    reliable_qos_ = declare_parameter<bool>("reliable_qos", false);
    buffer_count_ = declare_parameter<int>("buffer_count", 4);
    poll_timeout_ms_ = declare_parameter<int>("poll_timeout_ms", 1000);
    reconnect_delay_ms_ = declare_parameter<int>("reconnect_delay_ms", 1000);
    swap_left_right_ = declare_parameter<bool>("swap_left_right", true);
    apply_camera_controls_ = declare_parameter<bool>("apply_camera_controls", true);
    brightness_ = declare_parameter<int>("brightness", 50);
    contrast_ = declare_parameter<int>("contrast", 0);
    saturation_ = declare_parameter<int>("saturation", 56);
    hue_ = declare_parameter<int>("hue", 0);
    white_balance_automatic_ = declare_parameter<bool>("white_balance_automatic", false);
    white_balance_temperature_ = declare_parameter<int>("white_balance_temperature", 4600);
    gamma_ = declare_parameter<int>("gamma", 100);
    gain_ = declare_parameter<int>("gain", 10);
    power_line_frequency_ = declare_parameter<int>("power_line_frequency", 0);
    sharpness_ = declare_parameter<int>("sharpness", 0);
    backlight_compensation_ = declare_parameter<int>("backlight_compensation", 0);
    auto_exposure_ = declare_parameter<int>("auto_exposure", V4L2_EXPOSURE_MANUAL);
    exposure_time_absolute_ = declare_parameter<int>("exposure_time_absolute", 10000);
    // A negative value leaves an optional control unchanged. Some cameras do not expose these.
    exposure_dynamic_framerate_ = declare_parameter<int>(
      "exposure_dynamic_framerate", -1);
    focus_automatic_continuous_ = declare_parameter<int>(
      "focus_automatic_continuous", -1);
    focus_absolute_ = declare_parameter<int>("focus_absolute", -1);
    disabled_camera_controls_ = declare_parameter<std::vector<std::string>>(
      "disabled_camera_controls", std::vector<std::string>{});
    left_frame_id_ = declare_parameter<std::string>(
      "left_frame_id", "camera_left_frame");
    right_frame_id_ = declare_parameter<std::string>(
      "right_frame_id", "camera_right_frame");
    camera_time_offset_ms_ = declare_parameter<double>("camera_time_offset_ms", 0.0);
    const std::string left_info_path = declare_parameter<std::string>(
      "left_camera_info_file", package_share + "/config/left.yaml");
    const std::string right_info_path = declare_parameter<std::string>(
      "right_camera_info_file", package_share + "/config/right.yaml");

    ExecuteValidateParameters();

    auto qos = rclcpp::SensorDataQoS().keep_last(qos_depth_);
    if (reliable_qos_) {
      qos.reliable();
    }
    //auto qos = rclcpp::QoS(rclcpp::KeepLast()).reliable().durability_volatile();
    left_image_pub_ = create_publisher<sensor_msgs::msg::Image>(
      "/stereo/left/camera/image_mono", qos);
    right_image_pub_ = create_publisher<sensor_msgs::msg::Image>(
      "/stereo/right/camera/image_mono", qos);
    left_info_pub_ = create_publisher<sensor_msgs::msg::CameraInfo>(
      "/stereo/left/camera/camera_info", qos);
    right_info_pub_ = create_publisher<sensor_msgs::msg::CameraInfo>(
      "/stereo/right/camera/camera_info", qos);

    left_info_ = GetCameraInfoValue(left_info_path, left_frame_id_);
    right_info_ = GetCameraInfoValue(right_info_path, right_frame_id_);

    if (publish_fps_ > 0) {
      RCLCPP_INFO(
        get_logger(), "Latest-frame publishing limited to %d fps",
        publish_fps_);
    }

    running_.store(true);
    publisher_thread_ = std::thread(&StereoV4l2DirectNode::ExecutePublisherLoop, this);
    capture_thread_ = std::thread(&StereoV4l2DirectNode::ExecuteCaptureLoop, this);
  }

  ~StereoV4l2DirectNode() override
  {
    running_.store(false);
    frame_condition_.notify_all();
    if (capture_thread_.joinable()) {
      capture_thread_.join();
    }
    if (publisher_thread_.joinable()) {
      publisher_thread_.join();
    }
    ExecuteCloseDevice();
  }

private:
  struct MappedBuffer
  {
    void * start{MAP_FAILED};
    std::size_t length{0};
  };

  static int ExecuteIoctl(int fd, unsigned long request, void * argument)
  {
    // ioctl 被信号中断时自动重试。
    int result;
    do {
      result = ioctl(fd, request, argument);
    } while (result == -1 && errno == EINTR);
    return result;
  }

  void ExecuteValidateParameters()
  {
    // 直采节点支持等宽拼接的YUYV或MJPEG双目图。
    if (width_ < 2 || width_ % 2 != 0 || height_ <= 0 || fps_ <= 0 || publish_fps_ < 0) {
      throw std::invalid_argument(
              "image_width must be even; dimensions/capture fps must be positive; "
              "publish fps must be non-negative");
    }
    if (qos_depth_ <= 0 || buffer_count_ < 2 || poll_timeout_ms_ <= 0 ||
      reconnect_delay_ms_ <= 0)
    {
      throw std::invalid_argument(
              "qos_depth must be positive; buffer_count >= 2 and timeout values must be positive");
    }
    if (!std::isfinite(camera_time_offset_ms_)) {
      throw std::invalid_argument("camera_time_offset_ms must be finite");
    }

    std::transform(
      pixel_format_name_.begin(), pixel_format_name_.end(), pixel_format_name_.begin(),
      [](unsigned char character) {return static_cast<char>(std::toupper(character));});
    if (pixel_format_name_ == "YUYV" || pixel_format_name_ == "YUY2") {
      pixel_format_name_ = "YUYV";
      pixel_format_fourcc_ = V4L2_PIX_FMT_YUYV;
    } else if (pixel_format_name_ == "MJPEG" || pixel_format_name_ == "MJPG") {
      pixel_format_name_ = "MJPEG";
      pixel_format_fourcc_ = V4L2_PIX_FMT_MJPEG;
    } else {
      throw std::invalid_argument("pixel_format must be YUYV or MJPEG");
    }
  }

  sensor_msgs::msg::CameraInfo GetCameraInfoValue(
    const std::string & yaml_path, const std::string & frame_id)
  {
    // 标定加载失败时发布明确的未标定CameraInfo，不阻止相机运行。
    sensor_msgs::msg::CameraInfo info;
    info.width = static_cast<uint32_t>(width_ / 2);
    info.height = static_cast<uint32_t>(height_);
    info.header.frame_id = frame_id;

    try {
      const YAML::Node config = YAML::LoadFile(yaml_path);
      info.width = config["image_width"].as<int>();
      info.height = config["image_height"].as<int>();
      info.distortion_model = config["distortion_model"].as<std::string>();

      const YAML::Node camera_matrix = config["camera_matrix"]["data"];
      const YAML::Node distortion = config["distortion_coefficients"]["data"];
      const YAML::Node rectification = config["rectification_matrix"]["data"];
      const YAML::Node projection = config["projection_matrix"]["data"];
      if (camera_matrix.size() != 9 || rectification.size() != 9 ||
        projection.size() != 12)
      {
        throw std::runtime_error("invalid CameraInfo matrix size");
      }
      for (std::size_t index = 0; index < 9; ++index) {
        info.k[index] = camera_matrix[index].as<double>();
        info.r[index] = rectification[index].as<double>();
      }
      info.d.reserve(distortion.size());
      for (std::size_t index = 0; index < distortion.size(); ++index) {
        info.d.push_back(distortion[index].as<double>());
      }
      for (std::size_t index = 0; index < 12; ++index) {
        info.p[index] = projection[index].as<double>();
      }
      RCLCPP_INFO(get_logger(), "Loaded CameraInfo: %s", yaml_path.c_str());
    } catch (const std::exception & error) {
      RCLCPP_WARN(
        get_logger(), "CameraInfo unavailable (%s): %s; publishing uncalibrated info",
        yaml_path.c_str(), error.what());
    }
    return info;
  }

  bool ExecuteOpenDevice()
  {
    ExecuteCloseDevice();
    fd_ = open(device_.c_str(), O_RDWR | O_NONBLOCK);
    if (fd_ < 0) {
      RCLCPP_WARN(get_logger(), "Cannot open %s: %s", device_.c_str(), std::strerror(errno));
      return false;
    }

    v4l2_capability capability{};
    if (ExecuteIoctl(fd_, VIDIOC_QUERYCAP, &capability) < 0) {
      RCLCPP_ERROR(get_logger(), "VIDIOC_QUERYCAP failed: %s", std::strerror(errno));
      ExecuteCloseDevice();
      return false;
    }
    if ((capability.capabilities & V4L2_CAP_VIDEO_CAPTURE) == 0 ||
      (capability.capabilities & V4L2_CAP_STREAMING) == 0)
    {
      RCLCPP_ERROR(get_logger(), "Device does not support capture + streaming");
      ExecuteCloseDevice();
      return false;
    }

    if (!ExecuteConfigureDevice() || !ExecuteConfigureControls() || !ExecuteInitializeBuffers() ||
      !ExecuteStartStreaming())
    {
      ExecuteCloseDevice();
      return false;
    }
    return true;
  }

  bool ExecuteConfigureDevice()
  {
    // 请求拼接图和固定帧率，并严格核对驱动实际接受值。
    v4l2_format format{};
    format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    format.fmt.pix.width = static_cast<uint32_t>(width_);
    format.fmt.pix.height = static_cast<uint32_t>(height_);
    format.fmt.pix.pixelformat = pixel_format_fourcc_;
    format.fmt.pix.field = V4L2_FIELD_NONE;
    if (ExecuteIoctl(fd_, VIDIOC_S_FMT, &format) < 0) {
      RCLCPP_ERROR(get_logger(), "VIDIOC_S_FMT failed: %s", std::strerror(errno));
      return false;
    }
    if (format.fmt.pix.width != static_cast<uint32_t>(width_) ||
      format.fmt.pix.height != static_cast<uint32_t>(height_) ||
      format.fmt.pix.pixelformat != pixel_format_fourcc_)
    {
      RCLCPP_ERROR(
        get_logger(), "Driver returned unexpected format %ux%u fourcc=0x%08x",
        format.fmt.pix.width, format.fmt.pix.height, format.fmt.pix.pixelformat);
      return false;
    }
    bytes_per_line_ = format.fmt.pix.bytesperline;
    if (pixel_format_fourcc_ == V4L2_PIX_FMT_YUYV &&
      bytes_per_line_ < static_cast<uint32_t>(width_ * 2))
    {
      bytes_per_line_ = static_cast<uint32_t>(width_ * 2);
    }

    v4l2_streamparm stream_parameter{};
    stream_parameter.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    stream_parameter.parm.capture.timeperframe.numerator = 1;
    stream_parameter.parm.capture.timeperframe.denominator = static_cast<uint32_t>(fps_);
    if (ExecuteIoctl(fd_, VIDIOC_S_PARM, &stream_parameter) < 0) {
      RCLCPP_ERROR(get_logger(), "VIDIOC_S_PARM failed: %s", std::strerror(errno));
      return false;
    }

    const auto numerator = stream_parameter.parm.capture.timeperframe.numerator;
    const auto denominator = stream_parameter.parm.capture.timeperframe.denominator;
    const double actual_fps = numerator == 0 ? 0.0 :
      static_cast<double>(denominator) / static_cast<double>(numerator);
    RCLCPP_INFO(
      get_logger(), "Configured %s: %dx%d %s @ %.3f fps, stride=%u",
      device_.c_str(), width_, height_, pixel_format_name_.c_str(), actual_fps, bytes_per_line_);
    if (publish_fps_ > 0 && actual_fps < static_cast<double>(publish_fps_)) {
      RCLCPP_ERROR(
        get_logger(), "Actual capture rate %.3f fps is below requested publish rate %d fps",
        actual_fps, publish_fps_);
      return false;
    }
    return actual_fps > 0.0;
  }

  bool IsCameraControlEnabled(const char * name) const
  {
    return std::find(
      disabled_camera_controls_.begin(), disabled_camera_controls_.end(), name) ==
           disabled_camera_controls_.end();
  }

  bool ConfigureCameraControlValue(uint32_t control_id, int32_t value, const char * name)
  {
    if (!IsCameraControlEnabled(name)) {
      RCLCPP_INFO(get_logger(), "Camera control %s is disabled by configuration", name);
      return true;
    }
    return SetCameraControlValue(control_id, value, name);
  }

  bool ConfigureOptionalCameraControlValue(
    uint32_t control_id, int32_t value, const char * name)
  {
    if (value < 0) {
      return true;
    }
    return ConfigureCameraControlValue(control_id, value, name);
  }

  bool SetCameraControlValue(uint32_t control_id, int32_t requested_value, const char * name)
  {
    // 写入前检查设备范围，写入后回读，确保驱动实际采用了目标值。
    v4l2_queryctrl query{};
    query.id = control_id;
    if (ExecuteIoctl(fd_, VIDIOC_QUERYCTRL, &query) < 0 ||
      (query.flags & V4L2_CTRL_FLAG_DISABLED) != 0)
    {
      RCLCPP_ERROR(get_logger(), "Camera control %s is unavailable", name);
      return false;
    }
    if (requested_value < query.minimum || requested_value > query.maximum ||
      ((requested_value - query.minimum) % query.step) != 0)
    {
      RCLCPP_ERROR(
        get_logger(), "Camera control %s=%d is outside [%d, %d], step=%d",
        name, requested_value, query.minimum, query.maximum, query.step);
      return false;
    }

    v4l2_control control{};
    control.id = control_id;
    control.value = requested_value;
    if (ExecuteIoctl(fd_, VIDIOC_S_CTRL, &control) < 0) {
      RCLCPP_ERROR(
        get_logger(), "Failed to set camera control %s=%d: %s",
        name, requested_value, std::strerror(errno));
      return false;
    }

    control.value = 0;
    if (ExecuteIoctl(fd_, VIDIOC_G_CTRL, &control) < 0) {
      RCLCPP_ERROR(
        get_logger(), "Failed to read camera control %s: %s", name,
        std::strerror(errno));
      return false;
    }
    if (control.value != requested_value) {
      RCLCPP_ERROR(
        get_logger(), "Camera control %s requested=%d, actual=%d",
        name, requested_value, control.value);
      return false;
    }
    RCLCPP_INFO(get_logger(), "Camera control %s=%d", name, control.value);
    return true;
  }

  bool ExecuteConfigureControls()
  {
    // 格式和帧率设置后再配置控件，防止驱动重新协商时恢复自动模式。
    if (!apply_camera_controls_) {
      RCLCPP_WARN(get_logger(), "Camera control configuration is disabled");
      return true;
    }

    // 必须先关闭自动模式，再设置对应的手动值。
    return ConfigureCameraControlValue(
      V4L2_CID_EXPOSURE_AUTO, auto_exposure_, "auto_exposure") &&
           ConfigureOptionalCameraControlValue(
      V4L2_CID_EXPOSURE_AUTO_PRIORITY,
      exposure_dynamic_framerate_, "exposure_dynamic_framerate") &&
           ConfigureCameraControlValue(
      V4L2_CID_EXPOSURE_ABSOLUTE, exposure_time_absolute_, "exposure_time_absolute") &&
           ConfigureCameraControlValue(
      V4L2_CID_AUTO_WHITE_BALANCE,
      white_balance_automatic_ ? 1 : 0, "white_balance_automatic") &&
           ConfigureCameraControlValue(
      V4L2_CID_WHITE_BALANCE_TEMPERATURE,
      white_balance_temperature_, "white_balance_temperature") &&
           ConfigureCameraControlValue(V4L2_CID_BRIGHTNESS, brightness_, "brightness") &&
           ConfigureCameraControlValue(V4L2_CID_CONTRAST, contrast_, "contrast") &&
           ConfigureCameraControlValue(V4L2_CID_SATURATION, saturation_, "saturation") &&
           ConfigureCameraControlValue(V4L2_CID_HUE, hue_, "hue") &&
           ConfigureCameraControlValue(V4L2_CID_GAMMA, gamma_, "gamma") &&
           ConfigureCameraControlValue(V4L2_CID_GAIN, gain_, "gain") &&
           ConfigureCameraControlValue(
      V4L2_CID_POWER_LINE_FREQUENCY, power_line_frequency_, "power_line_frequency") &&
           ConfigureCameraControlValue(V4L2_CID_SHARPNESS, sharpness_, "sharpness") &&
           ConfigureCameraControlValue(
      V4L2_CID_BACKLIGHT_COMPENSATION,
      backlight_compensation_, "backlight_compensation") &&
           ConfigureOptionalCameraControlValue(
      V4L2_CID_FOCUS_AUTO,
      focus_automatic_continuous_, "focus_automatic_continuous") &&
           ConfigureOptionalCameraControlValue(
      V4L2_CID_FOCUS_ABSOLUTE, focus_absolute_, "focus_absolute");
  }

  bool ExecuteInitializeBuffers()
  {
    // 申请多个mmap缓冲以维持内核采集流水线。
    v4l2_requestbuffers request{};
    request.count = static_cast<uint32_t>(buffer_count_);
    request.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    request.memory = V4L2_MEMORY_MMAP;
    if (ExecuteIoctl(fd_, VIDIOC_REQBUFS, &request) < 0 || request.count < 2) {
      RCLCPP_ERROR(get_logger(), "VIDIOC_REQBUFS failed or returned fewer than 2 buffers");
      return false;
    }

    buffers_.resize(request.count);
    for (uint32_t index = 0; index < request.count; ++index) {
      v4l2_buffer buffer{};
      buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
      buffer.memory = V4L2_MEMORY_MMAP;
      buffer.index = index;
      if (ExecuteIoctl(fd_, VIDIOC_QUERYBUF, &buffer) < 0) {
        RCLCPP_ERROR(get_logger(), "VIDIOC_QUERYBUF failed: %s", std::strerror(errno));
        return false;
      }

      buffers_[index].length = buffer.length;
      buffers_[index].start = mmap(
        nullptr, buffer.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd_, buffer.m.offset);
      if (buffers_[index].start == MAP_FAILED) {
        RCLCPP_ERROR(get_logger(), "mmap failed: %s", std::strerror(errno));
        return false;
      }
      if (ExecuteIoctl(fd_, VIDIOC_QBUF, &buffer) < 0) {
        RCLCPP_ERROR(get_logger(), "Initial VIDIOC_QBUF failed: %s", std::strerror(errno));
        return false;
      }
    }
    return true;
  }

  bool ExecuteStartStreaming()
  {
    v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (ExecuteIoctl(fd_, VIDIOC_STREAMON, &type) < 0) {
      RCLCPP_ERROR(get_logger(), "VIDIOC_STREAMON failed: %s", std::strerror(errno));
      return false;
    }
    streaming_ = true;
    last_sequence_valid_ = false;
    return true;
  }

  void ExecuteCloseDevice()
  {
    // 按stream-off、unmap、close顺序释放资源，支持反复重连。
    if (fd_ >= 0 && streaming_) {
      v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
      ExecuteIoctl(fd_, VIDIOC_STREAMOFF, &type);
    }
    streaming_ = false;
    for (auto & buffer : buffers_) {
      if (buffer.start != MAP_FAILED) {
        munmap(buffer.start, buffer.length);
        buffer.start = MAP_FAILED;
      }
    }
    buffers_.clear();
    if (fd_ >= 0) {
      close(fd_);
      fd_ = -1;
    }
  }

  builtin_interfaces::msg::Time GetFrameTimestampValue(const v4l2_buffer & buffer)
  {
    // 将内核CLOCK_MONOTONIC曝光时间映射到ROS时钟，再应用Kalibr相机到IMU时偏。
    const auto ros_now = get_clock()->now();
    const int64_t offset_ns = static_cast<int64_t>(
      std::llround(camera_time_offset_ms_ * 1000000.0));
    const bool is_monotonic =
      (buffer.flags & V4L2_BUF_FLAG_TIMESTAMP_MASK) ==
      V4L2_BUF_FLAG_TIMESTAMP_MONOTONIC;
    if (!is_monotonic || (buffer.timestamp.tv_sec == 0 && buffer.timestamp.tv_usec == 0)) {
      const rclcpp::Time corrected_time(
        ros_now.nanoseconds() + offset_ns, get_clock()->get_clock_type());
      return static_cast<builtin_interfaces::msg::Time>(corrected_time);
    }

    const int64_t capture_ns =
      static_cast<int64_t>(buffer.timestamp.tv_sec) * 1000000000LL +
      static_cast<int64_t>(buffer.timestamp.tv_usec) * 1000LL;
    const int64_t monotonic_now_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
    const rclcpp::Time capture_time(
      ros_now.nanoseconds() - monotonic_now_ns + capture_ns + offset_ns,
      get_clock()->get_clock_type());
    return static_cast<builtin_interfaces::msg::Time>(capture_time);
  }

  bool IsFrameValid(const v4l2_buffer & buffer) const
  {
    if (buffer.index >= buffers_.size() || buffers_[buffer.index].start == MAP_FAILED ||
      buffer.bytesused == 0 || buffer.bytesused > buffers_[buffer.index].length)
    {
      return false;
    }
    if (pixel_format_fourcc_ == V4L2_PIX_FMT_MJPEG) {
      return true;
    }
    const std::size_t minimum_size =
      static_cast<std::size_t>(bytes_per_line_) * static_cast<std::size_t>(height_);
    return buffer.bytesused >= minimum_size;
  }

  struct StereoFrame
  {
    uint64_t generation{0};
    sensor_msgs::msg::Image left_image;
    sensor_msgs::msg::Image right_image;
  };

  std::unique_ptr<StereoFrame> GetStereoFrameValue(
    const uint8_t * source, std::size_t source_size,
    const builtin_interfaces::msg::Time & stamp, uint64_t generation)
  {
    const int half_width = width_ / 2;
    auto frame = std::make_unique<StereoFrame>();
    frame->generation = generation;
    auto & left_image = frame->left_image;
    auto & right_image = frame->right_image;
    left_image.header.stamp = stamp;
    left_image.header.frame_id = left_frame_id_;
    right_image.header.stamp = stamp;
    right_image.header.frame_id = right_frame_id_;
    for (auto * image : {&left_image, &right_image}) {
      image->height = static_cast<uint32_t>(height_);
      image->width = static_cast<uint32_t>(half_width);
      image->encoding = "mono8";
      image->is_bigendian = false;
      image->step = static_cast<uint32_t>(half_width);
      image->data.resize(static_cast<std::size_t>(half_width * height_));
    }

    if (pixel_format_fourcc_ == V4L2_PIX_FMT_MJPEG) {
      try {
        cv::Mat encoded(
          1, static_cast<int>(source_size), CV_8UC1, const_cast<uint8_t *>(source));
        const cv::Mat decoded = cv::imdecode(encoded, cv::IMREAD_GRAYSCALE);
        if (decoded.empty() || decoded.cols != width_ || decoded.rows != height_) {
          RCLCPP_WARN(
            get_logger(), "MJPEG decoder returned an unexpected image size: %dx%d",
            decoded.cols, decoded.rows);
          return nullptr;
        }
        for (int row = 0; row < height_; ++row) {
          const uint8_t * decoded_row = decoded.ptr<uint8_t>(row);
          const uint8_t * first_half = decoded_row;
          const uint8_t * second_half = decoded_row + half_width;
          uint8_t * left_row =
            left_image.data.data() + static_cast<std::size_t>(row * half_width);
          uint8_t * right_row =
            right_image.data.data() + static_cast<std::size_t>(row * half_width);
          std::memcpy(left_row, swap_left_right_ ? second_half : first_half, half_width);
          std::memcpy(right_row, swap_left_right_ ? first_half : second_half, half_width);
        }
      } catch (const cv::Exception & error) {
        RCLCPP_WARN(get_logger(), "MJPEG decode failed: %s", error.what());
        return nullptr;
      }
    } else {
      // 直接提取YUYV的Y字节，同时完成左右拆分。
      for (int row = 0; row < height_; ++row) {
        const uint8_t * source_row = source + static_cast<std::size_t>(row) * bytes_per_line_;
        const uint8_t * first_half = source_row;
        const uint8_t * second_half = source_row + half_width * 2;
        uint8_t * left_row =
          left_image.data.data() + static_cast<std::size_t>(row * half_width);
        uint8_t * right_row =
          right_image.data.data() + static_cast<std::size_t>(row * half_width);
        const uint8_t * left_source = swap_left_right_ ? second_half : first_half;
        const uint8_t * right_source = swap_left_right_ ? first_half : second_half;
        for (int column = 0; column < half_width; ++column) {
          left_row[column] = left_source[column * 2];
          right_row[column] = right_source[column * 2];
        }
      }
    }

    return frame;
  }

  void ExecutePublishFrame(std::unique_ptr<StereoFrame> frame)
  {
    auto left_info = std::make_unique<sensor_msgs::msg::CameraInfo>(left_info_);
    auto right_info = std::make_unique<sensor_msgs::msg::CameraInfo>(right_info_);
    left_info->header = frame->left_image.header;
    right_info->header = frame->right_image.header;
    auto left_image =
      std::make_unique<sensor_msgs::msg::Image>(std::move(frame->left_image));
    auto right_image =
      std::make_unique<sensor_msgs::msg::Image>(std::move(frame->right_image));

    // 交替先发左/右图，避免高负载时固定一侧总是最后进入DDS队列。
    if ((frame->generation & 1U) == 0U) {
      left_image_pub_->publish(std::move(left_image));
      right_image_pub_->publish(std::move(right_image));
    } else {
      right_image_pub_->publish(std::move(right_image));
      left_image_pub_->publish(std::move(left_image));
    }
    left_info_pub_->publish(std::move(left_info));
    right_info_pub_->publish(std::move(right_info));
    published_frame_count_.fetch_add(1, std::memory_order_relaxed);
  }

  void ExecuteQueueLatestFrame(std::unique_ptr<StereoFrame> frame)
  {
    {
      std::lock_guard<std::mutex> lock(frame_mutex_);
      latest_frame_ = std::move(frame);
    }
    frame_condition_.notify_one();
  }

  void ExecutePublisherLoop()
  {
    if (publish_fps_ == 0) {
      while (running_.load()) {
        std::unique_ptr<StereoFrame> frame;
        {
          std::unique_lock<std::mutex> lock(frame_mutex_);
          frame_condition_.wait(
            lock, [this]() {return !running_.load() || latest_frame_ != nullptr;});
          if (!running_.load()) {
            return;
          }
          frame = std::move(latest_frame_);
        }
        ExecutePublishFrame(std::move(frame));
      }
      return;
    }

    const auto period = std::chrono::nanoseconds(1000000000LL / publish_fps_);
    auto next_publish = std::chrono::steady_clock::now() + period;
    while (running_.load()) {
      std::unique_ptr<StereoFrame> frame;
      {
        std::unique_lock<std::mutex> lock(frame_mutex_);
        frame_condition_.wait_until(
          lock, next_publish, [this]() {return !running_.load();});
        if (!running_.load()) {
          return;
        }
        frame = std::move(latest_frame_);
      }
      if (frame) {
        ExecutePublishFrame(std::move(frame));
      }

      const auto now = std::chrono::steady_clock::now();
      do {
        next_publish += period;
      } while (next_publish <= now);
    }
  }

  void ExecuteCaptureLoop()
  {
    // 捕获失败后关闭并重开设备，保证USB短暂断线能够恢复。
    while (running_.load()) {
      if (!ExecuteOpenDevice()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(reconnect_delay_ms_));
        continue;
      }

      uint64_t captured_frames_since_report = 0;
      uint64_t dropped_since_report = 0;
      uint64_t published_at_report = published_frame_count_.load(std::memory_order_relaxed);
      auto report_start = std::chrono::steady_clock::now();
      bool restart_required = false;

      while (running_.load() && !restart_required) {
        pollfd descriptor{};
        descriptor.fd = fd_;
        descriptor.events = POLLIN;
        const int poll_result = poll(&descriptor, 1, poll_timeout_ms_);
        if (poll_result < 0) {
          if (errno == EINTR) {
            continue;
          }
          RCLCPP_WARN(get_logger(), "poll failed: %s", std::strerror(errno));
          restart_required = true;
          continue;
        }
        if (poll_result == 0 || (descriptor.revents & (POLLERR | POLLHUP | POLLNVAL)) != 0) {
          RCLCPP_WARN(get_logger(), "Camera poll timeout/error, reopening device");
          restart_required = true;
          continue;
        }

        v4l2_buffer buffer{};
        buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buffer.memory = V4L2_MEMORY_MMAP;
        if (ExecuteIoctl(fd_, VIDIOC_DQBUF, &buffer) < 0) {
          if (errno == EAGAIN) {
            continue;
          }
          RCLCPP_WARN(get_logger(), "VIDIOC_DQBUF failed: %s", std::strerror(errno));
          restart_required = true;
          continue;
        }

        if (last_sequence_valid_ && buffer.sequence > last_sequence_ + 1) {
          dropped_since_report += buffer.sequence - last_sequence_ - 1;
        }
        last_sequence_ = buffer.sequence;
        last_sequence_valid_ = true;

        std::unique_ptr<StereoFrame> frame;
        if (IsFrameValid(buffer)) {
          const auto stamp = GetFrameTimestampValue(buffer);
          const auto * source = static_cast<const uint8_t *>(buffers_[buffer.index].start);
          frame = GetStereoFrameValue(
            source, static_cast<std::size_t>(buffer.bytesused), stamp, ++frame_generation_);
          ++captured_frames_since_report;
        } else {
          RCLCPP_WARN(get_logger(), "Invalid V4L2 frame received");
        }

        if (ExecuteIoctl(fd_, VIDIOC_QBUF, &buffer) < 0) {
          RCLCPP_WARN(get_logger(), "VIDIOC_QBUF failed: %s", std::strerror(errno));
          restart_required = true;
          continue;
        }
        // 内核缓冲已立即归还；DDS输出在独立线程中处理。
        if (frame) {
          ExecuteQueueLatestFrame(std::move(frame));
        }

        const auto now = std::chrono::steady_clock::now();
        const double elapsed = std::chrono::duration<double>(now - report_start).count();
        if (elapsed >= 5.0) {
          const uint64_t published_now =
            published_frame_count_.load(std::memory_order_relaxed);
          RCLCPP_INFO(
            get_logger(),
            "Direct capture: %.2f fps, topic publish: %.2f fps, kernel sequence drops: %lu",
            static_cast<double>(captured_frames_since_report) / elapsed,
            static_cast<double>(published_now - published_at_report) / elapsed,
            static_cast<unsigned long>(dropped_since_report));
          captured_frames_since_report = 0;
          dropped_since_report = 0;
          published_at_report = published_now;
          report_start = now;
        }
      }

      ExecuteCloseDevice();
      if (running_.load()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(reconnect_delay_ms_));
      }
    }
    ExecuteCloseDevice();
  }

  std::string device_;
  int width_{1280};
  int height_{480};
  std::string pixel_format_name_{"YUYV"};
  uint32_t pixel_format_fourcc_{V4L2_PIX_FMT_YUYV};
  int fps_{15};
  int publish_fps_{0};
  int qos_depth_{4};
  bool reliable_qos_{false};
  int buffer_count_{4};
  int poll_timeout_ms_{1000};
  int reconnect_delay_ms_{1000};
  bool swap_left_right_{true};
  bool apply_camera_controls_{true};
  int brightness_{50};
  int contrast_{0};
  int saturation_{56};
  int hue_{0};
  bool white_balance_automatic_{false};
  int white_balance_temperature_{4600};
  int gamma_{100};
  int gain_{10};
  int power_line_frequency_{0};
  int sharpness_{0};
  int backlight_compensation_{0};
  int auto_exposure_{V4L2_EXPOSURE_MANUAL};
  int exposure_time_absolute_{10000};
  int exposure_dynamic_framerate_{-1};
  int focus_automatic_continuous_{-1};
  int focus_absolute_{-1};
  std::vector<std::string> disabled_camera_controls_;
  std::string left_frame_id_;
  std::string right_frame_id_;
  double camera_time_offset_ms_{0.0};

  int fd_{-1};
  bool streaming_{false};
  uint32_t bytes_per_line_{0};
  std::vector<MappedBuffer> buffers_;
  uint32_t last_sequence_{0};
  bool last_sequence_valid_{false};
  std::atomic<bool> running_{false};
  std::thread capture_thread_;
  std::thread publisher_thread_;

  std::mutex frame_mutex_;
  std::condition_variable frame_condition_;
  std::unique_ptr<StereoFrame> latest_frame_;
  uint64_t frame_generation_{0};
  std::atomic<uint64_t> published_frame_count_{0};

  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr left_image_pub_;
  rclcpp::Publisher<sensor_msgs::msg::Image>::SharedPtr right_image_pub_;
  rclcpp::Publisher<sensor_msgs::msg::CameraInfo>::SharedPtr left_info_pub_;
  rclcpp::Publisher<sensor_msgs::msg::CameraInfo>::SharedPtr right_info_pub_;
  sensor_msgs::msg::CameraInfo left_info_;
  sensor_msgs::msg::CameraInfo right_info_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<StereoV4l2DirectNode>());
  rclcpp::shutdown();
  return 0;
}
