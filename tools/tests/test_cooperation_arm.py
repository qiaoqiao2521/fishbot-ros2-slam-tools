"""Real child lifecycle with a bounded protocol fixture; no ROS or physics."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from cooperation_arm import query_approach


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
if mode=='timeout': time.sleep(5)
result={'query_id':payload['query_id'],'plan':{'planning':{'status':'solved'},'segments':[{}]*5}}
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


if __name__ == '__main__': unittest.main()
