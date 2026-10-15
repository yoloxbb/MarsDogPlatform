#!/usr/bin/env bash
set -eo pipefail
tools=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$tools/use-remote-viz.sh"
if [[ ${1:-} == --prepare-only ]]; then
  printf 'Automatic network ready: board=%s, domain=%s, DDS=%s\n' \
    "$MARSDOG_BOARD_IP" "$ROS_DOMAIN_ID" "$CYCLONEDDS_URI"
  exit 0
fi
if [[ -z ${DISPLAY:-} && -z ${WAYLAND_DISPLAY:-} ]]; then
  echo 'No GUI display is available. Run this in WSLg or a Linux desktop session.' >&2
  exit 1
fi
for package in rviz2 rtabmap_viz rtabmap_rviz_plugins; do
  ros2 pkg prefix "$package" >/dev/null
done
mkdir -p "$MARSDOG_VIZ_ASSETS/runs"
pid_file="$MARSDOG_VIZ_ASSETS/runs/visualization-launch.pid"
if [[ -f "$pid_file" ]]; then
  read -r previous_pid < "$pid_file"
  if [[ $previous_pid =~ ^[0-9]+$ && -r /proc/$previous_pid/cmdline ]] && \
     [[ $(tr '\0' ' ' < "/proc/$previous_pid/cmdline") == *"/remote_viz.launch.py"* ]]; then
    printf 'Remote visualization is already running (PID %s).\n' "$previous_pid"
    exit 0
  fi
fi
printf '%s\n' "$$" > "$pid_file"
exec ros2 launch "$tools/remote_viz.launch.py" "$@"
