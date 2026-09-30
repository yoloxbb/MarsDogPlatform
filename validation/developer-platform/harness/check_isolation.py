from pathlib import Path
import hashlib,json,subprocess,sys,platform
root=Path("/home/elephant/MarsDog/marsdog-platform")
fresh=Path("/tmp/marsdog-developer-platform-2468639")
out=root/"out/developer-platform"
initial=json.loads((out/"initial-worktree/manifest.json").read_text())
observed={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in initial["files"]}
changed=[n for n in observed if observed[n]!=initial["files"][n]]
assert changed==[".github/workflows/vision.yml"],changed
protected=subprocess.check_output(["git","-C",str(root),"diff","--name-only","3bf529e","HEAD","--","modules","interfaces","config","robotics","third_party"]).decode().splitlines()
assert not protected, protected
records={}
for module in ("emotion","behavior","action","voice","vision"):
    python=fresh/"modules"/module/".venv/bin/python"
    code="import json,sys;print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'path':sys.path}))"
    data=json.loads(subprocess.check_output([str(python),"-I","-B","-c",code],cwd="/tmp",text=True))
    assert Path(data["prefix"]).is_relative_to(fresh)
    assert not any("/home/elephant/MarsDog/" in p for p in data["path"]),data
    records[module]=data
data={"status":"PASS","source_commit":subprocess.check_output(["git","-C",str(root),"rev-parse","HEAD"],text=True).strip(),"initial_base_commit":initial["commit"],"initial_uncommitted_files":len(initial["files"]),"only_changed_inherited_file":changed,"unchanged_protected_trees":["modules","interfaces","config","robotics","third_party"],"fresh_checkout":str(fresh),"isolated_python":records,"python":sys.version,"platform":platform.platform(),"shared_download_inputs":["/home/elephant/MarsDog/migration/.cache/uv","/home/elephant/MarsDog/marsdog-platform/out/ros-deps/*.deb"],"existing_host_prerequisites":["Ubuntu 22.04 x86_64","/usr/bin/python3.10","/opt/ros/humble","/home/elephant/MarsDog/migration/.tools/uv"],"notes":"No old source/environment/build/install copied. uv/deb cache and supplied vendor archives are explicit inputs."}
(out/"preservation-and-isolation.json").write_text(json.dumps(data,indent=2)+"\n")
print(json.dumps({"status":"PASS","preserved_files":len(initial["files"])-1,"reviewed_fixes":changed,"independent_environments":list(records)}))
