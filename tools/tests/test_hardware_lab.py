import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import warnings

spec = importlib.util.spec_from_file_location('hardware_lab',Path(__file__).resolve().parents[1]/'fishbot_hardware_lab.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)

class HardwareLab(unittest.TestCase):
    def test_navigation_and_expected_drop_remain_independent(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            nav=root/'nav.json';nav.write_text(json.dumps({'source':{'basis':'measured'},'cases':[
                {'id':'route','acceptance_result':'passed','business_result':'route_completed','native_status':4,'metrics':{'actual_contact_steps_delta':0}}]}))
            suction=root/'suction.json';suction.write_text(json.dumps({'cases':[
                {'case':'wall_pressure_loss','status':'passed','vertical_drop_m':1.2,'no_weld_or_pose_servo':True}]}))
            report=lab.collect(real=nav,base=nav,suction=suction,output=root/'out')
            self.assertEqual([s['status'] for s in report['sections']],['passed']*3)
            self.assertEqual(report['sections'][2]['cases'][0]['label'],'墙面失压：预期脱落')
            self.assertEqual(report['sections'][0]['cases'][0]['business_result'],'route_completed')
            self.assertIn('不代表',report['limitations'][0])

    def test_missing_and_malformed_sections_do_not_drop_valid_failure(self):
        with tempfile.TemporaryDirectory() as root, warnings.catch_warnings():
            warnings.simplefilter('ignore');root=Path(root)
            bad=root/'bad.json';bad.write_text('{')
            failed=root/'failed.json';failed.write_text(json.dumps({'cases':[{'case':'wall_climb','status':'failed'}]}))
            report=lab.collect(real=bad,base=root/'absent',suction=failed,output=root/'out')
            self.assertEqual([s['status'] for s in report['sections']],['incomplete','incomplete','failed'])

    def test_edit_and_future_metadata_are_read_without_replaying(self):
        with tempfile.TemporaryDirectory() as root, warnings.catch_warnings():
            warnings.simplefilter('ignore');root=Path(root);p=root/'r.json'
            p.write_text('{"schema_version":9,"cases":null}')
            self.assertEqual(lab.section('real_map',p)['status'],'incomplete')
            p.write_text('{"cases":[{"id":"one","acceptance_result":"passed","metrics":"optional bad metadata"}]}')
            self.assertEqual(lab.section('real_map',p)['status'],'passed')
            p.write_text('{"cases":[{"id":"one","acceptance_result":"failed"}]}')
            self.assertEqual(lab.section('real_map',p)['status'],'failed')

    def test_transition_is_appended_without_relabeling_negative_control_as_delivery(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root)
            old=root/'old.json';old.write_text(json.dumps({'cases':[
                {'case':'wall_on','status':'passed'}]}))
            new=root/'new.json';new.write_text(json.dumps({'cases':[
                {'case':'ground_to_wall','status':'passed','task_motion_success':True},
                {'case':'pump_off','status':'passed','task_motion_success':False}]}))
            report=lab.collect(suction=old,transition=new,output=root/'out')
            section=report['sections'][2]
            self.assertEqual(section['status'],'passed')
            self.assertEqual([c['id'] for c in section['cases']],['wall_on','ground_to_wall','pump_off'])
            self.assertFalse(section['cases'][2]['metrics']['task_motion_success'])
            self.assertIn('预期不能',section['cases'][2]['label'])
            self.assertIn('不代表车辆任务成功',section['cases'][2]['reason'])

    def test_missing_transition_keeps_previous_cases_and_marks_only_new_case_incomplete(self):
        with tempfile.TemporaryDirectory() as root, warnings.catch_warnings():
            warnings.simplefilter('ignore');root=Path(root)
            old=root/'old.json';old.write_text('{"cases":[{"case":"wall_on","status":"passed"}]}')
            section=lab.collect(suction=old,transition=root/'missing',output=root/'out')['sections'][2]
            self.assertEqual(section['status'],'incomplete')
            self.assertEqual(section['cases'][0]['status'],'passed')
            self.assertEqual(section['cases'][1]['id'],'ground_to_wall')

    def test_transition_can_be_shown_without_legacy_suction_report(self):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);p=root/'new.json'
            p.write_text('{"cases":[{"case":"ground_to_wall","status":"failed"}]}')
            section=lab.collect(transition=p,output=root/'out')['sections'][2]
            self.assertEqual(section['status'],'failed')
            self.assertEqual(len(section['cases']),1)

if __name__=='__main__': unittest.main()
