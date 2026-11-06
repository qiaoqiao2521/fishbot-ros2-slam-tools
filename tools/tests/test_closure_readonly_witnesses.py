"""Read-only observers must not occupy Factory's domain before owner readiness."""
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock

spec=importlib.util.spec_from_file_location('visual_cloud_adapter',Path(__file__).resolve().parents[2]/'experiments/kaggle/f1_visual_recovery.py')
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)

class ReadonlyWitnessTests(unittest.TestCase):
 def test_starts_only_after_owned_api_response(self):
  order=[]
  response=Mock(status=200);response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
  def ready(*a,**k):order.append('api-ready');return response
  def spawn(*a,**k):order.append('spawn');return Mock()
  with tempfile.TemporaryDirectory() as tmp, patch('urllib.request.urlopen',side_effect=ready), patch.object(adapter.subprocess,'Popen',side_effect=spawn):
   witnesses,stop,thread=adapter.readonly_witnesses_after_ready([['read-only']],cwd=tmp,env={},port=9157,output=Path(tmp));thread.join(2);stop.set()
   self.assertFalse(thread.is_alive());self.assertEqual(order,['api-ready','spawn']);self.assertEqual(len(witnesses),1)
   for process,log in witnesses:log.close()
 def test_failed_startup_can_stop_without_spawning_a_domain_node(self):
  entered=threading.Event();release=threading.Event()
  def unavailable(*a,**k):entered.set();release.wait(1);raise OSError('owner not ready')
  with tempfile.TemporaryDirectory() as tmp, patch('urllib.request.urlopen',side_effect=unavailable), patch.object(adapter.subprocess,'Popen') as spawn:
   witnesses,stop,thread=adapter.readonly_witnesses_after_ready([['read-only']],cwd=tmp,env={},port=9157,output=Path(tmp))
   self.assertTrue(entered.wait(1));stop.set();release.set();thread.join(2)
   self.assertFalse(thread.is_alive());self.assertEqual(witnesses,[]);spawn.assert_not_called()

if __name__=='__main__':unittest.main()
