"""Official angle reuse, source-time progression and truth/observation binding."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import cooperation_lidar as lidar
import cooperation_sensor_experience as experience
import fishbot_lidar3d_probe as probe


class Mid360PatternTests(unittest.TestCase):
    def config(self):
        return lidar.configuration({'scene_profile': {'sensors': 'lidar3d'},
            'lidar3d': {'scan_pattern': 'livox_mid360_csv_stride5'}})

    def test_real_official_angles_and_unorganized_layout_are_not_renamed_uniform_rings(self):
        import numpy as np
        c = self.config(); actual = lidar.beam_directions(c)
        self.assertEqual((c['horizontal_samples'], c['lines']), (4000, 1))
        self.assertEqual(actual.shape, (4000, 3))
        np.testing.assert_allclose(np.linalg.norm(actual, axis=1), 1., atol=1e-14)
        pattern = lidar.mid360_pattern()
        self.assertEqual(pattern.shape, (160000, 3))
        elevation = np.degrees(np.arcsin(pattern[:, 2]))
        self.assertAlmostEqual(float(elevation.min()), -7.2122)
        self.assertAlmostEqual(float(elevation.max()), 52.162)
        self.assertGreater(len(np.unique(np.round(elevation, 3))), 100)
        self.assertEqual(c['angular_downsample'], 5)
        self.assertIn('1cce107', c['layout_source'])
        # First official CSV row is azimuth268.99/zenith37.838 degrees.
        self.assertAlmostEqual(float(pattern[0, 2]), np.sin(np.radians(52.162)))

    def test_profile_dictionary_replaces_prepared_uniform_dimensions(self):
        import json
        original=lidar.configuration({'scene_profile': {'sensors':'lidar3d'}})
        original.update(json.loads((TOOLS/'config/cooperation_profiles/mid360-sensor.json').read_text()))
        actual=lidar.configuration({'scene_profile': {'sensors':'lidar3d'},'lidar3d':original})
        self.assertEqual((actual['horizontal_samples'],actual['lines']),(4000,1))
        self.assertIn('mid360',actual['basis'])

    def test_window_advances_from_source_time_skips_missed_frames_and_wraps_declared_finite_csv(self):
        import numpy as np
        c=self.config();pattern=lidar.mid360_pattern()
        np.testing.assert_array_equal(lidar.beam_directions(c,.1), pattern[4000:8000])
        np.testing.assert_array_equal(lidar.beam_directions(c,.3), pattern[12000:16000])
        np.testing.assert_array_equal(lidar.beam_directions(c,4.), lidar.beam_directions(c,0.))
        self.assertFalse(np.array_equal(lidar.beam_directions(c,0),lidar.beam_directions(c,.1)))

    def test_existing_generic_profile_is_unchanged(self):
        c=lidar.configuration({'scene_profile': {'sensors':'lidar3d'}})
        self.assertEqual(lidar.beam_directions(c).shape,(5760,3))
        self.assertNotIn('scan_pattern', c)

    def test_costmap_probe_accepts_real_vertical_unorganized_returns_only_when_selected(self):
        unorganized={'valid_points':100,'width':4000,'height':1,'height_bins_2cm':20}
        self.assertFalse(probe.cloud_has_3d_returns(unorganized))
        self.assertTrue(probe.cloud_has_3d_returns(unorganized,allow_unorganized=True))
        self.assertFalse(probe.cloud_has_3d_returns({**unorganized,'height_bins_2cm':1},allow_unorganized=True))


class SourceBindingTests(unittest.TestCase):
    def metadata(self):
        return {'sequence':'7','episode_id':'one','scene_sha256':'scene','manifest_sha256':'manifest'}
    def state(self):
        return {'sequence':7,'stamp':.12,'episode_id':'one','source':{'scene_sha256':'scene','manifest_sha256':'manifest'}}
    def test_exact_match_requires_the_actual_source_identity_not_a_nearby_pose(self):
        metadata=self.metadata();state=self.state()
        self.assertTrue(experience.matching_state(metadata,state,120000000))
        for changed in ({'sequence':8},{'stamp':.12001},{'episode_id':'two'},
                        {'source':{'scene_sha256':'other','manifest_sha256':'manifest'}}):
            self.assertFalse(experience.matching_state(metadata,{**state,**changed},120000000))
        self.assertFalse(experience.matching_state({},state,120000000))
    def test_diagnostic_metadata_keeps_only_sensor_status(self):
        a=NS(name='unrelated',values=[NS(key='episode_id',value='wrong')])
        b=NS(name='cooperation_lidar3d_frame',values=[NS(key='episode_id',value='one'),NS(key='sequence',value='7')])
        self.assertEqual(experience.metadata_values(NS(status=[a,b])),{'episode_id':'one','sequence':'7'})


@unittest.skipUnless(importlib.util.find_spec('mujoco'), 'native query uses existing cloud planning environment')
class NativeMid360Tests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.world=Path(self.folder.name)/'world.xml'
        self.world.write_text("""<mujoco><worldbody>
          <geom name="floor" type="plane" size="5 5 .1"/>
          <geom name="wall" type="box" pos="2.1 0 1" size=".1 4 1"/>
          <body name="base_footprint"><freejoint/>
            <geom type="box" size=".5 .5 .2" mass="2"/>
            <body name="laser_link" pos="0 0 .2"/>
          </body></worldbody></mujoco>""")
        self.manifest={'world_xml':str(self.world),'scene_profile':{'sensors':'lidar3d'},
            'lidar3d':{'scan_pattern':'livox_mid360_csv_stride5'}}

    def test_actual_native_returns_and_pose_query_do_not_step_the_plant(self):
        import numpy as np
        query=lidar.NativeCloudQuery(self.world,lidar.configuration(self.manifest))
        state={'qpos':query.data.qpos.copy(),'qvel':query.data.qvel.copy(),'stamp':.12}
        original=state['qpos'].copy();frame=query.compute(state)
        self.assertEqual(frame['points'].shape,(4000,3))
        self.assertGreater(frame['valid_points'],0)
        self.assertGreater(frame['z_max'],frame['z_min'])
        self.assertEqual(query.data.time,.12)
        np.testing.assert_array_equal(state['qpos'],original)

    def test_same_source_truth_boxes_are_in_the_measured_sensor_frame(self):
        query=experience.TruthProjection(self.manifest)
        state={'qpos':query.data.qpos.copy(),'qvel':query.data.qvel.copy(),'stamp':.12}
        result=query.project(state)
        wall=next(x for x in result['boxes'] if x['id']=='wall')
        self.assertAlmostEqual(min(p[0] for p in wall['vertices']),2.)
        self.assertAlmostEqual(min(p[2] for p in wall['vertices']),-.235)
        self.assertTrue(result['reference_only'])
        self.assertEqual(result['omitted_nonbox_collision_geometries'],1)


if __name__=='__main__': unittest.main()
