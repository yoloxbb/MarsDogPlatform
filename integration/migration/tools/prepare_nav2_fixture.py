"""Checksum-verified ROS interface build fixture; never install a system package."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request
from baseline_lib import ROOT

RECORD = {
    "package": "ros-humble-nav2-msgs", "version": "1.1.20-1jammy.20260907.223327",
    "architecture": "amd64",
    "url": "https://mirrors.tuna.tsinghua.edu.cn/ros2/ubuntu/pool/main/r/ros-humble-nav2-msgs/ros-humble-nav2-msgs_1.1.20-1jammy.20260907.223327_amd64.deb",
    "sha256": "7ea288dd8e6718cb46658616eceb667bfda53c0d2b08596e3bc8a70061dc3487",
    "method": "apt metadata verified download; dpkg-deb extract only; system unchanged",
}


def main():
    root = ROOT / "work/nav2-msgs-1.1.20"
    root.mkdir(parents=True, exist_ok=True)
    archive = root / "nav2-msgs.deb"
    if archive.exists():
        payload = archive.read_bytes()
    else:
        with urllib.request.urlopen(RECORD["url"], timeout=30) as response:
            payload = response.read()
    assert hashlib.sha256(payload).hexdigest() == RECORD["sha256"], "Fixture hash mismatch; no overwrite"
    archive.write_bytes(payload)
    prefix = root / "extracted"
    if not prefix.exists():
        subprocess.run(["dpkg-deb", "--extract", str(archive), str(prefix)], check=True)
    record = {**RECORD, "prefix": str(prefix / "opt/ros/humble")}
    (root / "provenance.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
