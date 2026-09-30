import json, subprocess
from pathlib import Path
import yaml
root = Path("/home/elephant/MarsDog/marsdog-platform")
def unique(node, path):
    if isinstance(node, yaml.MappingNode):
        keys = set()
        for key, value in node.value:
            assert key.value not in keys, f"{path}:{key.start_mark.line+1}: duplicate {key.value}"
            keys.add(key.value)
            unique(value,path)
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            unique(item,path)
records = {}
for path in sorted((root / ".github/workflows").glob("*.yml")):
    unique(yaml.compose(path.read_text(),Loader=yaml.BaseLoader),path)
    doc = yaml.load(path.read_text(),Loader=yaml.BaseLoader)
    assert {"name","on","jobs"} <= doc.keys()
    runs = []
    for job in doc["jobs"].values():
        assert "runs-on" in job
        for step in job["steps"]:
            assert ("run" in step) != ("uses" in step), step
            if "run" in step:
                subprocess.run(["bash","-n"], input=step["run"],text=True,check=True)
                runs.append(step["run"])
    records[path.name] = runs
print(json.dumps({"status":"PASS","scope":"All workflow YAML parsed with duplicate-key rejection; run steps checked with bash -n. Hosted runner not executed.","workflows":records},indent=2))
