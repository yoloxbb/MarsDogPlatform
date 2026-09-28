"""Hand palm preprocessing with an optional virtual-address RGA bridge.

RGA is deliberately loaded lazily.  A workstation or a CPU-only deployment
therefore keeps the ordinary OpenCV path without importing or linking against
RGA.  The native bridge performs synchronous virtual-address operations only;
it does not import dma-bufs or bind memory to RKNN.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import cv2
import numpy as np


class RgaError(RuntimeError):
    """Raised when the explicitly selected RGA preprocessor cannot run."""


class RgaUnavailable(RgaError):
    """Raised when RGA mode was requested but its native helper is missing."""


@dataclass(frozen=True)
class LetterboxGeometry:
    """Geometry used to map model coordinates back to the selected view."""

    source_width: int
    source_height: int
    target_size: int
    scaled_width: int
    scaled_height: int
    pad_left: int
    pad_top: int
    scale: float


_RGB_CHANNELS: Final[int] = 3
_DEFAULT_SIZE: Final[int] = 192
_RGA_WIDTH_ALIGNMENT: Final[int] = 16
_MODE_NAMES = frozenset(("auto", "cpu", "rga"))


def _geometry(width: int, height: int, target_size: int) -> LetterboxGeometry:
    if width <= 0 or height <= 0:
        raise ValueError(f"frame dimensions must be positive, got {width}x{height}")
    if target_size <= 0:
        raise ValueError(f"target size must be positive, got {target_size}")
    scale = min(target_size / float(width), target_size / float(height))
    # Keep this convention shared with the RKNN decoder.  Python's round gives
    # deterministic integer dimensions for odd image sizes and half values.
    scaled_width = max(1, int(round(width * scale)))
    scaled_height = max(1, int(round(height * scale)))
    pad_left = (target_size - scaled_width) // 2
    pad_top = (target_size - scaled_height) // 2
    return LetterboxGeometry(
        source_width=width,
        source_height=height,
        target_size=target_size,
        scaled_width=scaled_width,
        scaled_height=scaled_height,
        pad_left=pad_left,
        pad_top=pad_top,
        scale=scale,
    )


def _validate_frame(frame_bgr: np.ndarray) -> np.ndarray:
    frame = np.asarray(frame_bgr)
    if frame.ndim != 3 or frame.shape[2] != _RGB_CHANNELS:
        raise ValueError(f"expected HxWx3 BGR image, got shape {frame.shape}")
    if frame.dtype != np.uint8:
        raise TypeError(f"expected uint8 BGR image, got {frame.dtype}")
    if frame.shape[0] <= 0 or frame.shape[1] <= 0:
        raise ValueError(f"frame dimensions must be positive, got {frame.shape}")
    return frame


def _cpu_letterbox(frame_bgr: np.ndarray, geo: LetterboxGeometry, pad_value: int) -> np.ndarray:
    resized_bgr = cv2.resize(
        frame_bgr,
        (geo.scaled_width, geo.scaled_height),
        interpolation=cv2.INTER_LINEAR,
    )
    resized_rgb = cv2.cvtColor(resized_bgr, cv2.COLOR_BGR2RGB)
    output = np.full(
        (geo.target_size, geo.target_size, _RGB_CHANNELS),
        pad_value,
        dtype=np.uint8,
    )
    bottom = geo.pad_top + geo.scaled_height
    right = geo.pad_left + geo.scaled_width
    output[geo.pad_top:bottom, geo.pad_left:right] = resized_rgb
    return output


def _candidate_paths(library_path: str | os.PathLike[str] | None) -> list[str]:
    candidates: list[str] = []
    if library_path:
        candidates.append(os.fspath(library_path))
    env_path = os.environ.get("MARSDOG_HAND_RGA_LIBRARY")
    if env_path:
        candidates.append(env_path)

    # Keep both paths for ament's symlink install: resolving __file__ points
    # back into the source tree while the native target lives under install/.
    package_dirs = [Path(__file__).parent, Path(__file__).resolve().parent]
    for package_dir in dict.fromkeys(package_dirs):
        candidates.extend(
            [
                str(package_dir / "native" / "libhand_rga.so"),
                str(package_dir / "native" / "hand_rga.so"),
            ]
        )
    # With ``colcon --symlink-install`` the Python module resolves to the
    # source tree, while compiled targets stay below the package's install
    # prefix.  Search those ament prefixes explicitly so a normal sourced ROS
    # workspace can load the bridge without a private environment override.
    for prefix_value in os.environ.get("AMENT_PREFIX_PATH", "").split(os.pathsep):
        if not prefix_value:
            continue
        prefix = Path(prefix_value)
        patterns = (
            "local/lib/python*/dist-packages/marsdog_vision_interaction/utils/native/libhand_rga.so",
            "lib/python*/site-packages/marsdog_vision_interaction/utils/native/libhand_rga.so",
        )
        for pattern in patterns:
            candidates.extend(str(path) for path in prefix.glob(pattern))
    candidates.extend(
        [
            "/usr/local/lib/libhand_rga.so",
            "/usr/lib/aarch64-linux-gnu/libhand_rga.so",
        ]
    )
    found = ctypes.util.find_library("hand_rga")
    if found:
        candidates.append(found)
    # Preserve order while avoiding repeated dlopen attempts.
    return list(dict.fromkeys(candidates))


class RgaPreprocessor:
    """Letterbox BGR frames into RGB model tensors.

    Args:
        library_path: Optional path to the project ``libhand_rga.so`` helper.
        mode: ``"cpu"`` forces the OpenCV reference, ``"rga"`` requires the
            helper, and ``"auto"`` uses RGA when the helper is installed and
            otherwise selects CPU.  The default is ``"rga"`` so a caller that
            explicitly requests the hardware path cannot accidentally report
            CPU preprocessing as accelerated.  A runtime RGA error is
            surfaced; auto mode does not silently claim acceleration after a
            failed RGA operation.
        pad_value: RGB border value.  RGA currently supports black padding,
            matching the palm model profile.  CPU mode accepts any scalar.
    """

    def __init__(
        self,
        library_path: str | os.PathLike[str] | None = None,
        *,
        mode: str = "rga",
        pad_value: int = 0,
    ) -> None:
        if mode not in _MODE_NAMES:
            raise ValueError(f"mode must be one of {sorted(_MODE_NAMES)}, got {mode!r}")
        if not isinstance(pad_value, (int, np.integer)) or not 0 <= int(pad_value) <= 255:
            raise ValueError(f"pad_value must be an integer in [0, 255], got {pad_value!r}")
        self.requested_mode = mode
        self.actual_mode = "closed"
        self.pad_value = int(pad_value)
        self.last_geometry: LetterboxGeometry | None = None
        self._library: ctypes.CDLL | None = None
        self._rga_call = None
        self._last_error_call = None
        self._output: np.ndarray | None = None
        self._source: np.ndarray | None = None

        if mode == "cpu":
            self.actual_mode = "cpu"
            return

        for candidate in _candidate_paths(library_path):
            try:
                library = ctypes.CDLL(candidate)
            except OSError:
                continue
            try:
                abi = library.marsdog_hand_rga_abi_version
                abi.restype = ctypes.c_int
                if abi() != 1:
                    continue
                call = library.marsdog_hand_rga_letterbox_bgr_to_rgb
                call.argtypes = [
                    ctypes.POINTER(ctypes.c_uint8),
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.POINTER(ctypes.c_uint8),
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_int),
                ]
                call.restype = ctypes.c_int
                error_call = library.marsdog_hand_rga_last_error
                error_call.restype = ctypes.c_char_p
            except (AttributeError, TypeError):
                continue
            self._library = library
            self._rga_call = call
            self._last_error_call = error_call
            self.actual_mode = "rga"
            break

        if self.actual_mode != "rga":
            if mode == "rga":
                searched = ", ".join(_candidate_paths(library_path))
                raise RgaUnavailable(f"libhand_rga.so not found; searched: {searched}")
            self.actual_mode = "cpu"

    @classmethod
    def available(cls, library_path: str | os.PathLike[str] | None = None) -> bool:
        """Return whether a compatible bridge can be loaded without opening RGA."""
        try:
            instance = cls(library_path, mode="rga")
        except RgaError:
            return False
        instance.close()
        return True

    @property
    def is_rga(self) -> bool:
        return self.actual_mode == "rga"

    def letterbox(self, frame_bgr: np.ndarray, size: int = _DEFAULT_SIZE) -> np.ndarray:
        """Return an RGB uint8 square and save its inverse-mapping geometry."""
        if self.actual_mode == "closed":
            raise RuntimeError("RgaPreprocessor is closed")
        frame = _validate_frame(frame_bgr)
        geo = _geometry(frame.shape[1], frame.shape[0], int(size))
        self.last_geometry = geo
        if self.actual_mode == "cpu":
            return _cpu_letterbox(frame, geo, self.pad_value)

        # RGA needs an addressable row stride.  A camera view with a crop or a
        # negative/column stride is copied once into a contiguous staging view;
        # no memory is imported into RKNN and the native call is synchronous.
        source = self._ensure_source(frame)
        output = self._ensure_output(geo.target_size)
        src_ptr = source.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8))
        dst_ptr = output.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8))
        out_w = ctypes.c_int()
        out_h = ctypes.c_int()
        out_left = ctypes.c_int()
        out_top = ctypes.c_int()
        result = self._rga_call(
            src_ptr,
            int(frame.shape[1]),
            int(frame.shape[0]),
            int(source.strides[0]),
            dst_ptr,
            geo.target_size,
            int(output.strides[0]),
            geo.scaled_width,
            geo.scaled_height,
            geo.pad_left,
            geo.pad_top,
            self.pad_value,
            ctypes.byref(out_w),
            ctypes.byref(out_h),
            ctypes.byref(out_left),
            ctypes.byref(out_top),
        )
        if result != 0:
            detail = "RGA preprocessing failed"
            if self._last_error_call is not None:
                raw = self._last_error_call()
                if raw:
                    detail = raw.decode("utf-8", errors="replace")
            raise RgaError(detail)
        # Native geometry is returned for diagnostics.  The requested geometry
        # is still authoritative for normal output, but a mismatch indicates a
        # bridge bug and must not be hidden from the decoder.
        native_geo = (out_w.value, out_h.value, out_left.value, out_top.value)
        expected_geo = (geo.scaled_width, geo.scaled_height, geo.pad_left, geo.pad_top)
        if native_geo != expected_geo:
            raise RgaError(f"RGA geometry mismatch: native={native_geo}, expected={expected_geo}")
        return output

    def letterbox_with_geometry(
        self, frame_bgr: np.ndarray, size: int = _DEFAULT_SIZE
    ) -> tuple[np.ndarray, LetterboxGeometry]:
        output = self.letterbox(frame_bgr, size)
        assert self.last_geometry is not None
        return output, self.last_geometry

    # Alias used by preprocessor adapters that call all image transforms
    # ``preprocess``.
    preprocess = letterbox

    def _ensure_output(self, size: int) -> np.ndarray:
        if self._output is None or self._output.shape != (size, size, _RGB_CHANNELS):
            self._output = np.empty((size, size, _RGB_CHANNELS), dtype=np.uint8)
        return self._output

    def _ensure_source(self, frame: np.ndarray) -> np.ndarray:
        """Return a C buffer whose pixel stride satisfies RGA's 16-pixel rule."""
        height, width = frame.shape[:2]
        aligned_width = (
            (width + _RGA_WIDTH_ALIGNMENT - 1) // _RGA_WIDTH_ALIGNMENT
        ) * _RGA_WIDTH_ALIGNMENT
        if aligned_width == width and frame.flags.c_contiguous:
            return frame
        shape = (height, aligned_width, _RGB_CHANNELS)
        if self._source is None or self._source.shape != shape:
            self._source = np.empty(shape, dtype=np.uint8)
        # Replicate the edge into the alignment margin.  Some librga software
        # implementations sample the aligned stride at the right border even
        # though the active image width remains the original width; replication
        # keeps that border stable instead of introducing a black seam.
        self._source[:] = frame[:, width - 1 : width]
        self._source[:, :width] = frame
        return self._source

    def close(self) -> None:
        """Release the Python handle; repeated calls are safe."""
        self._rga_call = None
        self._last_error_call = None
        self._library = None
        self._output = None
        self._source = None
        self.actual_mode = "closed"

    def __enter__(self) -> "RgaPreprocessor":
        if self.actual_mode == "closed":
            raise RuntimeError("RgaPreprocessor is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


__all__ = [
    "LetterboxGeometry",
    "RgaError",
    "RgaPreprocessor",
    "RgaUnavailable",
]
