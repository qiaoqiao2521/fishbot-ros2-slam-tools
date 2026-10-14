"""Source fences, system ABI separation and image-only marker regressions."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from cooperation_camera import LatestCameraSnapshot, system_vision_environment


class CameraSourceTests(unittest.TestCase):
    def test_latest_only_and_episode_fence_do_not_admit_old_frames(self):
        slot = LatestCameraSnapshot()
        self.assertTrue(slot.offer({'stamp': 1., 'episode_id': 'first', 'sequence': 1}))
        self.assertTrue(slot.offer({'stamp': 2., 'episode_id': 'first', 'sequence': 2}))
        self.assertEqual(slot.overwritten, 1)
        self.assertEqual(slot.take()['sequence'], 2)
        slot.fence('second')
        self.assertFalse(slot.offer({'stamp': 1.9, 'episode_id': 'first', 'sequence': 3}))
        self.assertFalse(slot.current('first'))
        self.assertTrue(slot.offer({'stamp': 2.1, 'episode_id': 'second', 'sequence': 4}))
        self.assertFalse(slot.offer({'stamp': 2.1, 'episode_id': 'second', 'sequence': 5}))
        self.assertEqual(slot.take()['sequence'], 4)

    def test_system_detector_keeps_ros_and_rejects_planning_numpy_path(self):
        env = {'PYTHONPATH': '/x/planning-venv/lib/python3.12/site-packages:/opt/ros/jazzy/lib/python3.12/site-packages:/usr/lib/python3/dist-packages',
               'ROS_DOMAIN_ID': '121', 'LD_LIBRARY_PATH': '/runtime/lib'}
        filtered = system_vision_environment(env)
        self.assertNotIn('planning-venv', filtered['PYTHONPATH'])
        self.assertIn('/opt/ros/jazzy/', filtered['PYTHONPATH'])
        self.assertEqual(filtered['ROS_DOMAIN_ID'], '121')
        self.assertEqual(filtered['LD_LIBRARY_PATH'], '/runtime/lib')
        self.assertIn('planning-venv', env['PYTHONPATH'])


class StationImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        code = r'''
import json,math,sys
import cv2,numpy as np
sys.path.insert(0,sys.argv[1])
from cooperation_camera import calibration
from cooperation_station_vision import estimate_station,transform
c=calibration([-1.8,-1.8,0.])
a=cv2.aruco;dictionary=a.getPredefinedDictionary(a.DICT_APRILTAG_36h11)
def bitmap(identity):
 rgb=np.full((480,640,3),255,dtype=np.uint8)
 rgb[120:360,200:440,:]=a.drawMarker(dictionary,identity,240)[:,:,None]
 return rgb
good=estimate_station(bitmap(0),c)
wrong=estimate_station(bitmap(1),c)
blank=estimate_station(np.full((480,640,3),255,dtype=np.uint8),c)
small=np.full((480,640,3),255,dtype=np.uint8)
small[216:264,296:344,:]=a.drawMarker(dictionary,0,48)[:,:,None]
low_resolution=estimate_station(small,c)
cov=np.asarray(good['covariance']).reshape(6,6)
distance=c['k'][0]*c['tag_size_m']/240.
expected=[.20-distance,-c['tag_lateral_offset_m'],math.pi]
tilted=[]
texture=cv2.copyMakeBorder(a.drawMarker(dictionary,0,512),64,64,64,64,cv2.BORDER_CONSTANT,value=255)
texture_corners=np.array([[-.5,-.5],[639.5,-.5],[639.5,639.5],[-.5,639.5]],dtype=np.float32)
plate=np.array([[-.075,.075,0.],[.075,.075,0.],[.075,-.075,0.],[-.075,-.075,0.]])
sensor=np.asarray(c['k']).reshape(3,3).copy()
sensor[0,0]*=2;sensor[1,1]*=2
sensor[0,2]=(sensor[0,2]+.5)*2-.5;sensor[1,2]=(sensor[1,2]+.5)*2-.5
base_camera=transform(c['base_camera_rotation'],c['base_camera_translation'])
world_tag=transform(c['tag_world_rotation'],c['tag_world_position'])
position=np.array([-1.235,-1.8,-.000058])
for pitch in (-.072,-.044,-.0123,.0123,.044,.072):
 cp,sp=math.cos(pitch),math.sin(pitch)
 rotation=np.array([[cp,0.,sp],[0.,1.,0.],[-sp,0.,cp]])
 world_base=transform(rotation,position)
 camera_tag=np.linalg.inv(world_base@base_camera)@world_tag
 projection,_=cv2.projectPoints(plate,cv2.Rodrigues(camera_tag[:3,:3])[0],camera_tag[:3,3],sensor,np.asarray(c['d']))
 mapping=cv2.getPerspectiveTransform(texture_corners,projection.reshape(4,2).astype(np.float32))
 pixels=cv2.warpPerspective(texture,mapping,(1280,960),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=255)
 pixels=cv2.resize(pixels,(640,480),interpolation=cv2.INTER_AREA)
 measured=estimate_station(np.repeat(pixels[:,:,None],3,axis=2),c)
 # Fixture poses create the image; expected poses are only scored afterwards.
 error_xy=error_yaw=None
 if measured['detected']:
  mx,my,myaw=measured['relative'];heading=math.pi-myaw
  reconstructed=np.array([-1.8-math.cos(heading)*mx+math.sin(heading)*my,
                           -1.8-math.sin(heading)*mx-math.cos(heading)*my])
  error_xy=float(np.linalg.norm(reconstructed-position[:2]))
  error_yaw=abs(math.atan2(math.sin(heading),math.cos(heading)))
  full_covariance=np.asarray(measured['unconstrained_pose_covariance6x6']).reshape(6,6)
  covariance_min=float(np.linalg.eigvalsh(full_covariance).min())
 else:covariance_min=None
 tilted.append({'pitch':pitch,'measured':measured,'world_xy_error_m':error_xy,
                'world_yaw_error_rad':error_yaw,'full_covariance_min_eigenvalue':covariance_min})
print(json.dumps({'good':good,'wrong':wrong,'blank':blank,'low_resolution':low_resolution,'expected':expected,
 'calibration_pose_model':c['pose_model'],'tilted':tilted,
 'covariance_min_eigenvalue':float(np.linalg.eigvalsh(cov).min()),
 'max_unused_axis_variance':float(np.max(np.abs(cov[[2,3,4]])))},allow_nan=False))
'''
        result = subprocess.run(['/usr/bin/python3', '-B', '-c', code, str(TOOLS)],
                                env=system_vision_environment(), capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise RuntimeError(result.stdout+result.stderr)
        cls.evidence = json.loads(result.stdout)

    def test_marker_size_and_mount_compose_the_native_dock_frame(self):
        measured, expected = self.evidence['good'], self.evidence['expected']
        self.assertTrue(measured['detected'], measured['reason'])
        self.assertAlmostEqual(measured['relative'][0], expected[0], delta=.003)
        self.assertAlmostEqual(measured['relative'][1], expected[1], delta=.003)
        yaw = measured['relative'][2]
        self.assertLess(abs(abs(yaw)-expected[2]), .005)
        self.assertGreater(len(measured['candidates']), 1)

    def test_wrong_identity_and_missing_pixels_never_create_a_station_pose(self):
        self.assertEqual(self.evidence['wrong']['reason'], 'wrong_or_duplicate_tag_id')
        for field in ('wrong', 'blank'):
            self.assertFalse(self.evidence[field]['detected'])
            self.assertIsNone(self.evidence[field]['relative'])
            self.assertIsNone(self.evidence[field]['covariance'])

    def test_covariance_is_psd_and_retains_only_declared_planar_axes(self):
        self.assertGreaterEqual(self.evidence['covariance_min_eigenvalue'], -1e-12)
        self.assertEqual(self.evidence['max_unused_axis_variance'], 0.)
        self.assertGreater(self.evidence['good']['covariance'][35], .0001)

    def test_decoded_small_tag_is_an_explicit_miss_without_a_station_pose(self):
        result = self.evidence['low_resolution']
        self.assertFalse(result['detected'])
        self.assertEqual(result['reason'], 'insufficient_resolution')
        self.assertLess(result['minimum_edge_px'], 60.)
        self.assertIsNone(result['relative'])
        self.assertIsNone(result['covariance'])

    def test_rgb_projection_during_pitch_preserves_6d_estimate_and_uncertainty(self):
        self.assertEqual(self.evidence['calibration_pose_model'], 'unconstrained_ippe')
        for frame in self.evidence['tilted']:
            with self.subTest(pitch=frame['pitch']):
                measured=frame['measured']
                self.assertTrue(measured['detected'],measured['reason'])
                self.assertEqual(measured['pose_model'],'unconstrained_ippe')
                self.assertGreaterEqual(measured['confidence'],.75)
                self.assertLessEqual(frame['world_xy_error_m'],.04)
                self.assertLessEqual(frame['world_yaw_error_rad'],.05)
                self.assertEqual(measured['covariance_model'],'full_6d_pixel_jacobian_with_calibration_floor')
                self.assertEqual(len(measured['unconstrained_pose_covariance6x6']),36)
                self.assertGreater(frame['full_covariance_min_eigenvalue'],0.)
                self.assertGreater(measured['covariance'][35],.0001)


if __name__ == '__main__':
    unittest.main()
