"""Native plant regression: configured skid steering must actually turn."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cooperation_scene import build_scene
from cooperation_sim import Physics


class CompiledSkidDriveTest(unittest.TestCase):
    def test_signed_turns_use_effective_track_without_changing_physical_geometry(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            manifest = build_scene(root.parent/'so101', root, output,
                                   scene_profile={'vehicle': 'jackal_j100'})
            (output/'scene-manifest.json').write_text(json.dumps(manifest))
            for sign in (1., -1.):
                with self.subTest(sign=sign):
                    plant = Physics(manifest['world_xml'])
                    for _ in range(500):
                        plant.step()
                    plant.wheels.set_hold(False)
                    for _ in range(1500):
                        plant.wheels.accept(0., sign*.3, time.monotonic())
                        plant.step()
                    plant.refresh_snapshot()
                    state = plant.state()
                    # The unadapted four-wheel plant only reached ~.04 rad/s.
                    # Test physical motion and encoder output independently.
                    self.assertGreater(sign*state['car']['velocity_world_angular_linear'][2], .22)
                    self.assertLess(sign*state['car']['velocity_world_angular_linear'][2], .36)
                    self.assertGreater(sign*plant.odom_angular, .27)
                    self.assertLess(sign*plant.odom_angular, .35)
                    geometry = state['encoder_odometry_geometry']
                    self.assertEqual(geometry['wheel_separation_m'], .37559)
                    self.assertAlmostEqual(geometry['effective_wheel_separation_m'], 1.690155)
                    self.assertEqual(len(plant.wheel_joint_names), 4)
                    self.assertEqual(state['car_forbidden_contact_total'], 0)
                    self.assertEqual(state['arm_forbidden_contact_total'], 0)


if __name__ == '__main__':
    unittest.main()
