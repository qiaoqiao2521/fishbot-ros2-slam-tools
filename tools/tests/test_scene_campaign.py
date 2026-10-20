"""The campaign composes existing owners and continues independent cases."""
import copy
import importlib.util
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scene_campaign',TOOLS/'fishbot_scene_campaign.py')
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


class SceneCampaign(unittest.TestCase):
    def test_new_base_geometry_fusion_and_controller_contract_reach_launch(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = campaign.validation.load_config(TOOLS/'config/jackal_scene_validation.example.json')
            with patch.object(campaign.subprocess,'Popen',side_effect=AssertionError('prepare is read-only')):
                campaign.run_campaign(config,temporary,prepare_only=True)
            case = campaign.validation.read_json(next(Path(temporary).glob('jackal-roundtrip-*/case.json')))
            args = case['launch_arguments']
            self.assertAlmostEqual(case['geometry']['half_length'],.244)
            self.assertAlmostEqual(case['geometry']['half_width'],.222795)
            self.assertGreater(float(args['robot_radius']),.33)
            self.assertEqual(args['wheel_odom_topic'],'/wheel/odom')
            self.assertEqual(args['localization_fusion'],'true')
            self.assertEqual(args['imu_broadcaster'],'true')
            self.assertTrue(Path(args['controllers_file']).is_file())
            self.assertTrue(Path(args['fusion_file']).is_file())

    def test_private_cyclone_domain_does_not_overwrite_explicit_xml(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ,{'RMW_IMPLEMENTATION':'rmw_cyclonedds_cpp','CYCLONEDDS_URI':''}):
                env = campaign.selected_environment(130,temporary)
            path = Path(temporary)/'cyclonedds-domain-130.xml'
            self.assertIn('Domain Id="130"',path.read_text())
            self.assertEqual(env['CYCLONEDDS_URI'],path.as_uri())
            with patch.dict(os.environ,{'RMW_IMPLEMENTATION':'rmw_cyclonedds_cpp','CYCLONEDDS_URI':'file:///caller-owned.xml'}):
                env = campaign.selected_environment(132,temporary)
            self.assertEqual(env['CYCLONEDDS_URI'],'file:///caller-owned.xml')
            self.assertFalse((Path(temporary)/'cyclonedds-domain-132.xml').exists())

    def test_prepare_only_never_launches_and_preserves_dimensioned_low_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = campaign.validation.load_config(TOOLS/'config/scene_validation.example.json')
            with patch.object(campaign.subprocess,'Popen',side_effect=AssertionError('no ROS launch')),patch.dict(os.environ,{},clear=False):
                result = campaign.run_campaign(config,temporary,prepare_only=True)
            self.assertEqual(len(result['cases']),3)
            self.assertTrue(all(case['acceptance_result']=='incomplete' for case in result['cases']))
            panel = campaign.validation.read_json(Path(temporary)/'panel.json')
            self.assertEqual(panel['source']['basis'],'synthetic_reference')
            self.assertFalse(panel['layout']['low_height_probe']['in_static_map'])
            self.assertTrue(all(Path(case['plugins_file']).is_file() for case in panel['cases']))

    def test_failed_case_cleans_only_owned_group_then_runs_later_cases(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = campaign.validation.load_config(TOOLS/'config/scene_validation.example.json')
            panel = campaign.validation.prepare_panel(config,Path(temporary)/'base')
            library = Path(temporary)/'official-library.so'
            library.write_text('fixture')
            prepared = {'scene':'scene.xml','plugins':'plugins.yaml','nav2':'nav2.yaml','library':str(library)}
            helper = SimpleNamespace(prepare=lambda *_a,**_k:copy.deepcopy(prepared))
            children = [SimpleNamespace(pid=100+i) for i in range(3)]
            calls = []
            def run(case,*_):
                calls.append(case['id'])
                if case['id']=='clear':
                    raise RuntimeError('first case failed after launch')
                return {'id':case['id'],'label':case['label'],'expected':case['expected'],'business_result':'route_completed',
                    'acceptance_result':'passed','reason':'fixture','metrics':{},'task_id':'task','native_goal_id':'e1'*16,'native_status':4}
            with patch.object(campaign.validation,'prepare_panel',return_value=panel), \
                    patch.object(campaign,'load_tool',return_value=helper), \
                    patch.object(campaign,'empty_domain'), \
                    patch.object(campaign.subprocess,'Popen',side_effect=children), \
                    patch.object(campaign,'wait_runtime',return_value={'instance_id':'runtime'}), \
                    patch.object(campaign,'lidar_probe',return_value={'status':'complete'}), \
                    patch.object(campaign.validation,'run_case',side_effect=run), \
                    patch.object(campaign,'stop_owned_group',return_value=True) as cleanup, \
                    patch.dict(os.environ,{},clear=False), warnings.catch_warnings():
                warnings.simplefilter('ignore')
                result = campaign.run_campaign(config,Path(temporary)/'run')
            self.assertEqual(calls,['clear','detour','blocked'])
            self.assertEqual([item['acceptance_result'] for item in result['cases']],['incomplete','passed','passed'])
            self.assertEqual([call.args[0] for call in cleanup.call_args_list],children)
            self.assertTrue(all(item['cleanup_complete'] for item in result['cases']))

    def test_bad_obstacle_is_preserved_while_other_cases_prepare(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = campaign.validation.load_config(TOOLS/'config/scene_validation.example.json')
            config['cases'].insert(1,{'id':'bad-obstacle','label':'缺少高度的障碍物','expected':'delivered',
                'obstacle':{'center':[.65,0.],'half_size':[.18,.18,.22]}})
            with patch.object(campaign.subprocess,'Popen',side_effect=AssertionError('prepare only')), \
                    patch.dict(os.environ,{},clear=False), warnings.catch_warnings():
                warnings.simplefilter('ignore')
                result = campaign.run_campaign(config,temporary,prepare_only=True)
            rows = {item['id']:item for item in result['cases']}
            self.assertEqual(set(rows),{'clear','bad-obstacle','detour','blocked'})
            self.assertEqual(rows['bad-obstacle']['acceptance_result'],'incomplete')
            self.assertEqual(rows['bad-obstacle']['business_result'],'unknown')
            self.assertTrue(rows['bad-obstacle']['preparation_error'])
            self.assertEqual(result['preparation_errors'][0]['case_id'],'bad-obstacle')
            self.assertEqual(result['preparation_errors'][0]['label'],'缺少高度的障碍物')
            panel = campaign.validation.read_json(Path(temporary)/'panel.json')
            self.assertEqual({case['id'] for case in panel['cases']},{'clear','detour','blocked'})
            self.assertTrue(all(Path(case['scene_path']).is_file() for case in panel['cases']))


if __name__ == '__main__':
    unittest.main()
