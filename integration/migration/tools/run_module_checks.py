"""Run existing tests in independent locked environments and disposable snapshots."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET
from baseline_lib import ROOT, clean_environment, verify_sources


def command(args: list[str], cwd: Path, log: Path, timeout: int = 600) -> dict:
    started = time.monotonic()
    env = clean_environment()
    env["QT_QPA_PLATFORM"] = "offscreen"
    try:
        with log.open("w") as stream:
            result = subprocess.run(args, cwd=cwd, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=timeout)
        code = result.returncode
    except subprocess.TimeoutExpired:
        code = 124
    return {
        "command": args, "cwd": str(cwd), "exit_code": code,
        "duration_sec": round(time.monotonic() - started, 3),
        "log": str(log), "status": "PASS" if code == 0 else "FAIL",
    }


def test_counts(path: Path) -> dict:
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    suites = list(root.iter("testsuite"))
    return {k: sum(int(s.get(k, 0)) for s in suites)
            for k in ("tests", "failures", "errors", "skipped")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--modules", nargs="+", choices=["emotion", "behavior", "action"],
                        default=["emotion", "behavior", "action"])
    args = parser.parse_args()
    if not args.run_id.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("Invalid run-id")
    if verify_sources()["status"] != "PASS":
        raise SystemExit("Original baseline changed; refusing to test.")
    report = ROOT / "reports" / args.run_id
    report.mkdir(parents=True, exist_ok=True)
    sources = ROOT / "work" / args.run_id / "sources"
    uv = str(ROOT / ".tools/uv")
    results = {"started_at": datetime.now(timezone.utc).isoformat(), "modules": {}}
    for module in args.modules:
        source = sources / module
        python = source / ".venv/bin/python"
        records = []
        if module == "emotion":
            if not python.exists():
                records.append(command([uv, "venv", "--python", "/usr/bin/python3.10",
                                        str(source / ".venv")], source,
                                       report / "emotion-venv.log"))
            records.append(command([
                uv, "pip", "install", "--python", str(python),
                "pytest==9.1.1", "PyYAML==6.0.3", "setuptools==79.0.1",
            ], source, report / "emotion-dependencies.log"))
        else:
            records.append(command([
                uv, "sync", "--locked", "--no-install-project", "--python",
                "/usr/bin/python3.10", "--project", str(source),
            ], source, report / f"{module}-dependencies.log"))
        if any(r["exit_code"] for r in records):
            results["modules"][module] = {
                "status": "BLOCKED", "reason": "dependency preparation failed", "checks": records,
            }
            continue
        inventory = command([
            uv, "pip", "freeze", "--python", str(python),
        ], source, report / f"{module}-installed.txt")
        records.append(inventory)
        targets = ["tests"]
        if module == "behavior":
            targets.append("marsdog_behavior/tests")
        junit = report / f"{module}-junit.xml"
        test = command([
            str(python), "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
            f"--junitxml={junit}", *targets,
        ], source, report / f"{module}-tests.log")
        test["counts"] = test_counts(junit)
        records.append(test)
        results["modules"][module] = {
            "status": test["status"], "scope": "existing tests, no ROS environment",
            "python": str(python), "checks": records,
        }
        (report / "module-checks.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n"
        )
        print(module, test["status"], test["counts"], flush=True)
    results["source_verification"] = verify_sources()
    (report / "module-checks.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n"
    )
    raise SystemExit(0 if all(
        m["status"] == "PASS" for m in results["modules"].values()
    ) and results["source_verification"]["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
