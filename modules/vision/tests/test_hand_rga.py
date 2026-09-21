from __future__ import annotations

import os

import numpy as np
import pytest

from marsdog_vision_interaction.utils import hand_rga
from marsdog_vision_interaction.utils.hand_rga import (
    RgaPreprocessor,
    RgaUnavailable,
    _candidate_paths,
)


def _reference(frame_bgr: np.ndarray, size: int, pad_value: int = 0) -> np.ndarray:
    import cv2

    height, width = frame_bgr.shape[:2]
    scale = min(size / float(width), size / float(height))
    scaled_width = max(1, int(round(width * scale)))
    scaled_height = max(1, int(round(height * scale)))
    left = (size - scaled_width) // 2
    top = (size - scaled_height) // 2
    resized = cv2.resize(frame_bgr, (scaled_width, scaled_height), interpolation=cv2.INTER_LINEAR)
    resized = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    expected = np.full((size, size, 3), pad_value, dtype=np.uint8)
    expected[top : top + scaled_height, left : left + scaled_width] = resized
    return expected


@pytest.mark.parametrize("shape,size", [((3, 5, 3), 7), ((479, 641, 3), 192), ((17, 13, 3), 16)])
def test_cpu_letterbox_matches_reference_for_odd_sizes(shape, size):
    frame = np.arange(np.prod(shape), dtype=np.uint8).reshape(shape)
    preprocessor = RgaPreprocessor(mode="cpu", pad_value=11)

    result, geometry = preprocessor.letterbox_with_geometry(frame, size)

    np.testing.assert_array_equal(result, _reference(frame, size, pad_value=11))
    assert result.dtype == np.uint8
    assert result.shape == (size, size, 3)
    assert geometry.source_width == shape[1]
    assert geometry.source_height == shape[0]
    assert geometry.pad_left >= 0
    assert geometry.pad_top >= 0
    preprocessor.close()


def test_non_contiguous_camera_view_is_accepted_by_cpu_path():
    source = np.arange(9 * 13 * 3, dtype=np.uint8).reshape(9, 13, 3)
    view = source[1:8:2, 2:12:2]
    assert not view.flags.c_contiguous

    result = RgaPreprocessor(mode="cpu").letterbox(view, 32)

    np.testing.assert_array_equal(result, _reference(view, 32))


def test_rga_staging_preserves_active_width():
    """Alignment padding belongs to the stride, not the active RGA image."""

    frame = np.zeros((7, 17, 3), dtype=np.uint8)
    preprocessor = RgaPreprocessor(mode="cpu")
    received: dict[str, int] = {}

    def fake_rga(
        _src,
        source_width,
        source_height,
        source_stride,
        _dst,
        _target_size,
        _destination_stride,
        scaled_width,
        scaled_height,
        pad_left,
        pad_top,
        _pad_value,
        out_width,
        out_height,
        out_left,
        out_top,
    ):
        received.update(
            width=source_width,
            height=source_height,
            stride=source_stride,
        )
        out_width._obj.value = scaled_width
        out_height._obj.value = scaled_height
        out_left._obj.value = pad_left
        out_top._obj.value = pad_top
        return 0

    preprocessor.actual_mode = "rga"
    preprocessor._rga_call = fake_rga
    preprocessor.letterbox(frame, 32)

    assert received == {"width": 17, "height": 7, "stride": 32 * 3}


def test_rga_mode_requires_a_compatible_helper(monkeypatch, tmp_path):
    monkeypatch.setattr(
        hand_rga, "_candidate_paths", lambda _path: [str(tmp_path / "missing.so")]
    )
    with pytest.raises(RgaUnavailable):
        RgaPreprocessor(library_path=tmp_path / "missing.so", mode="rga")


def test_auto_mode_without_helper_reports_cpu(monkeypatch, tmp_path):
    monkeypatch.setattr(
        hand_rga, "_candidate_paths", lambda _path: [str(tmp_path / "missing.so")]
    )
    monkeypatch.setenv("MARSDOG_HAND_RGA_LIBRARY", str(tmp_path / "missing.so"))
    preprocessor = RgaPreprocessor(mode="auto")
    assert preprocessor.actual_mode == "cpu"
    assert not preprocessor.is_rga
    preprocessor.close()
    preprocessor.close()


def test_candidate_paths_include_symlink_install_native_bridge(monkeypatch, tmp_path):
    bridge = (
        tmp_path
        / "local/lib/python3.10/dist-packages/marsdog_vision_interaction/utils/native/libhand_rga.so"
    )
    bridge.parent.mkdir(parents=True)
    bridge.touch()
    monkeypatch.setenv("AMENT_PREFIX_PATH", str(tmp_path))

    assert str(bridge) in _candidate_paths(None)


def test_validation_and_close_are_explicit():
    preprocessor = RgaPreprocessor(mode="cpu")
    with pytest.raises(ValueError):
        preprocessor.letterbox(np.zeros((10, 10), dtype=np.uint8))
    with pytest.raises(TypeError):
        preprocessor.letterbox(np.zeros((10, 10, 3), dtype=np.float32))
    preprocessor.close()
    with pytest.raises(RuntimeError):
        preprocessor.letterbox(np.zeros((10, 10, 3), dtype=np.uint8))


@pytest.mark.parametrize(
    ("shape", "non_contiguous"),
    [((479, 641), False), ((479, 641), True), ((241, 323), True)],
)
def test_rga_image_parity_when_helper_is_explicitly_requested(shape, non_contiguous):
    """Board/driver runs opt in; CPU CI must remain independent of librga."""
    library_path = os.environ.get("MARSDOG_HAND_RGA_TEST_LIBRARY")
    if not library_path:
        pytest.skip("set MARSDOG_HAND_RGA_TEST_LIBRARY for an RGA parity smoke")
    height, width = shape
    if non_contiguous:
        source = np.empty((height + 2, width + 6, 3), dtype=np.uint8)
        frame = source[1 : height + 1, 2 : width + 2]
        assert not frame.flags.c_contiguous
    else:
        frame = np.empty((height, width, 3), dtype=np.uint8)
    yy, xx = np.indices(frame.shape[:2])
    frame[:, :, 0] = np.rint(xx * 255.0 / (frame.shape[1] - 1)).astype(np.uint8)
    frame[:, :, 1] = np.rint(yy * 255.0 / (frame.shape[0] - 1)).astype(np.uint8)
    frame[:, :, 2] = np.rint((xx + yy) * 127.0 / (frame.shape[0] + frame.shape[1] - 2)).astype(
        np.uint8
    )
    cpu = RgaPreprocessor(mode="cpu").letterbox(frame, 192)
    rga = RgaPreprocessor(library_path=library_path, mode="rga").letterbox(frame, 192)
    difference = np.abs(cpu.astype(np.int16) - rga.astype(np.int16))
    # RGA and OpenCV use different fixed-point interpolation kernels.  This
    # catches channel swaps, padding drift and gross geometry errors while
    # allowing the expected small interpolation difference.
    assert float(difference.mean()) < 8.0
    assert int(difference.max()) < 64
