"""Independent acceptance failures and AMCL recovery ownership boundaries."""
import math
import json
import importlib.util
from concurrent.futures import Future
from pathlib import Path
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import numpy as np

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(TOOLS))
from fishbot_localization_quality import MapDistanceField, QualityGate, fresh_stationary_odom, quality_sample_fresh, recovery_quality_ready, resume_allowed
from fishbot_localization_recovery import AMCL_PROFILES, analyze_recording, confirmed_localization_loss, confirmed_observation_stop, confirmed_profile_change, initial_localization_error, localization_error, observation_chain, recovered_quality_window, select_transformed_scan, selected_environment, settle_owned_action
from fishbot_passage_goal import PendingGoal
_fixture_spec = importlib.util.spec_from_file_location('localization_fixture',TOOLS/'fishbot_localization_sim.launch.py')
_fixture = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture)


def good_recording():
    truth = [dict(steady_time=i*.05,stamp=100+i*.05,ros_now=100+i*.05,x=-2.4,y=-2.,yaw=0.,linear_speed=0.,angular_speed=0.)
             for i in range(-60,141)]
    recoveries = [dict(state='recovered',detector_state='lost',global_service_acknowledged=True,
                      stopped_from_odom=True,quality_state='healthy',fresh_post_service_pose=True,
                      duration_s=1.,truth_error=dict(xy_m=.03,yaw_rad=.03),finished_steady_time=1.,
                      started_steady_time=-1.,service_sent_steady_time=-.9,recovery_spin_uuid='spin-one',
                      quality_window_started_steady_time=0.,quality_window_after_ros_stamp=100.,finished_ros_now=101.),
                  dict(state='recovered',detector_state='lost',global_service_acknowledged=True,
                      stopped_from_odom=True,quality_state='healthy',fresh_post_service_pose=True,
                      duration_s=2.3,truth_error=dict(xy_m=.02,yaw_rad=.02),finished_steady_time=4.8,
                      started_steady_time=2.66,service_sent_steady_time=2.85,recovery_spin_uuid='spin-two',
                      quality_window_started_steady_time=3.72,quality_window_after_ros_stamp=103.72,finished_ros_now=104.8,
                      canceled_action_uuid='first-uuid')]
    actions = [dict(accepted=True,uuid='first-uuid',target=[-2.4,-2.,0.],sent_steady_time=1.1,
                    terminal_status=5,terminal_steady_time=2.8),
               dict(accepted=True,uuid='second-uuid',target=[-2.4,-2.,0.],sent_steady_time=4.9,
                    terminal_status=4,error_code=0,terminal_steady_time=5.5)]
    quality = [dict(steady_time=row['steady_time'],stamp=row['stamp'],ros_now=row['stamp'],
                    scan_received_steady_time=row['steady_time'],amcl_received_steady_time=row['steady_time'],
                    amcl_stamp=row['stamp'],covariance=[.001]*3,
                    estimated_pose=[.6,-2.,1.] if row['steady_time'] <= -1. else [row['x'],row['y'],row['yaw']],
                    score=dict(valid=True,match_ratio=0. if row['steady_time'] <= -1. or 2.05 <= row['steady_time'] <= 2.66 else 1.,known_fraction=1.)) for row in truth]
    changes = []
    for profile,sent,finished in [('global',-.98,-.92),('tracking',-.015,-.01),('global',2.81,2.82),('tracking',3.706,3.71)]:
        expected = AMCL_PROFILES[profile]
        changes.append(dict(profile=profile,state='confirmed',requested_parameters=dict(expected),
            parameter_service='/amcl/set_parameters_atomically',set_result=dict(successful=True),readback=dict(expected),
            readback_types={key:4 if isinstance(value,str) else 3 for key,value in expected.items()},
            sent_steady_time=sent,set_ack_steady_time=sent+.001,
            readback_steady_time=finished,sent_ros_now=100+sent,readback_ros_now=100+finished,
            odom=dict(stamp=100+sent,steady_time=sent,linear_speed=0.,angular_speed=0.)))
    for index,row in enumerate(recoveries):
        row.update(global_parameter_change_index=index*2,tracking_parameter_change_index=index*2+1,
                   observation_action_uuids=[row['recovery_spin_uuid']],quality_window_action_uuid=row['recovery_spin_uuid'],
                   service_ack_steady_time=row['service_sent_steady_time']+.005,
                   costmap_clears=[dict(service='/'+name+'/clear_entirely_'+name,
                                       sent_steady_time=row['finished_steady_time']-.02,ack_steady_time=row['finished_steady_time']-.01)
                                  for name in ('local_costmap','global_costmap')])
    return dict(target=[-2.4,-2.,0.],truth=truth,quality=quality,actions=actions,recoveries=recoveries,
                profile_changes=changes,odometry=[dict(row) for row in truth],
                recovery_actions=[dict(type='nav2_spin',accepted=True,uuid=name,terminal_status=4,error_code=0,
                                       sent_steady_time=sent,accepted_steady_time=sent+.01,terminal_steady_time=terminal,
                                       stationary_confirmed_steady_time=stop,stationary_confirmed_ros_now=100+stop,
                                       stationary_after_terminal=True,angular_distance_traveled=6.1)
                                  for name,sent,terminal,stop in (('spin-one',-.8,-.78,-.02),('spin-two',2.86,2.95,3.70))],
                faults=[dict(kind='moving_kidnap',service_success=True,steady_time=2.04,
                             before=dict(steady_time=2.,stamp=102.,ros_now=102.,linear_speed=.10,x=-.3,y=0.),
                             after=dict(x=1.8,y=2.4))],
                initial_error=dict(xy_m=3.,yaw_rad=1.),startup_pose_error_snapshot=None,
                initial_loss_quality_index=next(i for i,row in enumerate(quality) if row['steady_time'] == -1.),
                measurement_started=0.,final_steady_time=7.02,
                final_ros_now=107.02,map_to_odom_owner='AMCL',truth_decision_input=False,error=None,
                case_started_steady_time=-1.,mission_finished_steady_time=7.,case_deadline_steady_time=239.,
                cleanup_complete=True,action_cleanup_complete=True)


class ScanQualityTests(unittest.TestCase):
    def setUp(self):
        wall = np.zeros((21,21),dtype=bool)
        wall[[0,-1],:] = True
        wall[:,[0,-1]] = True
        self.wall = wall
        self.field = MapDistanceField(wall,np.ones_like(wall),.1,[-1.05,-1.05,0.])
        angles = np.arange(360)*math.pi/180
        self.ranges = 1/np.maximum(np.abs(np.cos(angles)),np.abs(np.sin(angles)))

    def score(self,pose=(0.,0.,0.)):
        return self.field.score(self.ranges,0.,math.pi/180,.10,2.,pose)

    def test_small_covariance_does_not_hide_wrong_scan_pose(self):
        true_score = self.score()
        wrong = self.score((.65,.55,.2))
        self.assertGreater(true_score['match_ratio'],.9)
        self.assertLess(wrong['match_ratio'],.5)
        gate = QualityGate(bad_duration=.5)
        for t in (0.,.1,.3,.6):
            state = gate.observe(wrong,[.0004,.0004,.001],t,t,t,t)
        self.assertTrue(state['confident'])
        self.assertEqual(state['state'],'lost')

    def test_unknown_endpoints_and_no_returns_cannot_pass(self):
        field = MapDistanceField(self.wall,~self.wall,.1,[-1.05,-1.05,0.])
        score = field.score(self.ranges,0.,math.pi/180,.1,2.,[0.,0.,0.])
        self.assertEqual(score['match_ratio'],0.)
        self.assertEqual(score['known_fraction'],0.)
        no_hits = self.field.score([math.inf]*360,0.,math.pi/180,.1,2.,[0.,0.,0.])
        self.assertFalse(no_hits['valid'])

    def test_small_dynamic_outlier_does_not_seal_the_map(self):
        ranges = self.ranges.copy()
        ranges[:30] = .2
        score = self.field.score(ranges,0.,math.pi/180,.1,2.,[0.,0.,0.])
        self.assertGreater(score['match_ratio'],.85)
        self.assertTrue(np.array_equal(self.field.occupied,self.wall))

    def test_wall_wait_never_promotes_one_old_pose(self):
        gate = QualityGate(good_duration=.3)
        score = self.score()
        for t in (0.,.1,.2,.3,.4):
            state = gate.observe(score,[.001,.001,.001],0.,0.,t,t)
        self.assertNotEqual(state['state'],'healthy')
        gate.reset(after_stamp=10.)
        for t in (10.,10.1,10.2,10.4,10.5):
            state = gate.observe(score,[.001,.001,.001],9.,t,t,t)
        self.assertNotEqual(state['state'],'healthy')

    def test_fresh_advancing_post_service_samples_can_recover(self):
        gate = QualityGate(good_duration=.3)
        gate.reset(after_stamp=2.)
        for t in (2.1,2.2,2.3,2.5):
            state = gate.observe(self.score(),[.001,.001,.001],t,t,t,t)
        self.assertEqual(state['state'],'healthy')

    def test_repeated_fresh_header_breaks_continuous_recovery_window(self):
        gate = QualityGate(good_duration=.3)
        gate.observe(self.score(),[.001]*3,1.,1.,1.,1.)
        gate.observe(self.score(),[.001]*3,1.,1.,1.2,1.2)
        state = gate.observe(self.score(),[.001]*3,1.4,1.4,1.4,1.4)
        self.assertNotEqual(state['state'],'healthy')
        gate.observe(self.score(),[.001]*3,1.6,1.6,1.6,1.6)
        state = gate.observe(self.score(),[.001]*3,1.8,1.8,1.8,1.8)
        self.assertEqual(state['state'],'healthy')

    def test_scan_before_tf_can_use_only_actually_recent_quality(self):
        sample = dict(stamp=1.,steady_time=2.,score=dict(valid=True))
        self.assertTrue(quality_sample_fresh(sample,2.10,1.10))
        self.assertFalse(quality_sample_fresh(sample,2.36,1.10))
        self.assertFalse(quality_sample_fresh(sample,2.10,1.36))
        self.assertFalse(quality_sample_fresh(dict(sample,score=dict(valid=False)),2.10,1.10))
        self.assertFalse(quality_sample_fresh(None,2.10,1.10))

    def test_ros_numpy_covariance_is_json_safe_and_only_roundoff_is_tolerated(self):
        gate = QualityGate()
        covariance = np.asarray([-2e-12,1e-3,1e-3],dtype=np.float64)
        state = gate.observe(self.score(),covariance,1.,1.,1.,1.)
        self.assertTrue(state['confident'])
        json.dumps(state,allow_nan=False)
        for t in (2.,2.2,2.4,2.6):
            state = gate.observe(self.score(),[-.001,.001,.001],t,t,t,t)
        self.assertEqual(state['state'],'lost')

    def test_unknown_cancel_never_hands_command_ownership_to_new_goal(self):
        action = dict(accepted=True,uuid='own',terminal_status=5)
        self.assertTrue(resume_allowed(action,True,'healthy',True))
        for status in (None,1,2,4):
            self.assertFalse(resume_allowed(dict(action,terminal_status=status),True,'healthy',True))
        self.assertFalse(resume_allowed(action,True,'healthy',False))
        self.assertFalse(resume_allowed(action,False,'healthy',True))
        self.assertFalse(resume_allowed(dict(action,uuid=''),True,'healthy',True))


class RecoveryAcceptanceTests(unittest.TestCase):
    def test_missing_or_frozen_raw_quality_cannot_verify_recovery(self):
        data = good_recording()
        data['quality'] = []
        self.assertFalse(analyze_recording(data)['passed'])
        data = good_recording()
        for row in data['quality']:
            row['stamp'] = 100.
        self.assertFalse(analyze_recording(data)['passed'])

    def test_second_recovery_cannot_reuse_first_spin_window(self):
        data = good_recording()
        for key in ('quality_window_started_steady_time','quality_window_after_ros_stamp',
                    'finished_steady_time','finished_ros_now'):
            data['recoveries'][1][key] = data['recoveries'][0][key]
        self.assertFalse(analyze_recording(data)['passed'])

    def test_reported_error_cannot_override_raw_estimate_and_truth(self):
        data = good_recording()
        for row in data['quality']:
            row['estimated_pose'][0] += 1.5
        result = analyze_recording(data)
        self.assertFalse(result['passed'])
        self.assertEqual(result['checks']['raw_post_service_quality_windows']['status'],'failed')

    def test_sticky_healthy_does_not_authorize_bad_latest_evidence(self):
        data = good_recording()
        gate = QualityGate(good_duration=.3)
        for t in (0.,.1,.2,.4):
            status = gate.observe(dict(valid=True,match_ratio=1.,known_fraction=1.),[.001]*3,t,t,t,t)
        status = gate.observe(dict(valid=False),[.001]*3,.5,.5,.5,.5)
        self.assertEqual(status['state'],'healthy')
        row = dict(steady_time=.5,stamp=.5,scan_received_steady_time=.5,
                   amcl_stamp=.5,amcl_received_steady_time=.5,score=dict(valid=False),**status)
        self.assertFalse(recovery_quality_ready(gate,row,.5,.5))
        max((row for row in data['quality'] if row['steady_time'] <= 4.8),key=lambda row:row['steady_time'])['score'] = dict(valid=False,reason='late_failure')
        self.assertFalse(recovered_quality_window(data,data['recoveries'][1])['passed'])

    def test_fresh_receipt_cannot_hide_old_scan_source(self):
        sample = dict(stamp=1.,steady_time=10.,scan_received_steady_time=10.,score=dict(valid=True))
        self.assertFalse(quality_sample_fresh(sample,10.,10.))
        sample.update(stamp=10.,scan_received_steady_time=9.)
        self.assertFalse(quality_sample_fresh(sample,10.,10.))

    def test_stationary_update_requires_fresh_source_and_receipt(self):
        sample = dict(stamp=10.,steady_time=20.,linear_speed=0.,angular_speed=0.)
        self.assertTrue(fresh_stationary_odom(sample,20.1,10.1))
        for change in (dict(linear_speed=.2),dict(angular_speed=.3),dict(stamp=9.),
                       dict(steady_time=19.),dict(stamp=11.),dict(linear_speed=float('nan'))):
            self.assertFalse(fresh_stationary_odom(dict(sample,**change),20.1,10.1))
        self.assertFalse(fresh_stationary_odom(None,20.,10.))

    def test_good_recording_requires_multiple_independent_boundaries(self):
        self.assertTrue(analyze_recording(good_recording())['passed'])
        self.assertFalse(analyze_recording({})['passed'])

    def test_action_success_with_confident_wrong_recovery_fails(self):
        data = good_recording()
        data['recoveries'][1]['truth_error'] = dict(xy_m=1.2,yaw_rad=.6)
        result = analyze_recording(data)
        self.assertFalse(result['passed'])
        self.assertEqual(result['checks']['two_automatic_amcl_recoveries']['status'],'failed')

    def test_goal_success_and_stop_do_not_override_physical_endpoint_error(self):
        data = good_recording()
        for sample in data['truth']:
            sample['x'] += .177
        result = analyze_recording(data)
        self.assertFalse(result['passed'])
        self.assertEqual(result['checks']['known_cancel_then_same_semantic_goal']['status'],'passed')
        self.assertEqual(result['checks']['fresh_continuous_independent_truth']['status'],'passed')
        self.assertEqual(result['checks']['final_goal_pose_and_physical_stop']['status'],'failed')

    def test_stationary_or_stale_kidnap_is_not_motion_recovery(self):
        for value in (0.,.01):
            data = good_recording()
            data['faults'][0]['before']['linear_speed'] = value
            self.assertFalse(analyze_recording(data)['passed'])
        data = good_recording()
        data['faults'][0]['before']['ros_now'] = 105.
        self.assertFalse(analyze_recording(data)['passed'])

    def test_uncertain_terminal_and_reordered_resend_fail(self):
        for value in (None,1,4):
            data = good_recording()
            data['actions'][0]['terminal_status'] = value
            self.assertFalse(analyze_recording(data)['passed'])
        data = good_recording()
        data['actions'][1]['sent_steady_time'] = 2.5
        self.assertFalse(analyze_recording(data)['passed'])

    def test_spin_acceptance_alone_is_not_sampling_or_stop(self):
        for field,value in (('angular_distance_traveled',0.),('stationary_after_terminal',False),('terminal_status',2)):
            data = good_recording()
            data['recovery_actions'][0][field] = value
            self.assertFalse(analyze_recording(data)['passed'])
        data = good_recording()
        data['actions'][1]['uuid'] = data['actions'][0]['uuid']
        self.assertFalse(analyze_recording(data)['passed'])

    def test_frozen_truth_final_motion_and_nonzero_error_code_fail(self):
        for change in ('frozen','motion','error'):
            data = good_recording()
            if change == 'frozen':
                data['final_ros_now'] = 110.
            elif change == 'motion':
                data['truth'][-1]['angular_speed'] = .3
            else:
                data['actions'][1]['error_code'] = 1
            self.assertFalse(analyze_recording(data)['passed'])

    def test_pose_score_rejects_missing_or_unpaired_samples(self):
        sample = dict(stamp=10.,steady_time=20.,estimated_pose=[1.,2.,.1])
        truth = dict(stamp=10.,steady_time=20.,x=1.,y=2.,yaw=.1)
        self.assertAlmostEqual(localization_error(sample,truth)['xy_m'],0.)
        self.assertIsNone(localization_error(sample,dict(truth,stamp=11.)))
        self.assertIsNone(localization_error(None,truth))
        self.assertIsNone(localization_error(dict(sample,estimated_pose=[1.,2.]),truth))

    def test_baseline_domains_and_static_peers_are_rejected(self):
        env = dict(ROS_DOMAIN_ID='99',FISHBOT_MUJOCO_DOMAIN_ID='99',ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
        self.assertEqual(selected_environment(env),env)
        for domain in ('0','93','96','98'):
            with self.assertRaises(RuntimeError):
                selected_environment(dict(env,ROS_DOMAIN_ID=domain,FISHBOT_MUJOCO_DOMAIN_ID=domain))
        with self.assertRaises(RuntimeError):
            selected_environment(dict(env,ROS_STATIC_PEERS='192.0.2.1'))

    def test_help_and_import_do_not_launch_ros(self):
        result = subprocess.run(['bash',str(TOOLS/'fishbot_localization_recovery.sh'),'--help'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        isolated = subprocess.run([sys.executable,'-I','-c',
            'import runpy,sys;runpy.run_path(sys.argv[1]);assert "rclpy" not in sys.modules',
            str(TOOLS/'fishbot_localization_recovery.py')],capture_output=True,text=True)
        self.assertEqual(isolated.returncode,0,isolated.stderr)

    def test_late_spin_ack_keeps_cancel_intent_and_owned_uuid(self):
        record = dict(type='nav2_spin',accepted=False)
        tracker = PendingGoal(record)
        pending = tracker.track(Future())
        now,cancellations = [0.],[]
        terminal = Future()
        terminal.set_result(SimpleNamespace(status=5,result=SimpleNamespace(error_code=0)))
        def cancel():
            cancellations.append(True)
            response = Future()
            response.set_result(SimpleNamespace(goals_canceling=[SimpleNamespace(goal_id=SimpleNamespace(uuid=bytes(range(16))))]))
            return response
        handle = SimpleNamespace(accepted=True,goal_id=SimpleNamespace(uuid=bytes(range(16))),
                                 cancel_goal_async=cancel,get_result_async=lambda:terminal)
        def spin():
            now[0] += .1
            if not pending.done():
                pending.set_result(handle)
        self.assertTrue(settle_owned_action(tracker,spin,lambda:True,lambda:now[0],2.))
        self.assertEqual(record['uuid'],bytes(range(16)).hex())
        self.assertEqual(record['terminal_status'],5)
        self.assertEqual(len(cancellations),1)

    def test_unknown_spin_ack_and_unconfirmed_stop_remain_incomplete(self):
        record = dict(type='nav2_spin',accepted=False)
        tracker = PendingGoal(record)
        tracker.track(Future())
        now = [0.]
        def spin():
            now[0] += .1
        self.assertFalse(settle_owned_action(tracker,spin,lambda:True,lambda:now[0],1.))
        self.assertTrue(tracker.cancel_requested)
        self.assertFalse(record['cleanup_confirmed'])


class NavigationTreeReuseTests(unittest.TestCase):
    default = '''<root><BehaviorTree><RecoveryNode number_of_retries="6"><PipelineSequence>
      <RateController hz="1.0"><RecoveryNode number_of_retries="1">
        <ComputePathToPose goal="{goal}" path="{path}" error_code_id="{original_planner_error}"/>
        <Sequence><WouldAPlannerRecoveryHelp error_code="{original_planner_error}"/><ClearEntireCostmap service_name="global"/></Sequence>
      </RecoveryNode></RateController>
      <RecoveryNode number_of_retries="1"><FollowPath error_code_id="{original_controller_error}"/>
        <Sequence><WouldAControllerRecoveryHelp error_code="{original_controller_error}"/><ClearEntireCostmap service_name="local"/></Sequence>
      </RecoveryNode></PipelineSequence>
      <Sequence><GoalUpdated/><Spin spin_dist="1.57" error_code_id="{original_spin_error}"/><BackUp error_code_id="{original_backup_error}"/></Sequence>
    </RecoveryNode></BehaviorTree></root>'''
    validity = '''<root><RateController><RecoveryNode><Fallback>
      <ReactiveSequence><Inverter><GlobalUpdatedGoal/></Inverter><IsPathValid path="{path}"/></ReactiveSequence>
      <ComputePathToPose error_code_id="{alternative_error}"/>
    </Fallback></RecoveryNode></RateController></root>'''

    def test_only_official_planning_condition_changes(self):
        changed = ET.fromstring(_fixture.compose_navigation_tree(self.default,self.validity))
        self.assertEqual(changed.find('.//RateController').attrib,{'hz':'1.0'})
        self.assertEqual(changed.find('.//ComputePathToPose').attrib,
                         ET.fromstring(self.default).find('.//ComputePathToPose').attrib)
        self.assertIsNotNone(changed.find('.//Fallback/ReactiveSequence/IsPathValid'))
        for tag in ('WouldAPlannerRecoveryHelp','WouldAControllerRecoveryHelp','GoalUpdated','Spin','BackUp'):
            self.assertEqual(changed.find('.//'+tag).attrib,ET.fromstring(self.default).find('.//'+tag).attrib)
        self.assertEqual([node.attrib for node in changed.findall('.//RecoveryNode')],
                         [node.attrib for node in ET.fromstring(self.default).findall('.//RecoveryNode')])

    def test_missing_or_ambiguous_official_branch_fails_closed(self):
        with self.assertRaisesRegex(ValueError,'validity condition'):
            _fixture.compose_navigation_tree(self.default,self.validity.replace('<IsPathValid path="{path}"/>',''))
        with self.assertRaisesRegex(ValueError,'ambiguous'):
            _fixture.compose_navigation_tree(self.default,self.validity.replace('</RecoveryNode>',
                '<Fallback><ComputePathToPose/></Fallback></RecoveryNode>'))

    def test_timing_wrappers_preserve_all_official_non_leaf_recoveries(self):
        trees = Path('/opt/ros/jazzy/share/nav2_bt_navigator/behavior_trees')
        original = (trees/'navigate_to_pose_w_replanning_and_recovery.xml').read_text()
        validity = (trees/'navigate_w_recovery_and_replanning_only_if_path_becomes_invalid.xml').read_text()
        timing = (TOOLS/'config/fishbot_passage_tolerant_tree.xml').read_text()
        baseline = ET.fromstring(_fixture.compose_navigation_tree(original,validity))
        changed = ET.fromstring(_fixture.compose_navigation_tree(original,validity,timing))
        scope = changed.find('BehaviorTree/Sequence')
        self.assertEqual(scope[0].get('code').count('localization_tf_waits := 0'),1)
        tree = changed.find('BehaviorTree')
        tree.remove(scope)
        tree.append(scope[1])
        for tag in ('ComputePathToPose','FollowPath'):
            wrapper = changed.find('.//RecoveryNode[@name="BoundedTiming'+tag+'"]')
            self.assertEqual(wrapper.get('number_of_retries'),'5')
            self.assertEqual(wrapper.find('.//Wait').get('wait_duration'),'1.0')
            self.assertEqual(wrapper.find('.//ScriptCondition').get('code'),'localization_tf_waits < 5')
            action = wrapper.find('Sequence/'+tag)
            owner = next(node for node in changed.iter() if wrapper in list(node))
            index = list(owner).index(wrapper)
            owner.remove(wrapper)
            owner.insert(index,action)
        def signature(node):
            return node.tag,dict(node.attrib),[signature(child) for child in node]
        self.assertEqual(signature(changed),signature(baseline))


class ParameterProfileBoundaries(unittest.TestCase):
    def test_partial_set_or_incomplete_readback_cannot_authorize_motion(self):
        row = good_recording()['profile_changes'][1]
        self.assertTrue(confirmed_profile_change(row))
        row['set_result'] = dict(successful=False,reason='parameter rejected')
        self.assertFalse(confirmed_profile_change(row))
        data = good_recording()
        data['profile_changes'][1]['readback'].pop('z_hit')
        self.assertFalse(analyze_recording(data)['passed'])

    def test_atomic_ack_does_not_override_wrong_model_or_parameter_type(self):
        row = good_recording()['profile_changes'][1]
        row['readback']['laser_model_type'] = 'likelihood_field'
        self.assertFalse(confirmed_profile_change(row))
        row = good_recording()['profile_changes'][1]
        row['readback_types']['laser_model_type'] = 3
        self.assertFalse(confirmed_profile_change(row))
        row = good_recording()['profile_changes'][1]
        row['parameter_service'] = '/amcl/set_parameters'
        self.assertFalse(confirmed_profile_change(row))

    def test_initial_pose_error_uses_first_loss_raw_pose_and_truth(self):
        data = good_recording()
        self.assertIsNone(data['startup_pose_error_snapshot'])
        self.assertAlmostEqual(initial_localization_error(data)['xy_m'],3.)
        data['initial_error'] = dict(xy_m=999.,yaw_rad=1.)
        data['quality'][data['initial_loss_quality_index']]['estimated_pose'] = [-2.4,-2.,0.]
        self.assertEqual(analyze_recording(data)['checks']['initial_pose_really_wrong']['status'],'failed')
        data = good_recording()
        data['initial_loss_quality_index'] = next(i for i,row in enumerate(data['quality']) if row['steady_time'] == 4.)
        self.assertIsNone(initial_localization_error(data))

    def test_readback_cannot_reuse_old_recovery_window(self):
        data = good_recording()
        data['profile_changes'][3].update(readback_steady_time=3.99,readback_ros_now=103.99)
        self.assertFalse(recovered_quality_window(data,data['recoveries'][1])['passed'])
        self.assertEqual(analyze_recording(data)['checks']['official_parameter_profiles_confirmed']['status'],'failed')

    def test_new_source_with_receipt_before_profile_readback_is_not_fresh(self):
        gate = QualityGate()
        gate.reset(100.,5.)
        score = dict(valid=True,match_ratio=1.,known_fraction=1.)
        early = gate.observe(score,[.001]*3,100.01,4.99,5.01,100.02)
        self.assertFalse(early['fresh'])
        for n in range(12):
            new = gate.observe(score,[.001]*3,100.03+n*.1,5.03+n*.1,5.03+n*.1,100.03+n*.1)
        self.assertEqual(new['state'],'healthy')


class ObservationEvidenceBoundaries(unittest.TestCase):
    def test_stop_flag_cannot_override_raw_motion_or_frozen_source(self):
        data = good_recording()
        action = data['recovery_actions'][1]
        self.assertTrue(confirmed_observation_stop(data,action))
        for row in data['odometry']:
            if 3. <= row['steady_time'] <= 3.70:
                row['angular_speed'] = .08
        self.assertFalse(confirmed_observation_stop(data,action))
        data = good_recording()
        for row in data['odometry']:
            if 2.95 <= row['steady_time'] <= 3.70:
                row['stamp'] = 102.95
        self.assertFalse(confirmed_observation_stop(data,data['recovery_actions'][1]))
        data = good_recording()
        data['truth'] = []
        self.assertFalse(confirmed_observation_stop(data,data['recovery_actions'][1]))

    def test_last_observation_identity_and_terminal_cannot_be_skipped(self):
        data = good_recording()
        recovery = data['recoveries'][1]
        recovery['observation_action_uuids'].append('backup-own')
        backup = dict(type='nav2_backup',uuid='backup-own',accepted=True,error_code=0,terminal_status=4,
                      requested_distance_m=.10,requested_speed_mps=.04,distance_traveled=.10,
                      sent_steady_time=3.71,accepted_steady_time=3.72,terminal_steady_time=3.8,
                      stationary_confirmed_steady_time=4.55,stationary_confirmed_ros_now=104.55)
        data['observation_actions'] = [backup]
        self.assertIsNone(observation_chain(data,recovery))
        recovery['quality_window_action_uuid'] = 'backup-own'
        self.assertIsNotNone(observation_chain(data,recovery))
        self.assertFalse(recovered_quality_window(data,recovery)['passed'])
        backup['terminal_status'] = 6
        self.assertIsNone(observation_chain(data,recovery))

    def test_nan_feedback_or_duplicate_observation_is_not_a_completed_action(self):
        data = good_recording()
        data['recovery_actions'][1]['angular_distance_traveled'] = float('nan')
        self.assertIsNone(observation_chain(data,data['recoveries'][1]))
        data = good_recording()
        data['recoveries'][1]['observation_action_uuids'] += ['spin-two']
        self.assertIsNone(observation_chain(data,data['recoveries'][1]))

    def test_complete_backup_window_requires_new_profile_and_new_healthy_samples(self):
        data = good_recording()
        recovery = data['recoveries'][1]
        backup = dict(type='nav2_backup',uuid='backup-own',accepted=True,error_code=0,terminal_status=4,
                      requested_distance_m=.10,requested_speed_mps=.04,distance_traveled=.10,
                      sent_steady_time=3.71,accepted_steady_time=3.72,terminal_steady_time=3.8,
                      stationary_confirmed_steady_time=4.55,stationary_confirmed_ros_now=104.55)
        data['observation_actions'] = [backup]
        recovery.update(observation_action_uuids=['spin-two','backup-own'],quality_window_action_uuid='backup-own',
                        quality_window_started_steady_time=4.6,quality_window_after_ros_stamp=104.6,
                        finished_steady_time=5.7,finished_ros_now=105.7)
        profile = data['profile_changes'][3]
        profile.update(sent_steady_time=4.56,sent_ros_now=104.56,set_ack_steady_time=4.565,
                       readback_steady_time=4.57,readback_ros_now=104.57,
                       odom=dict(stamp=104.56,steady_time=4.56,linear_speed=0.,angular_speed=0.))
        self.assertTrue(recovered_quality_window(data,recovery)['passed'])
        for row in data['quality']:
            if row['steady_time'] > 4.6:
                row['stamp'] = 104.6
        self.assertFalse(recovered_quality_window(data,recovery)['passed'])

    def test_forged_duration_cannot_hide_shared_recovery_or_case_deadline(self):
        data = good_recording()
        data['recoveries'][1].update(started_steady_time=-50.,duration_s=.01)
        result = analyze_recording(data)
        self.assertEqual(result['checks']['two_automatic_amcl_recoveries']['status'],'failed')
        data = good_recording()
        data['mission_finished_steady_time'] = 240.
        self.assertEqual(analyze_recording(data)['checks']['shared_case_deadline']['status'],'failed')


class ObservableLocalizationFailureTests(unittest.TestCase):
    bad = dict(valid=True,match_ratio=.05,known_fraction=1.)
    good = dict(valid=True,match_ratio=1.,known_fraction=1.)

    def test_missing_transform_time_cannot_be_borrowed_by_first_bad_pose(self):
        gate = QualityGate()
        for t in (0.,.2,.4,.6):
            gate.observe(dict(valid=False,reason='missing_scan_transform'),[.001]*3,t,t,t,t)
        first = gate.observe(self.bad,[.001]*3,.7,.7,.7,.7)
        self.assertFalse(first['localization_lost_current'])
        for t in (.8,.9,1.,1.1,1.2,1.3):
            status = gate.observe(self.bad,[.001]*3,t,t,t,t)
        self.assertTrue(status['localization_lost_current'])
        status = gate.observe(self.good,[.001]*3,1.4,1.4,1.4,1.4)
        self.assertFalse(status['localization_lost_current'])
        sample = dict(stamp=1.4,steady_time=1.4,scan_received_steady_time=1.4,score=self.good,
                      amcl_stamp=1.4,amcl_received_steady_time=1.4,**status)
        self.assertFalse(recovery_quality_ready(gate,sample,1.4,1.4))

    def test_repeated_bad_source_and_gap_cannot_prove_continuous_loss(self):
        gate = QualityGate()
        for n in range(8):
            now=n*.1
            status=gate.observe(self.bad,[.001]*3,0.,now,now,now)
        self.assertFalse(status['localization_lost_current'])
        gate = QualityGate()
        for t in (0.,.1,.2,.6,.7,.8):
            status=gate.observe(self.bad,[.001]*3,t,t,t,t)
        self.assertFalse(status['localization_lost_current'])

    def test_summary_lost_without_fresh_raw_bad_window_fails_acceptance(self):
        data=good_recording()
        self.assertTrue(confirmed_localization_loss(data,2.66))
        for row in data['quality']:
            if 2.05 <= row['steady_time'] <= 2.66:
                row['score']=dict(valid=False,reason='missing_scan_transform')
        self.assertFalse(confirmed_localization_loss(data,2.66))
        self.assertEqual(analyze_recording(data)['checks']['raw_fresh_localization_loss_windows']['status'],'failed')

    def test_queue_uses_latest_transformable_real_source_without_expiry_relaxation(self):
        calls=[]
        rows=[dict(stamp=t,steady_time=10+t-1.,message='scan') for t in (.8,.9,1.)]
        def lookup(row):
            calls.append(row['stamp'])
            if row['stamp'] == 1.:
                raise RuntimeError('extrapolation into future at 1.0')
            return ('exact-laser-'+str(row['stamp']),'exact-base-'+str(row['stamp']))
        chosen,transforms,failures=select_transformed_scan(rows,10.1,1.1,None,None,lookup)
        self.assertEqual(chosen['stamp'],.9)
        self.assertEqual(calls,[1.,.9])
        self.assertIn('extrapolation into future',failures[0]['exception'])
        self.assertEqual(transforms[0],'exact-laser-0.9')
        self.assertIsNone(select_transformed_scan(rows,10.36,1.36,None,None,lookup)[0])
        self.assertIsNone(select_transformed_scan([dict(stamp=1.1,steady_time=9.)],10.1,1.1,None,None,lookup)[0])


if __name__ == '__main__':
    unittest.main()
