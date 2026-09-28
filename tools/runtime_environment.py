"""Environment assembly only; no module business code or shared Python environment."""
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CYCLONE_XML = '<CycloneDDS><Domain><General><MaxMessageSize>1200B</MaxMessageSize><FragmentSize>1000B</FragmentSize><AllowMulticast>false</AllowMulticast></General><Discovery><ParticipantIndex>auto</ParticipantIndex><MaxAutoParticipantIndex>64</MaxAutoParticipantIndex><Peers><Peer Address="127.0.0.1"/></Peers></Discovery></Domain></CycloneDDS>'

def clean_environment():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1", CUDA_VISIBLE_DEVICES="")
    for key in list(env):
        if key.startswith(("ROS_", "AMENT_", "COLCON_", "RMW_", "FASTRTPS_", "FASTDDS_", "CYCLONEDDS_")):
            env.pop(key)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "LOG_FILE", "CMAKE_PREFIX_PATH", "LD_LIBRARY_PATH", "UV_PROJECT_ENVIRONMENT"):
        env.pop(key, None)
    return env

def add_ros_dependencies(env):
    lock = json.loads((ROOT / "third_party/local-ros-deps.lock.json").read_text())
    def prepend(key, paths):
        env[key] = os.pathsep.join([str(p) for p in paths if p.exists()] + ([env[key]] if env.get(key) else []))
    for record in lock["packages"]:
        directory = ROOT / "out/ros-deps" / record["package"]
        marker = directory / "archive.sha256"
        if not marker.is_file() or marker.read_text().strip() != record["sha256"]:
            raise RuntimeError("Prepare fixed ROS dependency: " + record["package"])
        prefix = directory / "opt/ros/humble"
        prepend("AMENT_PREFIX_PATH", [prefix])
        prepend("CMAKE_PREFIX_PATH", [prefix])
        prepend("LD_LIBRARY_PATH", [prefix / "lib", prefix / "lib/x86_64-linux-gnu"])
        prepend("PYTHONPATH", [prefix / "local/lib/python3.10/dist-packages"])
    return env

def local_transport(env, domain):
    if not 180 <= int(domain) <= 219:
        raise ValueError("Local profile domain must be between 180 and 219")
    env.update(ROS_DOMAIN_ID=str(domain), ROS_LOCALHOST_ONLY="1",
               RMW_IMPLEMENTATION="rmw_cyclonedds_cpp", CYCLONEDDS_URI=CYCLONE_XML)
    return env

def ros_environment(install=None, domain=210):
    env = add_ros_dependencies(clean_environment())
    scripts = [Path("/opt/ros/humble/setup.bash")]
    if install is not None:
        scripts.append(Path(install) / "local_setup.bash")
    for script in scripts:
        if not script.is_file():
            raise RuntimeError("Missing ROS setup: " + str(script))
    shell = "set -e\n" + "\n".join("source " + shlex.quote(str(s)) for s in scripts)
    shell += "\n/usr/bin/python3 -B -c " + shlex.quote("import os,json;print(json.dumps(dict(os.environ)))")
    result = subprocess.run(["bash", "--noprofile", "--norc", "-c", shell],
                            env=env, text=True, capture_output=True, check=True, timeout=30)
    env = json.loads(result.stdout.splitlines()[-1])
    # Underlay setup can reset paths; fixed dependencies must remain available.
    add_ros_dependencies(env)
    return local_transport(env, domain)
