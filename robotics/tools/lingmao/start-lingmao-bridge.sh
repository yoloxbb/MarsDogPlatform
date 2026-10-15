#!/usr/bin/env bash
set -eo pipefail
root=${MARSDOG_ROOT:-/home/marsdog/MarsDogPlatform}
profile=${LINGMAO_PROFILE:-legacy}
case $profile in
  legacy) base=$root/out/rk3588-lingmao-communication-legacy ;;
  modern) base=$root/out/rk3588-lingmao-communication ;;
  *) echo 'LINGMAO_PROFILE must be legacy or modern' >&2; exit 2 ;;
esac
if [[ -f $base/robot.env ]]; then source "$base/robot.env"; fi
device=${1:-${ROBOT_DEVICE_ID:-}}
if [[ -z $device ]]; then
  printf '%s\n' 'Usage: bash start-lingmao-bridge.sh DEVICE_SN' \
    'Provide the target robot deviceNo from its App; a blank device ID is not accepted.' >&2
  exit 2
fi
if ! ip -4 -o address show dev eth0 | grep -q 'inet '; then
  echo 'eth0 has no IPv4 address; configure the robot-facing Ethernet network first.' >&2
  exit 1
fi
source "$base/use-lingmao-communication.sh"
exec ros2 launch uniubi_motion_bridge motion_bridge.launch.py device_id:="$device"
