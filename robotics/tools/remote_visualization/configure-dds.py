#!/usr/bin/env python3
"""Write the explicit DDS interfaces used by board mapping or PC visualization."""
import argparse
import ipaddress
import json
import pathlib
import subprocess
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=('board', 'pc'), required=True)
    parser.add_argument('--peer', type=ipaddress.IPv4Address)
    parser.add_argument('--interface', action='append')
    parser.add_argument('--output', required=True, type=pathlib.Path)
    args = parser.parse_args()
    if args.role == 'pc' and args.peer is None:
        parser.error('--peer is required for the PC role')
    interfaces = args.interface
    if not interfaces:
        if args.role == 'board':
            addresses = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr'], text=True))
            active = {item['ifname'] for item in addresses if any(
                address['family'] == 'inet' and address.get('scope') != 'host'
                for address in item.get('addr_info', []))}
            routes = json.loads(subprocess.check_output(['ip', '-j', '-4', 'route'], text=True))
            preferred = next((route['dev'] for route in routes if route.get('dst') == 'default'
                              and route.get('dev') in active), None)
            interfaces = list(dict.fromkeys(name for name in (preferred, 'wlan0', 'eth0')
                                           if name in active))
        else:
            route = json.loads(subprocess.check_output(
                ['ip', '-j', 'route', 'get', str(args.peer)], text=True))
            interfaces = [route[0]['dev']]
    available = json.loads(subprocess.check_output(['ip', '-j', '-4', 'addr'], text=True))
    names = {entry['ifname'] for entry in available if entry.get('addr_info')}
    if not interfaces or any(name not in names for name in interfaces):
        parser.error('Every selected interface must exist and have an IPv4 address')
    root = ET.Element('CycloneDDS')
    domain = ET.SubElement(root, 'Domain', Id='any')
    general = ET.SubElement(domain, 'General')
    devices = ET.SubElement(general, 'Interfaces')
    for index, name in enumerate(dict.fromkeys(interfaces)):
        ET.SubElement(devices, 'NetworkInterface', name=name,
                      priority='10' if args.role == 'board' and index == 0 else '0',
                      multicast='true' if args.role == 'board' else 'false')
    # Cyclone 0.10.5 disables multicast globally if any selected interface is
    # marked non-multicast. Keep both board interfaces capable, receive discovery
    # on both, and restrict multicast to SPDP. Application data remains unicast.
    ET.SubElement(general, 'AllowMulticast').text = 'spdp' if args.role == 'board' else 'false'
    ET.SubElement(general, 'MulticastRecvNetworkInterfaceAddresses').text = (
        'all' if args.role == 'board' else 'none')
    ET.SubElement(general, 'DontRoute').text = 'false'
    # Avoid IP fragmentation on the existing WSL/Wi-Fi transport.
    ET.SubElement(general, 'MaxMessageSize').text = '1200B'
    ET.SubElement(general, 'FragmentSize').text = '1000B'
    discovery = ET.SubElement(domain, 'Discovery')
    ET.SubElement(discovery, 'ParticipantIndex').text = 'auto'
    ET.SubElement(discovery, 'MaxAutoParticipantIndex').text = '30'
    peers = ET.SubElement(discovery, 'Peers')
    peer_addresses = set()
    if args.peer is not None:
        ET.SubElement(peers, 'Peer', Address=str(args.peer))
        peer_addresses.add(str(args.peer))
    for name in dict.fromkeys(interfaces):
        entry = next(entry for entry in available if entry['ifname'] == name)
        for address in entry['addr_info']:
            if address['family'] == 'inet' and address['local'] not in peer_addresses:
                ET.SubElement(peers, 'Peer', Address=address['local'])
                peer_addresses.add(address['local'])
    internal = ET.SubElement(domain, 'Internal')
    ET.SubElement(internal, 'SocketReceiveBufferSize', min='1MB', max='4MB')
    ET.indent(root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    contents = ET.tostring(root, encoding='unicode') + '\n'
    if not args.output.exists() or args.output.read_text(encoding='utf-8') != contents:
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=args.output.parent, delete=False) as stream:
            stream.write(contents)
            temporary = pathlib.Path(stream.name)
        try:
            os.replace(temporary, args.output)
        finally:
            temporary.unlink(missing_ok=True)
    print(json.dumps({'role': args.role, 'interfaces': interfaces,
                      'peer': str(args.peer) if args.peer is not None else None,
                      'output': str(args.output)}))


if __name__ == '__main__':
    main()
