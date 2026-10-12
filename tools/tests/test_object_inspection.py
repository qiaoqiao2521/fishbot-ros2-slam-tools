import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOLS))
from fishbot_object_inspection import aggregate,score_fixture,save_report,Worker,verify_age_evidence
from fishbot_object_scene import build_scene,prepare_navigation,AMCL_PROFILE
from fishbot_object_infer import validate_weight
from fishbot_inspection import validate_environment,validate_capture_pose,freshness_evidence


def frame(*labels):
    return {'evidence':{'detections':[{'label':label} for label in labels]}}


class ObjectInspectionTest(unittest.TestCase):
    def test_two_fresh_votes_identify_requested_object_not_other_classes(self):
        self.assertEqual(aggregate([frame('cup'),frame('cup'),frame('orange')],{'label':'cup'})['state'],'present')
        self.assertEqual(aggregate([frame('cup'),frame('sports ball'),frame()],{'label':'cup'})['state'],'unknown')

    def test_no_detection_stays_unknown_instead_of_asserting_absence(self):
        result=aggregate([frame(),frame(),frame()],{'label':'cup'})
        self.assertEqual(result['state'],'unknown');self.assertEqual(result['votes'],0)

    def test_age_evidence_uses_separate_source_and_receipt_clocks(self):
        evidence=freshness_evidence(100.,9999.9,100.2,10000.)
        self.assertTrue(verify_age_evidence(evidence))
        self.assertAlmostEqual(evidence['source_age_s'],.2)
        self.assertAlmostEqual(evidence['receipt_age_s'],.1)
        evidence['source_age_s']=0.
        self.assertFalse(verify_age_evidence(evidence))

    def test_old_source_or_old_receipt_cannot_be_reported_as_fresh(self):
        with self.assertRaises(ValueError):freshness_evidence(100.,9999.9,101.,10000.)
        with self.assertRaises(ValueError):freshness_evidence(100.,9998.,100.2,10000.)
        self.assertFalse(verify_age_evidence({}))

    def test_missing_negative_evidence_cannot_pass_fixture(self):
        self.assertFalse(score_fixture({'stations':[]})['passed'])
        record={'name':'absent-cup','state':'unknown','frames':[frame('cup')]}
        self.assertFalse(score_fixture({'stations':[record]})['checks']['absent_not_hallucinated'])

    def test_occlusion_must_recover_from_model_evidence(self):
        report={'stations':[{'name':'occluded-cup','primary_state':'unknown','state':'unknown',
                             'alternate_view':{'state':'unknown'}}]}
        self.assertTrue(score_fixture(report)['checks']['occluded_primary_unknown'])
        self.assertFalse(score_fixture(report)['checks']['alternate_view_recovers'])

    def test_claimed_present_without_model_boxes_cannot_pass(self):
        report={'stations':[{'name':'laptop','state':'present','frames':[frame(),frame(),frame()]}]}
        self.assertFalse(score_fixture(report)['checks']['laptop_detected'])

    def test_prediction_without_matching_capture_sha_cannot_pass(self):
        frames=[{'sha256':'a'*64,'evidence':{'input_sha256':'b'*64,'detections':[]}}
                for _ in range(18)]
        report={'stations':[{'name':'cup','frames':frames}]}
        self.assertFalse(score_fixture(report)['checks']['model_inputs_match_captures'])

    def test_unpinned_weight_is_rejected_without_importing_ml_dependencies(self):
        with tempfile.TemporaryDirectory() as t:
            model=Path(t)/'yolo11n.pt';model.write_bytes(b'not an official weight')
            with self.assertRaisesRegex(ValueError,'pinned official'):validate_weight(model)

    def test_domain101_is_explicit_and_original97_default_is_preserved(self):
        env={'ROS_DOMAIN_ID':'101','FISHBOT_MUJOCO_DOMAIN_ID':'101',
             'ROS_AUTOMATIC_DISCOVERY_RANGE':'LOCALHOST','ROS_STATIC_PEERS':''}
        validate_environment(env,'101')
        with self.assertRaises(ValueError):validate_environment(env)
        env['ROS_STATIC_PEERS']='192.168.0.2'
        with self.assertRaises(ValueError):validate_environment(env,'101')

    def test_internal_domain_injection_cannot_target_real_car_domain_zero(self):
        env={'ROS_DOMAIN_ID':'0','FISHBOT_MUJOCO_DOMAIN_ID':'0',
             'ROS_AUTOMATIC_DISCOVERY_RANGE':'LOCALHOST','ROS_STATIC_PEERS':''}
        with self.assertRaises(ValueError):validate_environment(env,'0')

    def test_worker_startup_failure_cleans_owned_process(self):
        import subprocess
        with tempfile.TemporaryDirectory() as t:
            output=Path(t);model=output/'yolo11n.pt';model.write_bytes(b'wrong')
            children=[];original=subprocess.Popen
            def capture(*args,**kwargs):
                child=original(*args,**kwargs);children.append(child);return child
            with patch('fishbot_object_inspection.subprocess.Popen',side_effect=capture):
                with self.assertRaisesRegex(RuntimeError,'Detector exited'):
                    Worker(sys.executable,model,output)
            self.assertEqual(len(children),1);self.assertIsNotNone(children[0].returncode)

    def test_truth_remains_capture_pose_gate(self):
        with self.assertRaises(ValueError):
            validate_capture_pose('inspection_camera_optical_frame',1.,1.,[1.,1.,0.],
                                  [0.,0.,0.],[0.,0.,0.])

    def test_modified_cached_asset_is_rejected_before_scene_output(self):
        with tempfile.TemporaryDirectory() as t:
            cache=Path(t)/'assets';cache.mkdir();(cache/'a.stl').write_bytes(b'changed')
            (cache/'manifest.json').write_text(json.dumps({'license':'MIT','files':[{'file':'a.stl','sha256':'0'*64}]}))
            with self.assertRaises(ValueError):build_scene(cache,Path(t)/'scene')
            self.assertFalse((Path(t)/'scene').exists())

    def test_fixture_navigation_copy_preserves_baseline_and_observation_unrelated_parameters(self):
        import yaml
        share=TOOLS.parent/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco'
        source=share/'config/nav2.yaml';original=source.read_bytes()
        baseline=yaml.safe_load(original)
        with tempfile.TemporaryDirectory() as t:
            output=Path(t);(output/'provenance.json').write_text('{}')
            copied=yaml.safe_load(prepare_navigation(share,output).read_text())
            for key in AMCL_PROFILE:baseline['amcl']['ros__parameters'][key]=AMCL_PROFILE[key]
            measured=yaml.safe_load((TOOLS/'config/fishbot_passage_nav.yaml').read_text())
            baseline['controller_server']['ros__parameters']['progress_checker']=measured['controller_server']['ros__parameters']['progress_checker']
            self.assertEqual(copied,baseline)
            self.assertEqual(source.read_bytes(),original)
            self.assertEqual(copied['controller_server']['ros__parameters']['general_goal_checker']['yaw_goal_tolerance'],.15)
            with self.assertRaises(FileExistsError):prepare_navigation(share,output)

    def test_report_preserves_unknown_and_does_not_invent_missing_images(self):
        with tempfile.TemporaryDirectory() as t:
            report={'overall_status':'completed_with_unknown','trajectory':[],
                    'stations':[{'name':'absent-cup','state':'unknown','reason':'zero detections'}]}
            save_report(report,Path(t));html=(Path(t)/'index.html').read_text()
            self.assertIn('unknown',html);self.assertNotIn('<image ',html)


if __name__=='__main__':unittest.main()
