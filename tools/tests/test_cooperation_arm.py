"""Real child lifecycle with a bounded protocol fixture; no ROS or physics."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from cooperation_arm import query_approach, query_placement


class ApproachProcessTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        self.script = Path(self.folder.name)/'query.py'
        self.children = []
        self.spawn = subprocess.Popen

    def worker(self, mode='success'):
        self.script.write_text('''import json,sys,time
from pathlib import Path
request,response=map(Path,sys.argv[-2:]); payload=json.loads(request.read_text())
mode='''+repr(mode)+'''
placement=mode.startswith('placement_')
if placement: mode=mode[len('placement_'):]
if mode=='timeout': time.sleep(5)
result={'query_id':payload['query_id'],'plan':{'planning':{'status':'solved'},'segments':[{}]*5}}
if placement: result['plan']={'retreat':{'status':'solved'},'report':{},'segments':[{}]*(len(payload['centers_local'])+3)}
if mode=='selection': result['plan'].update({k:payload[k] for k in ('arm_id','cargo_id','snapshot')})
if placement and mode=='selection': result['plan']['centers_local']=payload['centers_local']
if mode=='unsolved': result['plan']['retreat']['status']='timeout'
if mode=='identity': result['query_id']='other-query'
if mode=='error': result['error']='original collision query failed'
if mode=='malformed': result['plan']['segments']=[]
response.write_text('x'*1048577 if mode=='oversize' else json.dumps(result))
if mode=='error': sys.exit(1)
''')
        def start(argv, **kwargs):
            child = self.spawn([sys.executable, '-B', str(self.script), *argv[-2:]], **kwargs)
            self.children.append(child); return child
        return patch('subprocess.Popen', side_effect=start)

    def query(self, **kwargs):
        return query_approach({}, [0.]*6, [0.]*7, check=kwargs.pop('check', lambda: None), **kwargs)

    def test_real_child_returns_only_matching_result_and_exits_before_admission(self):
        with self.worker(): result = self.query()
        self.assertTrue(result['planning']['execution']['child_exited'])
        self.assertFalse(result['planning']['execution']['shortcut_applied'])
        self.assertEqual(result['planning']['execution']['seed_scope'], 'first_plan_of_each_query_process')
        self.assertRegex(result['planning']['execution']['query_id'], r'^[a-f0-9-]{36}$')
        self.assertRegex(result['planning']['execution']['input_sha256'], r'^[a-f0-9]{64}$')
        self.assertEqual(self.children[0].poll(), 0)

    def test_original_owner_cancel_terminates_and_joins_only_its_query(self):
        calls = 0
        def canceled():
            nonlocal calls
            calls += 1
            if calls >= 2: raise RuntimeError('original owner canceled')
        with self.worker('timeout'), self.assertRaisesRegex(RuntimeError, 'original owner canceled'):
            self.query(check=canceled)
        self.assertEqual(len(self.children), 1); self.assertIsNotNone(self.children[0].poll())

    def test_owned_query_carries_named_selection_and_the_measured_snapshot(self):
        snapshot = {'qpos': [1., 2.], 'qvel': [3.]}
        with self.worker('selection'):
            result = self.query(arm_id='unload_line_b', cargo_id='cargo_2', snapshot=snapshot)
        self.assertEqual(result['arm_id'], 'unload_line_b')
        self.assertEqual(result['cargo_id'], 'cargo_2')
        self.assertEqual(result['snapshot'], snapshot)
        self.assertEqual(self.children[0].poll(), 0)

    def test_deadline_terminates_owned_child_without_accepting_late_result(self):
        with self.worker('timeout'), self.assertRaises(TimeoutError): self.query(timeout_s=.08)
        self.assertIsNotNone(self.children[0].poll())

    def test_no_child_is_launched_after_precheck_or_invalid_budget(self):
        with self.worker(), self.assertRaisesRegex(RuntimeError, 'stale episode'):
            self.query(check=lambda: (_ for _ in ()).throw(RuntimeError('stale episode')))
        with self.worker(), self.assertRaises(ValueError): self.query(timeout_s=31)
        self.assertEqual(self.children, [])

    def test_wrong_identity_original_failure_bad_shape_and_oversize_are_rejected(self):
        for mode in ('identity', 'error', 'malformed', 'oversize'):
            with self.subTest(mode=mode), self.worker(mode), self.assertRaises(RuntimeError): self.query()
        self.assertTrue(all(child.poll() is not None for child in self.children))


class PlacementProcessTests(unittest.TestCase):
    setUp = ApproachProcessTests.setUp
    worker = ApproachProcessTests.worker

    def query(self, **kwargs):
        return query_placement({}, {'car': {'position': [0.]*3, 'quaternion_wxyz': [1.,0.,0.,0.]},
            'qpos': [1.,2.], 'qvel': [3.]}, [[.18,0.,.06]]*5,
            check=kwargs.pop('check',lambda:None), timeout_s=kwargs.pop('timeout_s',180.),
            arm_id='load',cargo_id='cargo_2',**kwargs)

    def test_placement_child_binds_actual_snapshot_centers_and_remaining_budget(self):
        with self.worker('placement_selection'):result=self.query(timeout_s=179.)
        self.assertEqual(result['cargo_id'],'cargo_2')
        self.assertEqual(result['arm_id'],'load')
        self.assertEqual(result['snapshot']['qpos'],[1.,2.])
        self.assertEqual(result['centers_local'],[[.18,0.,.06]]*5)
        execution=result['report']['execution']
        self.assertTrue(execution['child_exited'])
        self.assertEqual(execution['wall_budget_s'],179.)
        self.assertGreater(execution['wall_remaining_s'],0.)
        self.assertFalse(execution['is_controller_consumption_ack'])
        self.assertNotEqual(execution['child_pid'],execution['caller_pid'])
        self.assertEqual(self.children[0].poll(),0)

    def test_original_owner_cancel_kills_and_joins_only_placement_child(self):
        calls=0
        def canceled():
            nonlocal calls
            calls+=1
            if calls>=2:raise RuntimeError('original placement owner canceled')
        with self.worker('placement_timeout'),self.assertRaisesRegex(RuntimeError,'original placement owner canceled'):
            self.query(check=canceled)
        self.assertEqual(len(self.children),1)
        self.assertIsNotNone(self.children[0].poll())

    def test_remaining_deadline_rejects_late_placement_without_resend(self):
        with self.worker('placement_timeout'),self.assertRaises(TimeoutError):self.query(timeout_s=.06)
        self.assertEqual(len(self.children),1)
        self.assertIsNotNone(self.children[0].poll())

    def test_placement_rejects_invalid_original_budget_before_child_spawn(self):
        for timeout in (0.,-1.,361.,float('nan')):
            with self.subTest(timeout=timeout),self.worker('placement_success'),self.assertRaises(ValueError):
                self.query(timeout_s=timeout)
        self.assertEqual(self.children,[])
        # An original load budget above approach's30s ceiling is accepted.
        with self.worker('placement_success'):result=self.query(timeout_s=360.)
        self.assertEqual(result['report']['execution']['wall_budget_s'],360.)

    def test_bad_placement_identity_original_failure_or_shape_never_accepted(self):
        for mode in ('identity','error','malformed','oversize','unsolved'):
            with self.subTest(mode=mode),self.worker('placement_'+mode),self.assertRaises(RuntimeError):
                self.query()
        self.assertTrue(all(child.poll() is not None for child in self.children))


if __name__ == '__main__': unittest.main()
