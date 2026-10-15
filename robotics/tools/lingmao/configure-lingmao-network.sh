#!/usr/bin/env bash
# Only the RK3588 board's robot-facing Ethernet connection is changed.
set -euo pipefail
mode=${1:-}
if [[ $mode != --modern-static && $mode != --legacy-dhcp ]]; then
  printf '%s\n' 'Usage: sudo bash configure-lingmao-network.sh --modern-static' \
    '       sudo bash configure-lingmao-network.sh --legacy-dhcp' \
    'Use legacy DHCP for firmware older than Cyvet-V1.00.002; never enable both profiles.' >&2
  exit 2
fi
if [[ $EUID != 0 ]]; then
  printf '%s\n' 'NetworkManager system changes require sudo; run this script in your board terminal.' >&2
  exit 1
fi
iface=${LINGMAO_NIC:-eth0}
[[ -e /sys/class/net/$iface/carrier ]] || { echo "No interface: $iface" >&2; exit 1; }
[[ $(cat "/sys/class/net/$iface/carrier") == 1 ]] || { echo 'Ethernet cable has no carrier' >&2; exit 1; }
root=${MARSDOG_ROOT:-/home/marsdog/MarsDogPlatform}
if [[ $mode == --legacy-dhcp ]]; then
  base=$root/out/rk3588-lingmao-communication-legacy
  name=lingmao-legacy-ethernet
  address=192.168.50.1/24
  if ! command -v dnsmasq >/dev/null; then
    apt-get update
    apt-get install -y dnsmasq-base
  fi
  if ss -Hlun 'sport = :67' | grep -q . && ! systemctl is-active --quiet marsdog-lingmao-dhcp; then
    echo 'UDP 67 is occupied by another DHCP server; inspect it before proceeding.' >&2
    exit 1
  fi
else
  base=$root/out/rk3588-lingmao-communication
  name=lingmao-ethernet
  address=172.29.140.2/24
fi
mkdir -p "$base/network-backups"
stamp=$(date +%Y%m%dT%H%M%S)
ip -j address show dev "$iface" > "$base/network-backups/address-$stamp.json"
ip -j route show > "$base/network-backups/routes-$stamp.json"
nmcli -f NAME,UUID,TYPE,DEVICE connection show > "$base/network-backups/connections-$stamp.txt"
if [[ $mode == --legacy-dhcp ]] && nmcli -g connection.id connection show lingmao-ethernet >/dev/null 2>&1; then
  nmcli connection modify lingmao-ethernet connection.autoconnect no
fi
if ! nmcli -g connection.id connection show "$name" >/dev/null 2>&1; then
  nmcli connection add type ethernet ifname "$iface" con-name "$name" \
    ipv4.method manual ipv4.addresses "$address" ipv4.never-default yes \
    ipv4.ignore-auto-dns yes ipv6.never-default yes ipv6.ignore-auto-dns yes \
    connection.autoconnect yes connection.autoconnect-priority 50
else
  [[ $(nmcli -g connection.interface-name connection show "$name") == "$iface" ]] || \
    { echo 'Existing lingmao-ethernet profile belongs to another interface' >&2; exit 1; }
  nmcli connection modify "$name" ipv4.method manual ipv4.addresses "$address" \
    ipv4.gateway '' ipv4.dns '' ipv4.never-default yes ipv4.ignore-auto-dns yes \
    ipv6.never-default yes ipv6.ignore-auto-dns yes \
    connection.autoconnect yes connection.autoconnect-priority 50
fi
nmcli connection up "$name" ifname "$iface"
ip -4 address show dev "$iface"
if [[ $mode == --legacy-dhcp ]]; then
  config=/etc/dnsmasq.d/marsdog-lingmao-eth0.conf
  unit=/etc/systemd/system/marsdog-lingmao-dhcp.service
  for target in "$config" "$unit"; do
    if [[ -e $target ]] && ! grep -q 'Managed by MarsDog lingmao communication' "$target"; then
      echo "Existing unowned configuration will not be overwritten: $target" >&2
      exit 1
    fi
  done
  install -d -m 755 /etc/dnsmasq.d /var/lib/marsdog-lingmao-dhcp
  chown nobody:nogroup /var/lib/marsdog-lingmao-dhcp
  cat > "$config" <<EOF
# Managed by MarsDog lingmao communication
interface=$iface
bind-interfaces
port=0
user=nobody
group=nogroup
dhcp-range=192.168.50.100,192.168.50.200,255.255.255.0,12h
dhcp-option=3
dhcp-option=6
dhcp-leasefile=/var/lib/marsdog-lingmao-dhcp/leases
log-dhcp
EOF
  chmod 644 "$config"
  dnsmasq --test --conf-file="$config"
  cat > "$unit" <<'EOF'
# Managed by MarsDog lingmao communication
[Unit]
Description=MarsDog Lingmao Ethernet-only DHCP
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=simple
ExecStart=/usr/sbin/dnsmasq --keep-in-foreground --conf-file=/etc/dnsmasq.d/marsdog-lingmao-eth0.conf --pid-file=/run/marsdog-lingmao-dhcp.pid
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
  chmod 644 "$unit"
  systemctl daemon-reload
  systemctl enable --now marsdog-lingmao-dhcp
  systemctl restart marsdog-lingmao-dhcp
  for attempt in $(seq 1 15); do
    if [[ -s /var/lib/marsdog-lingmao-dhcp/leases ]]; then
      cat /var/lib/marsdog-lingmao-dhcp/leases
      printf '%s\n' 'DHCP lease received. Next verify the robot identity, Ping and read-only DDS/RPC.'
      exit 0
    fi
    sleep 2
  done
  systemctl --no-pager --full status marsdog-lingmao-dhcp || true
  printf '%s\n' 'DHCP is configured but no lease has arrived yet; reconnect the robot Ethernet cable to trigger DHCP.'
  exit 3
fi
ip route get 172.29.140.1
ping -I "$iface" -c 4 -W 2 172.29.140.1
printf '%s\n' 'Network reachability verified. DDS/RPC and robot identity still require separate verification.'
