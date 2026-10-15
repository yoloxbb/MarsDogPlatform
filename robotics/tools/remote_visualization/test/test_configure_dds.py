"""Offline network-change regression; never starts DDS or contacts hardware."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET


SOURCE = Path(__file__).resolve().parents[1] / 'configure-dds.py'
SPEC = importlib.util.spec_from_file_location('configure_dds', SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NetworkChangeTests(unittest.TestCase):
    def generate(self, wifi, wifi_name='wlan0', wifi_present=True):
        addresses = [{'ifname': 'eth0', 'addr_info': [
            {'family': 'inet', 'local': '192.168.50.1', 'scope': 'global'}]}]
        if wifi_present:
            addresses.append({'ifname': wifi_name, 'addr_info': [
                {'family': 'inet', 'local': wifi, 'scope': 'global'}]})
        routes = [{'dst': 'default', 'dev': wifi_name}] if wifi_present else []
        def output(command, **kwargs):
            return json.dumps(addresses if command[-1] == 'addr' else routes)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'dds.xml'
            with patch('sys.argv', ['configure-dds.py', '--role', 'board', '--output', str(target)]), \
                    patch.object(MODULE.subprocess, 'check_output', side_effect=output):
                MODULE.main()
            return ET.parse(target).getroot()

    def test_new_wifi_has_current_self_peer_without_fixed_computer_ip(self):
        root = self.generate('10.42.7.118')
        peers = [p.attrib['Address'] for p in root.findall('./Domain/Discovery/Peers/Peer')]
        self.assertEqual(set(peers), {'10.42.7.118', '192.168.50.1'})
        self.assertNotIn('192.168.5.99', peers)
        self.assertNotIn('192.168.5.101', peers)

    def test_discovery_still_receives_robot_ethernet_multicast(self):
        root = self.generate('10.42.7.118')
        self.assertEqual(root.findtext('./Domain/General/AllowMulticast'), 'spdp')
        self.assertEqual(root.findtext('./Domain/General/MulticastRecvNetworkInterfaceAddresses'), 'all')
        self.assertTrue(all(i.attrib['multicast'] == 'true'
                            for i in root.findall('./Domain/General/Interfaces/NetworkInterface')))

    def test_new_default_route_interface_is_preferred(self):
        root = self.generate('172.20.10.3', wifi_name='wlp1s0')
        interfaces = root.findall('./Domain/General/Interfaces/NetworkInterface')
        self.assertEqual([i.attrib['name'] for i in interfaces], ['wlp1s0', 'eth0'])

    def test_ethernet_only_start_has_no_missing_wifi_interface(self):
        root = self.generate(None, wifi_present=False)
        interfaces = root.findall('./Domain/General/Interfaces/NetworkInterface')
        self.assertEqual([i.attrib['name'] for i in interfaces], ['eth0'])


if __name__ == '__main__':
    unittest.main()
