"""Preserve actual RGB-D evidence when extraction fails before inference."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cooperation_visual_grasp import model_proposals

class CaptureReceiptTests(unittest.TestCase):
    def test_failed_extraction_keeps_images_and_source_identity_without_inventing_cloud(self):
        fake = SimpleNamespace(MjData=lambda model:SimpleNamespace(qpos=np.zeros(3),time=0.),
                               mj_forward=lambda model,data:None)
        camera={'name':'input-camera','frame_id':'optical','width':2,'height':2}
        snapshot={'qpos':[0.,0.,0.],'stamp':1.25,'sequence':9,'episode_id':'episode'}
        with tempfile.TemporaryDirectory() as tmp, patch.dict(sys.modules,{'mujoco':fake}), \
             patch('cooperation_workcell_vision.render_rgbd',return_value=(np.zeros((2,2,3),dtype=np.uint8),np.ones((2,2),dtype=np.float32))), \
             patch('cooperation_workcell_vision.object_points',side_effect=ImportError('numpy ABI extraction failure')):
            manifest={'pretrained_grasp':{'enabled':True,'output_directory':tmp},
                      'workcell_cameras':{'load':camera}}
            with self.assertRaisesRegex(ImportError,'numpy ABI'):
                model_proposals(manifest,snapshot,'load','cargo',model=object())
            folder=Path(tmp)/'episode-load-cargo-9'
            receipt=json.loads((folder/'observation.json').read_text())
            self.assertEqual((receipt['stamp'],receipt['sequence'],receipt['episode_id']),(1.25,9,'episode'))
            self.assertEqual(receipt['capture_status'],'rgbd_saved_only')
            self.assertIsNone(receipt['point_count']);self.assertTrue((folder/'rgb.png').is_file())
            np.testing.assert_array_equal(np.load(folder/'depth.npy'),np.ones((2,2),dtype=np.float32))
            self.assertFalse((folder/'points.npy').exists());self.assertFalse((folder/'mask.png').exists())
            self.assertFalse((folder/'inference').exists())

if __name__=='__main__':unittest.main()
