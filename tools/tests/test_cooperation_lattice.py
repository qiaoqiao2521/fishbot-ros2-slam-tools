"""Installed native planner contracts and actual generated primitive geometry."""
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import yaml
from cooperation_lattice import DEFAULT_LATTICE, lattice_parameters
from cooperation_prepare import navigation_planner, staging_navigation

ROOT = Path(__file__).resolve().parents[2]


class DifferentialLatticeTests(unittest.TestCase):
    def setUp(self):
        self.params=yaml.safe_load((ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/nav2.yaml').read_text())
        self.params['global_costmap']['global_costmap']['ros__parameters']['resolution']=.02

    def test_native_asset_grid_endpoints_curves_and_turns_match_declared_kinematics(self):
        data=json.loads(DEFAULT_LATTICE.read_text());metadata=data['lattice_metadata']
        self.assertEqual(metadata['motion_model'],'diff')
        self.assertEqual(metadata['grid_resolution'],.02)
        self.assertEqual(metadata['turning_radius'],.6)
        rotations=set()
        for primitive in data['primitives']:
            poses=primitive['poses']
            self.assertTrue(all(math.isfinite(v) for pose in poses for v in pose))
            for v in poses[-1][:2]:self.assertAlmostEqual(v/.02,round(v/.02),places=7)
            if primitive['trajectory_length']==0.:
                rotations.add(primitive['start_angle_index'])
                self.assertTrue(all(math.hypot(*pose[:2])<1e-9 for pose in poses))
            elif primitive['arc_length']>0.:
                self.assertGreaterEqual(primitive['trajectory_radius']+1e-8,.6)
        self.assertEqual(rotations,set(range(metadata['num_of_headings'])))

    def test_native_plugin_leaves_limits_and_original_planner_untouched(self):
        before=copy.deepcopy(self.params)
        info=navigation_planner(self.params,'smac-lattice')
        planner=self.params['planner_server']['ros__parameters']['HeadingAware']
        self.assertEqual(planner['plugin'],'nav2_smac_planner::SmacPlannerLattice')
        self.assertEqual(planner['tolerance'],0.)
        self.assertFalse(planner['allow_reverse_expansion'])
        self.assertFalse(planner['smooth_path'])
        self.assertTrue(info['transport_in_place_rotation'])
        self.assertFalse(info['transport_reversing'])
        self.assertGreater(info['in_place_rotation_primitives'],0)
        self.assertEqual(self.params['planner_server']['ros__parameters']['GridBased'],
                         before['planner_server']['ros__parameters']['GridBased'])
        for name in ('controller_server','velocity_smoother','collision_monitor','local_costmap','global_costmap'):
            self.assertEqual(self.params[name],before[name])

    def test_incompatible_grid_or_motion_model_does_not_partially_mutate_configuration(self):
        data=json.loads(DEFAULT_LATTICE.read_text())
        for field,value in (('grid_resolution',.05),('motion_model','omni'),('turning_radius',0.)):
            with tempfile.TemporaryDirectory() as directory:
                modified=copy.deepcopy(data);modified['lattice_metadata'][field]=value
                file=Path(directory)/'primitive.json';file.write_text(json.dumps(modified))
                before=copy.deepcopy(self.params)
                with self.assertRaises(ValueError):navigation_planner(self.params,'smac-lattice',lattice_filepath=file)
                self.assertEqual(self.params,before)

    def test_optional_reverse_expansion_reuses_existing_rpp_direction_contract(self):
        info=navigation_planner(self.params,'smac-lattice',lattice_allow_reversing=True)
        self.assertTrue(self.params['planner_server']['ros__parameters']['HeadingAware']['allow_reverse_expansion'])
        self.assertTrue(info['transport_reversing'])
        self.assertFalse(info['transport_in_place_rotation'])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'main.xml';path.write_text('<root><FollowPath/></root>')
            staging_navigation(self.params,path,directory,transport_planner=info['transport_planner'],
                transport_reversing=info['transport_reversing'])
            controller=self.params['controller_server']['ros__parameters']
            self.assertTrue(controller['FollowPath']['allow_reversing'])
            self.assertFalse(controller['FollowPath']['use_rotate_to_heading'])
            self.assertFalse(controller['StagingPath']['allow_reversing'])
            self.assertTrue(controller['StagingPath']['use_rotate_to_heading'])

    def test_optional_native_rotation_shim_keeps_staging_primary_and_limits(self):
        before=copy.deepcopy(self.params)
        info=navigation_planner(self.params,'smac-lattice',lattice_allow_reversing=True,
                                lattice_rotation_shim=True)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'main.xml';path.write_text('<root><FollowPath/></root>')
            staging_navigation(self.params,path,directory,transport_reversing=True,
                transport_rotation_shim=info['transport_rotation_shim'])
        controller=self.params['controller_server']['ros__parameters']
        follow=controller['FollowPath'];source=before['controller_server']['ros__parameters']['FollowPath']
        self.assertEqual(follow['plugin'],'nav2_rotation_shim_controller::RotationShimController')
        self.assertEqual(follow['primary_controller'],source['plugin'])
        self.assertEqual(controller['StagingPath']['plugin'],source['plugin'])
        self.assertTrue(follow['use_path_orientations'])
        self.assertTrue(follow['rotate_to_goal_heading'])
        self.assertEqual(follow['forward_sampling_distance'],.02)
        for key in ('desired_linear_vel','max_angular_accel','rotate_to_heading_angular_vel',
                    'min_approach_linear_velocity','use_collision_detection'):
            self.assertEqual(follow[key],source[key])
        self.assertEqual(self.params['velocity_smoother'],before['velocity_smoother'])
        self.assertEqual(self.params['collision_monitor'],before['collision_monitor'])

    def test_forward_rotation_tree_contract_preserves_source_velocity_and_collision_limits(self):
        before=copy.deepcopy(self.params)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'main.xml'
            path.write_text('<root><BehaviorTree><ComputePathToPose planner_id="GridBased"/><FollowPath/></BehaviorTree></root>')
            info=navigation_planner(self.params,'smac-lattice')
            stage=staging_navigation(self.params,path,directory,transport_planner=info['transport_planner'],
                transport_in_place_rotation=info['transport_in_place_rotation'])
            self.assertEqual(ET.parse(stage).find('.//ComputePathToPose').get('planner_id'),'GridBased')
            self.assertEqual(ET.parse(path).find('.//ComputePathToPose').get('planner_id'),'HeadingAware')
            controller=self.params['controller_server']['ros__parameters']
            for name in ('FollowPath','StagingPath'):
                self.assertFalse(controller[name]['allow_reversing'])
                self.assertTrue(controller[name]['use_rotate_to_heading'])
                self.assertEqual(controller[name]['desired_linear_vel'],before['controller_server']['ros__parameters']['FollowPath']['desired_linear_vel'])
                self.assertTrue(controller[name]['use_collision_detection'])


if __name__=='__main__':unittest.main()
