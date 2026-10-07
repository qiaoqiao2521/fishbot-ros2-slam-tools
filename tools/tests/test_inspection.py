"""Task data contracts and image freshness, independent of ROS middleware."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fishbot_inspection as inspection


class InspectionContracts(unittest.TestCase):
    def test_only_dedicated_loopback_domain(self):
        good = {'ROS_DOMAIN_ID': '97', 'FISHBOT_MUJOCO_DOMAIN_ID': '97',
                'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST', 'ROS_STATIC_PEERS': ''}
        inspection.validate_environment(good)
        for key, value in [('ROS_DOMAIN_ID', '0'), ('ROS_DOMAIN_ID', '93'),
                           ('FISHBOT_MUJOCO_DOMAIN_ID', '96'),
                           ('ROS_AUTOMATIC_DISCOVERY_RANGE', 'SUBNET'), ('ROS_STATIC_PEERS', '192.0.2.1')]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                inspection.validate_environment({**good, key: value})

    def test_old_source_and_frozen_receive_rejected(self):
        self.assertTrue(inspection.fresh(20., 10., 20.1, 10.1))
        for args in [(10., 10., 20., 10.), (20., 1., 20., 10.),
                     (21., 10., 20., 10.), (float('nan'), 10., 20., 10.)]:
            self.assertFalse(inspection.fresh(*args))

    def test_padded_bgr_decoded(self):
        msg = SimpleNamespace(encoding='bgr8', width=1, height=2, step=4,
                              data=bytes([1, 2, 3, 0, 4, 5, 6, 0]))
        np.testing.assert_array_equal(inspection.decode_rgb(msg), [[[3, 2, 1]], [[6, 5, 4]]])
        msg.data = msg.data[:-1]
        with self.assertRaises(ValueError):
            inspection.decode_rgb(msg)

    def test_pose_error_wraparound(self):
        xy, yaw = inspection.pose_error([0., 0., -3.13], [0., 0., 3.13])
        self.assertEqual(xy, 0.)
        self.assertLess(yaw, .03)

    def test_capture_rejects_wrong_frame_motion_location_and_old_pose(self):
        good = ['inspection_camera_optical_frame', 20., 20., [1., 2., 0.], [0., 0., 0.], [1., 2., 0.]]
        self.assertEqual(inspection.validate_capture_pose(*good)['time_error_s'], 0.)
        for index, bad in [(0, 'arena_overview'), (2, 19.), (3, [2., 2., 0.]),
                           (4, [.1, 0., 0.]), (3, [1., 2., .5]), (1, float('nan'))]:
            values = good.copy()
            values[index] = bad
            with self.subTest(index=index, bad=bad), self.assertRaises(ValueError):
                inspection.validate_capture_pose(*values)


if __name__ == '__main__':
    unittest.main()
