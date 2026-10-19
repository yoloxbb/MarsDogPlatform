#!/usr/bin/env python3
"""Publish a binary XYZRGB PLY file as a ROS2 PointCloud2 topic for RViz."""

from __future__ import annotations

import argparse
import struct
from pathlib import Path

import numpy as np
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import PointCloud2, PointField
from sensor_msgs_py import point_cloud2
from std_msgs.msg import Header
from path_defaults import GetOutputDirectoryValue


def GetRgbFloatValue(red: np.ndarray, green: np.ndarray, blue: np.ndarray) -> np.ndarray:
    """Pack uint8 RGB channels into the float32 rgb layout used by RViz/PCL."""
    rgb_uint32 = (
        red.astype(np.uint32) << 16
        | green.astype(np.uint32) << 8
        | blue.astype(np.uint32)
    )
    return rgb_uint32.view(np.float32)


def GetPlyCloudValue(path: Path, every: int, max_points: int) -> tuple[np.ndarray, np.ndarray]:
    """Read the binary little-endian XYZRGB PLY produced by monocular_planesweep.py."""
    with path.open("rb") as handle:
        vertex_count = None
        while True:
            line = handle.readline().decode("ascii").strip()
            if line.startswith("element vertex"):
                vertex_count = int(line.split()[-1])
            if line == "end_header":
                break
        if vertex_count is None:
            raise RuntimeError(f"PLY file has no vertex count: {path}")
        raw = handle.read()

    record_size = 15
    if len(raw) < vertex_count * record_size:
        raise RuntimeError(f"PLY data is shorter than expected: {path}")

    selected_indices = np.arange(0, vertex_count, max(1, every), dtype=np.int64)
    if max_points > 0 and len(selected_indices) > max_points:
        selected_indices = selected_indices[:max_points]

    points = np.empty((len(selected_indices), 3), dtype=np.float32)
    colors = np.empty((len(selected_indices), 3), dtype=np.uint8)
    for out_idx, ply_idx in enumerate(selected_indices):
        offset = int(ply_idx) * record_size
        x, y, z, r, g, b = struct.unpack_from("<fffBBB", raw, offset)
        points[out_idx] = (x, y, z)
        colors[out_idx] = (r, g, b)

    finite = np.isfinite(points).all(axis=1)
    return points[finite], colors[finite]


def GetPointCloudMessageValue(points: np.ndarray, colors: np.ndarray, frame_id: str) -> PointCloud2:
    """Create a PointCloud2 message with XYZ and packed RGB fields."""
    header = Header()
    header.frame_id = frame_id
    fields = [
        PointField(name="x", offset=0, datatype=PointField.FLOAT32, count=1),
        PointField(name="y", offset=4, datatype=PointField.FLOAT32, count=1),
        PointField(name="z", offset=8, datatype=PointField.FLOAT32, count=1),
        PointField(name="rgb", offset=12, datatype=PointField.FLOAT32, count=1),
    ]
    rgb = GetRgbFloatValue(colors[:, 0], colors[:, 1], colors[:, 2])
    cloud_rows = np.column_stack((points, rgb))
    return point_cloud2.create_cloud(header, fields, cloud_rows)


class PlyPublisher(Node):
    """Small ROS2 node that republishes a static PLY cloud for RViz."""

    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__("dense_recon_ply_publisher")
        points, colors = GetPlyCloudValue(Path(args.ply), args.every, args.max_points)
        self.message = GetPointCloudMessageValue(points, colors, args.frame_id)
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.publisher = self.create_publisher(PointCloud2, args.topic, qos)
        self.timer = self.create_timer(args.period, self.ExecutePublish)
        self.get_logger().info(
            f"Loaded {len(points)} points from {args.ply}; publishing {args.topic} in frame {args.frame_id}"
        )
        self.ExecutePublish()

    def ExecutePublish(self) -> None:
        """Publish the static point cloud with the current ROS time."""
        self.message.header.stamp = self.get_clock().now().to_msg()
        self.publisher.publish(self.message)


def GetParserValue() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    default_ply = GetOutputDirectoryValue() / "dense_recon" / "pointcloud_voxel_3cm.ply"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ply",
        default=str(default_ply),
        help="PLY file to publish",
    )
    parser.add_argument("--topic", default="/dense_recon/cloud")
    parser.add_argument("--frame-id", default="world")
    parser.add_argument("--period", type=float, default=1.0)
    parser.add_argument("--every", type=int, default=1, help="Publish every Nth point")
    parser.add_argument("--max-points", type=int, default=0, help="Optional cap for RViz performance")
    return parser


def main() -> None:
    args = GetParserValue().parse_args()
    rclpy.init()
    node = PlyPublisher(args)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
