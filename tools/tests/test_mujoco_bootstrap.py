"""Offline checks for pinned optional bootstrap packages and workspace isolation."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('bootstrap', ROOT/'tools/fishbot_mujoco_bootstrap.py')
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class MujocoBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)/'project'
        self.workspace = self.project/'workspaces/fishbot_mujoco_ws'
        self.workspace.mkdir(parents=True)
        self.runtime = Path(self.temporary.name)/'private-prefix'
        self.debs = self.runtime/'debs'
        self.debs.mkdir(parents=True)
        self.pins = []
        for name, data in (('pkg-one', b'first archive'), ('pkg-two', b'second archive')):
            filename = name+'_1.2_amd64.deb'
            (self.debs/filename).write_bytes(data)
            self.pins.append({'package': name, 'version': '1.2', 'file': filename,
                              'sha256': hashlib.sha256(data).hexdigest()})
        self.lock = Path(self.temporary.name)/'packages.json'
        self.events = []

    def run_bootstrap(self, *, pins=None, no_link=False, default=False, mismatch=None):
        pins = copy.deepcopy(self.pins if pins is None else pins)
        lock = self.workspace/'src/fishbot_mujoco/docs/runtime-packages.json' if default else self.lock
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(json.dumps(pins))
        args = ['bootstrap', '--runtime', str(self.runtime)]
        if not default:
            args += ['--packages-file', str(lock)]
        if no_link:
            args.append('--no-link')
        def run(command, **kwargs):
            self.events.append(command)
            if command[:2] == ['dpkg-deb', '-f']:
                pin = next(p for p in self.pins if p['file'] == Path(command[2]).name)
                value = pin[command[3].lower()]
                if mismatch == (pin['package'], command[3]):
                    value = 'changed'
                return subprocess.CompletedProcess(command, 0, stdout=value+'\n')
            return subprocess.CompletedProcess(command, 0)
        with patch.object(bootstrap, '__file__', str(self.project/'tools/bootstrap.py')), \
                patch('sys.argv', args), patch.object(bootstrap.subprocess, 'run', side_effect=run), \
                patch('builtins.print'):
            bootstrap.main()

    def extracts(self):
        return [event for event in self.events if event[:2] == ['dpkg-deb', '-x']]

    def test_custom_set_verifies_every_selected_archive_before_extract_and_ignores_cached_others(self):
        (self.debs/'unrelated_9_amd64.deb').write_bytes(b'unrelated cached archive')
        self.run_bootstrap()
        self.assertEqual(self.events[0], ['apt-get', 'download', 'pkg-one=1.2', 'pkg-two=1.2'])
        first_extract = next(i for i, event in enumerate(self.events) if event[:2] == ['dpkg-deb', '-x'])
        self.assertEqual(len([e for e in self.events[:first_extract] if e[:2] == ['dpkg-deb', '-f']]), 4)
        self.assertEqual([Path(e[2]).name for e in self.extracts()], [p['file'] for p in self.pins])
        self.assertEqual(json.loads((self.runtime/'download-manifest.json').read_text()),
                         [{'file': p['file'], 'sha256': p['sha256']} for p in self.pins])
        self.assertEqual((self.workspace/'.runtime').resolve(), self.runtime)

    def test_missing_or_bad_hash_in_last_package_prevents_all_extraction(self):
        for missing in (True, False):
            with self.subTest(missing=missing):
                path = self.debs/self.pins[-1]['file']
                if missing:
                    path.unlink()
                else:
                    path.write_bytes(b'tampered bytes')
                self.events.clear()
                with self.assertRaisesRegex(ValueError, 'Missing|SHA256 mismatch'):
                    self.run_bootstrap()
                self.assertEqual(self.extracts(), [])
                self.assertFalse((self.runtime/'download-manifest.json').exists())

    def test_wrong_declared_package_or_version_prevents_all_extraction(self):
        for field in ('Package', 'Version'):
            with self.subTest(field=field):
                self.events.clear()
                with self.assertRaisesRegex(ValueError, 'mismatch'):
                    self.run_bootstrap(mismatch=('pkg-two', field))
                self.assertEqual(self.extracts(), [])

    def test_duplicate_package_or_filename_and_missing_pins_fail_before_download(self):
        cases = [self.pins+[copy.deepcopy(self.pins[0])],
                 [self.pins[0], {**self.pins[1], 'file': self.pins[0]['file']}]]
        for field in ('package', 'version', 'file', 'sha256'):
            pins = copy.deepcopy(self.pins); del pins[0][field]; cases.append(pins)
        for pins in cases:
            with self.subTest(pins=pins):
                self.events.clear()
                with self.assertRaises(ValueError):
                    self.run_bootstrap(pins=pins)
                self.assertEqual(self.events, [])

    def test_no_link_keeps_workspace_and_existing_link_untouched(self):
        self.run_bootstrap(no_link=True)
        link = self.workspace/'.runtime'
        self.assertFalse(link.exists()); self.assertFalse(link.is_symlink())
        other = Path(self.temporary.name)/'other-runtime'; other.mkdir()
        link.symlink_to(other, target_is_directory=True)
        self.run_bootstrap(no_link=True)
        self.assertEqual(link.resolve(), other)
        self.assertEqual(len(self.extracts()), 4)

    def test_default_lock_and_cached_deb_behavior_remain_compatible(self):
        default = [{'package': 'existing-pkg', 'version': '3.4'}]
        self.run_bootstrap(default=True, pins=default)
        self.assertEqual(self.events[0], ['apt-get', 'download', 'existing-pkg=3.4'])
        self.assertFalse(any(e[:2] == ['dpkg-deb', '-f'] for e in self.events))
        self.assertEqual([Path(e[2]).name for e in self.extracts()], sorted(p['file'] for p in self.pins))
        self.assertEqual((self.workspace/'.runtime').resolve(), self.runtime)

    def test_public_cyclone_pins_and_localhost_configuration_have_only_declared_scope(self):
        pins = json.loads((ROOT/'tools/config/fishbot_cyclonedds_packages.json').read_text())
        bootstrap.validate_pins(pins)
        self.assertEqual(len(pins), 7)
        self.assertEqual({p['package'] for p in pins}, {'libacl1-dev', 'libattr1-dev',
            'ros-jazzy-cyclonedds', 'ros-jazzy-rmw-cyclonedds-cpp', 'ros-jazzy-iceoryx-binding-c',
            'ros-jazzy-iceoryx-hoofs', 'ros-jazzy-iceoryx-posh'})
        self.assertTrue(all(set(p) == {'package', 'version', 'sha256', 'file'} for p in pins))
        domain = ET.parse(ROOT/'tools/config/fishbot_cyclonedds_localhost.xml').getroot()[0]
        self.assertEqual(domain.attrib, {'Id': '129'})
        ns = {'c': 'https://cdds.io/config'}
        self.assertEqual(domain.find('c:General/c:Interfaces/c:NetworkInterface', ns).attrib,
                         {'name': 'lo', 'multicast': 'false'})
        self.assertEqual(domain.find('c:General/c:AllowMulticast', ns).text, 'false')
        self.assertEqual(domain.find('c:SharedMemory/c:Enable', ns).text, 'false')


if __name__ == '__main__':
    unittest.main()
