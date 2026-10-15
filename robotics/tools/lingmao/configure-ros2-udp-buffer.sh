#!/usr/bin/env bash
# Reusable RK3588 ROS 2 receive-buffer setup; does not restart any service.
set -euo pipefail
if [[ ${1:-} == --help ]]; then
  printf '%s\n' 'Usage: sudo bash configure-ros2-udp-buffer.sh --apply'
  exit 0
fi
[[ ${1:-} == --apply ]] || { echo 'Expected --apply; use --help for usage.' >&2; exit 2; }
[[ $EUID == 0 ]] || { echo 'Run with sudo in the board terminal; this changes a kernel setting and /etc/sysctl.d.' >&2; exit 1; }
root=${MARSDOG_ROOT:-/home/marsdog/MarsDogPlatform}
[[ -f "$root/AGENTS.md" ]] || { echo 'MARSDOG_ROOT must point to MarsDogPlatform.' >&2; exit 1; }
target=/etc/sysctl.d/99-marsdog-ros2-udp.conf
marker='# Managed by MarsDog ROS2 UDP receive-buffer setup'
limit=8388608
if [[ -L $target ]]; then
  echo "Refusing symlink target: $target" >&2
  exit 1
fi
if [[ -e $target ]] && ! grep -Fxq "$marker" "$target"; then
  echo "Existing unowned configuration will not be overwritten: $target" >&2
  exit 1
fi
old=$(sysctl -n net.core.rmem_max)
install -d -m 755 "$root/out/rk3588-lingmao-communication-legacy/network-backups"
backup=$(mktemp -d "$root/out/rk3588-lingmao-communication-legacy/network-backups/udp-buffer-XXXXXXXX")
chmod 755 "$backup"
printf '%s\n' "$old" > "$backup/rmem_max.before"
if [[ -f $target ]]; then
  cp -p "$target" "$backup/sysctl.conf.before"
else
  touch "$backup/config-was-absent"
fi
pending=$(mktemp)
trap 'rm -f "$pending"' EXIT
printf '%s\n' "$marker" 'net.core.rmem_max = 8388608' > "$pending"
install -m 644 "$pending" "$target"
if ! sysctl -p "$target"; then
  if [[ -f "$backup/sysctl.conf.before" ]]; then
    cp -p "$backup/sysctl.conf.before" "$target"
  else
    rm -f "$target"
  fi
  sysctl -w "net.core.rmem_max=$old" || true
  echo "Apply failed; previous configuration restored. Backup: $backup" >&2
  exit 1
fi
actual=$(sysctl -n net.core.rmem_max)
[[ $actual == "$limit" ]] || { echo "Unexpected rmem_max: $actual" >&2; exit 1; }
printf 'Applied: net.core.rmem_max=%s\nPersistent file: %s\nBackup: %s\n' "$actual" "$target" "$backup"
printf '%s\n' 'No service was restarted. New DDS sockets can request larger buffers.'
