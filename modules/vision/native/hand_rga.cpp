// Optional RGA bridge for the hand palm preprocessor.
//
// The public interface deliberately uses plain pointers and scalar arguments.
// This keeps the Python boundary independent of librga's C++ structs and makes
// it explicit that this helper uses virtual-address buffers only.  It does not
// import dma-bufs or bind an RGA buffer to an RKNN input.

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>

#include <rga/im2d.h>

namespace {

thread_local char g_last_error[256] = "";

void clear_error() {
    g_last_error[0] = '\0';
}

int fail(const char* message) {
    if (message == nullptr) {
        message = "unknown RGA error";
    }
    std::snprintf(g_last_error, sizeof(g_last_error), "%s", message);
    return -1;
}

int fail_status(const char* operation, IM_STATUS status) {
    const char* detail = imStrError_t(status);
    if (detail == nullptr) {
        detail = "unknown status";
    }
    std::snprintf(g_last_error, sizeof(g_last_error), "%s failed (%d): %s",
                  operation, static_cast<int>(status), detail);
    return -1;
}

bool valid_image_args(const uint8_t* src, int src_width, int src_height,
                      int src_stride, uint8_t* dst, int dst_size,
                      int dst_stride) {
    if (src == nullptr || dst == nullptr || src_width <= 0 ||
        src_height <= 0 || dst_size <= 0 || src_stride < src_width * 3 ||
        dst_stride < dst_size * 3 || (src_stride % 3) != 0 ||
        (dst_stride % 3) != 0) {
        fail("invalid image dimensions, stride or buffer");
        return false;
    }
    return true;
}

}  // namespace

extern "C" {

int marsdog_hand_rga_abi_version() {
    return 1;
}

const char* marsdog_hand_rga_last_error() {
    return g_last_error;
}

// Resize a BGR888 image into an RGB888 square using RGA.  The destination is
// synchronously filled with black and the resized image is written into its
// centered letterbox rectangle.  scaled_* and pad_* return the exact geometry
// used by RGA, which the caller can use for inverse coordinate mapping.
int marsdog_hand_rga_letterbox_bgr_to_rgb(
    const uint8_t* src, int src_width, int src_height, int src_stride,
    uint8_t* dst, int dst_size, int dst_stride, int scaled_width,
    int scaled_height, int pad_left, int pad_top, int pad_value,
    int* out_scaled_width, int* out_scaled_height, int* out_pad_left,
    int* out_pad_top) {
    clear_error();
    if (!valid_image_args(src, src_width, src_height, src_stride, dst,
                          dst_size, dst_stride)) {
        return -1;
    }
    if (scaled_width <= 0 || scaled_height <= 0 || pad_left < 0 ||
        pad_top < 0 || scaled_width + pad_left > dst_size ||
        scaled_height + pad_top > dst_size) {
        return fail("invalid letterbox geometry");
    }
    // RGA's color-fill encoding is format-dependent.  The hand model uses a
    // black border, so reject other values rather than silently producing a
    // different color on one RGA generation.
    if (pad_value != 0) {
        return fail("RGA letterbox supports only black padding");
    }

    const int src_wstride = src_stride / 3;
    const int dst_wstride = dst_stride / 3;
    rga_buffer_t src_buffer = wrapbuffer_virtualaddr_t(
        const_cast<uint8_t*>(src), src_width, src_height, src_wstride,
        src_height, RK_FORMAT_BGR_888);
    // The RK3588 board can schedule imfill through an RGA2 core whose MMU
    // rejects high virtual addresses after RKNN has initialized.  Padding is
    // only a 192x192 CPU operation, so keep it out of the RGA job.  This also
    // avoids passing an interior pointer plus the parent hstride to librga:
    // the native bridge now maps only complete, independently allocated image
    // extents.
    std::memset(dst, pad_value, static_cast<size_t>(dst_stride) * dst_size);

    // Keep the resize destination at address zero of its own allocation.  A
    // shifted ROI pointer with the parent hstride can make librga validate an
    // extent beyond the object actually supplied by the Python caller.
    constexpr int kRgaPixelAlignment = 16;
    const int resized_wstride =
        ((scaled_width + kRgaPixelAlignment - 1) / kRgaPixelAlignment) *
        kRgaPixelAlignment;
    std::vector<uint8_t> resized(
        static_cast<size_t>(resized_wstride) * scaled_height * 3);
    rga_buffer_t resized_buffer = wrapbuffer_virtualaddr_t(
        resized.data(), scaled_width, scaled_height, resized_wstride,
        scaled_height, RK_FORMAT_RGB_888);
    // Select RGA3 explicitly.  RGA2 on this board does not support the high
    // virtual-address pages used by Python/RKNN processes.  The setting is
    // process-wide in librga and harmless when repeated for synchronous calls.
    IM_STATUS status = imconfig(IM_CONFIG_SCHEDULER_CORE,
                                IM_SCHEDULER_RGA3_DEFAULT);
    if (status != IM_STATUS_SUCCESS && status != IM_STATUS_NOERROR) {
        return fail_status("imconfig(RGA3)", status);
    }

    im_rect src_rect{0, 0, src_width, src_height};
    im_rect dst_rect{0, 0, scaled_width, scaled_height};
    status = imcheck(src_buffer, resized_buffer, src_rect, dst_rect);
    if (status != IM_STATUS_SUCCESS && status != IM_STATUS_NOERROR) {
        return fail_status("imcheck", status);
    }

    // sync=1 is intentional.  The Python caller owns the NumPy arrays and
    // may immediately pass the output to RKNN after this function returns.
    status = imresize(src_buffer, resized_buffer, 0, 0, INTER_LINEAR, 1);
    if (status != IM_STATUS_SUCCESS && status != IM_STATUS_NOERROR) {
        return fail_status("imresize", status);
    }
    for (int row = 0; row < scaled_height; ++row) {
        std::memcpy(
            dst + static_cast<size_t>(pad_top + row) * dst_stride +
                static_cast<size_t>(pad_left) * 3,
            resized.data() + static_cast<size_t>(row) * resized_wstride * 3,
            static_cast<size_t>(scaled_width) * 3);
    }
    if (out_scaled_width != nullptr) {
        *out_scaled_width = scaled_width;
    }
    if (out_scaled_height != nullptr) {
        *out_scaled_height = scaled_height;
    }
    if (out_pad_left != nullptr) {
        *out_pad_left = pad_left;
    }
    if (out_pad_top != nullptr) {
        *out_pad_top = pad_top;
    }
    return 0;
}

}  // extern "C"
