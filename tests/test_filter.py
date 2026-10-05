import importlib.util
import ipaddress
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('uu_filter', Path(__file__).resolve().parents[1] / 'filter.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class ProxyFlowRegression(unittest.TestCase):
    def setUp(self):
        mod.ADDRESS = '192.0.2.10'
        mod.NETWORK = ipaddress.IPv4Network('192.0.2.0/24')
        mod.PROCESS_PREFIX = 'UURemote'

    def test_vif_local_address_still_discovers_overlay_destination(self):
        # The application-facing socket and the proxy's upstream socket have
        # different local addresses/ports. The peer endpoint identifies both.
        listing = ('p123\ncUURemote\nf1\nPTCP\nn198.18.0.1:55001->192.0.2.11:59001\n'
                   'f2\nPUDP\nn192.0.2.10:48000\n'
                   'f3\nPTCP\nn198.18.0.1:55002->203.0.113.20:443\n'
                   'p456\ncUURemoteImpostor\nf4\nPTCP\nn192.0.2.10:55003->192.0.2.12:22\n')
        result = subprocess.CompletedProcess([], 0, stdout=listing, stderr='')
        with patch.object(mod, 'run', return_value=result), patch.object(mod, 'is_uu', side_effect=lambda pid: pid == 123):
            found = mod.ports()
        self.assertEqual(found['TCP'], {55001})
        self.assertEqual(found['UDP'], {48000})
        self.assertEqual(found['remote_endpoints'], {('TCP', '192.0.2.11', 59001)})
        rules = mod.build_rules('feth123', found)
        self.assertIn('from any to 192.0.2.11 port 59001', rules)
        self.assertIn('from 192.0.2.11 port 59001 to any', rules)
        self.assertNotIn('203.0.113.20', rules)
        self.assertNotIn('55003', rules)
        self.assertNotIn('on feth', rules)

    def test_inactive_interface_installs_no_block_rules(self):
        self.assertEqual(mod.build_rules(None, {'TCP': {55001}, 'UDP': set(), 'remote_endpoints': set()}), '\n')

if __name__ == '__main__':
    unittest.main()
