"""Pure configuration/XML checks; no ROS, compilation or physics stepping."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import yaml

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cooperation_prepare import amcl_motion_model, navigation_planner, staging_navigation

ROOT = Path(__file__).resolve().parents[2]


class StagingNavigationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.params = yaml.safe_load((ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/config/nav2.yaml').read_text())
        self.controller = self.params['controller_server']['ros__parameters']
        self.controller['FollowPath']['stateful'] = False
        self.controller['general_goal_checker']['stateful'] = False
        self.behavior = self.folder/'navigation.xml'
        self.behavior.write_text('<root><BehaviorTree><RecoveryNode number_of_retries="6">'
            '<ControllerSelector default_controller="FollowPath"/>'
            '<ComputePathToPose planner_id="{selected_planner}"/>'
            '<FollowPath path="{path}" controller_id="{selected_controller}"/>'
            '<Wait wait_duration="5.0"/></RecoveryNode></BehaviorTree></root>')

    def test_default_planner_keeps_source_configuration_editable_and_unchanged(self):
        before = copy.deepcopy(self.params)
        result = navigation_planner(self.params)
        self.assertEqual(self.params, before)
        self.assertEqual(result['plugin'],
                         before['planner_server']['ros__parameters']['GridBased']['plugin'])

    def test_native_omni_changes_only_reference_point_motion_proposal(self):
        before=copy.deepcopy(self.params)
        self.assertEqual(amcl_motion_model(self.params)['plugin'],
                         before['amcl']['ros__parameters']['robot_model_type'])
        self.assertEqual(self.params,before)
        chosen=amcl_motion_model(self.params,'omni')
        self.assertFalse(chosen['truth_input'])
        self.assertFalse(chosen['physical_kinematics_changed'])
        expected=copy.deepcopy(before)
        expected['amcl']['ros__parameters']['robot_model_type']='nav2_amcl::OmniMotionModel'
        self.assertEqual(self.params,expected)

    def test_smac_changes_only_global_planning_preserving_all_control_and_safety(self):
        before = copy.deepcopy(self.params)
        result = navigation_planner(self.params, 'smac-hybrid')
        planner = self.params['planner_server']['ros__parameters']
        self.assertEqual(result['plugin'], 'nav2_smac_planner::SmacPlannerHybrid')
        self.assertEqual(planner['HeadingAware']['motion_model_for_search'], 'DUBIN')
        self.assertEqual(planner['HeadingAware']['tolerance'], 0.)
        self.assertEqual(planner['HeadingAware']['allow_unknown'],
                         before['planner_server']['ros__parameters']['GridBased']['allow_unknown'])
        self.assertEqual(planner['GridBased'],before['planner_server']['ros__parameters']['GridBased'])
        self.assertEqual(planner['planner_plugins'],['GridBased','HeadingAware'])
        self.assertEqual({key: value for key, value in planner.items() if key not in ('HeadingAware','planner_plugins')},
                         {key: value for key, value in before['planner_server']['ros__parameters'].items()
                          if key != 'planner_plugins'})
        self.assertEqual({key: value for key, value in self.params.items() if key != 'planner_server'},
                         {key: value for key, value in before.items() if key != 'planner_server'})

    def test_explicit_radius_preserves_all_other_planner_and_control_settings(self):
        parent=copy.deepcopy(self.params)
        navigation_planner(parent,'smac-hybrid')
        result=navigation_planner(self.params,'smac-hybrid',minimum_turning_radius=.10)
        expected=copy.deepcopy(parent)
        expected['planner_server']['ros__parameters']['HeadingAware']['minimum_turning_radius']=.10
        self.assertEqual(self.params,expected)
        self.assertEqual(result['minimum_turning_radius_m'],.10)
        self.assertEqual(parent['planner_server']['ros__parameters']['HeadingAware']['minimum_turning_radius'],.20)

    def test_invalid_radius_does_not_partially_mutate_native_configuration(self):
        for radius in (0.,-.1,float('nan'),float('inf')):
            with self.subTest(radius=radius):
                before=copy.deepcopy(self.params)
                with self.assertRaisesRegex(ValueError,'finite and positive'):
                    navigation_planner(self.params,'smac-hybrid',minimum_turning_radius=radius)
                self.assertEqual(self.params,before)

    def test_optional_planner_routes_only_transport_and_preserves_stage_navfn(self):
        profile=navigation_planner(self.params,'smac-hybrid')
        path=staging_navigation(self.params,self.behavior,self.folder,
                                transport_planner=profile['transport_planner'])
        self.assertEqual(ET.parse(self.behavior).find('.//ComputePathToPose').get('planner_id'),
                         'HeadingAware')
        self.assertEqual(ET.parse(path).find('.//ComputePathToPose').get('planner_id'),'GridBased')
        before=copy.deepcopy(self.params)
        navigation_planner(self.params,'smac-hybrid')
        self.assertEqual(self.params,before)

    def test_unknown_planner_does_not_partially_mutate_configuration(self):
        before = copy.deepcopy(self.params)
        with self.assertRaisesRegex(ValueError, 'unknown native planner'):
            navigation_planner(self.params, 'missing-plugin')
        self.assertEqual(self.params, before)

    def test_phase_copies_only_xy_latches_and_preserves_original_delivery_and_collision_parameters(self):
        before = copy.deepcopy(self.params)
        staging_navigation(self.params,self.behavior,self.folder)
        original = before['controller_server']['ros__parameters']
        self.assertEqual(self.controller['FollowPath'],original['FollowPath'])
        self.assertEqual(self.controller['general_goal_checker'],original['general_goal_checker'])
        self.assertEqual(self.controller['StagingPath'],{**original['FollowPath'],'stateful':True})
        self.assertEqual(self.controller['staging_goal_checker'],{**original['general_goal_checker'],'stateful':True})
        self.assertEqual(self.controller['progress_checker'],original['progress_checker'])
        for name in ('local_costmap','global_costmap','collision_monitor','velocity_smoother'):
            self.assertEqual(self.params[name],before[name])
        self.controller['FollowPath']['min_approach_linear_velocity'] = .005
        self.assertEqual(self.controller['StagingPath']['min_approach_linear_velocity'],
                         original['FollowPath']['min_approach_linear_velocity'])

    def test_each_tree_explicitly_selects_its_checker_and_retains_original_recovery_graph(self):
        path = staging_navigation(self.params,self.behavior,self.folder)
        main,staging = ET.parse(self.behavior).getroot(),ET.parse(path).getroot()
        self.assertEqual(main.find('.//FollowPath').get('goal_checker_id'),'general_goal_checker')
        self.assertEqual(main.find('.//FollowPath').get('controller_id'),'{selected_controller}')
        self.assertEqual(staging.find('.//FollowPath').get('goal_checker_id'),'staging_goal_checker')
        self.assertEqual(staging.find('.//FollowPath').get('controller_id'),'StagingPath')
        self.assertEqual(staging.find('.//ControllerSelector').get('default_controller'),'StagingPath')
        for tree in (main,staging):
            self.assertEqual(tree.find('.//RecoveryNode').get('number_of_retries'),'6')
            self.assertEqual(tree.find('.//Wait').get('wait_duration'),'5.0')

    def test_regeneration_does_not_duplicate_plugins_or_change_delivery_state(self):
        staging_navigation(self.params,self.behavior,self.folder)
        before = copy.deepcopy(self.params)
        staging_navigation(self.params,self.behavior,self.folder)
        self.assertEqual(self.params,before)
        self.assertEqual(self.controller['controller_plugins'].count('StagingPath'),1)
        self.assertEqual(self.controller['goal_checker_plugins'].count('staging_goal_checker'),1)


if __name__ == '__main__':
    unittest.main()
