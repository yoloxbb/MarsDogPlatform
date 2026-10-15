#!/usr/bin/env bash
# Source in the PC's Ubuntu 22.04 WSL terminal.
_remote_viz_tools=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ! -f /opt/ros/humble/setup.bash ]]; then
  echo 'ROS 2 Humble is required on the visualization PC.' >&2
  return 1
fi
source /opt/ros/humble/setup.bash
export MARSDOG_VIZ_ASSETS=${MARSDOG_VIZ_ASSETS:-$HOME/.local/share/marsdog/remote-visualization}
if ! command -v powershell.exe >/dev/null || ! command -v wslpath >/dev/null; then
  echo 'Automatic board discovery requires Windows PowerShell interoperability in WSL.' >&2
  return 1
fi
_remote_viz_helper=$(wslpath -a -w "$_remote_viz_tools/prepare-remote-network.ps1")
_remote_viz_arguments=(-NoProfile -ExecutionPolicy Bypass -File "$_remote_viz_helper")
if [[ -n ${MARSDOG_BOARD_IP:-} ]]; then
  _remote_viz_arguments+=(-PreferredIP "$MARSDOG_BOARD_IP")
fi
if ! _remote_viz_network=$(powershell.exe "${_remote_viz_arguments[@]}" </dev/null); then
  echo 'Unable to discover the paired board or prepare the Windows firewall.' >&2
  unset _remote_viz_tools _remote_viz_helper _remote_viz_arguments _remote_viz_network
  return 1
fi
MARSDOG_BOARD_IP=$(printf '%s' "$_remote_viz_network" | python3 -c \
  'import json,sys; print(json.loads(sys.stdin.read().lstrip("\ufeff"))["boardIP"])') || return 1
export MARSDOG_BOARD_IP
if [[ -d "$MARSDOG_VIZ_ASSETS/description_overlay" ]]; then
  export AMENT_PREFIX_PATH="$MARSDOG_VIZ_ASSETS/description_overlay:${AMENT_PREFIX_PATH:-}"
fi
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=42 ROS_LOCALHOST_ONLY=0
# The initial two-window Intel/WSLg GPU run coincided with a whole-host freeze.
# Keep this dedicated visualization session on bounded CPU rendering by default.
export LIBGL_ALWAYS_SOFTWARE=true
export LP_NUM_THREADS=2 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
_remote_viz_dds="$HOME/.cache/marsdog/remote-visualization/cyclonedds-pc.xml"
python3 "$_remote_viz_tools/configure-dds.py" --role pc --peer "$MARSDOG_BOARD_IP" \
  --output "$_remote_viz_dds" >/dev/null || return 1
export CYCLONEDDS_URI="file://$_remote_viz_dds"
unset _remote_viz_tools _remote_viz_dds _remote_viz_helper _remote_viz_arguments _remote_viz_network
