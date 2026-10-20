"""Pure observation parsers; no ROS node, domain or port is created."""
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('lidar3d_probe', ROOT / 'tools/fishbot_lidar3d_probe.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class ProbeParserTests(unittest.TestCase):
    @staticmethod
    def cloud(seconds, nanoseconds=0):
        return NS(header=NS(stamp=NS(sec=seconds, nanosec=nanoseconds)))

    def test_pending_frames_survive_tf_delay_and_preserve_original_stamps(self):
        queue = probe.PendingClouds()
        messages = [self.cloud(12, index * 100000000) for index in range(10)]
        for index, message in enumerate(messages):
            queue.add(message, received_wall=20 + index / 10)
        self.assertEqual(len(queue.entries), 10)
        self.assertIs(queue.entries[0]['message'], messages[0])
        stamp = probe.cloud_stamp_ns(messages[4])
        queue.consume_through(stamp)
        self.assertEqual(queue.processed, 1)
        self.assertEqual(probe.cloud_stamp_ns(queue.entries[0]['message']), 12500000000)
        queue.add(messages[4], received_wall=22)
        self.assertEqual(queue.dropped['duplicate'], 1)
        self.assertEqual(messages[4].header.stamp.nanosec, 400000000)

    def test_pending_queue_is_bounded_by_capacity_and_source_window(self):
        queue = probe.PendingClouds(max_frames=3, source_window_sec=3)
        for seconds in range(5):
            queue.add(self.cloud(seconds), received_wall=seconds)
        self.assertEqual(len(queue.entries), 3)
        self.assertEqual(queue.dropped['capacity'], 2)
        queue.add(self.cloud(10), received_wall=10)
        self.assertEqual(len(queue.entries), 1)
        self.assertEqual(queue.dropped['source_window'], 3)

    def test_tf_diagnostics_keep_exact_source_stamp_and_first_last_error(self):
        state = {'failed_lookups': 0, 'exception_types': {},
                 'first_exception': None, 'last_exception': None}
        first = RuntimeError('map does not exist')
        last = LookupError('requested 12.6, latest 12.4')
        probe.record_transform_failure(state, first, source='lidar3d_link',
                                       target='map', seconds=12, nanoseconds=300000000)
        probe.record_transform_failure(state, last, source='lidar3d_link',
                                       target='map', seconds=12, nanoseconds=600000000)
        self.assertEqual(state['failed_lookups'], 2)
        self.assertEqual(state['first_exception']['message'], 'map does not exist')
        self.assertEqual(state['first_exception']['requested_stamp_nanosec'], 300000000)
        self.assertEqual(state['last_exception']['type'], 'LookupError')
        self.assertEqual(state['last_exception']['requested_stamp_nanosec'], 600000000)
        self.assertEqual(state['exception_types'], {'RuntimeError': 1, 'LookupError': 1})

    def test_cloud_summary_ignores_nonfinite_and_preserves_actual_dimensions_and_heights(self):
        result = probe.summarize_points(
            [(1, 2, -0.2), (1, 3, 0.0), (1, 4, 0.4), (math.nan, 2, 3)],
            frame='lidar3d_link', width=360, height=16)
        self.assertEqual(result, {
            'frame': 'lidar3d_link', 'width': 360, 'height': 16,
            'valid_points': 3, 'height_bins_2cm': 3,
            'z_min': -0.2, 'z_max': 0.4,
        })

    def test_region_reads_actual_grid_values_with_rotated_origin(self):
        grid = NS(
            header=NS(frame_id='map'),
            info=NS(width=3, height=2, resolution=0.1, origin=NS(
                position=NS(x=1.0, y=2.0),
                orientation=NS(x=0.0, y=0.0, z=math.sin(math.pi / 4), w=math.cos(math.pi / 4)))),
            data=[0, 100, 90, -1, 20, 0],
        )
        result = probe.costmap_region(grid, (0.95, 2.15), 0.01)
        self.assertEqual(result['cells'], 1)
        self.assertEqual(result['lethal_cells'], 1)
        self.assertEqual(result['max_occupancy'], 100)
        empty = probe.costmap_region(grid, (-10, -10), 0.12)
        self.assertEqual(empty['cells'], 0)
        self.assertIsNone(empty['max_occupancy'])


if __name__ == '__main__':
    unittest.main()
