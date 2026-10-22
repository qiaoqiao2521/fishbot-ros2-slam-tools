"""Pure configuration/XML checks; no ROS, compilation or physics stepping."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import yaml

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cooperation_prepare import navigation_planner, staging_navigation

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
            '<FollowPath path="{path}" controller_id="{selected_controller}"/>'
            '<Wait wait_duration="5.0"/></RecoveryNode></BehaviorTree></root>')

    def test_default_planner_keeps_source_configuration_editable_and_unchanged(self):
        before = copy.deepcopy(self.params)
        result = navigation_planner(self.params)
        self.assertEqual(self.params, before)
        self.assertEqual(result['plugin'],
                         before['planner_server']['ros__parameters']['GridBased']['plugin'])

    def test_smac_changes_only_global_planning_preserving_all_control_and_safety(self):
        before = copy.deepcopy(self.params)
        result = navigation_planner(self.params, 'smac-hybrid')
        planner = self.params['planner_server']['ros__parameters']
        self.assertEqual(result['plugin'], 'nav2_smac_planner::SmacPlannerHybrid')
        self.assertEqual(planner['GridBased']['motion_model_for_search'], 'DUBIN')
        self.assertEqual(planner['GridBased']['tolerance'], 0.)
        self.assertEqual(planner['GridBased']['allow_unknown'],
                         before['planner_server']['ros__parameters']['GridBased']['allow_unknown'])
        self.assertEqual({key: value for key, value in planner.items() if key != 'GridBased'},
                         {key: value for key, value in before['planner_server']['ros__parameters'].items()
                          if key != 'GridBased'})
        self.assertEqual({key: value for key, value in self.params.items() if key != 'planner_server'},
                         {key: value for key, value in before.items() if key != 'planner_server'})

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
