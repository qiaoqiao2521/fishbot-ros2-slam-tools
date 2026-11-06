"""Native OMPL obstacle cases using the unchanged source edge validator."""
import copy
from importlib.util import module_from_spec, spec_from_file_location
import math
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from cooperation_path_simplify import path_length, simplify_joint_plan
spec=spec_from_file_location('source_joint_planner',ROOT.parent/'so101/experiments/colab-twin/joint_planner.py')
source=module_from_spec(spec);spec.loader.exec_module(source)


def planned(path):
    return {'status':'solved','exact_solution':True,'path':path,'planner':'RRTConnect',
            'resolution_rad':.01,'path_length_rad':path_length(path),'waypoint_count':len(path)}


class PathSimplificationTests(unittest.TestCase):
    bounds=[[-2.,2.],[-2.,2.],[-1.,1.],[-1.,1.],[-1.,1.]]

    def test_native_simplification_keeps_blocked_direct_path_outside_obstacle(self):
        def valid(q):return not(abs(q[0])<.4 and abs(q[1])<.4)
        path=[[x,y,0.,0.,0.] for x,y in [(-1,0),(-1,.9),(-.7,.9),(-.6,.65),(.6,.65),(.7,.9),(1,.9),(1,0)]]
        direct=source.validate_joint_path([path[0],path[-1]],valid,.01)
        self.assertFalse(direct['valid'])
        original=planned(path);before=copy.deepcopy(original)
        result=simplify_joint_plan(original,self.bounds,valid,source.validate_joint_path,budget_s=.2)
        audit=result['path_simplification']
        self.assertTrue(audit['applied'],audit)
        self.assertEqual(result['path'][0],path[0]);self.assertEqual(result['path'][-1],path[-1])
        self.assertLess(result['path_length_rad'],original['path_length_rad'])
        self.assertTrue(source.validate_joint_path(result['path'],valid,.01)['valid'])
        self.assertTrue(any(abs(q[1])>=.4 for q in result['path'] if abs(q[0])<.4))
        self.assertEqual(original,before)
        self.assertLess(audit['native_simplify_wall_s'],.6)
        self.assertEqual(audit['original_planner'],'RRTConnect')
        self.assertFalse(audit['rng_reseeded'])

    def test_no_improvement_retains_original_and_does_not_change_resolution(self):
        original=planned([[0.,0.,0.,0.,0.],[.5,0.,0.,0.,0.]])
        result=simplify_joint_plan(original,self.bounds,lambda q:True,source.validate_joint_path,
                                   resolution_rad=.02,budget_s=.2)
        self.assertFalse(result['path_simplification']['applied'])
        self.assertEqual(result['path'],original['path'])
        self.assertEqual(result['path_simplification']['resolution_rad'],.01)

    def test_native_budget_does_not_keep_calling_expensive_geometry_after_deadline(self):
        import time
        def valid(q):
            time.sleep(.002)
            return not(abs(q[0])<.4 and abs(q[1])<.4)
        path=[[x,y,0.,0.,0.] for x,y in [(-1,0),(-1,.9),(-.6,.65),(.6,.65),(1,.9),(1,0)]]
        original=planned(path)
        result=simplify_joint_plan(original,self.bounds,valid,source.validate_joint_path,budget_s=.025)
        self.assertLess(result['path_simplification']['native_simplify_wall_s'],.20)
        self.assertEqual(result['path'][0],path[0]);self.assertEqual(result['path'][-1],path[-1])
        self.assertTrue(source.validate_joint_path(result['path'],lambda q:not(abs(q[0])<.4 and abs(q[1])<.4),.01)['valid'])

    def test_callback_failure_is_audited_and_original_path_is_preserved(self):
        original=planned([[0.,0.,0.,0.,0.],[.5,0.,0.,0.,0.]])
        def broken(q):raise RuntimeError('original query unavailable')
        result=simplify_joint_plan(original,self.bounds,broken,source.validate_joint_path)
        self.assertFalse(result['path_simplification']['applied'])
        self.assertEqual(result['path'],original['path'])
        self.assertEqual(result['path_simplification']['error_type'],'RuntimeError')

    def test_candidate_rejected_by_final_original_validator_keeps_original_route(self):
        original=planned([[0.,0.,0.,0.,0.],[0.,1.,0.,0.,0.],[1.,1.,0.,0.,0.],[1.,0.,0.,0.,0.]])
        calls=[]
        def final_validator(path,valid,resolution):
            calls.append(path)
            result=source.validate_joint_path(path,valid,resolution)
            if len(calls)>1:
                result.update(valid=False,reason='candidate_rejected_by_authoritative_validator')
            return result
        result=simplify_joint_plan(original,self.bounds,lambda q:True,final_validator,budget_s=.2)
        self.assertEqual(len(calls),2)
        self.assertFalse(result['path_simplification']['applied'])
        self.assertEqual(result['path'],original['path'])
        self.assertEqual(result['path_simplification']['reason'],'simplified_path_post_validation_failed')

    def test_original_invalid_or_unsolved_path_is_never_repaired_into_a_pass(self):
        original=planned([[0.,0.,0.,0.,0.],[.5,0.,0.,0.,0.]])
        result=simplify_joint_plan(original,self.bounds,lambda q:False,source.validate_joint_path)
        self.assertFalse(result['path_simplification']['applied'])
        self.assertEqual(result['path_simplification']['reason'],'original_path_invalid_in_current_context')
        result=simplify_joint_plan({**original,'status':'timeout'},self.bounds,lambda q:True,source.validate_joint_path)
        self.assertEqual(result['path_simplification']['reason'],'original_plan_not_exact_solved')


if __name__=='__main__':unittest.main()
