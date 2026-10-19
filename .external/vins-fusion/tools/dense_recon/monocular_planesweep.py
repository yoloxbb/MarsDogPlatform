#!/usr/bin/env python3
"""Semi-dense monocular plane-sweep reconstruction from image poses."""

from __future__ import annotations

import argparse
import csv
import math
import struct
from pathlib import Path

import cv2
import numpy as np
from path_defaults import GetOutputDirectoryValue


def GetQuaternionMatrixValue(qw: float, qx: float, qy: float, qz: float) -> np.ndarray:
    """Convert [qw, qx, qy, qz] into a rotation matrix."""
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


def GetRotationAngleValue(r_a: np.ndarray, r_b: np.ndarray) -> float:
    """Return the relative rotation angle in degrees."""
    delta = r_a.T @ r_b
    cos_angle = np.clip((np.trace(delta) - 1.0) * 0.5, -1.0, 1.0)
    return math.degrees(math.acos(float(cos_angle)))


def GetCameraValue(camera_path: Path) -> dict:
    """Read pinhole intrinsics and distortion parameters from OpenCV YAML."""
    storage = cv2.FileStorage(str(camera_path), cv2.FILE_STORAGE_READ)
    if not storage.isOpened():
        raise RuntimeError(f"Cannot open camera file {camera_path}")
    fx = float(storage.getNode("projection_parameters").getNode("fx").real())
    fy = float(storage.getNode("projection_parameters").getNode("fy").real())
    cx = float(storage.getNode("projection_parameters").getNode("cx").real())
    cy = float(storage.getNode("projection_parameters").getNode("cy").real())
    width = int(storage.getNode("image_width").real())
    height = int(storage.getNode("image_height").real())
    distortion = storage.getNode("distortion_parameters")
    k1 = float(distortion.getNode("k1").real())
    k2 = float(distortion.getNode("k2").real())
    p1 = float(distortion.getNode("p1").real())
    p2 = float(distortion.getNode("p2").real())
    storage.release()
    return {
        "K": np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64),
        "dist": np.array([k1, k2, p1, p2], dtype=np.float64),
        "width": width,
        "height": height,
    }


def GetFrameValues(frames_path: Path) -> list[dict]:
    """Read the matched frame manifest from prepare_vins_poses.py."""
    frames = []
    with frames_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rotation = GetQuaternionMatrixValue(
                float(row["qw"]), float(row["qx"]), float(row["qy"]), float(row["qz"])
            )
            frames.append(
                {
                    "time": float(row["image_time"]),
                    "image_path": Path(row["image_path"]),
                    "R_w_c": rotation,
                    "t_w_c": np.array([float(row["tx"]), float(row["ty"]), float(row["tz"])], dtype=np.float64),
                }
            )
    if not frames:
        raise RuntimeError(f"No frames read from {frames_path}")
    return frames


def GetImageValue(path: Path, camera: dict, undistort: bool) -> np.ndarray:
    """Load an image as grayscale float32 and optionally undistort it."""
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        raise RuntimeError(f"Cannot read image {path}")
    if undistort and np.linalg.norm(camera["dist"]) > 0:
        image = cv2.undistort(image, camera["K"], camera["dist"])
    return image.astype(np.float32)


def GetReferenceIndicesValue(frames: list[dict], args: argparse.Namespace) -> list[int]:
    """Select reference keyframes by translation and rotation thresholds."""
    indices = []
    last_idx = None
    for idx, frame in enumerate(frames):
        if idx % args.ref_stride != 0:
            continue
        if last_idx is None:
            indices.append(idx)
            last_idx = idx
        else:
            baseline = np.linalg.norm(frame["t_w_c"] - frames[last_idx]["t_w_c"])
            angle = GetRotationAngleValue(frames[last_idx]["R_w_c"], frame["R_w_c"])
            if baseline >= args.keyframe_translation and angle <= args.keyframe_max_rotation:
                indices.append(idx)
                last_idx = idx
        if args.max_ref_frames and len(indices) >= args.max_ref_frames:
            break
    return indices


def GetSourceIndicesValue(frames: list[dict], ref_idx: int, args: argparse.Namespace) -> list[int]:
    """Choose nearby source frames with enough baseline for one reference frame."""
    ref = frames[ref_idx]
    candidates = []
    start = max(0, ref_idx - args.source_search_window)
    end = min(len(frames), ref_idx + args.source_search_window + 1)
    for idx in range(start, end):
        if idx == ref_idx:
            continue
        frame = frames[idx]
        baseline = np.linalg.norm(frame["t_w_c"] - ref["t_w_c"])
        angle = GetRotationAngleValue(ref["R_w_c"], frame["R_w_c"])
        if baseline < args.min_baseline or angle > args.source_max_rotation:
            continue
        candidates.append((abs(idx - ref_idx), idx))
    candidates.sort()
    return [idx for _distance, idx in candidates[: args.max_sources]]


def SampleBilinearValue(image: np.ndarray, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sample an image at floating point pixel positions."""
    height, width = image.shape
    valid = (u >= 1.0) & (u < width - 2.0) & (v >= 1.0) & (v < height - 2.0)
    values = np.zeros_like(u, dtype=np.float32)
    if not np.any(valid):
        return values, valid

    u_valid = u[valid]
    v_valid = v[valid]
    x0 = np.floor(u_valid).astype(np.int32)
    y0 = np.floor(v_valid).astype(np.int32)
    dx = (u_valid - x0).astype(np.float32)
    dy = (v_valid - y0).astype(np.float32)
    values_valid = (
        image[y0, x0] * (1.0 - dx) * (1.0 - dy)
        + image[y0, x0 + 1] * dx * (1.0 - dy)
        + image[y0 + 1, x0] * (1.0 - dx) * dy
        + image[y0 + 1, x0 + 1] * dx * dy
    )
    values[valid] = values_valid
    return values, valid


def ExecutePlaneSweepFrame(
    ref_idx: int,
    source_indices: list[int],
    frames: list[dict],
    images: dict[int, np.ndarray],
    camera: dict,
    depth_values: np.ndarray,
    args: argparse.Namespace,
) -> tuple[np.ndarray, np.ndarray]:
    """Estimate semi-dense points for one reference frame."""
    ref = frames[ref_idx]
    ref_image = images[ref_idx]
    height, width = ref_image.shape
    fx, fy = camera["K"][0, 0], camera["K"][1, 1]
    cx, cy = camera["K"][0, 2], camera["K"][1, 2]

    grad_x = cv2.Sobel(ref_image, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(ref_image, cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.magnitude(grad_x, grad_y)

    ys, xs = np.mgrid[args.border : height - args.border : args.stride, args.border : width - args.border : args.stride]
    xs = xs.reshape(-1).astype(np.float64)
    ys = ys.reshape(-1).astype(np.float64)
    texture_mask = grad[ys.astype(np.int32), xs.astype(np.int32)] >= args.gradient_threshold
    xs = xs[texture_mask]
    ys = ys[texture_mask]
    if len(xs) == 0:
        return np.empty((0, 3), dtype=np.float32), np.empty((0, 3), dtype=np.uint8)

    rays = np.column_stack(((xs - cx) / fx, (ys - cy) / fy, np.ones_like(xs))).astype(np.float64)
    ref_values = ref_image[ys.astype(np.int32), xs.astype(np.int32)].astype(np.float32)

    best_cost = np.full(len(xs), np.inf, dtype=np.float32)
    second_cost = np.full(len(xs), np.inf, dtype=np.float32)
    best_depth = np.zeros(len(xs), dtype=np.float32)
    best_count = np.zeros(len(xs), dtype=np.int32)

    r_ref = ref["R_w_c"]
    t_ref = ref["t_w_c"]
    source_data = [(frames[idx], images[idx]) for idx in source_indices]

    for depth in depth_values:
        points_ref = rays * float(depth)
        points_world = points_ref @ r_ref.T + t_ref
        cost_sum = np.zeros(len(xs), dtype=np.float32)
        valid_count = np.zeros(len(xs), dtype=np.int32)

        for source_frame, source_image in source_data:
            points_source = (points_world - source_frame["t_w_c"]) @ source_frame["R_w_c"]
            z = points_source[:, 2]
            positive = z > 1e-6
            u = fx * points_source[:, 0] / np.maximum(z, 1e-6) + cx
            v = fy * points_source[:, 1] / np.maximum(z, 1e-6) + cy
            sampled, valid = SampleBilinearValue(source_image, u, v)
            valid &= positive
            cost_sum[valid] += np.abs(ref_values[valid] - sampled[valid])
            valid_count[valid] += 1

        enough = valid_count >= args.min_source_observations
        if not np.any(enough):
            continue
        mean_cost = np.full(len(xs), np.inf, dtype=np.float32)
        mean_cost[enough] = cost_sum[enough] / valid_count[enough]
        improved = mean_cost < best_cost
        second_cost[improved] = best_cost[improved]
        best_cost[improved] = mean_cost[improved]
        best_depth[improved] = float(depth)
        best_count[improved] = valid_count[improved]
        not_improved = (~improved) & (mean_cost < second_cost)
        second_cost[not_improved] = mean_cost[not_improved]

    finite_cost = np.isfinite(best_cost) & np.isfinite(second_cost)
    unique = np.zeros(len(xs), dtype=bool)
    unique[finite_cost] = (second_cost[finite_cost] - best_cost[finite_cost]) >= args.uniqueness_margin
    accepted = (
        np.isfinite(best_cost)
        & (best_cost <= args.max_photo_cost)
        & unique
        & (best_count >= args.min_source_observations)
    )
    if not np.any(accepted):
        return np.empty((0, 3), dtype=np.float32), np.empty((0, 3), dtype=np.uint8)

    points_ref = rays[accepted] * best_depth[accepted, None].astype(np.float64)
    points_world = points_ref @ r_ref.T + t_ref
    gray = np.clip(ref_values[accepted], 0, 255).astype(np.uint8)
    colors = np.column_stack((gray, gray, gray))
    return points_world.astype(np.float32), colors


def WritePlyValue(path: Path, points: np.ndarray, colors: np.ndarray) -> None:
    """Write a binary little-endian XYZRGB PLY file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        header = (
            "ply\n"
            "format binary_little_endian 1.0\n"
            f"element vertex {len(points)}\n"
            "property float x\n"
            "property float y\n"
            "property float z\n"
            "property uchar red\n"
            "property uchar green\n"
            "property uchar blue\n"
            "end_header\n"
        )
        handle.write(header.encode("ascii"))
        for point, color in zip(points, colors):
            handle.write(struct.pack("<fffBBB", float(point[0]), float(point[1]), float(point[2]), int(color[0]), int(color[1]), int(color[2])))


def GetVoxelDownsampleValue(points: np.ndarray, colors: np.ndarray, voxel_size: float) -> tuple[np.ndarray, np.ndarray]:
    """Voxel downsample points by averaging coordinates and colors."""
    if len(points) == 0:
        return points, colors
    keys = np.floor(points / voxel_size).astype(np.int64)
    unique, inverse = np.unique(keys, axis=0, return_inverse=True)
    counts = np.bincount(inverse).astype(np.float64)
    point_sums = np.zeros((len(unique), 3), dtype=np.float64)
    color_sums = np.zeros((len(unique), 3), dtype=np.float64)
    np.add.at(point_sums, inverse, points)
    np.add.at(color_sums, inverse, colors)
    return (point_sums / counts[:, None]).astype(np.float32), np.clip(color_sums / counts[:, None], 0, 255).astype(np.uint8)


def ExecuteReconstruct(args: argparse.Namespace) -> None:
    """Run semi-dense plane sweep and write PLY outputs."""
    frames = GetFrameValues(Path(args.frames))
    camera = GetCameraValue(Path(args.camera))
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    depth_values = 1.0 / np.linspace(1.0 / args.max_depth, 1.0 / args.min_depth, args.depth_samples)
    ref_indices = GetReferenceIndicesValue(frames, args)
    print(f"Selected {len(ref_indices)} reference frames")

    all_points = []
    all_colors = []
    keyframe_log = output_dir / "planesweep_keyframes.csv"
    with keyframe_log.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["ref_index", "ref_time", "source_indices", "point_count"])
        for ref_idx in ref_indices:
            source_indices = GetSourceIndicesValue(frames, ref_idx, args)
            if len(source_indices) < args.min_source_observations:
                writer.writerow([ref_idx, f"{frames[ref_idx]['time']:.9f}", " ".join(map(str, source_indices)), 0])
                continue

            needed = [ref_idx] + source_indices
            images = {idx: GetImageValue(frames[idx]["image_path"], camera, not args.no_undistort) for idx in needed}
            points, colors = ExecutePlaneSweepFrame(ref_idx, source_indices, frames, images, camera, depth_values, args)
            writer.writerow([ref_idx, f"{frames[ref_idx]['time']:.9f}", " ".join(map(str, source_indices)), len(points)])
            print(f"ref {ref_idx}: sources={source_indices}, points={len(points)}")
            if len(points):
                all_points.append(points)
                all_colors.append(colors)

    if all_points:
        points = np.vstack(all_points)
        colors = np.vstack(all_colors)
    else:
        points = np.empty((0, 3), dtype=np.float32)
        colors = np.empty((0, 3), dtype=np.uint8)

    raw_path = output_dir / "pointcloud_raw.ply"
    voxel_path = output_dir / f"pointcloud_voxel_{int(args.voxel_size * 100):d}cm.ply"
    WritePlyValue(raw_path, points, colors)
    voxel_points, voxel_colors = GetVoxelDownsampleValue(points, colors, args.voxel_size)
    WritePlyValue(voxel_path, voxel_points, voxel_colors)

    print(f"Wrote {len(points)} raw points to {raw_path}")
    print(f"Wrote {len(voxel_points)} voxel points to {voxel_path}")
    print(f"Wrote keyframe log to {keyframe_log}")


def GetParserValue() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    output_dir = GetOutputDirectoryValue() / "dense_recon"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", default=str(output_dir / "matched_frames.csv"))
    parser.add_argument("--camera", default="config/euroc/cam0_pinhole.yaml")
    parser.add_argument("--output-dir", default=str(output_dir))
    parser.add_argument("--min-depth", type=float, default=0.5)
    parser.add_argument("--max-depth", type=float, default=8.0)
    parser.add_argument("--depth-samples", type=int, default=64)
    parser.add_argument("--stride", type=int, default=4)
    parser.add_argument("--border", type=int, default=8)
    parser.add_argument("--gradient-threshold", type=float, default=18.0)
    parser.add_argument("--max-photo-cost", type=float, default=22.0)
    parser.add_argument("--uniqueness-margin", type=float, default=2.5)
    parser.add_argument("--min-source-observations", type=int, default=2)
    parser.add_argument("--keyframe-translation", type=float, default=0.08)
    parser.add_argument("--keyframe-max-rotation", type=float, default=20.0)
    parser.add_argument("--ref-stride", type=int, default=1)
    parser.add_argument("--max-ref-frames", type=int, default=40)
    parser.add_argument("--source-search-window", type=int, default=40)
    parser.add_argument("--min-baseline", type=float, default=0.05)
    parser.add_argument("--source-max-rotation", type=float, default=20.0)
    parser.add_argument("--max-sources", type=int, default=4)
    parser.add_argument("--voxel-size", type=float, default=0.03)
    parser.add_argument("--no-undistort", action="store_true")
    return parser


def main() -> None:
    ExecuteReconstruct(GetParserValue().parse_args())


if __name__ == "__main__":
    main()
