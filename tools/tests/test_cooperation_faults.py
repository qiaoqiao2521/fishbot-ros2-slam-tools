import copy
import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cooperation_faults import FaultInjector, normalize_fault_config


class FaultTests(unittest.TestCase):
    def setUp(self):
        self.identity = {'scene_sha256': '1'*64, 'manifest_sha256': '2'*64}
        self.episode = str(uuid.uuid4())
        self.trigger = {**self.identity, 'episode_id': self.episode, 'native_goal_uuid': '3'*32, 'source_stamp': 10.}
        self.sample = {**self.identity, 'episode_id': self.episode, 'stamp': 10., 'sequence': 1,
                       'detected': True, 'confidence': 1., 'reason': 'detected',
                       'relative': [.7, 0, 3.14], 'covariance': [0.]*36,
                       'frame_id': 'base_footprint', 'station_id': 'so101_station'}

    def injector(self, config):
        result = FaultInjector(config, self.identity)
        result.begin_episode(self.episode)
        result.trigger(self.trigger)
        return result

    def apply(self, injector, wall=100., source=10., moving=True, **kwargs):
        sample = dict(self.sample, stamp=source, sequence=round((source-9.)*100))
        return injector.apply(sample, wall_time=wall, source_stamp=source,
                              episode_id=self.episode, moving=moving, **kwargs)

    def test_defaults_and_invalid_configuration(self):
        self.assertEqual(normalize_fault_config()['kind'], 'none')
        for config in ({'kind': 'bad'}, {'kind':'delay'}, {'kind':'long_occlusion','duration_wall_s':.6},
                       {'kind':'short_occlusion','duration_wall_s':True}, {'duration_wall_s':1}, {'extra':1}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                normalize_fault_config(config)

    def test_requires_accepted_identity_and_motion(self):
        injector = self.injector({'kind':'long_occlusion'})
        self.assertTrue(self.apply(injector, moving=False)[0]['detected'])
        self.assertIsNone(injector.start_wall)
        self.assertFalse(self.apply(injector)[0]['detected'])
        self.assertFalse(injector.trigger(self.trigger))
        for field in self.identity:
            with self.assertRaises(ValueError): injector.trigger(dict(self.trigger, **{field:'0'*64}))
        with self.assertRaises(ValueError): injector.trigger(dict(self.trigger, episode_id=str(uuid.uuid4())))

    def test_occlusion_does_not_restamp_or_modify_source(self):
        injector = self.injector({'kind':'short_occlusion'})
        old = copy.deepcopy(self.sample)
        output = injector.apply(self.sample, wall_time=100., source_stamp=10., episode_id=self.episode, moving=True)
        self.assertEqual(self.sample, old)
        self.assertEqual(output[0]['stamp'], 10.)
        self.assertEqual(output[0]['sequence'], 1)
        self.assertIsNone(output[0]['relative'])
        self.assertTrue(self.apply(injector, wall=100.11, source=10.02)[0]['detected'])

    def test_rgb_visibility_is_not_synthetically_overridden(self):
        injector = self.injector({'kind':'long_occlusion'})
        self.assertTrue(self.apply(injector, synthetic_occlusion=False)[0]['detected'])
        self.assertTrue(injector.occlusion_active(wall_time=100.1,source_stamp=10.02,episode_id=self.episode,moving=True))
        self.assertFalse(injector.occlusion_active(wall_time=100.81,source_stamp=10.04,episode_id=self.episode,moving=True))

    def test_delay_retains_original_frame_and_is_bounded(self):
        injector = self.injector({'kind':'delay','delay_wall_s':.55,'delay_source_s':.30})
        self.assertEqual(self.apply(injector), [])
        self.assertEqual(self.apply(injector, wall=100.56, source=10.20), [])
        released = self.apply(injector, wall=100.60,source=10.31)[0]
        self.assertEqual(released['stamp'],10.)
        self.assertIsNone(injector.saved)
        self.assertEqual(self.apply(injector,wall=100.61,source=10.32)[0]['stamp'],10.32)

    def test_replay_packets_interleave_without_erasing_fresh_input(self):
        injector = self.injector({'kind':'replay_identity'})
        injector.apply(self.sample,wall_time=99.,source_stamp=9.99,episode_id=self.episode,moving=False)
        packets=[]
        for i in range(13): packets.extend(self.apply(injector,wall=100.+i*.02,source=10.+i*.02))
        self.assertEqual(injector.status()['replay_packets'],6)
        self.assertEqual(packets[0]['stamp'],10.)
        self.assertEqual(packets[2]['stamp'],packets[0]['stamp'])
        self.assertNotEqual(packets[4]['episode_id'],self.episode)
        self.assertEqual(packets[6]['frame_id'],'wrong_camera_frame')
        self.assertEqual(packets[8]['station_id'],'wrong_station')
        self.assertEqual(packets[10]['manifest_sha256'],'0'*64)
        self.assertEqual(packets[-1]['episode_id'],self.episode)

    def test_episode_reset_removes_pending_delay_and_owner(self):
        injector=self.injector({'kind':'delay','delay_wall_s':1})
        self.apply(injector)
        injector.begin_episode(str(uuid.uuid4()))
        self.assertIsNone(injector.saved)
        self.assertIsNone(injector.accepted_goal)
        self.assertEqual(injector.status()['counts']['triggers'],0)

    def test_timeline_distinguishes_epoch_wall_and_monotonic(self):
        injector = self.injector({'kind':'short_occlusion'})
        with patch('cooperation_faults.time.time', return_value=1760000000.):
            self.apply(injector, wall=100., source=10.)
        self.assertEqual(injector.status()['started_wall_time'],1760000000.)
        self.assertEqual(injector.status()['started_monotonic'],100.)
        injector.begin_episode(str(uuid.uuid4()))
        self.assertIsNone(injector.status()['started_wall_time'])


if __name__ == '__main__': unittest.main()
