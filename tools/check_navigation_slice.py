"""Build and test current public navigation interfaces in an isolated ROS domain."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import xml.etree.ElementTree as ET

from runtime_environment import ROOT, ros_environment, local_transport


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "out/navigation-interfaces")
    parser.add_argument("--underlay", type=Path, default=ROOT / "out/local/ros/install")
    parser.add_argument("--test-only", action="store_true")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    result_path = out / "result.json"
    result_path.write_text(json.dumps({"status": "RUNNING"}) + "\n")
    env = ros_environment(args.underlay, domain=213)
    env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", ROS_LOG_DIR=str(out / "ros-log"),
               CMAKE_BUILD_PARALLEL_LEVEL="2", COLCON_EXTENSION_BLOCKLIST="colcon_core.event_handler.desktop_notification")
    build_tools = ROOT / "platform/humble-build-tools/.venv/bin"
    paths = [ROOT / p for p in ("interfaces/ros2/marsdog_interfaces", "modules/action",
             "robotics/ros2/src/waypoint_nav", "robotics/ros2/src/go2_uwb_behavior")]
    colcon = str(build_tools / "colcon")
    locations = ["--base-paths", *map(str, paths), "--build-base", str(out / "build"),
                 "--install-base", str(out / "install"), "--executor", "sequential"]

    def run(command, timeout=900):
        with (out / "commands.log").open("a") as log:
            log.write(json.dumps(command) + "\n")
            log.flush()
            subprocess.run(command, env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           timeout=timeout, check=True)

    try:
        if not args.test_only:
            run([colcon, "--log-base", str(out / "build-log"), "build", *locations,
                 "--event-handlers", "console_direct+", "--cmake-args", "-DBUILD_TESTING=ON",
                 "-DPython3_EXECUTABLE=" + str(build_tools / "python"),
                 "-DPYTHON_EXECUTABLE=" + str(build_tools / "python")])
        shell = "set -e\nsource " + shlex.quote(str(out / "install/local_setup.bash"))
        shell += "\n/usr/bin/python3 -c " + shlex.quote("import os,json;print(json.dumps(dict(os.environ)))")
        merged = subprocess.run(["bash", "--noprofile", "--norc", "-c", shell], env=env,
                                capture_output=True, text=True, check=True, timeout=30)
        env = local_transport(json.loads(merged.stdout.splitlines()[-1]), 213)
        # Verify the installed overlay before adding source paths for fixture tests.
        probe = "\n".join([
            "import importlib.util,pathlib",
            "import marsdog_action_executor,waypoint_nav,marsdog_interfaces",
            "from marsdog_action_executor.ros2_compat import get_action_source",
            "from marsdog_interfaces.srv import NavigationTask",
            "assert get_action_source() == 'marsdog_interfaces'",
            "assert importlib.util.find_spec('marsdog_action_executor.action') is None",
            "assert importlib.util.find_spec('waypoint_nav.legacy_voice_task') is None",
            "root = pathlib.Path(" + repr(str(out / "install")) + ")",
            "assert pathlib.Path(marsdog_action_executor.__file__).resolve().is_relative_to(root)",
            "assert pathlib.Path(waypoint_nav.__file__).resolve().is_relative_to(root)",
            "assert set(NavigationTask.Request.get_fields_and_field_types()) == {'task_id','task_type','params_json'}",
            "print('Installed public types verified; retired modules absent')",
        ])
        run([str(ROOT / "modules/action/.venv/bin/python"), "-B", "-c", probe])
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "modules/behavior"),
            str(ROOT / "modules/action"), env.get("PYTHONPATH", "")])
        run([str(ROOT / "modules/action/.venv/bin/python"), "-B", "-m", "pytest",
             "robotics/ros2/src/waypoint_nav/tests", "integration/ros/tests", "-q",
             "-p", "no:cacheprovider", "--junitxml=" + str(out / "navigation.xml")])
        suites = ET.parse(out / "navigation.xml").getroot().iter("testsuite")
        counts = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
        for suite in suites:
            for key in counts:
                counts[key] += int(suite.get(key, 0))
        assert counts["tests"] and not any(counts[k] for k in ("failures", "errors", "skipped")), counts
        run([colcon, "--log-base", str(out / "test-log"), "test", *locations,
             "--packages-select", "go2_uwb_behavior", "--return-code-on-test-failure",
             "--ctest-args", "-R", "^test_", "--output-on-failure"])
        run([colcon, "test-result", "--test-result-base", str(out / "build"), "--verbose"])
        uwb_counts = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
        for path in (out / "build/go2_uwb_behavior/test_results").rglob("*.xml"):
            root = ET.parse(path).getroot()
            suites = [root] if root.tag == "testsuite" else root.iter("testsuite")
            for suite in suites:
                for key in uwb_counts:
                    uwb_counts[key] += int(suite.get(key, 0))
        assert uwb_counts["tests"] and not any(uwb_counts[k] for k in ("failures", "errors", "skipped")), uwb_counts
        result = {"status": "PASS", "navigation": counts, "uwb": uwb_counts, "domain": 213,
                  "transport": "CycloneDDS localhost", "hardware_acceptance": False}
    except Exception as error:
        result_path.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
    result_path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
