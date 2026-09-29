"""Run real Nav2 failure/recovery contracts without competing business commands."""
from argparse import Namespace
import json

from runtime_environment import ROOT
import marsdog
import nav2_profile

def specs(directory):
    # Test freezes a navigator for less than the normal bond timeout; its task
    # cancellation deadline is shortened to observe RECOVERY_REQUIRED promptly.
    result = nav2_profile.specs(directory, marsdog.process_specs, marsdog.BUILD_TOOLS / "python", navigation_only=True)
    for name, command in result:
        if name == "waypoint":
            command += ["-p", "cancel_confirmation_timeout_sec:=1.0"]
    return result

if __name__ == "__main__":
    nav2_profile.check()
    marsdog.supervise(Namespace(command="smoke", duration=0),
        profile=nav2_profile.PROFILE, local=ROOT / "out/nav2-recovery",
        specs=specs, probe_script="nav2_recovery_probe.py",
        env_transform=nav2_profile.nav_environment, shutdown_hook=nav2_profile.shutdown)
