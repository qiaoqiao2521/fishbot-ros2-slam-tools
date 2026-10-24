"""Compiled distance-query regression; no executing world is advanced."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cooperation_arm import ArmPlanner
from cooperation_profiles import _geom_vertical_bounds
from cooperation_scene import build_scene


class LocalClearanceQueryTest(unittest.TestCase):
    def test_reported_far_collision_is_removed_but_near_collision_still_rejected(self):
        import mujoco
        import numpy as np
        root = Path(__file__).resolve().parents[2]
        car = [-1.5864021783587894, -1.717583964436229, -.000032912843293480015,
               .9999766427548313, .00000019373125269537426,
               .00000329442223506154, .006834759241310945]
        q6 = [-.6099175017298354, .4713020575915541, -.24548858033409968,
              1.3449828495388463, -.00000000000021320724708995284, .11578534145682455]
        with tempfile.TemporaryDirectory() as folder:
            manifest = build_scene(root.parent/'so101', root, Path(folder),
                                   scene_profile={'vehicle':'jackal_j100'})
            planner = ArmPlanner(manifest, car_pose=car)
            checker = planner.closed_checker
            model, data = checker.model, checker.data
            data.qpos[:] = q6
            mujoco.mj_forward(model, data)
            box = model.geom('base_collision').id
            jaw = model.geom('collision_moving_jaw_so101_v1_0').id
            gap = (_geom_vertical_bounds(model, data, jaw)['bottom_world_m']-
                   _geom_vertical_bounds(model, data, box)['top_world_m'])
            self.assertGreater(gap, .030)
            # Original distmax=.1 contradicted that independent plane bound.
            self.assertLess(mujoco.mj_geomDistance(model, data, box, jaw, .1, None), .001)
            self.assertEqual(checker.distance_cap_m, .002)
            self.assertEqual(checker.margin_m, .001)
            self.assertTrue(checker.evaluate(q6, require_fixed_gripper=False)['valid'])
            self.assertEqual(mujoco.mj_geomDistance(model, data, box, jaw, .002, None), .002)
            original_z = float(model.geom_pos[box, 2])
            for signed_gap in (.0005, -.0005):
                with self.subTest(gap=signed_gap):
                    model.geom_pos[box, 2] = original_z+gap-signed_gap
                    result = checker.evaluate(q6, require_fixed_gripper=False)
                    self.assertFalse(result['valid'])
                    self.assertLess(mujoco.mj_geomDistance(model, data, box, jaw, .002, None), .001)
            self.assertEqual(planner.common.opt.disableflags, model.opt.disableflags)
            self.assertTrue(np.isfinite(data.qpos).all())

    def test_carried_box_query_removes_false_penetration_but_keeps_near_contacts(self):
        import mujoco
        import numpy as np
        root = Path(__file__).resolve().parents[2]
        car = [-1.5822991743829624, -1.637943136284486, -.0014710398316701329,
               .9996925323739713, .00005773078976302475,
               -.0005057600735378793, .024790756132486977]
        with tempfile.TemporaryDirectory() as folder:
            manifest = build_scene(root.parent/'so101', root, Path(folder),
                                   scene_profile={'vehicle':'robot_base_mecanum'})
            planner = ArmPlanner(manifest, car_pose=car)
            model, data = planner.contact, mujoco.MjData(planner.contact)
            data.qpos[:6] = [-.6099175017296702, .4447623907334535,
                            -.3950672634216676, 1.521101199452125, 0., .015]
            data.qpos[6:9] = [.2386342837316434, .13913551954420175, .0405061698794085]
            rotation = np.array([[.37894806604565134, -.9251785960355595, -.02104587080476095],
                                 [.9251950643094887, .3792579074768171, -.013324135756816024],
                                 [.020309018135319334, -.014422380315884862, .9996897212277428]])
            mujoco.mju_mat2Quat(data.qpos[9:13], rotation.flatten())
            mujoco.mj_forward(model, data)
            cargo, wall = (model.geom(name).id for name in ('target_collision', 'place_wall_x_-1'))
            self.assertLess(mujoco.mj_geomDistance(model, data, cargo, wall, .02, None), -.07)
            query = planner.payload_placement.mujoco.mj_geomDistance
            self.assertGreater(query(model, data, cargo, wall, .02, None), .0002)
            self.assertGreater(query(model, data, wall, cargo, .02, None), .0002)
            data.qpos[6:9] = [.23862894170386986, .13916708087671217, .02622377644905126]
            mujoco.mj_forward(model, data)
            floor = model.geom('place_floor').id
            self.assertGreater(query(model, data, cargo, floor, .02, None), .018)
            wall_rotation = data.geom_xmat[wall].reshape(3, 3).copy()
            mujoco.mju_mat2Quat(data.qpos[9:13], wall_rotation.flatten())
            for gap in (.0001, -.0005):
                with self.subTest(gap=gap):
                    data.qpos[6:9] = data.geom_xpos[wall]+wall_rotation @ np.array([.010+gap, 0., 0.])
                    mujoco.mj_forward(model, data)
                    self.assertLess(query(model, data, cargo, wall, .02, None), .0002)
            self.assertEqual(planner.common.opt.disableflags, planner.rig.opt.disableflags)
            self.assertEqual(planner.common.opt.disableflags, model.opt.disableflags)
            self.assertIs(planner.modules['placement'].mujoco, mujoco)
            self.assertEqual(planner.closed_checker.margin_m, .001)


if __name__ == '__main__':
    unittest.main()
