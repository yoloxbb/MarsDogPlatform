#!/usr/bin/env bash
# Install the paired DNS-SD advertisement into the existing system Avahi service.
set -euo pipefail
if [[ $EUID -ne 0 ]]; then
  echo 'Run with sudo; this installs /etc/avahi/services/marsdog-rk3588.service.' >&2
  exit 1
fi
tools=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source_file=${1:-$tools/board-discovery.service}
target=/etc/avahi/services/marsdog-rk3588.service
if [[ ! -f $source_file ]]; then echo 'Missing paired board-discovery.service.' >&2; exit 1; fi
if [[ -e $target ]] && ! grep -q 'Managed by MarsDog remote visualization' "$target"; then
  echo 'Refusing to replace an unmanaged Avahi service file.' >&2
  exit 1
fi
install -d -m 755 /etc/avahi/services
if [[ -f $target ]]; then
  backup="$tools/../../../out/rk3588-remote-visualization/backups/avahi-$(date +%Y%m%d-%H%M%S)"
  install -d -m 700 "$backup"
  cp -p -- "$target" "$backup/board-discovery.service"
fi
install -m 644 -- "$source_file" "$target"
systemctl enable avahi-daemon.service >/dev/null
if systemctl is-active --quiet avahi-daemon.service; then
  systemctl reload avahi-daemon.service
else
  systemctl start avahi-daemon.service
fi
echo 'MarsDog board discovery installed in system Avahi; no robot or ROS node was restarted.'
