"""Real child lifecycle with a bounded protocol fixture; no ROS or physics."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from cooperation_arm import ArmPlanner, query_approach, query_placement


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
print('owned child diagnostic marker',file=sys.stderr,flush=True)
placement=mode.startswith('placement_')
if placement: mode=mode[len('placement_'):]
if mode=='timeout': time.sleep(5)
result={'query_id':payload['query_id'],'plan':{'planning':{'status':'solved'},'segments':[{}]*5}}
if placement: result['plan']={'retreat':{'status':'solved'},'report':{},'segments':[{}]*(len(payload['centers_local'])+3)}
if mode=='shortcut': result['plan']['planning']['path_simplification']={'applied':True}
if mode=='selection': result['plan'].update({k:payload[k] for k in ('arm_id','cargo_id','snapshot')})
if placement and mode=='selection': result['plan']['centers_local']=payload['centers_local']
if mode=='unsolved': result['plan']['retreat']['status']='timeout'
if mode=='prepared':
 result['plan']['transfer_inputs']={'paths':payload['prepared_models']['paths'],
  'exists':all(Path(p).is_file() for p in payload['prepared_models']['paths'].values()),
  'frozen_geoms':payload['prepared_models']['frozen_geoms']}
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

    def test_real_shortcut_audit_is_preserved_in_execution_receipt(self):
        with self.worker('shortcut'): result = self.query()
        self.assertTrue(result['planning']['execution']['shortcut_applied'])

    def test_unloaded_optimization_is_opt_in_and_preserves_original_checker(self):
        from types import SimpleNamespace
        original = {'status':'solved','path':[[0]*5,[1]*5]}
        planner = ArmPlanner.__new__(ArmPlanner); planner.manifest = {}
        with patch('cooperation_path_simplify.simplify_joint_plan') as optimize:
            self.assertIs(planner._simplify_unloaded(original, .015), original)
            optimize.assert_not_called()
            planner.manifest['arm_path_simplification_s'] = 1.
            checker = SimpleNamespace(bounds=[[-2,2]]*5,is_valid=lambda q:True)
            validator = lambda *args: {'valid':True}
            planner.open_checker = checker
            planner.modules = {'joint_planner':SimpleNamespace(validate_joint_path=validator)}
            planner._simplify_unloaded(original, .015)
            optimize.assert_called_once_with(original, checker.bounds, checker.is_valid,
                validator, resolution_rad=.015, budget_s=1.)

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

    def test_prepared_models_use_owned_temporary_transfer_and_are_removed_after_child(self):
        class Prepared:
            def save_query_models(self, directory):
                paths = {}
                for name in ('common', 'contact', 'rig'):
                    path = directory/(name+'.mjb'); path.write_bytes(b'protocol fixture only')
                    paths[name] = str(path)
                return {'paths': paths, 'frozen_geoms': [{'source': 'kept', 'query': 'kept'}]}
        with self.worker('prepared'):
            result = self.query(prepared_planner=Prepared())
        transfer = result['transfer_inputs']
        self.assertTrue(transfer['exists'])
        self.assertEqual(transfer['frozen_geoms'], [{'source': 'kept', 'query': 'kept'}])
        self.assertTrue(result['planning']['execution']['prepared_model_transfer'])
        self.assertTrue(all(not Path(path).exists() for path in transfer['paths'].values()))
        self.assertEqual(self.children[0].poll(), 0)

    def test_prepared_transfer_files_are_removed_after_timeout_cancel_and_child_failure(self):
        class Prepared:
            def save_query_models(self, directory):
                self.paths = {}
                for name in ('common', 'contact', 'rig'):
                    path = directory/(name+'.mjb'); path.write_bytes(b'protocol fixture only')
                    self.paths[name] = str(path)
                return {'paths': self.paths, 'frozen_geoms': []}
        for failure in ('timeout', 'cancel', 'error'):
            with self.subTest(failure=failure):
                prepared = Prepared()
                checks = 0
                def checked():
                    nonlocal checks
                    checks += 1
                    if failure == 'cancel' and checks >= 3:
                        raise RuntimeError('original owner canceled')
                mode = 'error' if failure == 'error' else 'timeout'
                with self.worker(mode), self.assertRaises((RuntimeError, TimeoutError)):
                    self.query(prepared_planner=prepared, timeout_s=.2, check=checked)
                self.assertTrue(all(not Path(path).exists() for path in prepared.paths.values()))
                self.assertIsNotNone(self.children[-1].poll())

    def test_failed_prepared_model_save_reclaims_partial_models_without_spawning(self):
        class BrokenPrepared:
            def save_query_models(self, directory):
                self.directory = directory
                (directory/'common.mjb').write_bytes(b'incomplete protocol fixture')
                raise OSError('fixture serialization failed')
        prepared = BrokenPrepared()
        with self.worker(), self.assertRaisesRegex(OSError, 'serialization failed'):
            self.query(prepared_planner=prepared)
        self.assertFalse(prepared.directory.exists())
        self.assertEqual(self.children, [])

    def test_prepared_model_serialization_consumes_the_original_query_wall_budget(self):
        import time
        class SlowPrepared:
            def save_query_models(self, directory):
                time.sleep(.12)
                return {'paths': {}, 'frozen_geoms': []}
        with self.worker(), self.assertRaises(TimeoutError):
            self.query(prepared_planner=SlowPrepared(), timeout_s=.05)
        self.assertEqual(self.children, [])

    def test_visual_query_timeout_keeps_real_child_diagnostics_after_temp_cleanup(self):
        import json
        directory = Path(self.folder.name)/'evidence'
        manifest = {'pretrained_grasp': {'enabled': True, 'output_directory': str(directory)}}
        with self.worker('timeout'), self.assertRaises(TimeoutError):
            query_approach(manifest, [0.]*6, [0.]*7, check=lambda: None, timeout_s=.2)
        receipts = list((directory/'query-receipts').iterdir())
        self.assertEqual(len(receipts), 1)
        receipt = receipts[0]
        stages = [json.loads(line) for line in (receipt/'stages.jsonl').read_text().splitlines()]
        self.assertIn('query_deadline_reached', [row['stage'] for row in stages])
        self.assertIn('query_cleanup_completed', [row['stage'] for row in stages])
        cleanup = json.loads((receipt/'cleanup.json').read_text())
        self.assertTrue(cleanup['child_exited'])
        self.assertEqual(cleanup['outcome'], 'TimeoutError')
        self.assertIn('owned child diagnostic marker', (receipt/'child-log-tail.txt').read_text())
        self.assertTrue((receipt/'request.json').is_file())
        self.assertFalse((receipt/'response.json').exists())
        self.assertIsNotNone(self.children[0].poll())

    def test_ideal_query_can_record_evidence_without_enabling_a_model(self):
        from cooperation_query_trace import optional_query_trace
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            trace = optional_query_trace({'arm_query_evidence_directory':directory, 'pretrained_grasp':None}, 'ideal-query', 0.)
            self.assertIsNotNone(trace)
            trace.emit('ideal_test', inference_called=False)
            self.assertTrue((Path(directory)/'query-receipts/ideal-query/stages.jsonl').is_file())

    def test_unwritable_optional_trace_does_not_reject_valid_original_query(self):
        directory = Path(self.folder.name)/'not-a-directory'
        directory.write_text('keep original')
        manifest = {'pretrained_grasp': {'enabled': True, 'output_directory': str(directory)}}
        with self.worker(), self.assertLogs(level='WARNING'):
            result = query_approach(manifest, [0.]*6, [0.]*7, check=lambda: None)
        self.assertEqual(result['planning']['status'], 'solved')
        self.assertEqual(directory.read_text(), 'keep original')

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

    def test_placement_can_transfer_fresh_owner_models_without_changing_named_snapshot(self):
        class Prepared:
            def save_query_models(self, directory):
                self.paths={}
                for name in ('common','contact','rig'):
                    path=directory/(name+'.mjb');path.write_bytes(b'placement fixture only')
                    self.paths[name]=str(path)
                return {'paths':self.paths,'frozen_geoms':[{'source':'post-grasp','query':'post-grasp'}]}
        prepared=Prepared()
        with self.worker('placement_prepared'):
            result=self.query(prepared_planner=prepared,timeout_s=179.)
        self.assertEqual(result['transfer_inputs']['frozen_geoms'],[{'source':'post-grasp','query':'post-grasp'}])
        self.assertTrue(result['report']['execution']['prepared_model_transfer'])
        self.assertTrue(all(not Path(path).exists() for path in prepared.paths.values()))

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


class PlacementPreparedContextTests(unittest.TestCase):
    def test_only_owned_prepared_context_skips_duplicate_refresh_but_maps_real_snapshot(self):
        import numpy as np
        from types import SimpleNamespace as NS
        from unittest.mock import Mock
        local = {'qpos': list(range(13)), 'qvel': list(range(12)), 'ctrl': list(range(6))}
        raw = {'source_snapshot': 'post-grasp'}
        for prepared in (False, True):
            with self.subTest(prepared=prepared):
                data = NS(qpos=np.zeros(13),qvel=np.zeros(12),ctrl=np.zeros(6))
                planner = ArmPlanner.__new__(ArmPlanner)
                planner.np=np;planner.contact=object()
                def contact_boundary(model, actual):
                    np.testing.assert_array_equal(actual.qpos, local['qpos'])
                    np.testing.assert_array_equal(actual.qvel, local['qvel'])
                    np.testing.assert_array_equal(actual.ctrl, local['ctrl'])
                    raise RuntimeError('stop_after_real_contact_context_boundary')
                planner.mujoco=NS(MjData=lambda model:data,mj_forward=contact_boundary)
                planner.entity_view=NS(canonical_snapshot=Mock(return_value=local))
                planner.refresh_placement_context=Mock(return_value=local)
                with self.assertRaisesRegex(RuntimeError,'real_contact_context_boundary'):
                    planner.prepare_placement(raw, [[.18,0.,.06]], _context_prepared=prepared)
                if prepared:
                    planner.entity_view.canonical_snapshot.assert_called_once_with(raw)
                    planner.refresh_placement_context.assert_not_called()
                else:
                    planner.refresh_placement_context.assert_called_once_with(raw,car_pose=None)
                    planner.entity_view.canonical_snapshot.assert_not_called()

    def test_prepared_context_keeps_original_measured_control_requirement(self):
        import numpy as np
        from types import SimpleNamespace as NS
        planner=ArmPlanner.__new__(ArmPlanner);planner.np=np;planner.mujoco=object()
        planner.entity_view=NS(canonical_snapshot=lambda snapshot:{'qpos':[], 'qvel':[]})
        with self.assertRaisesRegex(ValueError,'current actuator references'):
            planner.prepare_placement({}, [[.18,0.,.06]], _context_prepared=True)


if __name__ == '__main__': unittest.main()
