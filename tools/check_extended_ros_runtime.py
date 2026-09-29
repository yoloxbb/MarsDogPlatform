"""Dependency resolution and existing CTest gate for the fixed CPU SLAM build."""
import json
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

from runtime_environment import ROOT, ros_environment
from prepare_extended_ros import BASE, environment, sha, LOCK
from check_extended_ros_build import source_sha256

def main():
    reports = {}
    for layer in ("nav2-plugin", "openvins", "rtabmap"):
        record = json.loads((BASE / (layer + "-build.json")).read_text())
        assert record["status"] == "PASS", layer + " has not built"
        assert record["dependency_lock_sha256"] == sha(LOCK), layer + " dependencies changed"
        assert record.get("source_sha256") == source_sha256([ROOT / p for p in record["source_paths"]]), layer + " source changed"
        reports[layer] = record
    env = environment(ros_environment(BASE / "install", 213))
    started = time.monotonic()
    command = ["ctest", "--test-dir", str(BASE / "build/ov_msckf"),
               "--output-on-failure", "--output-junit", str(BASE / "openvins-tests.xml")]
    result = subprocess.run(command, env=env, text=True, capture_output=True, timeout=120)
    (BASE / "openvins-tests.log").write_text(result.stdout + result.stderr)
    tests = ET.parse(BASE / "openvins-tests.xml").getroot()
    assert tests.findall(".//testcase"), "No registered vendor test executed"
    checked, errors = [], []
    for path in sorted((BASE / "install").rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                continue
        linked = subprocess.run(["ldd", str(path)], env=env, text=True,
                                capture_output=True, timeout=20)
        missing = [line.strip() for line in (linked.stdout + linked.stderr).splitlines()
                   if "not found" in line]
        if linked.returncode or missing:
            errors.append({"path": str(path), "returncode": linked.returncode, "missing": missing})
        checked.append(str(path.relative_to(BASE / "install")))
    features = [line for line in (BASE / "rtabmap-build.log").read_text().splitlines()
                if "With " in line or "Found OpenVINS:" in line]
    report = {"status": "PASS" if result.returncode == 0 and not errors else "FAIL",
              "scope": "Existing OpenVINS CTest and ELF dependency resolution; no sensor/accuracy/performance acceptance",
              "ctest_returncode": result.returncode, "ctest_cases": len(tests.findall(".//testcase")),
              "checked_elf_files": checked, "errors": errors, "rtabmap_features": features,
              "elapsed_seconds": round(time.monotonic()-started, 2)}
    (BASE / "runtime.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"status": report["status"], "elf_files": len(checked),
                      "ctest_cases": report["ctest_cases"], "errors": errors}, indent=2))
    if report["status"] != "PASS":
        raise RuntimeError("CPU SLAM runtime prerequisites failed")

if __name__ == "__main__":
    main()
