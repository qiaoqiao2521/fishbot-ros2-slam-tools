"""Small CPU-only evidence fixtures. Never installed as public run evidence."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import cooperation_visual_evidence_export as exporter


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value)+'\n')


class VisualEvidenceExportTests(unittest.TestCase):
    def test_selected_station_pose_is_inverse_transformed_and_score_stays_raw(self):
        camera = {'T_station_camera': [[1,0,0,1],[0,1,0,2],[0,0,1,0],[0,0,0,1]], 'frame_id':'camera'}
        selected = {'selected':{'index':8,'score':3.2,'origin':'obb'},
                    'pose_station':[[1,0,0,1.2],[0,1,0,2.3],[0,0,1,.7],[0,0,0,1]]}
        result=exporter.camera_candidate(selected,camera)
        self.assertAlmostEqual(result['pose_camera'][0][3],.2)
        self.assertAlmostEqual(result['pose_camera'][1][3],.3)
        self.assertEqual(result['score'],3.2)
        self.assertFalse(result['score_is_success_probability'])

    def test_depth_legend_is_fixed_and_source_array_unchanged(self):
        import numpy as np
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'depth.npy';target=root/'depth.png'
            depth=np.array([[.05,.775,1.5],[float('nan'),.01,2]],dtype=np.float32)
            np.save(source,depth);before=source.read_bytes()
            legend=exporter.save_depth(source,target)
            pixels=np.asarray(Image.open(target))
            self.assertEqual(legend['min_m'],.05);self.assertEqual(legend['max_m'],1.5)
            self.assertFalse(legend['per_frame_normalization'])
            self.assertTrue((pixels[1,:3]==0).all());self.assertEqual(source.read_bytes(),before)

    def test_observation_requires_unique_episode_arm_and_cargo_task(self):
        observation={'episode_id':'e','cargo_id':'second','arm_id':'load'}
        def case(task,cargo):return {'task_id':task,'episode_id':'e','entity_binding':{'cargo_id':cargo,'pickup_arm_id':'load','unload_arm_id':'unload'}}
        a,b=case('a','first'),case('b','second')
        self.assertEqual(exporter.bound_case(observation,[a,b])['task_id'],'b')
        self.assertIsNone(exporter.bound_case(observation,[b,b]))
        self.assertIsNone(exporter.bound_case({**observation,'episode_id':'wrong'},[b]))

    def test_query_timeout_and_loading_are_not_inference_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'query-receipts/q';folder.mkdir(parents=True)
            events=[{'query_id':'q','stage':'query_started','elapsed_wall_s':0,'wall_budget_s':30},
                    {'query_id':'q','stage':'official_server_loaded','elapsed_wall_s':4},
                    {'query_id':'q','stage':'query_deadline_reached','elapsed_wall_s':30.1}]
            (folder/'stages.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
            result=exporter.read_queries(root,[])
            self.assertEqual(result[0]['timeout_s'],30)
            self.assertEqual(result[0]['outcome'],'deadline_observed')
            self.assertNotIn('inference_completed',result[0]['outcome'])

    def test_partial_run_exports_missing_assets_without_creating_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'original';run.mkdir();obs=root/'observations';d=obs/'frame';d.mkdir(parents=True)
            write(run/'result.json',{'run_id':'r','passed':False,'orders':[]})
            write(run/'declaration.json',{})
            write(run/'manifest-used.json',{'factory_delivery':{'id':'scene'}})
            write(d/'observation.json',{'episode_id':'e','sequence':2,'stamp':1.,'arm_id':'load','cargo_id':'cargo_2','frame':'optical','point_count':25})
            write(d/'camera.json',{})
            output=root/'derived';result=exporter.export(run,obs,output)
            entry=result['entries'][0]
            self.assertIsNone(entry['task_id']);self.assertEqual(entry['phase'],'load')
            self.assertIsNone(entry['selected']);self.assertEqual(entry['inference']['status'],'not_observed')
            self.assertTrue(all(v is None for v in entry['images'].values()))
            self.assertTrue(all(v is None for v in entry['milestones'].values()))
            self.assertFalse(result['new_execution']);self.assertFalse(result['rescored'])
            self.assertTrue((output/'visual-chain.json').is_file())

    def test_wrong_episode_video_is_never_used_for_lift(self):
        from unittest.mock import patch
        case={'task_id':'t','episode_id':'e','spans':[{'label':'arm_lift','start_source_s':2,'end_source_s':4}]}
        observation={'episode_id':'e','stamp':1}
        index=[{'video_frame':5,'metadata':{'episode_id':'other','stamp':3}}]
        with tempfile.TemporaryDirectory() as tmp, patch.object(exporter,'original_gate',return_value=({'first_pass_stamp':3,'passed':False},.2)):
            root=Path(tmp);warnings=[]
            result=exporter.milestone(root,case,{'frames':[]},observation,'load','lift',index,root/'missing.mp4',root,'/workbench/',warnings)
            self.assertIsNone(result['image']);self.assertFalse(result['original_passed'])
            self.assertTrue(any('no actual overview frame' in w for w in warnings))


if __name__ == '__main__':unittest.main()
