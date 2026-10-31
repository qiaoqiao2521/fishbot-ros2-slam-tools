"""Contract checks; these do not claim pretrained or physical success."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from cooperation_grasp_inference import candidate_pool, observed_points, warm_candidates


class GraspInferenceContractTests(unittest.TestCase):
    def test_visible_cloud_is_not_completed_or_resampled(self):
        points = np.arange(93, dtype=np.float32).reshape(31, 3)/1000
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'points.npy'
            np.save(path, points)
            np.testing.assert_array_equal(observed_points(path), points)

    def test_keeps_entire_pool_and_branch_origins(self):
        result = {'grasps_diff': np.repeat(np.eye(4)[None], 25, axis=0),
                  'scores_diff': np.arange(25)/25,
                  'grasps_obb': np.repeat(np.eye(4)[None], 54, axis=0),
                  'scores_obb': np.arange(54)/54}
        transform = np.eye(4)
        transform[:3, 3] = [.1, -.2, .3]
        poses, scores, origins = candidate_pool(result, transform)
        self.assertEqual(poses.shape, (79, 4, 4))
        self.assertEqual(len(scores), 79)
        self.assertEqual(list(origins).count('diff'), 25)
        self.assertEqual(list(origins).count('obb'), 54)
        np.testing.assert_allclose(poses[:, :3, 3], np.tile(transform[:3, 3], (79, 1)))

    def test_rotated_optical_transform_preserves_camera_pose(self):
        station_from_camera = np.array([[0., 0., -1., .45],
                                        [1., 0., 0., -.50],
                                        [0., -1., 0., .60],
                                        [0., 0., 0., 1.]])
        camera_pose = np.eye(4)
        camera_pose[:3, 3] = [.05, -.02, .7]
        result = {'grasps_diff': (station_from_camera @ camera_pose)[None],
                  'scores_diff': np.array([.75]),
                  'grasps_obb': np.empty((0, 4, 4)), 'scores_obb': np.empty(0)}
        poses, _, _ = candidate_pool(result, np.linalg.inv(station_from_camera))
        np.testing.assert_allclose(poses[0], camera_pose, atol=1e-7)

    def test_official_warm_client_retains_all_candidates_and_options(self):
        calls = []
        class Client:
            def __init__(self, **kwargs):
                calls.append(('connection', kwargs))
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            @property
            def server_metadata(self):
                return {'runtime': {'request_seed': 11, 'gpu': 'fixture'}}
            def infer_object(self, points, params, **kwargs):
                calls.append(('infer', kwargs))
                return np.repeat(np.eye(4)[None], 408, axis=0), np.ones(408), ['diff']*48+['obb']*360
        with patch('cooperation_grasp_inference.official_client', return_value=Client):
            result, report = warm_candidates(SimpleNamespace(server_port=10177, seed=11, samples=16),
                                            np.ones((312, 3)), {'params': {'declared': 'descriptor'}})
        poses, scores, tags = candidate_pool(result)
        self.assertEqual(len(scores), 408)
        self.assertEqual((tags == 'diff').sum(), 48)
        self.assertEqual((tags == 'obb').sum(), 360)
        request = next(value for kind, value in calls if kind == 'infer')
        self.assertEqual(request['topk_num_grasps'], -1)
        self.assertEqual(request['moe_z_offsets_cm'], (-2, 0))
        self.assertEqual(request['moe_obb_density'], 'dense-topandside')
        self.assertEqual(report['inference_runtime'], 'official_owned_zmq')
        self.assertTrue(all(value['host'] == '127.0.0.1' for kind, value in calls if kind == 'connection'))

    def test_rejects_nonfinite_or_nonrigid_output(self):
        result = {'grasps_diff': np.eye(4)[None], 'scores_diff': np.array([np.nan]),
                  'grasps_obb': np.empty((0, 4, 4)), 'scores_obb': np.empty(0)}
        with self.assertRaisesRegex(ValueError, 'nonfinite'):
            candidate_pool(result)
        result['scores_diff'][0] = .5
        result['grasps_diff'][0, 0, 0] = 2
        with self.assertRaisesRegex(ValueError, 'rotations'):
            candidate_pool(result)


if __name__ == '__main__':
    unittest.main()
