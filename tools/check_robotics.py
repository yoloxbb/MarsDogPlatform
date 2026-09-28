"""Build original/native ROS packages and run their existing CPU functional tests."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import xml.etree.ElementTree as ET
from runtime_environment import add_ros_dependencies, local_transport

ROOT = Path(__file__).resolve().parents[1]
PATHS = {
    "stereo_v4l2_camera": "sensor_ws/src/stereo_v4l2_camera",
    "wit_imu": "sensor_ws/src/wit_imu",
    "person_3d_localization": "slam_ws/src/person_3d_localization",
    "robot_slam_bringup": "slam_ws/src/robot_slam_bringup",
    "stereo_slam_legacy_bringup": "slam_ws/src/stereo_slam_legacy_bringup",
    "go2_uwb_local_follow": "go2_follow_ws/src/go2_uwb_local_follow",
    "go2_uwb_behavior": "go2_follow_ws/src/go2_uwb_behavior",
}
TEST_PACKAGES = ["uwb_aoa_pkg", "go2_uwb_local_follow", "go2_uwb_behavior", "person_3d_localization"]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-source", type=Path)
    parser.add_argument("--test-only", action="store_true")
    parser.add_argument("--uwb-source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = out / "result.json"
    report.write_text('{"status":"RUNNING"}\n')
    log = out / "commands.log"
    log.write_text("")
    tools = ROOT / "platform/humble-build-tools/.venv"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", ROS_LOCALHOST_ONLY="1",
               ROS_DOMAIN_ID="211", ROS_LOG_DIR=str(out / "ros-log"), CMAKE_BUILD_PARALLEL_LEVEL="2",
               COLCON_EXTENSION_BLOCKLIST="colcon_core.event_handler.desktop_notification",
               RMW_IMPLEMENTATION="rmw_fastrtps_cpp",
               FASTRTPS_DEFAULT_PROFILES_FILE=str(ROOT / "integration/migration/fixtures/fastdds-local-udp.xml"))
    for k in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "AMENT_PREFIX_PATH", "COLCON_PREFIX_PATH", "CMAKE_PREFIX_PATH"):
        env.pop(k, None)
    commands = []
    def run(command, timeout=900, check=True):
        commands.append(command)
        with log.open("a") as f:
            f.write(json.dumps(command) + "\n")
            f.flush()
            result = subprocess.run(command, env=env, cwd=out, stdout=f,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError(f"Exit {result.returncode}; see {log}")
        return result.returncode
    try:
        shell = "set -e\nsource /opt/ros/humble/setup.bash\n"
        shell += shlex.quote(str(tools / "bin/python")) + " -B -c " + shlex.quote(
            "import os,json;print(json.dumps(dict(os.environ)))")
        result = subprocess.run(["bash", "--noprofile", "--norc", "-c", shell],
                                env=env, text=True, capture_output=True, check=True)
        env = local_transport(add_ros_dependencies(json.loads(result.stdout.splitlines()[-1])), 211)
        if args.legacy_source:
            source = args.legacy_source.resolve()
            paths = [source / s for s in PATHS.values()] + [source / "go2_follow_ws/src/uwb"]
        else:
            assert args.uwb_source, "Explicit pinned UWB source required"
            paths = [ROOT / "robotics/ros2/src" / n for n in PATHS] + [args.uwb_source.resolve()]
        if not args.test_only:
            run([str(tools / "bin/colcon"), "--log-base", str(out / "log"), "build",
                 "--base-paths", *map(str, paths), "--build-base", str(out / "build"),
                 "--install-base", str(out / "install"), "--executor", "sequential",
                 "--event-handlers", "console_direct+", "--cmake-args", "-DBUILD_TESTING=ON",
                 "-DBUILD_UWB_VENDOR_DRIVER=OFF", "-DPython3_EXECUTABLE=" + str(tools / "bin/python"),
                 "-DPYTHON_EXECUTABLE=" + str(tools / "bin/python")])
        # Original algorithm and transport tests only. Historical lint debt is separate.
        code = run([str(tools / "bin/colcon"), "--log-base", str(out / "test-log"), "test",
                    "--base-paths", *map(str, paths),
                    "--build-base", str(out / "build"), "--install-base", str(out / "install"),
                    "--packages-select", *TEST_PACKAGES, "--executor", "sequential",
                    "--event-handlers", "console_direct+", "--return-code-on-test-failure",
                    "--ctest-args", "-R", "^test_", "--output-on-failure"], check=False)
        run([str(tools / "bin/colcon"), "test-result", "--test-result-base", str(out / "build"),
             "--verbose"], check=False)
        junit = list((out / "build").glob("*/test_results/**/*.xml"))
        counts = {k: 0 for k in ("tests", "failures", "errors", "skipped")}
        for file in junit:
            root = ET.parse(file).getroot()
            suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
            for suite in suites:
                for key in counts:
                    counts[key] += int(suite.get(key, 0))
        assert counts["tests"] > 0, "No functional tests ran"
        assert not any(counts[k] for k in ("failures", "errors", "skipped")), counts
        ctest = []
        for package in TEST_PACKAGES:
            results = sorted((out / "build" / package / "Testing").glob("*/Test.xml"))
            assert results, "Missing CTest results for " + package
            for test in ET.parse(results[-1]).getroot().findall("./Testing/Test"):
                ctest.append({"package": package, "name": test.findtext("Name"), "status": test.get("Status")})
        assert ctest and all(t["status"] == "passed" for t in ctest), ctest
        data = {"transport": "Cyclone DDS / localhost / fixed extracted dependency",
                "ctest": ctest, "status": "PASS_WITH_EXPLICIT_LIMITS" if code == 0 else "FAIL",
                "counts": counts, "junit_reports": [str(f.relative_to(out)) for f in junit],
                "source_paths": list(map(str, paths)), "functional_test_returncode": code,
                "build_packages": list(PATHS) + ["uwb_aoa_pkg"], "test_packages": TEST_PACKAGES,
                "commands": commands,
                "limits": ["No hardware/device launch", "ARM64 UWB vendor algorithm disabled by original option",
                           "behavior_ext_plugins requires unavailable Nav2 libraries; excluded",
                           "Bringup install is not mapping/navigation runtime acceptance",
                           "Historical lint not part of CPU functional gate"]}
        report.write_text(json.dumps(data, indent=2) + "\n")
        print(json.dumps(data, indent=2))
        raise SystemExit(0 if code == 0 else 1)
    except Exception as error:
        report.write_text(json.dumps({"status":"FAIL","error":str(error),"commands":commands},indent=2)+"\n")
        raise

if __name__ == "__main__":
    main()
