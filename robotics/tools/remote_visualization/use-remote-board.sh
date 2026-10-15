#!/usr/bin/env bash
# Shared board ROS environment, also loaded by the board's interactive .bashrc.
# The bridge wrapper may still use its original Ethernet-only SDK environment;
# board discovery receives Ethernet SPDP and exposes mapping over Wi-Fi unicast.
_remote_board_root=${MARSDOG_ROOT:-$HOME/MarsDogPlatform}
source "$_remote_board_root/out/rk3588-lingmao-communication-legacy/use-lingmao-communication.sh"
_remote_board_dds="$_remote_board_root/out/rk3588-remote-visualization/cyclonedds-board.xml"
if ! python3 "$_remote_board_root/robotics/tools/remote_visualization/configure-dds.py" \
    --role board --output "$_remote_board_dds" >/dev/null; then
  echo 'Unable to prepare DDS for the current board network.' >&2
  unset _remote_board_root _remote_board_dds
  return 1
fi
export CYCLONEDDS_URI="file://$_remote_board_dds"
unset _remote_board_root _remote_board_dds
