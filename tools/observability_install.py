"""Prepare the local public logging dependency for source-independent wheel checks."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "packages/observability"


def copy_source(work):
    target = work / "packages/observability"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy2(SOURCE / name, target / name)
    shutil.copytree(SOURCE / "marsdog_observability", target / "marsdog_observability",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"), dirs_exist_ok=True)
    return target


def build_wheel(run, uv, work):
    source = copy_source(work)
    directory = work / "observability-wheels"
    run([uv, "build", "--wheel", "--out-dir", str(directory), str(source)])
    wheels = list(directory.glob("*.whl"))
    assert len(wheels) == 1
    return str(wheels[0])
