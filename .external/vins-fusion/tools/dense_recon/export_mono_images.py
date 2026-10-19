#!/usr/bin/env python3
"""Export one image topic from a ROS2 bag for offline reconstruction."""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
from rosbags.highlevel import AnyReader
from rosbags.typesys import Stores, get_typestore
from path_defaults import GetOutputDirectoryValue


def GetTimestampValue(msg) -> float:
    """Return a ROS message header stamp as floating-point seconds."""
    return float(msg.header.stamp.sec) + float(msg.header.stamp.nanosec) * 1e-9


def GetImageValue(msg) -> np.ndarray:
    """Convert a sensor_msgs/Image message into an OpenCV image array."""
    height = int(msg.height)
    width = int(msg.width)
    step = int(msg.step)
    encoding = str(msg.encoding).lower()
    data = np.asarray(msg.data, dtype=np.uint8)

    if encoding in ("mono8", "8uc1"):
        rows = data.reshape(height, step)
        return rows[:, :width].copy()

    if encoding in ("bgr8", "rgb8"):
        rows = data.reshape(height, step)
        image = rows[:, : width * 3].reshape(height, width, 3)
        if encoding == "rgb8":
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        return image.copy()

    if encoding in ("bgra8", "rgba8"):
        rows = data.reshape(height, step)
        image = rows[:, : width * 4].reshape(height, width, 4)
        code = cv2.COLOR_BGRA2BGR if encoding == "bgra8" else cv2.COLOR_RGBA2BGR
        return cv2.cvtColor(image, code)

    if encoding in ("mono16", "16uc1"):
        data16 = np.asarray(msg.data, dtype=np.uint8).view(np.uint16)
        rows = data16.reshape(height, step // 2)
        image16 = rows[:, :width]
        return cv2.convertScaleAbs(image16, alpha=255.0 / max(float(image16.max()), 1.0))

    raise ValueError(f"Unsupported image encoding: {msg.encoding}")


def ExecuteExport(args: argparse.Namespace) -> None:
    """Read the bag topic and write timestamp-named PNG files."""
    bag_path = Path(args.bag)
    output_dir = Path(args.output)
    times_path = Path(args.times)
    output_dir.mkdir(parents=True, exist_ok=True)
    times_path.parent.mkdir(parents=True, exist_ok=True)

    typestore = get_typestore(Stores.ROS2_HUMBLE)
    count = 0
    with AnyReader([bag_path], default_typestore=typestore) as reader, times_path.open("w") as times_file:
        connections = [conn for conn in reader.connections if conn.topic == args.topic]
        if not connections:
            topics = ", ".join(sorted({conn.topic for conn in reader.connections}))
            raise RuntimeError(f"Topic {args.topic} not found. Available topics: {topics}")

        times_file.write("# timestamp_sec image_path ros_sec ros_nanosec frame_id\n")
        for index, (conn, _timestamp, rawdata) in enumerate(reader.messages(connections=connections)):
            if index % args.every != 0:
                continue
            if args.max_images and count >= args.max_images:
                break

            msg = reader.deserialize(rawdata, conn.msgtype)
            stamp = GetTimestampValue(msg)
            filename = f"{stamp:.9f}.png"
            image_path = output_dir / filename
            if image_path.exists() and not args.overwrite:
                raise FileExistsError(f"{image_path} exists; pass --overwrite to replace exported images")

            image = GetImageValue(msg)
            if image.size == 0:
                raise RuntimeError(f"Decoded empty image at timestamp {stamp:.9f}")
            if not cv2.imwrite(str(image_path), image):
                raise RuntimeError(f"Failed to write {image_path}")

            times_file.write(
                f"{stamp:.9f} {image_path} {msg.header.stamp.sec} "
                f"{msg.header.stamp.nanosec} {msg.header.frame_id}\n"
            )
            count += 1

    print(f"Exported {count} images to {output_dir}")
    print(f"Wrote timestamps to {times_path}")


def GetParserValue() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    output_dir = GetOutputDirectoryValue() / "dense_recon"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag", default="datasets/euroc/V1_01_easy_mono_imu_ros2")
    parser.add_argument("--topic", default="/cam0/image_raw")
    parser.add_argument("--output", default=str(output_dir / "images"))
    parser.add_argument("--times", default=str(output_dir / "image_times.txt"))
    parser.add_argument("--every", type=int, default=1, help="Export every Nth image")
    parser.add_argument("--max-images", type=int, default=0, help="Optional cap for quick tests")
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> None:
    args = GetParserValue().parse_args()
    ExecuteExport(args)


if __name__ == "__main__":
    main()
