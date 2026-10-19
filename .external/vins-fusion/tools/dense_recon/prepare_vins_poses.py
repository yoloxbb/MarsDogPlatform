#!/usr/bin/env python3
"""Convert VINS body poses to camera poses and match them to exported images."""

from __future__ import annotations

import argparse
import bisect
import csv
import math
import re
from pathlib import Path

import cv2
import numpy as np
from path_defaults import GetOutputDirectoryValue


def GetQuaternionMatrixValue(qw: float, qx: float, qy: float, qz: float) -> np.ndarray:
    """Convert a normalized quaternion into a rotation matrix."""
    q = np.array([qw, qx, qy, qz], dtype=np.float64)
    q /= max(np.linalg.norm(q), 1e-12)
    qw, qx, qy, qz = q
    return np.array(
        [
            [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
            [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
            [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
        ],
        dtype=np.float64,
    )


def GetQuaternionValue(rotation: np.ndarray) -> np.ndarray:
    """Convert a rotation matrix into [qw, qx, qy, qz]."""
    trace = float(np.trace(rotation))
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        qw = 0.25 * s
        qx = (rotation[2, 1] - rotation[1, 2]) / s
        qy = (rotation[0, 2] - rotation[2, 0]) / s
        qz = (rotation[1, 0] - rotation[0, 1]) / s
    else:
        idx = int(np.argmax(np.diag(rotation)))
        if idx == 0:
            s = math.sqrt(1.0 + rotation[0, 0] - rotation[1, 1] - rotation[2, 2]) * 2.0
            qw = (rotation[2, 1] - rotation[1, 2]) / s
            qx = 0.25 * s
            qy = (rotation[0, 1] + rotation[1, 0]) / s
            qz = (rotation[0, 2] + rotation[2, 0]) / s
        elif idx == 1:
            s = math.sqrt(1.0 + rotation[1, 1] - rotation[0, 0] - rotation[2, 2]) * 2.0
            qw = (rotation[0, 2] - rotation[2, 0]) / s
            qx = (rotation[0, 1] + rotation[1, 0]) / s
            qy = 0.25 * s
            qz = (rotation[1, 2] + rotation[2, 1]) / s
        else:
            s = math.sqrt(1.0 + rotation[2, 2] - rotation[0, 0] - rotation[1, 1]) * 2.0
            qw = (rotation[1, 0] - rotation[0, 1]) / s
            qx = (rotation[0, 2] + rotation[2, 0]) / s
            qy = (rotation[1, 2] + rotation[2, 1]) / s
            qz = 0.25 * s
    q = np.array([qw, qx, qy, qz], dtype=np.float64)
    q /= max(np.linalg.norm(q), 1e-12)
    return q


def GetBodyCameraTransformValue(config_path: Path) -> np.ndarray:
    """Read body_T_cam0 from an OpenCV YAML config file."""
    storage = cv2.FileStorage(str(config_path), cv2.FILE_STORAGE_READ)
    matrix = storage.getNode("body_T_cam0").mat() if storage.isOpened() else None
    storage.release()
    if matrix is not None and matrix.shape == (4, 4):
        return matrix.astype(np.float64)

    text = config_path.read_text()
    match = re.search(r"body_T_cam0:.*?data:\s*\[([^\]]+)\]", text, flags=re.S)
    if not match:
        raise RuntimeError(f"Cannot read body_T_cam0 from {config_path}")
    values = [float(item) for item in re.split(r"[,\s]+", match.group(1).strip()) if item]
    if len(values) != 16:
        raise RuntimeError(f"body_T_cam0 in {config_path} has {len(values)} values, expected 16")
    return np.asarray(values, dtype=np.float64).reshape(4, 4)


def GetVinsPoseValues(vio_path: Path) -> list[dict]:
    """Read VINS vio.csv as body poses in the world frame."""
    poses = []
    with vio_path.open() as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip().rstrip(",")
            if not line:
                continue
            fields = [field.strip() for field in line.split(",") if field.strip()]
            if len(fields) < 8:
                continue
            try:
                timestamp, x, y, z, qw, qx, qy, qz = map(float, fields[:8])
            except ValueError as exc:
                raise ValueError(f"Bad VINS row {line_no}: {line}") from exc
            rotation = GetQuaternionMatrixValue(qw, qx, qy, qz)
            poses.append({"time": timestamp, "R_w_b": rotation, "t_w_b": np.array([x, y, z], dtype=np.float64)})
    poses.sort(key=lambda item: item["time"])
    if not poses:
        raise RuntimeError(f"No poses read from {vio_path}")
    return poses


def GetImageTimeValues(path: Path) -> list[tuple[float, Path]]:
    """Read image timestamps and paths produced by export_mono_images.py."""
    values = []
    with path.open() as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.split()
            values.append((float(fields[0]), Path(fields[1])))
    if not values:
        raise RuntimeError(f"No image timestamps read from {path}")
    return values


def GetNearestPoseValue(poses: list[dict], times: list[float], timestamp: float) -> tuple[dict, float]:
    """Find the nearest trajectory pose to an image timestamp."""
    idx = bisect.bisect_left(times, timestamp)
    candidates = []
    if idx < len(times):
        candidates.append(idx)
    if idx > 0:
        candidates.append(idx - 1)
    best = min(candidates, key=lambda item: abs(times[item] - timestamp))
    return poses[best], times[best] - timestamp


def ExecutePrepare(args: argparse.Namespace) -> None:
    """Create TUM camera poses and a frame manifest for plane sweep."""
    vio_path = Path(args.vio)
    image_times_path = Path(args.image_times)
    output_tum = Path(args.output_tum)
    output_frames = Path(args.output_frames)
    output_tum.parent.mkdir(parents=True, exist_ok=True)
    output_frames.parent.mkdir(parents=True, exist_ok=True)

    body_t_cam = GetBodyCameraTransformValue(Path(args.config))
    r_b_c = body_t_cam[:3, :3]
    t_b_c = body_t_cam[:3, 3]

    poses = GetVinsPoseValues(vio_path)
    pose_times = [pose["time"] for pose in poses]
    image_times = GetImageTimeValues(image_times_path)

    fractional_count = sum(abs(pose["time"] - round(pose["time"])) > 1e-6 for pose in poses[: min(len(poses), 200)])
    if fractional_count == 0:
        print("WARNING: VINS timestamps look like integer seconds. Re-run VINS with fractional timestamp output.")

    matched = []
    max_dt = 0.0
    for image_time, image_path in image_times:
        pose, delta = GetNearestPoseValue(poses, pose_times, image_time)
        abs_delta = abs(delta)
        max_dt = max(max_dt, abs_delta)
        if abs_delta > args.max_time_diff:
            continue

        r_w_c = pose["R_w_b"] @ r_b_c
        t_w_c = pose["t_w_b"] + pose["R_w_b"] @ t_b_c
        qw, qx, qy, qz = GetQuaternionValue(r_w_c)
        matched.append((image_time, image_path, pose["time"], delta, t_w_c, (qw, qx, qy, qz)))

    if not matched:
        raise RuntimeError(f"No image poses matched within {args.max_time_diff}s; max nearest dt was {max_dt:.6f}s")

    with output_tum.open("w") as tum_file, output_frames.open("w", newline="") as frames_file:
        writer = csv.writer(frames_file)
        writer.writerow(["image_time", "image_path", "pose_time", "time_delta", "tx", "ty", "tz", "qw", "qx", "qy", "qz"])
        for image_time, image_path, pose_time, delta, t_w_c, quat in matched:
            qw, qx, qy, qz = quat
            tum_file.write(
                f"{image_time:.9f} {t_w_c[0]:.9f} {t_w_c[1]:.9f} {t_w_c[2]:.9f} "
                f"{qx:.9f} {qy:.9f} {qz:.9f} {qw:.9f}\n"
            )
            writer.writerow(
                [
                    f"{image_time:.9f}",
                    str(image_path),
                    f"{pose_time:.9f}",
                    f"{delta:.9f}",
                    f"{t_w_c[0]:.9f}",
                    f"{t_w_c[1]:.9f}",
                    f"{t_w_c[2]:.9f}",
                    f"{qw:.9f}",
                    f"{qx:.9f}",
                    f"{qy:.9f}",
                    f"{qz:.9f}",
                ]
            )

    print(f"Matched {len(matched)} / {len(image_times)} images")
    print(f"Max accepted time delta: {max(abs(item[3]) for item in matched):.6f}s")
    print(f"Wrote {output_tum}")
    print(f"Wrote {output_frames}")


def GetParserValue() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    output_dir = GetOutputDirectoryValue()
    dense_recon_dir = output_dir / "dense_recon"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vio", default=str(output_dir / "vio.csv"))
    parser.add_argument("--image-times", default=str(dense_recon_dir / "image_times.txt"))
    parser.add_argument("--config", default="config/euroc/euroc_mono_imu_config.yaml")
    parser.add_argument("--output-tum", default=str(dense_recon_dir / "cam_poses_tum.txt"))
    parser.add_argument("--output-frames", default=str(dense_recon_dir / "matched_frames.csv"))
    parser.add_argument("--max-time-diff", type=float, default=0.03)
    return parser


def main() -> None:
    ExecutePrepare(GetParserValue().parse_args())


if __name__ == "__main__":
    main()
