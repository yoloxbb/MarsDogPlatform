"""Generate isolated run configuration from original resources without editing them."""
import argparse
import json
from pathlib import Path
import shutil
import yaml

ROOT = Path(__file__).resolve().parents[1]

def prepare(run, install, profile_name="lite3-local-cpu"):
    profile = json.loads((ROOT / "config/profiles" / (profile_name + ".json")).read_text())
    run.mkdir(parents=True, exist_ok=True)
    share = lambda package: install / package / "share" / package
    voice_share = share("marsdog_voice_interaction") / "config"
    voice = yaml.safe_load((voice_share / "voice.mock.yaml").read_text())
    voice["mock"].update(seed=profile["voice_mock_seed"],
                         event_interval_sec=profile["voice_event_interval_sec"])
    voice["mock"]["command_catalog"] = str(voice_share / "command_catalog.yaml")
    voice["logging"].update(dir=str(run / "voice-log"), file=True, console=True)
    voice["storage"]["root"] = str(run / "voice-data")
    for key in ("command_lexicon", "object_target_routing"):
        voice[key]["catalog"] = str(voice_share / Path(voice[key]["catalog"]).name)
    (run / "voice.yaml").write_text(yaml.safe_dump(voice, allow_unicode=True))
    vision = yaml.safe_load((share("marsdog_vision_interaction") / "config/vision.mock.yaml").read_text())
    vision["logging"]["dir"] = str(run / "vision-log")
    vision["storage"]["root"] = str(run / "vision-data")
    (run / "vision.yaml").write_text(yaml.safe_dump(vision, allow_unicode=True))
    action = run / "action-config"
    shutil.copytree(share("marsdog_action_executor") / "config", action)
    for filename in ("uwb_follow.yaml", "wake_orientation.yaml", "visual_target_approach.yaml"):
        path = action / filename
        data = yaml.safe_load(path.read_text())
        data["enabled"] = False
        path.write_text(yaml.safe_dump(data, allow_unicode=True))
    path = action / "sound_config.yaml"
    data = yaml.safe_load(path.read_text())
    data["bark_sound"]["enabled"] = False
    path.write_text(yaml.safe_dump(data, allow_unicode=True))
    path = action / "navigation_waypoints.yaml"
    navigation = yaml.safe_load(path.read_text())
    navigation["enabled"] = True
    path.write_text(yaml.safe_dump(navigation, allow_unicode=True))
    waypoints = {"version": 1, "frame_id": "map", "map": "SIMULATED_MAP",
                 "resolution": 0.1, "origin": [0.0, 0.0, 0.0], "size": [80, 80],
                 "waypoints": []}
    for index, (key, name) in enumerate(navigation["waypoint_nav"]["places"].items()):
        waypoints["waypoints"].append({"id": key, "name": name, "pose": {
            "position": {"x": float(index + 1), "y": 1.0, "z": 0.0},
            "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}}})
    (run / "waypoints.yaml").write_text(yaml.safe_dump(waypoints, allow_unicode=True))
    if profile_name == "lite3-nav2-cpu":
        config = yaml.safe_load((ROOT / "config/nav2/cpu.yaml").read_text())
        bt = config["bt_navigator"]["ros__parameters"]
        bt["default_nav_to_pose_bt_xml"] = str(ROOT / "config/nav2/cpu.xml")
        bt["default_nav_through_poses_bt_xml"] = str(ROOT / "config/nav2/through_poses.xml")
        (run / "nav2.yaml").write_text(yaml.safe_dump(config))
    (run / "profile.json").write_text(json.dumps(profile, indent=2) + "\n")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--profile", choices=("lite3-local-cpu", "lite3-nav2-cpu"), default="lite3-local-cpu")
    args = parser.parse_args()
    prepare(args.run.resolve(), args.install.resolve(), args.profile)

if __name__ == "__main__":
    main()
