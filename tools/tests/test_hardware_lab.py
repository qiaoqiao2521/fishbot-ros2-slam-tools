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

if __name__=='__main__': unittest.main()
