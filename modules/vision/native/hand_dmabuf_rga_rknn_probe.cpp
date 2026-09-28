// Board-only validation for the Hand input path:
// dma-heap FD -> RGA FD import/resize/color/letterbox -> RKNN C API FD input.
//
// This file intentionally does not use RKNNLite or NumPy.  It is an opt-in
// diagnostic executable and is not part of the installed Python provider.

#include <cstddef>
#include <cstdint>
#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <cmath>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <linux/dma-buf.h>
#include <linux/dma-heap.h>
#include <memory>
#include <openssl/evp.h>
#include <rga/im2d.h>
#include <sstream>
#include <string>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <utility>
#include <vector>

#include <rknn_api.h>

namespace {

constexpr int kSourceWidth = 640;
constexpr int kSourceHeight = 480;
constexpr int kDetectorSize = 192;
constexpr int kDetectorChannels = 3;
constexpr char kExpectedDetectorSha256[] =
    "588b2b3749a864766de23caccd12b979305158dad8ea836098529c3f1874c373";

bool sha256_file(const std::string& path, std::string* digest, std::string* error) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        if (error != nullptr) {
            *error = "open failed";
        }
        return false;
    }

    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(
        EVP_MD_CTX_new(), &EVP_MD_CTX_free);
    if (!context || EVP_DigestInit_ex(context.get(), EVP_sha256(), nullptr) != 1) {
        if (error != nullptr) {
            *error = "EVP_DigestInit_ex failed";
        }
        return false;
    }

    std::array<char, 64 * 1024> buffer{};
    while (input) {
        input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        const std::streamsize count = input.gcount();
        if (count > 0 && EVP_DigestUpdate(context.get(), buffer.data(),
                                           static_cast<size_t>(count)) != 1) {
            if (error != nullptr) {
                *error = "EVP_DigestUpdate failed";
            }
            return false;
        }
    }
    if (input.bad()) {
        if (error != nullptr) {
            *error = "read failed";
        }
        return false;
    }

    std::array<unsigned char, EVP_MAX_MD_SIZE> bytes{};
    unsigned int length = 0;
    if (EVP_DigestFinal_ex(context.get(), bytes.data(), &length) != 1) {
        if (error != nullptr) {
            *error = "EVP_DigestFinal_ex failed";
        }
        return false;
    }
    std::ostringstream hex;
    hex << std::hex << std::setfill('0');
    for (unsigned int index = 0; index < length; ++index) {
        hex << std::setw(2) << static_cast<unsigned int>(bytes[index]);
    }
    *digest = hex.str();
    return true;
}

std::string tensor_dims(const rknn_tensor_attr& attr) {
    std::ostringstream dimensions;
    for (uint32_t index = 0; index < attr.n_dims; ++index) {
        if (index != 0) {
            dimensions << 'x';
        }
        dimensions << attr.dims[index];
    }
    return dimensions.str();
}

bool rga_ok(IM_STATUS status) {
    return status == IM_STATUS_SUCCESS || status == IM_STATUS_NOERROR;
}

std::string rga_status(const char* operation, IM_STATUS status) {
    const char* detail = imStrError_t(status);
    if (detail == nullptr) {
        detail = "unknown";
    }
    return std::string(operation) + " failed (" + std::to_string(static_cast<int>(status)) +
           "): " + detail;
}

bool dma_buf_sync(int fd, uint64_t flags, const char* operation) {
    struct dma_buf_sync sync{};
    sync.flags = flags;
    if (ioctl(fd, DMA_BUF_IOCTL_SYNC, &sync) == 0) {
        return true;
    }
    const int saved_errno = errno;
    std::cerr << "stage=dma_buf_sync operation=" << operation
              << " return=-1 errno=" << saved_errno
              << " error=" << std::strerror(saved_errno) << "\n";
    return false;
}

class DmaBuffer {
public:
    DmaBuffer() = default;
    DmaBuffer(const DmaBuffer&) = delete;
    DmaBuffer& operator=(const DmaBuffer&) = delete;

    DmaBuffer(DmaBuffer&& other) noexcept
        : fd_(std::exchange(other.fd_, -1)),
          size_(std::exchange(other.size_, 0)),
          address_(std::exchange(other.address_, nullptr)),
          heap_(std::move(other.heap_)) {}

    DmaBuffer& operator=(DmaBuffer&& other) noexcept {
        if (this != &other) {
            close_resources();
            fd_ = std::exchange(other.fd_, -1);
            size_ = std::exchange(other.size_, 0);
            address_ = std::exchange(other.address_, nullptr);
            heap_ = std::move(other.heap_);
        }
        return *this;
    }

    ~DmaBuffer() { close_resources(); }

    static std::unique_ptr<DmaBuffer> allocate(const std::string& heap, size_t size,
                                                std::string* error) {
        int heap_fd = open(heap.c_str(), O_RDWR | O_CLOEXEC);
        if (heap_fd < 0) {
            if (error != nullptr) {
                *error = "open(" + heap + "): " + std::strerror(errno);
            }
            return nullptr;
        }
        dma_heap_allocation_data request{};
        request.len = size;
        request.fd_flags = O_RDWR | O_CLOEXEC;
        if (ioctl(heap_fd, DMA_HEAP_IOCTL_ALLOC, &request) < 0) {
            const int saved_errno = errno;
            close(heap_fd);
            if (error != nullptr) {
                *error = "DMA_HEAP_IOCTL_ALLOC(" + heap + "): " +
                         std::strerror(saved_errno);
            }
            return nullptr;
        }
        close(heap_fd);

        void* address = mmap(nullptr, size, PROT_READ | PROT_WRITE, MAP_SHARED,
                             request.fd, 0);
        if (address == MAP_FAILED) {
            const int saved_errno = errno;
            close(request.fd);
            if (error != nullptr) {
                *error = "mmap(" + heap + "): " + std::strerror(saved_errno);
            }
            return nullptr;
        }

        auto result = std::unique_ptr<DmaBuffer>(new DmaBuffer());
        result->fd_ = request.fd;
        result->size_ = size;
        result->address_ = address;
        result->heap_ = heap;
        return result;
    }

    int fd() const { return fd_; }
    size_t size() const { return size_; }
    void* address() const { return address_; }
    const std::string& heap() const { return heap_; }

private:
    void close_resources() {
        if (address_ != nullptr) {
            munmap(address_, size_);
            address_ = nullptr;
        }
        if (fd_ >= 0) {
            close(fd_);
            fd_ = -1;
        }
        size_ = 0;
    }

    int fd_ = -1;
    size_t size_ = 0;
    void* address_ = nullptr;
    std::string heap_;
};

class RgaImport {
public:
    RgaImport() = default;
    explicit RgaImport(rga_buffer_handle_t handle) : handle_(handle) {}
    RgaImport(const RgaImport&) = delete;
    RgaImport& operator=(const RgaImport&) = delete;
    RgaImport(RgaImport&& other) noexcept
        : handle_(std::exchange(other.handle_, 0)) {}
    RgaImport& operator=(RgaImport&& other) noexcept {
        if (this != &other) {
            reset();
            handle_ = std::exchange(other.handle_, 0);
        }
        return *this;
    }
    ~RgaImport() { reset(); }

    void reset() {
        if (handle_ != 0) {
            releasebuffer_handle(handle_);
            handle_ = 0;
        }
    }
    rga_buffer_handle_t handle() const { return handle_; }

private:
    rga_buffer_handle_t handle_ = 0;
};

class RknnContext {
public:
    RknnContext() = default;
    RknnContext(const RknnContext&) = delete;
    RknnContext& operator=(const RknnContext&) = delete;
    ~RknnContext() {
        if (context_ != 0) {
            rknn_destroy(context_);
        }
    }
    rknn_context* out() { return &context_; }
    rknn_context get() const { return context_; }

private:
    rknn_context context_ = 0;
};

class RknnInputMemory {
public:
    RknnInputMemory() = default;
    RknnInputMemory(const RknnInputMemory&) = delete;
    RknnInputMemory& operator=(const RknnInputMemory&) = delete;
    ~RknnInputMemory() {
        if (memory_ != nullptr && context_ != 0) {
            rknn_destroy_mem(context_, memory_);
        }
    }
    void reset(rknn_context context, rknn_tensor_mem* memory) {
        if (memory_ != nullptr && context_ != 0) {
            rknn_destroy_mem(context_, memory_);
        }
        context_ = context;
        memory_ = memory;
    }
    rknn_tensor_mem* get() const { return memory_; }

private:
    rknn_context context_ = 0;
    rknn_tensor_mem* memory_ = nullptr;
};

class RknnOutputMemory {
public:
    RknnOutputMemory() = default;
    RknnOutputMemory(const RknnOutputMemory&) = delete;
    RknnOutputMemory& operator=(const RknnOutputMemory&) = delete;
    ~RknnOutputMemory() {
        if (memory_ != nullptr && context_ != 0) {
            rknn_destroy_mem(context_, memory_);
        }
    }
    void reset(rknn_context context, rknn_tensor_mem* memory) {
        if (memory_ != nullptr && context_ != 0) {
            rknn_destroy_mem(context_, memory_);
        }
        context_ = context;
        memory_ = memory;
    }
    const rknn_tensor_mem* get() const { return memory_; }

private:
    rknn_context context_ = 0;
    rknn_tensor_mem* memory_ = nullptr;
};

struct Options {
    std::string model;
    std::string heap;
    std::string report;
    int warmup = 5;
    int loops = 30;
};

void print_usage(const char* program) {
    std::cout << "Usage: " << program
              << " --model MODEL [--heap /dev/dma_heap/NAME] [--warmup N]"
                 " [--loops N] [--report PATH]\n";
}

bool parse_positive(const char* text, int* value) {
    try {
        size_t consumed = 0;
        const int parsed = std::stoi(text, &consumed);
        if (parsed < 0 || text[consumed] != '\0') {
            return false;
        }
        *value = parsed;
        return true;
    } catch (...) {
        return false;
    }
}

bool parse_options(int argc, char** argv, Options* options) {
    for (int index = 1; index < argc; ++index) {
        const std::string argument = argv[index];
        if (argument == "--help" || argument == "-h") {
            print_usage(argv[0]);
            return false;
        }
        if (index + 1 >= argc) {
            std::cerr << "missing value for " << argument << "\n";
            return false;
        }
        const char* value = argv[++index];
        if (argument == "--model") {
            options->model = value;
        } else if (argument == "--heap") {
            options->heap = value;
        } else if (argument == "--report") {
            options->report = value;
        } else if (argument == "--warmup") {
            if (!parse_positive(value, &options->warmup)) {
                std::cerr << "invalid --warmup\n";
                return false;
            }
        } else if (argument == "--loops") {
            if (!parse_positive(value, &options->loops) || options->loops == 0) {
                std::cerr << "--loops must be positive\n";
                return false;
            }
        } else {
            std::cerr << "unknown argument: " << argument << "\n";
            return false;
        }
    }
    if (options->model.empty()) {
        std::cerr << "--model is required\n";
        return false;
    }
    return true;
}

std::vector<std::string> heap_candidates(const Options& options) {
    if (!options.heap.empty()) {
        return {options.heap};
    }
    return {
        "/dev/dma_heap/system-uncached",
        "/dev/dma_heap/system-uncached-dma32",
        "/dev/dma_heap/system",
    };
}

std::unique_ptr<DmaBuffer> allocate_from_candidates(const Options& options, size_t size,
                                                    std::string* selected_heap,
                                                    std::string* error) {
    std::string last_error;
    for (const std::string& heap : heap_candidates(options)) {
        auto buffer = DmaBuffer::allocate(heap, size, &last_error);
        if (buffer != nullptr) {
            *selected_heap = heap;
            return buffer;
        }
    }
    if (error != nullptr) {
        *error = last_error;
    }
    return nullptr;
}

bool fill_source(DmaBuffer* source) {
    auto* bytes = static_cast<uint8_t*>(source->address());
    if (!dma_buf_sync(source->fd(), DMA_BUF_SYNC_START | DMA_BUF_SYNC_WRITE,
                      "source begin")) {
        return false;
    }
    for (int y = 0; y < kSourceHeight; ++y) {
        for (int x = 0; x < kSourceWidth; ++x) {
            uint8_t* pixel = bytes + (static_cast<size_t>(y) * kSourceWidth + x) * 3;
            pixel[0] = static_cast<uint8_t>(x * 255 / (kSourceWidth - 1));
            pixel[1] = static_cast<uint8_t>(y * 255 / (kSourceHeight - 1));
            pixel[2] = 77;
        }
    }
    return dma_buf_sync(source->fd(), DMA_BUF_SYNC_END | DMA_BUF_SYNC_WRITE,
                        "source end");
}

bool validate_letterbox(const DmaBuffer& destination, int width, int scaled_height,
                        int pad_top, int hstride) {
    auto* bytes = static_cast<const uint8_t*>(destination.address());
    if (!dma_buf_sync(destination.fd(), DMA_BUF_SYNC_START | DMA_BUF_SYNC_READ,
                      "destination begin")) {
        return false;
    }
    bool valid = true;
    const size_t row_bytes = static_cast<size_t>(hstride) * kDetectorChannels;
    for (int row = 0; row < pad_top; ++row) {
        for (int column = 0; column < width * kDetectorChannels; ++column) {
            if (bytes[static_cast<size_t>(row) * row_bytes + column] != 0) {
                valid = false;
            }
        }
    }
    for (int row = pad_top + scaled_height; row < kDetectorSize; ++row) {
        for (int column = 0; column < width * kDetectorChannels; ++column) {
            if (bytes[static_cast<size_t>(row) * row_bytes + column] != 0) {
                valid = false;
            }
        }
    }
    const size_t first_active = static_cast<size_t>(pad_top) * row_bytes;
    const bool active_nonzero = bytes[first_active] != 0 || bytes[first_active + 1] != 0 ||
                                bytes[first_active + 2] != 0;
    valid = valid && active_nonzero;
    // The source is BGR with a fixed red channel of 77 and horizontal/vertical
    // blue/green ramps. Check an interior point away from interpolation edges.
    const int sample_x = width / 4;
    const int sample_y = pad_top + scaled_height / 4;
    const size_t sample_offset = static_cast<size_t>(sample_y) * row_bytes + sample_x * 3;
    const int expected_blue = sample_x * 255 / (width - 1);
    const int expected_green = (scaled_height / 4) * 255 / (scaled_height - 1);
    const bool sample_valid = std::abs(static_cast<int>(bytes[sample_offset]) - 77) <= 8 &&
                              std::abs(static_cast<int>(bytes[sample_offset + 1]) - expected_green) <= 8 &&
                              std::abs(static_cast<int>(bytes[sample_offset + 2]) - expected_blue) <= 8;
    valid = valid && sample_valid;
    valid = dma_buf_sync(destination.fd(), DMA_BUF_SYNC_END | DMA_BUF_SYNC_READ,
                         "destination end") && valid;
    std::cout << "rga_output_check padding_top=" << pad_top
              << " active_nonzero=" << (active_nonzero ? "true" : "false")
              << " rgb_sample_valid=" << (sample_valid ? "true" : "false")
              << " result=" << (valid ? "PASS" : "FAIL") << "\n";
    return valid;
}

bool validate_outputs(
    const std::vector<std::unique_ptr<RknnOutputMemory>>& output_memories,
    const std::vector<rknn_tensor_attr>& output_attrs, int iteration,
    float* detector_first_value) {
    bool valid = output_memories.size() == 2;
    float first_value = 0.0F;
    for (size_t index = 0; index < output_memories.size(); ++index) {
        const rknn_tensor_mem* memory = output_memories[index]->get();
        if (iteration == 0) {
            std::cout << "rknn_output_runtime index=" << index
                      << " buf=" << (memory == nullptr ? nullptr : memory->virt_addr)
                      << " size=" << (memory == nullptr ? 0 : memory->size) << "\n";
        }
        const size_t required_bytes = static_cast<size_t>(output_attrs[index].n_elems) *
                                      sizeof(float);
        if (memory == nullptr || memory->virt_addr == nullptr ||
            memory->size < required_bytes) {
            if (iteration == 0) {
                std::cout << "rknn_output_runtime_invalid index=" << index << "\n";
            }
            valid = false;
            continue;
        }
        const auto* values = static_cast<const float*>(memory->virt_addr);
        const size_t count = output_attrs[index].n_elems;
        if (index == 0) {
            first_value = values[0];
            *detector_first_value = first_value;
        }
        for (size_t value_index = 0; value_index < count; ++value_index) {
            if (!std::isfinite(values[value_index])) {
                if (iteration == 0) {
                    std::cout << "rknn_output_runtime_nonfinite index=" << index
                              << " value_index=" << value_index << "\n";
                }
                valid = false;
                break;
            }
        }
    }
    if (iteration == 0) {
        std::cout << "rknn_output_check count=" << output_memories.size()
                  << " first_value=" << first_value
                  << " result=" << (valid ? "PASS" : "FAIL") << "\n";
    }
    return valid;
}

bool check_detector_contract(rknn_context context, rknn_tensor_attr* input_attr,
                             rknn_input_output_num* io_num,
                             std::vector<rknn_tensor_attr>* output_attrs) {
    output_attrs->clear();
    *io_num = {};
    int result = rknn_query(context, RKNN_QUERY_IN_OUT_NUM, io_num, sizeof(*io_num));
    if (result != RKNN_SUCC) {
        std::cerr << "stage=rknn_query_io return=" << result << "\n";
        return false;
    }
    if (io_num->n_input != 1 || io_num->n_output != 2) {
        std::cerr << "stage=rknn_contract io=" << io_num->n_input << "/"
                  << io_num->n_output << " expected=1/2\n";
        return false;
    }
    *input_attr = {};
    input_attr->index = 0;
    result = rknn_query(context, RKNN_QUERY_INPUT_ATTR, input_attr, sizeof(*input_attr));
    if (result != RKNN_SUCC) {
        std::cerr << "stage=rknn_query_input return=" << result << "\n";
        return false;
    }
    std::cout << "rknn_input name=" << input_attr->name
              << " fmt=" << static_cast<int>(input_attr->fmt)
              << " type=" << static_cast<int>(input_attr->type)
              << " dims=";
    for (uint32_t index = 0; index < input_attr->n_dims; ++index) {
        std::cout << (index == 0 ? "" : "x") << input_attr->dims[index];
    }
    std::cout << " w_stride=" << input_attr->w_stride
              << " h_stride=" << input_attr->h_stride
              << " size=" << input_attr->size
              << " size_with_stride=" << input_attr->size_with_stride << "\n";

    const bool valid = input_attr->n_dims == 4 && input_attr->dims[0] == 1 &&
                       input_attr->dims[1] == kDetectorSize &&
                       input_attr->dims[2] == kDetectorSize &&
                       input_attr->dims[3] == kDetectorChannels &&
                       input_attr->fmt == RKNN_TENSOR_NHWC &&
                       (input_attr->type == RKNN_TENSOR_UINT8 ||
                        input_attr->type == RKNN_TENSOR_FLOAT16);
    if (!valid) {
        std::cerr << "stage=rknn_contract input does not match the verified NHWC 192x192 model shape\n";
        return false;
    }
    if (input_attr->type != RKNN_TENSOR_UINT8) {
        std::cout << "rknn_input_external_override queried_type="
                  << static_cast<int>(input_attr->type)
                  << " bound_type=UINT8 pass_through=false runtime_conversion=true\n";
    }

    for (uint32_t index = 0; index < io_num->n_output; ++index) {
        rknn_tensor_attr output_attr{};
        output_attr.index = index;
        result = rknn_query(context, RKNN_QUERY_OUTPUT_ATTR, &output_attr,
                            sizeof(output_attr));
        if (result != RKNN_SUCC) {
            std::cerr << "stage=rknn_query_output index=" << index
                      << " return=" << result << "\n";
            return false;
        }
        std::cout << "rknn_output index=" << index << " name=" << output_attr.name
                  << " dims=";
        for (uint32_t dim = 0; dim < output_attr.n_dims; ++dim) {
            std::cout << (dim == 0 ? "" : "x") << output_attr.dims[dim];
        }
        std::cout << " type=" << static_cast<int>(output_attr.type)
                  << " size=" << output_attr.size << "\n";
        const bool expected = output_attr.n_dims == 3 &&
                              output_attr.dims[0] == 1 &&
                              output_attr.dims[1] == 2016 &&
                              output_attr.dims[2] == (index == 0 ? 18U : 1U) &&
                              output_attr.n_elems == 2016U * (index == 0 ? 18U : 1U) &&
                              (output_attr.type == RKNN_TENSOR_FLOAT16 ||
                               output_attr.type == RKNN_TENSOR_FLOAT32);
        if (!expected) {
            std::cerr << "stage=rknn_contract unexpected output index=" << index << "\n";
            return false;
        }
        output_attrs->push_back(output_attr);
    }
    return true;
}

bool run_rga(rga_buffer_handle_t source_handle,
             rga_buffer_handle_t resized_handle, rga_buffer_handle_t destination_handle,
             int scaled_width, int scaled_height, int pad_top, int destination_wstride,
             int destination_hstride) {
    auto source_buffer = wrapbuffer_handle(source_handle, kSourceWidth, kSourceHeight,
                                           RK_FORMAT_BGR_888, kSourceWidth, kSourceHeight);
    auto resized_buffer = wrapbuffer_handle(resized_handle, scaled_width, scaled_height,
                                            RK_FORMAT_RGB_888, scaled_width, scaled_height);
    auto destination_buffer = wrapbuffer_handle(destination_handle, kDetectorSize,
                                                kDetectorSize, RK_FORMAT_RGB_888,
                                                destination_wstride, destination_hstride);
    const im_rect source_rect{0, 0, kSourceWidth, kSourceHeight};
    const im_rect resized_rect{0, 0, scaled_width, scaled_height};
    const im_rect destination_rect{0, pad_top, scaled_width, scaled_height};

    IM_STATUS status = imcheck(source_buffer, resized_buffer, source_rect, resized_rect);
    if (!rga_ok(status)) {
        std::cerr << "stage=rga_imcheck_resize " << rga_status("imcheck", status) << "\n";
        return false;
    }
    status = imresize(source_buffer, resized_buffer, 0, 0, INTER_LINEAR, 1);
    if (!rga_ok(status)) {
        std::cerr << "stage=rga_resize " << rga_status("imresize", status) << "\n";
        return false;
    }

    status = imcheck(resized_buffer, destination_buffer, resized_rect, destination_rect);
    if (!rga_ok(status)) {
        std::cerr << "stage=rga_imcheck_letterbox " << rga_status("imcheck", status) << "\n";
        return false;
    }
    status = imfill(destination_buffer, im_rect{0, 0, kDetectorSize, kDetectorSize}, 0, 1);
    if (!rga_ok(status)) {
        std::cerr << "stage=rga_fill " << rga_status("imfill", status) << "\n";
        return false;
    }

    rga_buffer_t pattern_buffer{};
    status = improcess(resized_buffer, destination_buffer, pattern_buffer,
                       resized_rect, destination_rect, im_rect{0, 0, 0, 0},
                       -1, nullptr, nullptr, 0);
    if (!rga_ok(status)) {
        std::cerr << "stage=rga_letterbox " << rga_status("improcess", status) << "\n";
        return false;
    }
    // Keep CPU access out of the RGA -> RKNN handoff.  The destination is
    // validated after rknn_run so the probe does not insert a CPU cache-domain
    // transition between the two device consumers.
    return true;
}

int run_probe(const Options& options) {
    struct stat model_stat {};
    if (stat(options.model.c_str(), &model_stat) != 0) {
        std::cerr << "stage=model_stat path=" << options.model << " error="
                  << std::strerror(errno) << "\n";
        return 2;
    }
    std::cout << "probe=hand_dmabuf_rga_rknn\n"
              << "model=" << options.model << "\n"
              << "expected_model_sha256=" << kExpectedDetectorSha256 << "\n"
              << "model_size=" << model_stat.st_size << "\n"
              << "model_sha256=";
    std::string model_sha256;
    std::string model_hash_error;
    if (!sha256_file(options.model, &model_sha256, &model_hash_error)) {
        std::cerr << "stage=model_sha256 error=" << model_hash_error << "\n";
        return 3;
    }
    std::cout << model_sha256 << "\n";
    if (model_sha256 != kExpectedDetectorSha256) {
        std::cerr << "stage=model_sha256_mismatch expected=" << kExpectedDetectorSha256
                  << " actual=" << model_sha256 << "\n";
        return 3;
    }
    std::cout << "rga_header_check=";
    const IM_STATUS header_status = imcheckHeader();
    std::cout << static_cast<int>(header_status) << "\n";
    if (!rga_ok(header_status)) {
        std::cerr << "stage=rga_header " << rga_status("imcheckHeader", header_status)
                  << "\n";
        return 3;
    }
    const char* rga_version = querystring(RGA_VERSION);
    std::string rga_version_text = rga_version == nullptr ? "unknown" : rga_version;
    for (char& character : rga_version_text) {
        if (character == '\n' || character == '\r') {
            character = ' ';
        }
    }
    std::cout << "rga_version=" << rga_version_text << "\n";

    RknnContext rknn;
    const int init_result = rknn_init(rknn.out(), const_cast<char*>(options.model.c_str()), 0,
                                      0, nullptr);
    if (init_result != RKNN_SUCC) {
        std::cerr << "stage=rknn_init return=" << init_result << "\n";
        return 4;
    }
    rknn_sdk_version sdk_version{};
    std::string rknn_api_version_text = "unknown";
    std::string rknn_driver_version_text = "unknown";
    const int version_result = rknn_query(rknn.get(), RKNN_QUERY_SDK_VERSION, &sdk_version,
                                          sizeof(sdk_version));
    if (version_result == RKNN_SUCC) {
        rknn_api_version_text = sdk_version.api_version;
        rknn_driver_version_text = sdk_version.drv_version;
        std::cout << "rknn_api_version=" << sdk_version.api_version
                  << " rknn_driver_version=" << sdk_version.drv_version << "\n";
    } else {
        std::cerr << "warning: stage=rknn_query_sdk return=" << version_result << "\n";
    }

    rknn_tensor_attr input_attr{};
    rknn_input_output_num io_num{};
    std::vector<rknn_tensor_attr> output_attrs;
    if (!check_detector_contract(rknn.get(), &input_attr, &io_num, &output_attrs)) {
        return 5;
    }
    const int destination_wstride = input_attr.w_stride == 0
                                        ? kDetectorSize
                                        : static_cast<int>(input_attr.w_stride);
    const int destination_hstride = input_attr.h_stride == 0
                                        ? kDetectorSize
                                        : static_cast<int>(input_attr.h_stride);
    const size_t destination_size = std::max(
        static_cast<size_t>(input_attr.size_with_stride),
        static_cast<size_t>(destination_wstride) * destination_hstride * kDetectorChannels);
    const double scale = std::min(
        static_cast<double>(kDetectorSize) / kSourceWidth,
        static_cast<double>(kDetectorSize) / kSourceHeight);
    const int scaled_width = std::max(1, static_cast<int>(std::round(kSourceWidth * scale)));
    const int scaled_height = std::max(1, static_cast<int>(std::round(kSourceHeight * scale)));
    const int pad_top = (kDetectorSize - scaled_height) / 2;
    const size_t source_size = static_cast<size_t>(kSourceWidth) * kSourceHeight * 3;
    const size_t resized_size = static_cast<size_t>(scaled_width) * scaled_height * 3;

    std::string heap;
    std::string allocation_error;
    auto source = allocate_from_candidates(options, source_size, &heap, &allocation_error);
    if (source == nullptr) {
        std::cerr << "stage=dma_heap_source error=" << allocation_error << "\n";
        return 6;
    }
    auto resized = DmaBuffer::allocate(heap, resized_size, &allocation_error);
    if (resized == nullptr) {
        std::cerr << "stage=dma_heap_resized heap=" << heap
                  << " error=" << allocation_error << "\n";
        return 6;
    }
    auto destination = DmaBuffer::allocate(heap, destination_size, &allocation_error);
    if (destination == nullptr) {
        std::cerr << "stage=dma_heap_destination heap=" << heap
                  << " error=" << allocation_error << "\n";
        return 6;
    }
    std::cout << "dma_heap=" << heap << " source_fd=" << source->fd()
              << " resized_fd=" << resized->fd() << " destination_fd=" << destination->fd()
              << " source_size=" << source->size() << " resized_size=" << resized->size()
              << " destination_size=" << destination->size() << "\n";
    if (!fill_source(source.get())) {
        std::cerr << "stage=dma_sync_source\n";
        return 18;
    }

    std::memset(resized->address(), 0, resized->size());
    if (!dma_buf_sync(destination->fd(), DMA_BUF_SYNC_START | DMA_BUF_SYNC_WRITE,
                      "destination clear begin")) {
        std::cerr << "stage=dma_sync_destination_begin\n";
        return 19;
    }
    std::memset(destination->address(), 0, destination->size());
    if (!dma_buf_sync(destination->fd(), DMA_BUF_SYNC_END | DMA_BUF_SYNC_WRITE,
                      "destination clear end")) {
        std::cerr << "stage=dma_sync_destination_end\n";
        return 20;
    }

    RgaImport source_import(importbuffer_fd(source->fd(), static_cast<int>(source->size())));
    RgaImport resized_import(importbuffer_fd(resized->fd(), static_cast<int>(resized->size())));
    RgaImport destination_import(
        importbuffer_fd(destination->fd(), static_cast<int>(destination->size())));
    if (source_import.handle() == 0 || resized_import.handle() == 0 ||
        destination_import.handle() == 0) {
        std::cerr << "stage=rga_import source=" << source_import.handle()
                  << " resized=" << resized_import.handle()
                  << " destination=" << destination_import.handle() << "\n";
        return 7;
    }
    std::cout << "rga_fd_handoff destination_fd=" << destination->fd()
              << " destination_import_handle=" << destination_import.handle() << "\n";

    RknnInputMemory input_memory;
    rknn_tensor_attr bind_attr = input_attr;
    bind_attr.type = RKNN_TENSOR_UINT8;
    bind_attr.fmt = RKNN_TENSOR_NHWC;
    bind_attr.pass_through = 0;
    bind_attr.h_stride = destination_hstride;
    rknn_tensor_mem* created_memory = rknn_create_mem_from_fd(
        rknn.get(), destination->fd(), destination->address(),
        static_cast<uint32_t>(destination->size()), 0);
    if (created_memory == nullptr) {
        std::cerr << "stage=rknn_create_mem_from_fd fd=" << destination->fd() << "\n";
        return 8;
    }
    input_memory.reset(rknn.get(), created_memory);
    std::cout << "rknn_input_memory mode=dmabuf_fd destination_fd=" << destination->fd()
              << " tensor_fd=" << created_memory->fd
              << " tensor_size=" << created_memory->size << "\n";
    if (created_memory->fd != destination->fd()) {
        std::cerr << "stage=rknn_fd_identity expected=" << destination->fd()
                  << " actual=" << created_memory->fd << "\n";
        return 9;
    }
    const int bind_result = rknn_set_io_mem(rknn.get(), created_memory, &bind_attr);
    if (bind_result != RKNN_SUCC) {
        std::cerr << "stage=rknn_set_io_mem fd=" << destination->fd()
                  << " return=" << bind_result << "\n";
        return 10;
    }

    std::vector<std::unique_ptr<RknnOutputMemory>> output_memories;
    output_memories.reserve(io_num.n_output);
    for (uint32_t index = 0; index < io_num.n_output; ++index) {
        rknn_tensor_attr output_attr = output_attrs[index];
        output_attr.type = RKNN_TENSOR_FLOAT32;
        rknn_tensor_mem* output_memory = rknn_create_mem(
            rknn.get(), output_attr.n_elems * sizeof(float));
        if (output_memory == nullptr) {
            std::cerr << "stage=rknn_create_output_memory index=" << index << "\n";
            return 15;
        }
        auto holder = std::make_unique<RknnOutputMemory>();
        holder->reset(rknn.get(), output_memory);
        const int output_bind_result = rknn_set_io_mem(
            rknn.get(), output_memory, &output_attr);
        if (output_bind_result != RKNN_SUCC) {
            std::cerr << "stage=rknn_set_output_mem index=" << index
                      << " return=" << output_bind_result << "\n";
            return 16;
        }
        output_memories.push_back(std::move(holder));
    }

    const int total_iterations = options.warmup + options.loops;
    int successful = 0;
    float detector_first_value = 0.0F;
    for (int iteration = 0; iteration < total_iterations; ++iteration) {
        if (!run_rga(source_import.handle(),
                     resized_import.handle(), destination_import.handle(), scaled_width,
                     scaled_height, pad_top, destination_wstride, destination_hstride)) {
            std::cerr << "stage=rga_pipeline iteration=" << iteration << "\n";
            return 11;
        }
        const int run_result = rknn_run(rknn.get(), nullptr);
        if (run_result != RKNN_SUCC) {
            std::cerr << "stage=rknn_run iteration=" << iteration
                      << " return=" << run_result << "\n";
            return 12;
        }
        if (!validate_outputs(output_memories, output_attrs, iteration,
                              &detector_first_value)) {
            return 13;
        }
        if (!validate_letterbox(*destination, kDetectorSize, scaled_height, pad_top,
                                destination_hstride)) {
            return 17;
        }
        ++successful;
    }
    if (!options.report.empty()) {
        std::ofstream report(options.report);
        if (!report) {
            std::cerr << "stage=report_open path=" << options.report << "\n";
            return 14;
        }
        report << "model=" << options.model << "\n"
               << "expected_model_sha256=" << kExpectedDetectorSha256 << "\n"
               << "model_sha256=" << model_sha256 << "\n"
               << "model_size=" << model_stat.st_size << "\n"
               << "dma_heap=" << heap << "\n"
               << "source_fd=" << source->fd() << "\n"
               << "source_size=" << source->size() << "\n"
               << "source_geometry=640x480x3\n"
               << "source_stride_pixels=" << kSourceWidth << "\n"
               << "resized_fd=" << resized->fd() << "\n"
               << "resized_size=" << resized->size() << "\n"
               << "resized_geometry=" << scaled_width << "x" << scaled_height << "x3\n"
               << "destination_fd=" << destination->fd() << "\n"
               << "destination_size=" << destination->size() << "\n"
               << "destination_geometry=192x192x3\n"
               << "destination_wstride_pixels=" << destination_wstride << "\n"
               << "destination_hstride_pixels=" << destination_hstride << "\n"
               << "letterbox_pad_top=" << pad_top << "\n"
               << "rga_api_version=" << rga_version_text << "\n"
               << "rknn_api_version=" << rknn_api_version_text << "\n"
               << "rknn_driver_version=" << rknn_driver_version_text << "\n"
               << "input_model_dims=" << tensor_dims(input_attr) << "\n"
               << "input_model_type=" << static_cast<int>(input_attr.type) << "\n"
               << "input_model_format=" << static_cast<int>(input_attr.fmt) << "\n"
               << "input_bound_type=UINT8\n"
               << "input_bound_format=NHWC\n"
               << "input_pass_through=false\n"
               << "input_tensor_fd=" << created_memory->fd << "\n"
               << "rknn_set_io_mem_return=0\n"
               << "rknn_output_bind_return=0\n"
               << "rknn_run_return=0\n"
               << "rga_output_validation=PASS\n"
               << "rknn_output_validation=PASS\n"
               << "detector_first_value=" << detector_first_value << "\n"
               << "cleanup=raii_reverse_order\n"
               << "output_count=" << output_attrs.size() << "\n";
        for (size_t index = 0; index < output_attrs.size(); ++index) {
            report << "output_" << index << "_name=" << output_attrs[index].name << "\n"
                   << "output_" << index << "_dims=" << tensor_dims(output_attrs[index])
                   << "\n"
                   << "output_" << index << "_type="
                   << static_cast<int>(output_attrs[index].type) << "\n"
                   << "output_" << index << "_n_elems=" << output_attrs[index].n_elems
                   << "\n";
        }
        report
               << "warmup=" << options.warmup << "\n"
               << "loops=" << options.loops << "\n"
               << "successful=" << successful << "\n"
               << "no_numpy_input=true\n"
               << "direct_rknn_c_api=true\n"
               << "result=PASS\n";
        report.flush();
        if (!report) {
            std::cerr << "stage=report_write path=" << options.report << "\n";
            return 14;
        }
    }
    std::cout << "result=PASS warmup=" << options.warmup << " loops=" << options.loops
              << " successful=" << successful << " destination_fd=" << destination->fd()
              << " no_numpy_input=true direct_rknn_c_api=true\n";
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    Options options;
    if (!parse_options(argc, argv, &options)) {
        return 2;
    }
    return run_probe(options);
}
