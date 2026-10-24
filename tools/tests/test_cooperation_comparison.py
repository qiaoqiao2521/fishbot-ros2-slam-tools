"""Display projection contracts only; these fixtures do not prove ROS motion."""
import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cooperation_comparison import project_case


class ComparisonTests(unittest.TestCase):
    def test_projection_preserves_native_failure_coordinates_and_gaps(self):
        case={'id':'case','task_id':'task','episode_id':'episode','scope':'route',
            'scene_id':'scene','vehicle':'jackal_j100','sensor':'lidar3d',
            'physical':{'final_position_error_m':.2},'route':{'start_wall_s':10.,'elapsed_s':120.01},
            'original_verdict':{'original_score_passed':False},'sampling':{'missing_samples':3},'spans':[]}
        rows=[{'source_s':100.+i*.1,'receive_wall_s':10.+i*.1,'sequence':i,'stage':'delivery',
            'car_position_m':[4.+i,-2.,0.],'car_quaternion_wxyz':[1.,0.,0.,0.],
            'cargo_position_m':[4.+i,-2.,.2],'arm_q6_rad':[0.]*6,'gap_before':i==1} for i in range(3)]
        before=copy.deepcopy(rows)
        result=project_case(case,iter(rows),label='baseline',manifest={
            'checkpoint_parent':{'snapshot_id':'same'}},project_arm=lambda q:[[1.,2.,3.],[4.,5.,6.]])
        self.assertEqual(rows,before)
        self.assertEqual(result['frames'][0]['car'],[4.,-2.,0.])
        self.assertTrue(result['frames'][1]['gap_before'])
        self.assertFalse(result['original_verdict']['original_score_passed'])
        self.assertEqual(result['anchors']['route'],100.)
        self.assertEqual(result['snapshot_id'],'same')
        self.assertEqual(result['frames'][0]['arm_joints_world'][1],[4.,5.,6.])

    def test_missing_source_does_not_discard_other_valid_samples(self):
        case={'id':'case','task_id':'task','episode_id':'episode','scene_id':'scene',
              'vehicle':'unknown','sensor':'unknown','physical':{},'route':{},
              'original_verdict':{},'sampling':{},'spans':[]}
        result=project_case(case,[{'source_s':None},{'source_s':.2}],label='partial',manifest={})
        self.assertEqual(len(result['frames']),1)
        self.assertTrue(result['warnings'])
        self.assertIsNone(result['frames'][0]['arm_joints_world'])


if __name__=='__main__':unittest.main()
