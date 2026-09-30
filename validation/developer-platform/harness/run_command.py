from pathlib import Path
import argparse, datetime, json, os, platform, subprocess, sys, time
ROOT = Path("/home/elephant/MarsDog/marsdog-platform")
BASE = ROOT / "out/developer-platform/commands"
p = argparse.ArgumentParser()
p.add_argument("--label", required=True)
p.add_argument("--cwd", type=Path, default=ROOT)
p.add_argument("--timeout", type=int, default=1800)
p.add_argument("command", nargs=argparse.REMAINDER)
a = p.parse_args()
command = a.command[1:] if a.command[0] == "--" else a.command
output = BASE / a.label
output.mkdir(parents=True, exist_ok=False)
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", UV_CACHE_DIR="/home/elephant/MarsDog/migration/.cache/uv", UV_PYTHON_DOWNLOADS="never", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
for key in list(env):
    if key.startswith(("ROS_","AMENT_","COLCON_","RMW_","FASTRTPS_","FASTDDS_","CYCLONEDDS_")) or key in ("PYTHONPATH","PYTHONHOME","VIRTUAL_ENV","CMAKE_PREFIX_PATH","LD_LIBRARY_PATH","UV_PROJECT_ENVIRONMENT"):
        env.pop(key, None)
record = {"command":command,"cwd":str(a.cwd),"started_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"platform":platform.platform(),"env":{"UV_CACHE_DIR":env["UV_CACHE_DIR"]},"source_commit":subprocess.check_output(["git","-C",str(a.cwd),"rev-parse","HEAD"],text=True).strip(),"source_status":subprocess.check_output(["git","-C",str(a.cwd),"status","--short"],text=True)}
start = time.monotonic()
with (output / "command.log").open("w") as log:
    try:
        result = subprocess.run(command,cwd=a.cwd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=a.timeout)
        record["returncode"] = result.returncode
    except Exception as error:
        record.update(returncode=-1,error=str(error))
record.update(duration_seconds=round(time.monotonic()-start,3),status="PASS" if record["returncode"] == 0 else "FAIL")
(output / "execution.json").write_text(json.dumps(record,indent=2)+"\n")
print(json.dumps(record,indent=2),flush=True)
print((output / "command.log").read_text(errors="replace")[-2500:],flush=True)
sys.exit(0 if record["returncode"] == 0 else 1)
