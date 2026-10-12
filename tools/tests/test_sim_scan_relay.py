"""Synthetic fixture and dropped-scan contracts; no ROS context or devices."""
import importlib.util
import json
import math
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import xml.etree.ElementTree as ET

import yaml


TOOLS = Path(__file__).resolve().parents[1]
ROOT = TOOLS.parent
PACKAGE = ROOT / 'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


relay = load('scan_relay', TOOLS / 'fishbot_sim_scan_relay.py')
fixture = load('passage_fixture', TOOLS / 'fishbot_passage_sim.launch.py')


class ScanGapTests(unittest.TestCase):
    def setUp(self):
        self.events, self.published = [], []
        self.gap = relay.ScanGap(.9, .15, self.events.append, 10.)
        self.gap.observe_truth(0., 0., 0., 100., 100., 10.)

    def test_request_without_actual_motion_cannot_trigger_gap(self):
        self.gap.observe_truth(.2, 0., 0., 100.1, 100.1, 10.1)
        self.assertIsNone(self.gap.gap_start)
        self.assertTrue(self.gap.forward(object(), 100.1, 10.1, 100.1, self.published.append))

    def test_stale_future_nonfinite_and_repeated_truth_cannot_trigger_gap(self):
        for stamp, ros_now, x in ((99., 100.1, .2), (101., 100.1, .2),
                                   (100.1, 100.1, math.nan), (100., 100., .2)):
            self.gap.observe_truth(x, 0., .05, stamp, ros_now, 10.1)
            self.assertIsNone(self.gap.gap_start)

    def test_gap_stops_forwarding_and_restores_new_message_with_original_stamp(self):
        before = SimpleNamespace(header=SimpleNamespace(stamp=100.05))
        self.gap.forward(before, 100.05, 10.05, 100.05, self.published.append)
        self.gap.observe_truth(.16, 0., .05, 100.1, 100.1, 10.1)
        dropped = SimpleNamespace(header=SimpleNamespace(stamp=100.2))
        self.assertFalse(self.gap.forward(dropped, 100.2, 10.2, 100.2, self.published.append))
        # The simulation clock can remain frozen; the gap still ends on steady time.
        self.gap.tick(11.01, 100.2)
        after = SimpleNamespace(header=SimpleNamespace(stamp=101.02))
        self.assertTrue(self.gap.forward(after, 101.02, 11.02, 101.04, self.published.append))
        self.assertEqual(self.published, [before, after])
        self.assertIs(self.published[-1], after)
        self.assertEqual(after.header.stamp, 101.02)
        self.assertEqual([e['event'] for e in self.events], ['gap_started', 'gap_ended', 'scan_restored'])
        restored = self.events[-1]
        self.assertEqual(restored['dropped_count'], 1)
        self.assertEqual(restored['sim_stamp'], after.header.stamp)
        self.assertEqual(restored['last_forwarded_stamp'], before.header.stamp)
        self.assertEqual(restored['steady_time'], 11.02)
        self.assertEqual(restored['pose'], {'x': .16, 'y': 0.})

    def test_gap_is_one_shot_even_after_further_motion(self):
        self.gap.observe_truth(.16, 0., .05, 100.1, 100.1, 10.1)
        self.gap.forward(object(), 101.1, 11.1, 101.1, self.published.append)
        self.gap.observe_truth(.4, 0., .05, 101.2, 101.2, 11.2)
        self.assertTrue(self.gap.forward(object(), 101.3, 11.3, 101.3, self.published.append))
        self.assertEqual(sum(e['event'] == 'gap_started' for e in self.events), 1)

    def test_recorder_is_private_exclusive_and_rejects_source_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'events.jsonl'
            recorder = relay.EventRecorder(path)
            recorder({'event': 'example'})
            recorder.close()
            self.assertEqual(json.loads(path.read_text()), {'event': 'example'})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                relay.EventRecorder(path)
        with self.assertRaises(ValueError):
            relay.EventRecorder(ROOT / 'public-events.jsonl')

    def test_preview_does_not_load_ros_or_create_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'not-created.jsonl'
            result = subprocess.run([sys.executable, str(TOOLS / 'fishbot_sim_scan_relay.py'),
                '--output', str(output)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(output.exists())


class PassageFixtureTests(unittest.TestCase):
    def build(self, path, **options):
        return fixture.build_fixture(PACKAGE / 'mjcf/passage.xml', PACKAGE / 'config/plugins.yaml',
                                     path, fixture.fixture_options(96, **options))

    def test_generated_door_clearance_matches_map_and_model_yaw(self):
        source = (PACKAGE / 'mjcf/fishbot.xml').read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            generated = self.build(Path(temporary) / 'fixture', door_width_m=.40, initial_yaw_rad=.2)
            scene = ET.parse(generated['generated_scene'])
            left = scene.getroot().find("worldbody/geom[@name='door_left']")
            right = scene.getroot().find("worldbody/geom[@name='door_right']")
            lower = float(left.get('pos').split()[1])-float(left.get('size').split()[1])
            upper = float(right.get('pos').split()[1])+float(right.get('size').split()[1])
            self.assertAlmostEqual(lower-upper, .40)
            model = ET.parse(generated['generated_model'])
            quaternion = list(map(float, model.getroot().find("worldbody/body[@name='base_footprint']").get('quat').split()))
            self.assertAlmostEqual(2*math.atan2(quaternion[3], quaternion[0]), .2)
            self.assertEqual(generated['map_to_odom'], [0., 0., .2])
            image = Path(yaml.safe_load(Path(generated['generated_map']).read_text())['image']).read_bytes()
            pixels = image.split(b'\n', 3)[3]
            # Static doorway x=.65: centerline stays free; y=.3 is occupied.
            col = math.floor((.65+.9)/.02)
            index = lambda y: (119-math.floor((y+1.2)/.02))*160+col
            self.assertEqual(pixels[index(0.)], 254)
            self.assertEqual(pixels[index(.3)], 0)
            self.assertTrue((Path(temporary) / 'fixture/provenance.json').is_file())
        self.assertEqual((PACKAGE / 'mjcf/fishbot.xml').read_bytes(), source)

    def test_scan_plugins_route_every_consumer_through_relay_without_frame_forgery(self):
        with tempfile.TemporaryDirectory() as temporary:
            generated = self.build(Path(temporary) / 'fixture', scan_gap_s=.9, timing_profile='tolerant')
            params = yaml.safe_load(Path(generated['generated_plugins']).read_text())
            laser = params['/**']['ros__parameters']['mujoco_plugins']['rangefinder_lidar_plugin']['laser']
            self.assertEqual(laser['laserscan_topic'], '/scan_raw')
            self.assertEqual(generated['scan_output'], '/scan')
            geometry = yaml.safe_load(Path(generated['generated_geometry']).read_text())
            self.assertEqual(geometry['frames']['scan'], laser['frame_name'])
            original = yaml.safe_load((TOOLS / 'config/fishbot_model_geometry.yaml').read_text())
            self.assertEqual(geometry['footprint'], original['footprint'])
            self.assertEqual(geometry['collision'], original['collision'])

    def test_disabled_gap_preserves_existing_scan_topic_and_other_domains(self):
        with tempfile.TemporaryDirectory() as temporary:
            generated = self.build(Path(temporary) / 'fixture')
            self.assertEqual(generated['scan_input'], '/scan')
        self.assertEqual(fixture.fixture_options(95)['domain'], 95)
        for domain in (0, 93, 233):
            with self.assertRaises(ValueError):
                fixture.fixture_options(domain)
        with self.assertRaises(ValueError):
            fixture.fixture_options(95, scan_gap_s=.9)

    def test_unsupported_parameters_and_existing_fixture_are_rejected(self):
        for options in ({'door_width_m': .24}, {'initial_yaw_rad': math.nan},
                        {'scan_gap_s': .1}, {'scan_trigger_distance_m': .01},
                        {'timing_profile': 'unbounded'}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                fixture.fixture_options(96, **options)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'fixture'
            self.build(path)
            with self.assertRaises(FileExistsError):
                self.build(path)


if __name__ == '__main__':
    unittest.main()
