"""Exercise the production receiver thread without ROS discovery or motion."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from cooperation_camera import system_vision_environment


class CameraReceiverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The main runner may use planning NumPy. Exercise the actual helper
        # under the detector's system interpreter, without initializing ROS.
        code = r'''
import json,queue,sys,threading
sys.path.insert(0,sys.argv[1])
from cooperation_station_vision import CameraReceiver
from cooperation_camera import LatestCameraSnapshot

class CallbackExecutor:
 def __init__(self):
  self.callbacks=queue.Queue();self.stopped=threading.Event();self.shutdown_calls=0
 def spin(self):
  while not self.stopped.is_set():
   try:callback=self.callbacks.get(timeout=.01)
   except queue.Empty:continue
   callback()
 def shutdown(self,timeout_sec):
  assert timeout_sec==2.
  self.shutdown_calls+=1;self.stopped.set();return True

executor=CallbackExecutor();receiver=CameraReceiver(executor);slot=LatestCameraSnapshot()
first=threading.Event();advanced=threading.Event();arrivals=[];clock=[0.]
inference_thread=threading.get_ident()
def captured(stamp):
 arrivals.append([stamp,threading.get_ident()])
 slot.offer({'stamp':stamp,'episode_id':'episode','sequence':int(stamp)})
 if stamp==1.:first.set()
 if stamp==4.:advanced.set()
receiver.start();executor.callbacks.put(lambda:captured(1.))
assert first.wait(1.)
inference_input=slot.take()
# Reception must advance during this controlled slow-inference interval.
# No inference call spins the executor or drains its callback queue.
for stamp in (2.,3.,4.):
 executor.callbacks.put(lambda stamp=stamp:clock.__setitem__(0,stamp))
 executor.callbacks.put(lambda stamp=stamp:captured(stamp))
received_during_inference=advanced.wait(1.)
receiver.check();latest=slot.take();receiver.close()

class FailedExecutor(CallbackExecutor):
 def spin(self):raise ValueError('receive fixture failed')
failed=CameraReceiver(FailedExecutor());failed.start();failed.thread.join(timeout=1.)
try:failed.check();failure=None
except RuntimeError as error:failure=str(error)
failed.close()

class IncompleteShutdown(CallbackExecutor):
 def spin(self):return
 def shutdown(self,timeout_sec):return False
incomplete=CameraReceiver(IncompleteShutdown());incomplete.start();incomplete.thread.join(timeout=1.)
try:incomplete.close();shutdown_failure=None
except RuntimeError as error:shutdown_failure=str(error)
print(json.dumps({'received_during_inference':received_during_inference,'arrivals':arrivals,
 'inference_thread':inference_thread,'inference_input':inference_input,'latest':latest,
 'clock':clock[0],'overwritten':slot.overwritten,'receiver_alive':receiver.thread.is_alive(),
 'shutdown_calls':executor.shutdown_calls,'failure':failure,'shutdown_failure':shutdown_failure}))
'''
        result = subprocess.run(['/usr/bin/python3', '-B', '-c', code, str(TOOLS)],
                                env=system_vision_environment(), capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise RuntimeError(result.stdout+result.stderr)
        cls.evidence = json.loads(result.stdout)

    def test_reception_and_clock_continue_on_distinct_thread_during_slow_inference(self):
        evidence=self.evidence
        self.assertTrue(evidence['received_during_inference'])
        self.assertEqual([row[0] for row in evidence['arrivals']],[1.,2.,3.,4.])
        receiver_threads={row[1] for row in evidence['arrivals']}
        self.assertEqual(len(receiver_threads),1)
        self.assertNotIn(evidence['inference_thread'],receiver_threads)
        self.assertEqual(evidence['clock'],4.)

    def test_completed_inference_does_not_replay_pending_frame_fifo(self):
        self.assertEqual(self.evidence['inference_input']['stamp'],1.)
        self.assertEqual(self.evidence['latest']['stamp'],4.)
        self.assertEqual(self.evidence['overwritten'],2)

    def test_receiver_shutdown_joins_thread_and_errors_remain_explicit(self):
        self.assertFalse(self.evidence['receiver_alive'])
        self.assertEqual(self.evidence['shutdown_calls'],1)
        self.assertIn('ValueError: receive fixture failed',self.evidence['failure'])
        self.assertIn('did not stop',self.evidence['shutdown_failure'])


class VisionPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        code = r'''
import json,sys,tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,sys.argv[1])
import cooperation_station_vision as vision

with tempfile.TemporaryDirectory() as directory:
 root=Path(directory);retained=[];pixels=np.zeros((8,8,3),dtype=np.uint8)
 original_png=root/'detection-evidence.png';original_png.write_bytes(b'original detector pixels')
 def metadata(sequence):
  return {'stamp':sequence*.02,'scene_sha256':'a'*64,'manifest_sha256':'b'*64,
   'episode_id':'00000000-0000-0000-0000-000000000001','sequence':sequence,
   'wall_time':1000.+sequence,'corners':[[1.,1.],[6.,1.],[6.,6.],[1.,6.]],
   'image_width':8,'image_height':8,
   'image_file':f'vision-00000000-0000-0000-0000-000000000001-{sequence}.jpg'}
 first=metadata(1);vision.commit_vision_preview(root,pixels,first,retained)
 first_image=(root/first['image_file']).read_bytes()
 first_json=(root/first['image_file']).with_suffix('.json').read_bytes()
 order=[];real_link=vision.os.link;real_replace=Path.replace
 def link(source,target):
  order.append('frame_metadata')
  assert json.loads((root/'vision-latest.json').read_text())==first
  return real_link(source,target)
 def replace(source,target):
  if Path(target).name=='vision-latest.json':
   order.append('latest_pointer');value=json.loads(source.read_text())
   image=root/value['image_file']
   assert image.is_file() and json.loads(image.with_suffix('.json').read_text())==value
  return real_replace(source,target)
 with patch.object(vision.os,'link',side_effect=link),patch.object(Path,'replace',replace):
  second=metadata(2);vision.commit_vision_preview(root,pixels,second,retained)
 immutable_error=None
 try:vision.commit_vision_preview(root,np.full_like(pixels,255),first,retained)
 except FileExistsError as error:immutable_error=type(error).__name__
 immutable_unchanged=((root/first['image_file']).read_bytes()==first_image and
  (root/first['image_file']).with_suffix('.json').read_bytes()==first_json)
 for sequence in range(3,36):vision.commit_vision_preview(root,pixels,metadata(sequence),retained)
 image_sequences=sorted(int(path.stem.rsplit('-',1)[1]) for path in root.glob('vision-*.jpg'))
 metadata_sequences=sorted(int(path.stem.rsplit('-',1)[1]) for path in root.glob('vision-*.json')
  if path.name!='vision-latest.json')
 values=[json.loads(path.with_suffix('.json').read_text()) for path in retained]
 print(json.dumps({'order':order,'immutable_error':immutable_error,'immutable_unchanged':immutable_unchanged,
  'image_sequences':image_sequences,'metadata_sequences':metadata_sequences,'retained_count':len(retained),
  'all_metadata_preserved':all(value==metadata(value['sequence']) for value in values),
  'latest':json.loads((root/'vision-latest.json').read_text()),'expected_latest':metadata(35),
  'png_unchanged':original_png.read_bytes()==b'original detector pixels',
  'temporary_files':[path.name for path in root.iterdir() if '.tmp' in path.name or path.name.startswith('vision-next-')]}))
'''
        result = subprocess.run(['/usr/bin/python3', '-B', '-c', code, str(TOOLS)],
                                env=system_vision_environment(), capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise RuntimeError(result.stdout+result.stderr)
        cls.evidence = json.loads(result.stdout)

    def test_frame_metadata_commits_before_latest_and_identity_is_immutable(self):
        self.assertEqual(self.evidence['order'], ['frame_metadata', 'latest_pointer'])
        self.assertEqual(self.evidence['immutable_error'], 'FileExistsError')
        self.assertTrue(self.evidence['immutable_unchanged'])

    def test_retains_32_actual_image_metadata_pairs_and_collects_both_files(self):
        self.assertEqual(self.evidence['retained_count'], 32)
        self.assertEqual(self.evidence['image_sequences'], list(range(4, 36)))
        self.assertEqual(self.evidence['metadata_sequences'], list(range(4, 36)))
        self.assertEqual(self.evidence['temporary_files'], [])

    def test_original_capture_identity_and_png_evidence_remain_unchanged(self):
        self.assertTrue(self.evidence['all_metadata_preserved'])
        self.assertTrue(self.evidence['png_unchanged'])
        self.assertEqual(self.evidence['latest'], self.evidence['expected_latest'])


if __name__ == '__main__':
    unittest.main()
