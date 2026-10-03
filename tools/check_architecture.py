"""Check maintained source boundaries and ROS DAG; does not import business code."""
import ast
import argparse
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def audit():
    manifest = json.loads((ROOT / "platform/modules.json").read_text())
    modules = manifest["modules"]
    owners = {ns: name for name, entry in modules.items() for ns in entry["namespaces"]}
    allowed = set(manifest["allowed_cross_imports"])
    exceptions = {(x["path"], x["import"]) for x in manifest["legacy_import_exceptions"]}
    errors, cross_imports = [], []
    def check_import(name, owner, path, line):
        provider = owners.get(name.split(".")[0])
        if provider and provider != owner:
            record = dict(consumer=owner, provider=provider, path=path, line=line, module=name)
            cross_imports.append(record)
            if name not in allowed and (path, name) not in exceptions:
                errors.append("Private cross-module import: " + str(record))
    for owner, entry in modules.items():
        if owner in ("robotics", "interfaces"):
            continue
        path = ROOT / entry["path"]
        if not (path / "uv.lock").is_file() or not (path / "pyproject.toml").is_file():
            errors.append("Missing independent lock/project: " + owner)
        for ns in entry["namespaces"]:
            for file in (path / ns).rglob("*.py"):
                if "tests" in file.parts or "__pycache__" in file.parts:
                    continue
                relative = file.relative_to(ROOT).as_posix()
                tree = ast.parse(file.read_text(), filename=relative)
                for node in ast.walk(tree):
                    imports = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                               else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0
                               else [])
                    if isinstance(node, ast.Call) and node.args:
                        func = node.func
                        dynamic = (isinstance(func, ast.Name) and func.id == "__import__"
                                   or isinstance(func, ast.Attribute) and func.attr == "import_module")
                        if dynamic and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                            imports.append(node.args[0].value)
                    for name in imports:
                        if name:
                            check_import(name, owner, relative, node.lineno)
    packages = {}
    xmls = [ROOT / modules[n]["path"] / "package.xml" for n in ("emotion", "behavior", "action", "voice", "vision")]
    xmls += list((ROOT / "packages").glob("*/package.xml"))
    xmls += list((ROOT / "robotics/ros2/src").glob("*/package.xml"))
    xmls += list((ROOT / "interfaces/ros2").glob("*/package.xml"))
    for file in xmls:
        root = ET.parse(file).getroot()
        name = root.findtext("name")
        if name in packages:
            errors.append("Duplicate ROS package: " + name)
        packages[name] = {
            "path": file.relative_to(ROOT).as_posix(),
            "compile": sorted({n.text for n in root if n.tag in ("depend", "build_depend", "build_export_depend", "buildtool_depend")}),
            "runtime": sorted({n.text for n in root if n.tag in ("depend", "exec_depend")}),
        }
    def walk(name, stack, done, edges):
        if name in stack:
            errors.append("ROS dependency cycle: " + " -> ".join(stack + [name]))
            return
        if name in done:
            return
        for dep in packages[name][edges]:
            if dep in packages:
                walk(dep, stack + [name], done, edges)
        done.add(name)
    for kind in ("compile", "runtime"):
        done = set()
        for name in packages:
            walk(name, [], done, kind)
    registry = json.loads((ROOT / "interfaces/registry.json").read_text())
    for item in registry["interfaces"]:
        for source in item["evidence"]:
            if not (ROOT / source).is_file():
                errors.append("Missing interface evidence: " + source)
        if item.get("idl"):
            source = ROOT / item["idl"]
            if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != item["idl_sha256"]:
                errors.append("IDL fingerprint changed: " + item["name"])
    # Explicit package presence: the platform profile uses the supplied public action type.
    if "marsdog_interfaces" not in packages["marsdog_action_executor"]["runtime"]:
        errors.append("Action runtime manifest omits selected public interface package")
    return {"status": "FAIL" if errors else "PASS", "errors": errors,
            "cross_module_imports": cross_imports, "ros_packages": packages,
            "registered_interfaces": len(registry["interfaces"]),
            "limits": ["Non-literal dynamic imports are not resolved statically",
                       "External ROS dependencies require the build/doctor gates",
                       "Communication feedback loops are allowed; implementation import/ROS dependency cycles are not"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "out/architecture.json")
    args = parser.parse_args()
    report = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "errors": report["errors"],
                      "ros_packages": len(report["ros_packages"]), "interfaces": report["registered_interfaces"]}))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
