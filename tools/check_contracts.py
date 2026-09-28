"""Run migrated Action -> BT -> Needs contracts in separate environments."""
import os
from pathlib import Path
import subprocess
from runtime_environment import ROOT, clean_environment

def main():
    out = ROOT / "validation/local-platform"
    out.mkdir(parents=True, exist_ok=True)
    env = clean_environment()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["MARSDOG_RESULT_FIXTURE"] = str(ROOT / "integration/migration/fixtures/behavior-result/energy-evidence-cases.json")
    for module in ("emotion", "behavior", "action"):
        env["MARSDOG_" + module.upper() + "_SOURCE"] = str(ROOT / "modules" / module)
    # The test coordinator owns no business implementation. Each stage invokes
    # that module's interpreter; the worker verifies foreign modules are absent.
    subprocess.run([str(ROOT / "modules/action/.venv/bin/python"), "-B", "-m", "pytest",
                    "integration/migration/tests", "-q", "-p", "no:cacheprovider",
                    "--junitxml=" + str(out / "contracts.xml")], cwd=ROOT, env=env, check=True)

if __name__ == "__main__":
    main()
