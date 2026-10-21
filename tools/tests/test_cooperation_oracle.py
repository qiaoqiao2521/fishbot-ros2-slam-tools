"""Independent scoring regressions; synthetic fixtures are not ROS acceptance."""
import ast
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cooperation_oracle', TOOLS/'cooperation_oracle.py')
oracle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)
base = oracle.oracle


def physical_samples():
    """Declare an independent ideal task timeline, without production helpers."""
    samples = []
    for index in range(626):
        t = index*.02
        lifting = 1. <= t < 2.5
        moving = 5. <= t < 11.
        x = min(.6, max(0., (t-5.)*.1))
        cargo_z = .20 if lifting else .17
        forces = [.04, .04] if lifting else [0., 0.]
        raw = {'finite': True, 'q6': ([.1]*6 if t < 3.5 else [0.]*6),
               'qvel6': [0.]*6, 'car_hold': not moving,
               'cargo': {'velocity_relative_tray': [0., 0., 0.]},
               'cargo_tray_floor_contact': not lifting,
               'arm_forbidden_contact_total': 0, 'car_forbidden_contact_total': 0}
        samples.append({'stamp': t, 'wall_time': 100.+t, 'car': [x, 0., 0.],
                        'cargo': [x, 0., cargo_z], 'relative': [0., 0., .01],
                        'extents': [.009, .009, .008], 'car_yaw': 0.,
                        'car_speed': .1 if moving else 0., 'yaw_rate': 0.,
                        'forces': forces, 'raw': raw, 'independent_crosscheck': True})
    return samples


def audit():
    return {'dock_pose': [0., 0., 0.], 'home_q6': [0.]*6}


def score_transport(samples):
    attempt = {'task_id': 'task', 'started_wall_time': 100., **base.full_score(samples, audit())}
    events = [{'kind': 'full_finished', 'task_id': 'task', 'wall_time': 113.}]
    return attempt, oracle.transport_checks(samples, audit(), [attempt], events)


class PhysicalOracleTests(unittest.TestCase):
    def test_complete_synthetic_task_passes_original_and_continuous_handoff(self):
        old, strict = score_transport(physical_samples())
        self.assertTrue(old['passed'])
        self.assertTrue(strict['passed'])
        self.assertAlmostEqual(old['transport']['max_true_cargo_displacement_m'], .6)
        self.assertLess(strict['windows'][0]['continuous_handoff']['first_pass_stamp'], 5.)

    def test_false_hold_cannot_pass_handoff_despite_original_score_success(self):
        samples = physical_samples()
        for item in samples:
            item['raw']['car_hold'] = False
        old, strict = score_transport(samples)
        self.assertTrue(old['passed'])
        self.assertFalse(strict['passed'])
        self.assertTrue(strict['windows'][0]['motion_before_handoff'])

    def test_arm_leaving_home_after_valid_handoff_fails_transport(self):
        samples = physical_samples()
        samples[400]['raw']['q6'][0] = .02
        old, strict = score_transport(samples)
        self.assertTrue(old['passed'])
        self.assertFalse(strict['passed'])
        self.assertFalse(strict['windows'][0]['violation_samples_preview'][0]['arm_home_quiet'])

    def test_arm_velocity_norm_uses_original_norm_threshold(self):
        samples = physical_samples()
        samples[400]['raw']['qvel6'][:2] = [.03, .04]
        old, strict = score_transport(samples)
        self.assertTrue(old['passed'])
        self.assertFalse(strict['passed'])

    def test_rotated_corner_cannot_hide_behind_center_or_successful_motion(self):
        samples = physical_samples()
        samples[400]['relative'][0] = .047
        samples[400]['extents'][0] = .009*math.sqrt(2)
        old, strict = score_transport(samples)
        self.assertTrue(old['passed'])
        self.assertEqual(old['transport']['full_footprint_violation_samples_after_release'], 1)
        self.assertFalse(strict['passed'])

    def test_original_lift_and_final_stop_are_not_relaxed(self):
        samples = physical_samples()
        for item in samples:
            item['forces'] = [0., 0.]
        old, strict = score_transport(samples)
        self.assertFalse(old['passed'])
        self.assertFalse(strict['passed'])

    def test_duplicate_or_missing_source_samples_do_not_establish_dwell(self):
        gate = base.Gate(1.)
        for _ in range(100):
            self.assertFalse(gate.update(1., True))
        self.assertFalse(gate.update(2., True))
        self.assertFalse(gate.update(2.1, True))
        self.assertIsNone(gate.first_pass)

    def test_true_origin_motion_ignores_reported_inertial_twist(self):
        pose = {'position': {'x': 0., 'y': 0., 'z': 0.},
                'orientation': {'w': 1., 'x': 0., 'y': 0., 'z': 0.}}
        twist = {'linear': {'x': 999., 'y': 0., 'z': 0.},
                 'angular': {'x': 0., 'y': 0., 'z': 0.}}
        truth = [{'source_stamp': t, 'payload': {'pose': {'pose': pose}, 'twist': {'twist': twist}}} for t in (.98, 1.)]
        cargo_pose = copy.deepcopy(pose)
        cargo_pose['position']['x'] = .047
        cargo_pose['orientation'] = {'w': math.cos(math.pi/8), 'x': 0., 'y': 0., 'z': math.sin(math.pi/8)}
        cargo = [{'source_stamp': 1., 'payload': {'pose': cargo_pose}}]
        raw = {'finger_normal_forces_n': {'left': 0., 'right': 0.},
               'car': {'position': [0., 0., 0.]},
               'cargo': {'position': [.047, 0., 0.], 'position_relative_tray': [.047, 0., 0.]}}
        result = base.physical_sample({'payload': raw, 'source_stamp': 1., 'received_wall_time': 1.},
                                      truth, cargo, [{'source_stamp': 1.}], [0.]*3, [.009, .009, .008])
        self.assertEqual(result['car_speed'], 0.)
        self.assertEqual(result['reported_twist_speed_not_scoring_authority'], 999.)
        self.assertTrue(result['independent_crosscheck'])
        self.assertGreater(abs(result['relative'][0])+result['extents'][0], .058)


def delivery_fixture():
    samples = physical_samples()
    for item in samples:
        item['raw'].update(episode_id='episode', source={'episode_id': 'episode'})
    target = {'x': .6, 'y': 0., 'yaw': 0.}
    started = {'kind': 'full_started', 'task_id': 'task', 'episode_id': 'episode',
               'wall_time': 100., 'expected_delivery_pose': target,
               'requested_delivery_pose': copy.deepcopy(target)}
    events = [started, {'kind': 'full_finished', 'task_id': 'task', 'wall_time': 113.}]
    action = {'uuid': '03'*16, 'label': 'Nav2', 'accepted': True, 'carrying': True,
              'goal_pose': copy.deepcopy(target), 'status': 4, 'result_known': True}
    records = [
        {'topic': 'http_state', 'received_wall_time': 100.1, 'payload': {
            'episode_id': 'episode', 'task': {'id': 'task', 'delivery_pose': copy.deepcopy(target)},
            'native_actions': []}},
        {'topic': 'nav_status', 'received_wall_time': 105., 'payload': {'status_list': [
            {'goal_info': {'goal_id': {'uuid': [3]*16}}, 'status': 2}]}},
        {'topic': 'nav_status', 'received_wall_time': 111., 'payload': {'status_list': [
            {'goal_info': {'goal_id': {'uuid': [3]*16}}, 'status': 4}]}},
        {'topic': 'http_state', 'received_wall_time': 112.8, 'payload': {
            'episode_id': 'episode', 'task': {'id': 'task', 'delivery_pose': copy.deepcopy(target)},
            'native_actions': [action]}}]
    attempt = {'task_id': 'task', 'started_wall_time': 100., **base.full_score(samples, audit())}
    return records, samples, attempt, events


def egress_delivery_fixture():
    records,samples,attempt,events=delivery_fixture()
    egress={'x':.3,'y':0.,'yaw':0.}
    for row in records:
        if row['topic']=='http_state':row['payload']['task']['egress_pose']=copy.deepcopy(egress)
    action={'uuid':'02'*16,'label':'Nav2','accepted':True,'carrying':True,
            'goal_pose':copy.deepcopy(egress),'status':4,'result_known':True}
    records[-1]['payload']['native_actions'].insert(0,action)
    records[1]['received_wall_time']=109.
    middle=copy.deepcopy(records[-1]);middle['received_wall_time']=108.2
    middle['payload']['native_actions']=[copy.deepcopy(action)]
    records[:0]=[{'topic':'physics','received_wall_time':100.,'payload':{
        'episode_id':'episode','source':{'episode_id':'episode','manifest':{'egress_pose':[.3,0.,0.]}}}}]
    records[2:2]=[
        {'topic':'nav_status','received_wall_time':105.,'payload':{'status_list':[
            {'goal_info':{'goal_id':{'uuid':[2]*16}},'status':2}]}},
        {'topic':'nav_status','received_wall_time':108.,'payload':{'status_list':[
            {'goal_info':{'goal_id':{'uuid':[2]*16}},'status':4}]}},middle]
    return records,samples,attempt,events


def drive_egress_delivery_fixture():
    records,samples,attempt,events=egress_delivery_fixture()
    motion={'type':'drive_on_heading','distance_m':.7,'speed_m_s':.05000000074505806,'time_allowance_s':45.}
    records[0]['payload']['source']['manifest']['egress_motion']={**motion,'speed_m_s':.05}
    for row in records:
        if row['topic']=='http_state':
            row['payload']['task']['egress_motion']=copy.deepcopy(motion)
            for action in row['payload']['native_actions']:
                if action['uuid']=='02'*16:
                    action.update(label='DriveOnHeading',goal_pose=None,goal_motion={
                        'target':{'x':.7,'y':0.,'z':0.},'speed':motion['speed_m_s'],
                        'time_allowance':{'sec':45,'nanosec':0}})
        if row['topic']=='nav_status' and row['payload']['status_list'][0]['goal_info']['goal_id']['uuid']==[2]*16:
            row['topic']='drive_on_heading_status'
    return records,samples,attempt,events


class TaskDeliveryTests(unittest.TestCase):
    def score(self, fixture):
        records, samples, attempt, events = fixture
        return oracle.delivery_checks(records, samples, audit(), [attempt], events)

    def test_same_task_goal_uuid_and_independent_final_pose_are_all_required(self):
        result = self.score(delivery_fixture())
        self.assertTrue(result['required'])
        self.assertTrue(result['passed'])
        window = result['attempts'][0]
        self.assertEqual(window['carrying_nav_uuid'], '03'*16)
        self.assertEqual(window['position_tolerance_m'], .04)
        self.assertEqual(window['yaw_tolerance_rad'], .05)
        self.assertEqual(window['continuous_final_dwell_s'], 1.)
        self.assertFalse(window['goal_request_independently_observed'])
        self.assertFalse(window['native_goal_consumption_ack_claimed'])

    def test_declared_egress_and_delivery_require_two_ordered_native_successes(self):
        result=self.score(egress_delivery_fixture())
        self.assertTrue(result['passed'])
        window=result['attempts'][0]
        self.assertTrue(window['egress_required'])
        self.assertEqual(window['expected_egress_pose'],{'x':.3,'y':0.,'yaw':0.})
        self.assertEqual(window['carrying_nav_uuid'],'03'*16)
        self.assertEqual([leg['uuid']for leg in window['carrying_nav_route']],['02'*16,'03'*16])
        self.assertTrue(window['carrying_nav_route_order_confirmed'])
        self.assertEqual(window['position_tolerance_m'],.04)
        self.assertEqual(window['yaw_tolerance_rad'],.05)
        self.assertEqual(window['continuous_final_dwell_s'],1.)

    def test_egress_cannot_hide_wrong_missing_extra_reused_or_out_of_order_actions(self):
        for changed in ('no_declaration','wrong_goal','wrong_task_egress','wrong_uuid','aborted',
                        'only_terminal','early_delivery','reverse','reused_uuid','extra','missing_delivery'):
            with self.subTest(changed=changed):
                fixture=egress_delivery_fixture();records=fixture[0]
                if changed=='no_declaration':records.pop(0)
                if changed=='wrong_goal':
                    for row in records:
                        for action in row['payload'].get('native_actions',[]):
                            if action['uuid']=='02'*16:action['goal_pose']['x']=.4
                if changed=='wrong_task_egress':records[-1]['payload']['task']['egress_pose']['x']=.4
                for row in records:
                    if row['topic']!='nav_status':continue
                    for status in row['payload']['status_list']:
                        identifier=status['goal_info']['goal_id']['uuid']
                        if identifier==[2]*16:
                            if changed=='wrong_uuid':status['goal_info']['goal_id']['uuid']=[4]*16
                            if changed=='aborted' and status['status']==4:status['status']=6
                            if changed=='only_terminal' and status['status']==2:status['status']=4
                        if changed=='early_delivery' and identifier==[3]*16 and status['status']==2:
                            row['received_wall_time']=107.
                actions=records[-1]['payload']['native_actions']
                if changed=='reverse':actions.reverse()
                if changed=='reused_uuid':actions[-1]['uuid']='02'*16
                if changed=='extra':actions.insert(1,{**copy.deepcopy(actions[0]),'uuid':'04'*16})
                if changed=='missing_delivery':actions.pop()
                self.assertFalse(self.score(fixture)['passed'])

    def test_undeclared_legacy_route_still_allows_exactly_one_carrying_goal(self):
        fixture=delivery_fixture()
        fixture[0][-1]['payload']['native_actions'].insert(0,{
            **copy.deepcopy(fixture[0][-1]['payload']['native_actions'][0]),'uuid':'02'*16})
        self.assertFalse(self.score(fixture)['passed'])

    def test_body_egress_uses_its_own_action_uuid_and_preserves_final_nav_uuid(self):
        result=self.score(drive_egress_delivery_fixture())
        self.assertTrue(result['passed'])
        window=result['attempts'][0]
        self.assertEqual(window['carrying_nav_uuid'],'03'*16)
        first=window['carrying_nav_route'][0]
        self.assertEqual(first['label'],'DriveOnHeading')
        self.assertIsNone(first['goal_pose'])
        self.assertEqual(first['goal_motion']['target'],{'x':.7,'y':0.,'z':0.})
        self.assertEqual(window['egress_map_pose_role'],'nominal_staging_reference_not_native_body_goal')

    def test_body_motion_cannot_borrow_map_goal_wrong_topic_or_inexact_native_payload(self):
        for changed in ('nominal_map_goal','wrong_topic','wrong_target','lateral','speed_float64',
                        'duration','boolean','extra_frame','missing_motion','wrong_task_motion'):
            with self.subTest(changed=changed):
                fixture=drive_egress_delivery_fixture();records=fixture[0]
                for row in records:
                    if changed=='wrong_topic' and row['topic']=='drive_on_heading_status':row['topic']='nav_status'
                    if row['topic']!='http_state':continue
                    if changed=='wrong_task_motion':row['payload']['task']['egress_motion']['distance_m']=.8
                    for action in row['payload']['native_actions']:
                        if action['uuid']!='02'*16:continue
                        if changed=='nominal_map_goal':action['goal_pose']={'x':.3,'y':0.,'yaw':0.}
                        if changed=='wrong_target':action['goal_motion']['target']['x']=.8
                        if changed=='lateral':action['goal_motion']['target']['y']=.1
                        if changed=='speed_float64':action['goal_motion']['speed']=.05
                        if changed=='duration':action['goal_motion']['time_allowance']['sec']=46
                        if changed=='boolean':action['goal_motion']['target']['y']=False
                        if changed=='extra_frame':action['goal_motion']['frame_id']='map'
                        if changed=='missing_motion':action.pop('goal_motion')
                self.assertFalse(self.score(fixture)['passed'])

    def test_request_acceptance_and_frozen_goal_mismatch_cannot_pass(self):
        for changed in ('request', 'accepted', 'goal', 'episode', 'late_mutation', 'missing_http'):
            fixture = delivery_fixture()
            records, samples, attempt, events = fixture
            if changed == 'request': events[0]['requested_delivery_pose']['x'] = 1.
            if changed == 'accepted': records[-1]['payload']['task']['delivery_pose']['x'] = 1.
            if changed == 'goal': records[-1]['payload']['native_actions'][0]['goal_pose']['x'] = 1.
            if changed == 'episode': records[-1]['payload']['episode_id'] = 'other'
            if changed == 'late_mutation':
                mutated = copy.deepcopy(records[-1]); mutated['received_wall_time'] = 112.9
                mutated['payload']['native_actions'][0]['goal_pose']['yaw'] = .1
                records.append(mutated)
            if changed == 'missing_http': records[:] = [r for r in records if r['topic'] != 'http_state']
            with self.subTest(changed=changed): self.assertFalse(self.score(fixture)['passed'])

    def test_http_success_cannot_replace_correct_native_uuid_and_carrying_goal(self):
        for changed in ('wrong_uuid', 'aborted', 'only_terminal', 'not_carrying', 'later_nav', 'missing_goal'):
            fixture = delivery_fixture(); records = fixture[0]
            if changed == 'wrong_uuid': records[2]['payload']['status_list'][0]['goal_info']['goal_id']['uuid'] = [4]*16
            if changed == 'aborted': records[2]['payload']['status_list'][0]['status'] = 6
            if changed == 'only_terminal': records.pop(1)
            action = records[-1]['payload']['native_actions'][0]
            if changed == 'not_carrying': action['carrying'] = False
            if changed == 'later_nav':
                records[-1]['payload']['native_actions'].append({**copy.deepcopy(action), 'carrying': False, 'uuid': '04'*16})
            if changed == 'missing_goal': action.pop('goal_pose')
            with self.subTest(changed=changed): self.assertFalse(self.score(fixture)['passed'])

    def test_old_success_at_wrong_place_yaw_or_bad_final_cargo_does_not_prove_delivery(self):
        for changed in ('position', 'yaw', 'cargo', 'arm', 'hold', 'crosscheck'):
            fixture = delivery_fixture()
            for item in fixture[1]:
                if item['stamp'] < 11.: continue
                if changed == 'position': item['car'][0] = .64001
                if changed == 'yaw': item['car_yaw'] = .05001
                if changed == 'cargo': item['relative'][0] = .06
                if changed == 'arm': item['raw']['q6'][0] = .02
                if changed == 'hold': item['raw']['car_hold'] = False
                if changed == 'crosscheck': item['independent_crosscheck'] = False
            with self.subTest(changed=changed): self.assertFalse(self.score(fixture)['passed'])

    def test_earlier_arrival_dwell_does_not_allow_a_moving_or_wrong_final_sample(self):
        fixture = delivery_fixture()
        fixture[1][-1]['car'][0] = .7
        result = self.score(fixture)
        self.assertTrue(result['attempts'][0]['final_true_pose_and_cargo_stop']['passed'])
        self.assertFalse(result['passed'])

    def test_sampling_gap_and_short_dwell_cannot_be_interpolated(self):
        for changed in ('gap', 'short'):
            fixture = delivery_fixture()
            if changed == 'gap': fixture[1][:] = [item for item in fixture[1] if item['stamp'] <= 11.6 or item['stamp'] >= 11.9]
            if changed == 'short': fixture[1][:] = [item for item in fixture[1] if item['stamp'] < 11.9]
            with self.subTest(changed=changed): self.assertFalse(self.score(fixture)['passed'])

    def test_http_target_without_marker_cannot_disable_new_acceptance(self):
        fixture = delivery_fixture()
        fixture[3][0].pop('expected_delivery_pose'); fixture[3][0].pop('requested_delivery_pose')
        result = self.score(fixture)
        self.assertTrue(result['required']); self.assertFalse(result['passed'])

    def test_legacy_capture_with_no_target_keeps_original_score_boundary(self):
        records = episode_records()
        attempt, unused = score_transport(physical_samples())
        events = records[-1]['payload']['events']
        result = oracle.delivery_checks(records, physical_samples(), audit(), [attempt], events)
        self.assertFalse(result['required']); self.assertTrue(result['passed'])

    def test_destination_failure_overrides_old_success_in_final_score(self):
        records, samples, attempt, events = delivery_fixture()
        for item in samples:
            if item['stamp'] >= 11.: item['car'][0] = .7
        settings = SimpleNamespace(scope='transport', expected_outcome='success',
            markers=Path('/nonexistent/markers.json'), expected_episode='episode',
            reset_receipt=None, allow_initial_episode=True, score_only=None, output=Path('/unused'))
        value = {'passed': True, 'full_attempts': [attempt],
                 'source_integrity': {'passed': True, 'current_driver_matches_collection_end': True}}
        with patch.object(oracle, 'options', settings), \
                patch.object(oracle, 'extra_checks', return_value={'passed': True, 'windows': []}), \
                patch.object(oracle, 'transport_checks', return_value={'passed': True}), \
                patch.object(oracle, 'observation_metrics', return_value={}), \
                patch.object(oracle, 'fault_checks', return_value={'passed': True}), \
                patch.object(oracle, 'plant_guard_telemetry', return_value={}):
            result = oracle.augment_score(value, records, samples, audit(), events)
        self.assertTrue(result['original_k_oracle_passed'])
        self.assertFalse(result['task_delivery_acceptance']['passed'])
        self.assertFalse(result['passed'])
        self.assertFalse(result['live_runtime_acceptance_claimed'])


def episode_records():
    records = []
    for index in range(3):
        t = 1.+index*.02
        payload = {'stamp': t, 'sequence': index+1, 'physics_steps': 100+index,
                   'episode_id': 'episode', 'source': {'episode_id': 'episode'},
                   'episode_reset': {'count': 0}}
        payload.update({name: 0 for name in ('arm_forbidden_contact_total', 'car_forbidden_contact_total',
                                            'arm_forbidden_contact_count', 'car_forbidden_contact_count')})
        records.append({'topic': 'physics', 'source_stamp': t, 'received_wall_time': 10.1+index*.02, 'payload': payload})
        records.append({'topic': 'clock', 'source_stamp': t, 'received_wall_time': 10.1+index*.02, 'payload': {}})
    for kind in ('dock', 'nav'):
        identity = [1]*16 if kind == 'dock' else [2]*16
        for status, wall in ((2, 10.2), (4, 10.3)):
            records.append({'topic': kind+'_status', 'received_wall_time': wall,
                            'payload': {'status_list': [{'goal_info': {'goal_id': {'uuid': identity}}, 'status': status}]}})
    records.append({'topic': 'http_state', 'received_wall_time': 10.4,
                    'payload': {'task': {'id': 'task', 'status': 'succeeded'}}})
    records.append({'topic': 'marker_file', 'received_wall_time': 10.4, 'payload': {'events': [
        {'kind': 'full_started', 'task_id': 'task', 'wall_time': 10.},
        {'kind': 'full_finished', 'task_id': 'task', 'wall_time': 10.5}]}})
    return records


class IdentityAndCancellationTests(unittest.TestCase):
    def extra(self, records):
        return oracle.extra_checks(records, Path('/nonexistent/no-marker-file'), 'episode', allow_initial_episode=True)

    def test_native_identity_and_episode_success_are_required_together(self):
        self.assertTrue(self.extra(episode_records())['passed'])
        records = episode_records()
        for item in records:
            if item['topic'] == 'dock_status' and item['payload']['status_list'][0]['status'] == 4:
                item['payload']['status_list'][0]['status'] = 6
        result = self.extra(records)
        self.assertFalse(result['passed'])
        self.assertTrue(result['windows'][0]['terminal_task_success'])
        self.assertFalse(result['windows'][0]['all_native_success'])

    def test_conflicting_episode_source_and_duplicate_sequence_fail(self):
        for field in ('episode_id', 'sequence'):
            records = episode_records()
            physics = [item for item in records if item['topic'] == 'physics']
            if field == 'episode_id':
                physics[1]['payload']['source']['episode_id'] = 'other'
            else:
                physics[1]['payload']['sequence'] = physics[0]['payload']['sequence']
            with self.subTest(field=field):
                self.assertFalse(self.extra(records)['passed'])

    def test_reset_inside_same_task_is_not_an_allowed_between_episode_reset(self):
        records = episode_records()
        for item in records:
            if item['topic'] == 'physics':
                item['payload']['episode_reset'] = {'count': 1, 'stamp': 1.02}
        result = self.extra(records)
        self.assertTrue(result['reset_count_fixed'])
        self.assertTrue(result['reset_receipts_inside_task'])
        self.assertFalse(result['passed'])

    def test_missing_clock_or_full_finish_never_passes(self):
        for topic in ('clock', 'marker_file'):
            records = [item for item in episode_records() if item['topic'] != topic]
            with self.subTest(topic=topic):
                self.assertFalse(self.extra(records)['passed'])

    def test_cancellation_matches_active_native_uuid_and_true_motion(self):
        identity = [1]*16
        records = [
            {'topic': 'nav_status', 'received_wall_time': 99., 'payload': {'status_list': [
                {'goal_info': {'goal_id': {'uuid': identity}}, 'status': 2}]}},
            {'topic': 'nav_feedback', 'received_wall_time': 99.5, 'payload': {'goal_id': {'uuid': identity}}},
            {'topic': 'nav_status', 'received_wall_time': 100.2, 'payload': {'status_list': [
                {'goal_info': {'goal_id': {'uuid': identity}}, 'status': 5}]}},
            {'topic': 'http_state', 'received_wall_time': 100.2, 'payload': {'task': {'id': 'task'}}}]
        samples = [{'wall_time': 99.9, 'stamp': 1., 'car_speed': .1, 'yaw_rate': 0.,
                    'independent_crosscheck': True, 'raw': {'qvel6': [0.]*6}}]
        samples += [{'wall_time': 100.+index*.02, 'stamp': 1.+index*.02, 'car_speed': 0., 'yaw_rate': 0.,
                     'independent_crosscheck': True, 'raw': {'qvel6': [0.]*6}} for index in range(1, 51)]
        event = {'wall_time': 100., 'task_id': 'task'}
        self.assertTrue(base.cancellation_score(records, samples, event, None)['passed'])
        wrong = copy.deepcopy(records)
        wrong[2]['payload']['status_list'][0]['goal_info']['goal_id']['uuid'] = [2]*16
        self.assertFalse(base.cancellation_score(wrong, samples, event, None)['passed'])
        stopped = copy.deepcopy(samples)
        stopped[0]['car_speed'] = 0.
        self.assertFalse(base.cancellation_score(records, stopped, event, None)['passed'])

        drive = copy.deepcopy(records)
        for row in drive:
            if row['topic'].startswith('nav_'):
                row['topic'] = row['topic'].replace('nav_', 'drive_on_heading_', 1)
        result = base.cancellation_score(drive, samples, event, None)
        self.assertTrue(result['passed'])
        self.assertEqual(result['matching_native_actions'], ['DriveOnHeading'])
        # The original Drive UUID must terminate on its actual action topic.
        wrong = copy.deepcopy(drive)
        wrong[2]['topic'] = 'nav_status'
        self.assertFalse(base.cancellation_score(wrong, samples, event, None)['passed'])

    def test_drive_cancel_marker_binds_exact_accepted_uuid_and_cancel_time(self):
        records = episode_records()
        events = records[-1]['payload']['events']
        events[0]['scope'] = 'transport'
        cancel = {'kind': 'cancel_requested', 'task_id': 'task',
                  'wall_time': 10.25, 'native_uuid': '02'*16}
        events.insert(1, cancel)
        for row in records:
            if row['topic'] == 'nav_status':
                row['topic'] = 'drive_on_heading_status'
                if row['payload']['status_list'][0]['status'] == 4:
                    row['payload']['status_list'][0]['status'] = 5
            if row['topic'] == 'http_state':
                row['payload']['task']['status'] = 'canceled'
                row['payload']['native_actions'] = [
                    {'uuid': '01'*16, 'label': 'Nav2停靠', 'accepted': True,
                     'result_known': True, 'status': 4},
                    {'uuid': '02'*16, 'label': 'DriveOnHeading', 'accepted': True,
                     'result_known': True, 'status': 5, 'cancel_requested_wall_time': 10.25}]
        result = oracle.extra_checks(records, Path('/nonexistent/no-marker-file'),
            'episode', allow_initial_episode=True, expected_outcome='cancel')
        self.assertTrue(result['windows'][0]['native_expected_outcome'])
        self.assertTrue(result['windows'][0]['cancel_marker_uuid_and_actual_time_bound'])
        cancel['wall_time'] = 10.26
        wrong = oracle.extra_checks(records, Path('/nonexistent/no-marker-file'),
            'episode', allow_initial_episode=True, expected_outcome='cancel')
        self.assertFalse(wrong['windows'][0]['cancel_marker_uuid_and_actual_time_bound'])


class PortableEntryTests(unittest.TestCase):
    def test_live_recording_limits_have_finite_defaults_and_reject_unbounded_values(self):
        args = ['--expected-episode','episode','--allow-initial-episode','--domain','120',
                '--markers','markers.json','--output','/nonexistent/new-oracle-output']
        parsed = oracle.parse_options(args)
        self.assertEqual(parsed.duration, 900.)
        self.assertEqual(parsed.max_record_bytes, 1024**3)
        for flag, value in [('--duration','inf'),('--duration','0'),('--duration','901'),
                            ('--max-record-bytes','1023'),('--max-record-bytes',str(4*1024**3+1))]:
            with self.subTest(flag=flag,value=value), self.assertRaises(SystemExit), patch('sys.stderr'):
                oracle.parse_options(args+[flag,value])

    def test_incomplete_capture_overrides_even_a_successful_physical_augmentation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'observer.jsonl').write_text('')
            (root/'source-start.json').write_text(json.dumps({'collection_policy':{
                'kind':'complete_bounded','max_record_bytes':4096}}))
            good = {'capture_complete':True,'closed':True,'failed':False,'truncated':False,
                    'offered':10,'written':10,'bytes':1000,'bytes_uncertain':False,'incomplete':0}
            cases = [None, {'errors':[], 'recording':{**good,'truncated':True}},
                     {'errors':[], 'recording':{**good,'failed':True}},
                     {'errors':[], 'recording':{**good,'closed':False}},
                     {'errors':[], 'recording':{**good,'written':9,'incomplete':1}},
                     {'errors':[], 'recording':{**good,'bytes':4097}},
                     {'errors':['HTTP observer worker did not stop'], 'recording':good},
                     {'errors':[], 'recording':{k:v for k,v in good.items() if k!='bytes'}},
                     {'errors':[], 'recording':good}]
            for index, ended in enumerate(cases):
                with self.subTest(index=index):
                    if ended is not None:(root/'collection-end.json').write_text(json.dumps(ended))
                    with patch('builtins.print'):
                        result = oracle.original_score(root,root/'markers.json',augment=lambda *unused:{'passed':True,
                            'live_runtime_acceptance_claimed':True,'task_completion_passed':True,
                            'expected_safety_passed':True,'full_transport_acceptance_claimed':True})
                    self.assertEqual(result['passed'],index==len(cases)-1)
                    if not result['passed']:
                        for key in ('live_runtime_acceptance_claimed','task_completion_passed','expected_safety_passed','full_transport_acceptance_claimed'):
                            self.assertFalse(result[key])
                    self.assertTrue(result['recording_integrity']['required'])

    def test_partial_io_tail_produces_a_failure_report_without_parsing_or_claiming_physics(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'observer.jsonl').write_text('{partial')
            (root/'source-start.json').write_text(json.dumps({'collection_policy':{
                'kind':'complete_bounded','max_record_bytes':4096}}))
            (root/'collection-end.json').write_text(json.dumps({'errors':[], 'recording':{
                'capture_complete':False,'closed':True,'failed':True,'truncated':True,'error':'write_failed'}}))
            with patch('builtins.print'):
                result = oracle.original_score(root,root/'markers.json')
            self.assertFalse(result['passed'])
            self.assertFalse(result['physical_evaluation_performed'])
            self.assertEqual(len(list(root.glob('score-*.json'))),1)

    def test_modules_do_not_import_control_helpers_or_ros_for_offline_scoring(self):
        for module_path in (TOOLS/'cooperation_oracle.py', TOOLS/'cooperation_oracle_base.py'):
            tree = ast.parse(module_path.read_text())
            top_imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
            names = [node.module if isinstance(node, ast.ImportFrom) else name.name
                     for node in top_imports for name in (node.names if isinstance(node, ast.Import) else [None])]
            self.assertFalse(any(name and name.startswith(('cooperation_core', 'cooperation_sim', 'cooperation_bridge', 'rclpy')) for name in names))
            self.assertNotIn('/home/muqiao', module_path.read_text())

    def test_replay_cannot_write_inside_original_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = ['--expected-episode', 'episode', '--allow-initial-episode', '--score-only', str(root),
                    '--markers', str(root/'markers.json'), '--output', str(root/'new')]
            with self.assertRaises(SystemExit), patch('sys.stderr'):
                oracle.parse_options(args)
            self.assertFalse((root/'new').exists())

    def test_existing_output_is_never_reused_or_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = ['--expected-episode', 'episode', '--allow-initial-episode', '--domain', '120',
                    '--markers', str(root/'markers.json'), '--output', str(root)]
            with self.assertRaises(SystemExit), patch('sys.stderr'):
                oracle.parse_options(args)

    def test_live_observer_refuses_protected_or_unspecified_domains(self):
        for domain in (None, '0', '107', '114', '-1'):
            args = ['--expected-episode', 'episode', '--allow-initial-episode',
                    '--markers', 'markers.json', '--output', '/nonexistent/new-oracle-output']
            if domain is not None:
                args += ['--domain', domain]
            with self.subTest(domain=domain), self.assertRaises(SystemExit), patch('sys.stderr'):
                oracle.parse_options(args)

    def test_failed_replay_preserves_original_and_writes_private_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            historical = root/'historical'
            historical.mkdir()
            (historical/'observer.jsonl').write_text('{malformed}\n')
            original = (historical/'observer.jsonl').read_bytes()
            output = root/'replay'
            args = ['--expected-episode', 'episode', '--allow-initial-episode', '--score-only', str(historical),
                    '--markers', str(root/'markers.json'), '--output', str(output)]
            with patch('builtins.print'):
                code = oracle.main(args)
            self.assertEqual(code, 1)
            self.assertEqual((historical/'observer.jsonl').read_bytes(), original)
            files = list(output.glob('score-error-*.json'))
            self.assertEqual(len(files), 1)
            result = json.loads(files[0].read_text())
            self.assertFalse(result['passed'])
            self.assertEqual(result['evidence_mode'], 'offline_replay')
            self.assertFalse(result['live_runtime_acceptance_claimed'])
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            self.assertEqual(output.stat().st_mode & 0o777, 0o700)


def docking_fixture():
    samples=[];records=[];identity=[1]*16
    for index in range(101):
        t=index*.02;wall=100.+t
        raw={'finite':True,'qvel6':[0.]*6,'q6':[0.]*6,'car_hold':True,
             'cargo':{'velocity_relative_tray':[0.]*3},'cargo_tray_floor_contact':True,
             'episode_id':'episode','source':{'episode_id':'episode'},'episode_reset':{'count':0},
             'stamp':t,'sequence':index+1,'physics_steps':index+1,
             'docking_guard':{'enabled':t<.4,'tripped':False}}
        for key in ('arm_forbidden_contact_total','car_forbidden_contact_total','arm_forbidden_contact_count','car_forbidden_contact_count'):raw[key]=0
        samples.append({'stamp':t,'wall_time':wall,'car':[0.,0.,0.],'car_yaw':0.,'car_speed':0.,
            'yaw_rate':0.,'forces':[0.,0.],'cargo':[0.,0.,.17],'relative':[0.,0.,.01],
            'extents':[.009,.009,.008],'raw':raw,'independent_crosscheck':True})
        records.append({'topic':'physics','source_stamp':t,'received_wall_time':wall,'payload':copy.deepcopy(raw)})
        records.append({'topic':'clock','source_stamp':t,'received_wall_time':wall,'payload':{}})
    for status,wall in ((2,100.1),(4,101.)):
        records.append({'topic':'dock_status','received_wall_time':wall,'payload':{'status_list':[
            {'goal_info':{'goal_id':{'uuid':identity}},'status':status}]}})
    records.append({'topic':'http_state','received_wall_time':101.1,'payload':{'task':{'id':'task','status':'succeeded','scope':'dock'},
        'native_actions':[{'uuid':'01'*16,'label':'Nav2停靠','accepted':True,'status':4,'result_known':True}]}})
    events=[{'kind':'dock_started','task_id':'task','wall_time':100.},
            {'kind':'dock_finished','task_id':'task','wall_time':101.2},
            {'kind':'cleanup_checked','task_id':'task','wall_time':102.}]
    records.append({'topic':'marker_file','received_wall_time':102.,'payload':{'events':events}})
    return records,samples,events


class DockScopeTests(unittest.TestCase):
    def test_docking_passes_without_falsely_claiming_original_full_transport(self):
        records,samples,events=docking_fixture()
        self.assertFalse(base.full_score(samples,audit())['passed'])
        result=oracle.dock_checks(records,samples,audit(),events)
        self.assertTrue(result['passed']);self.assertTrue(result['attempts'][0]['task_completion_passed'])
        self.assertFalse(result['attempts'][0]['full_transport_claimed'])
        self.assertTrue(oracle.extra_checks(records,Path('/nonexistent'), 'episode',scope='dock',allow_initial_episode=True)['passed'])
        self.assertFalse(oracle.extra_checks(records,Path('/nonexistent'), 'episode',allow_initial_episode=True)['passed'])

    def test_physical_position_and_yaw_thresholds_remain_original(self):
        for error_kind in ('position','yaw','contact','crosscheck'):
            records,samples,events=docking_fixture()
            for item in samples:
                if error_kind=='position':item['car'][0]=.04001
                if error_kind=='yaw':item['car_yaw']=.05001
                if error_kind=='contact':item['raw']['car_forbidden_contact_total']=1
                if error_kind=='crosscheck':item['independent_crosscheck']=False
            with self.subTest(kind=error_kind):self.assertFalse(oracle.dock_checks(records,samples,audit(),events)['passed'])

    def test_missing_cleanup_marker_stale_proof_and_guard_never_enabled_fail(self):
        for condition in ('missing','stale','guard'):
            records,samples,events=docking_fixture()
            if condition=='missing':events.pop()
            if condition=='stale':events[-1]['wall_time']=103.
            if condition=='guard':
                for sample in samples:sample['raw']['docking_guard']['enabled']=False
            with self.subTest(condition=condition):self.assertFalse(oracle.dock_checks(records,samples,audit(),events)['passed'])

    def test_http_success_cannot_replace_same_uuid_native_success(self):
        for condition in ('wrong_uuid','unknown','extra_goal'):
            records,samples,events=docking_fixture()
            terminal=next(r for r in records if r['topic']=='dock_status' and r['payload']['status_list'][0]['status']==4)
            if condition=='wrong_uuid':terminal['payload']['status_list'][0]['goal_info']['goal_id']['uuid']=[2]*16
            if condition=='unknown':terminal['payload']['status_list'][0]['status']=2
            if condition=='extra_goal':
                terminal['payload']['status_list'].append({'goal_info':{'goal_id':{'uuid':[2]*16}},'status':2})
            with self.subTest(condition=condition):
                self.assertFalse(oracle.extra_checks(records,Path('/nonexistent'),'episode',scope='dock',allow_initial_episode=True)['passed'])

    def test_cleanup_requires_current_source_age_and_continuous_quiet(self):
        for condition in ('future_clock','moved_after_quiet','gap'):
            records,samples,events=docking_fixture()
            if condition=='future_clock':
                next(r for r in reversed(records) if r['topic']=='clock')['source_stamp']=2.3
            if condition=='moved_after_quiet':samples[-1]['car_speed']=.02
            if condition=='gap':samples[:]=samples[::10]
            with self.subTest(condition=condition):self.assertFalse(oracle.cleanup_checks(records,samples,events,'task')['passed'])

    def test_safe_cancel_does_not_count_as_task_completion(self):
        records,samples,events=docking_fixture()
        for item in samples:
            if item['wall_time']<100.5:item['car_speed']=.1
        identity=[1]*16
        records.append({'topic':'dock_feedback','received_wall_time':100.2,'payload':{'goal_id':{'uuid':identity}}})
        terminal=next(r for r in records if r['topic']=='dock_status' and r['payload']['status_list'][0]['status']==4)
        terminal['payload']['status_list'][0]['status']=5
        next(r for r in records if r['topic']=='http_state')['payload']['task']['status']='canceled'
        next(r for r in records if r['topic']=='http_state')['payload']['native_actions'][0].update(status=5,cancel_requested_wall_time=100.5)
        events.append({'kind':'cancel_requested','task_id':'task','wall_time':100.5,'native_uuid':'01'*16})
        result=oracle.dock_checks(records,samples,audit(),events,expected_outcome='safe_cancel')
        self.assertTrue(result['passed']);self.assertTrue(result['attempts'][0]['expected_safety_passed'])
        self.assertFalse(result['attempts'][0]['task_completion_passed'])

    def test_admission_is_explicitly_not_native_consumption_ack(self):
        records,samples,_=docking_fixture()
        metrics=oracle.observation_metrics(records,samples,{'native_dock_pose':[0.,0.,0.]})
        self.assertFalse(metrics['admission_decisions_are_native_consumption_ack'])

    def test_accepted_handle_and_cancel_marker_cannot_borrow_other_uuid_or_post_time(self):
        for condition in ('handle','cancel_uuid','post_time','absent_handle'):
            records,_,events=docking_fixture()
            state=next(r for r in records if r['topic']=='http_state')['payload']
            if condition=='handle':state['native_actions'][0]['uuid']='02'*16
            if condition=='absent_handle':state.pop('native_actions')
            if condition in ('cancel_uuid','post_time'):
                state['native_actions'][0]['cancel_requested_wall_time']=100.5
                events.append({'kind':'cancel_requested','task_id':'task','wall_time':100.4 if condition=='post_time' else 100.5,
                               'native_uuid':'02'*16 if condition=='cancel_uuid' else '01'*16})
            with self.subTest(condition=condition):
                result=oracle.extra_checks(records,Path('/nonexistent'),'episode',scope='dock',allow_initial_episode=True)
                self.assertFalse(result['passed'])


def camera_fixture():
    header={'stamp':{'sec':1,'nanosec':0},'frame_id':'cooperation_camera_optical_frame'}
    expected={'scene_sha256':'a'*64,'manifest_sha256':'b'*64,'episode_id':'episode'}
    config={'width':640,'height':480,'k':[1.]*9,'d':[0.]*5}
    fields={**expected,'sequence':'1','capture_steady_ns':'123'}
    camera={'header':copy.deepcopy(header),'status':[{'hardware_id':'cooperation_camera',
        'values':[{'key':k,'value':v} for k,v in fields.items()]}]}
    metrics={**expected,'reason':'detected','capture_age_s':.04,'source_age_s':.02,'inference_duration_s':.01}
    return [
        {'topic':'physics','payload':{'source':{**expected,'manifest':{'station_camera':config}}}},
        {'topic':'camera_image','source_stamp':1.,'payload':{'header':copy.deepcopy(header),'width':640,'height':480,'encoding':'rgb8'}},
        {'topic':'camera_info','source_stamp':1.,'payload':{'header':copy.deepcopy(header),**copy.deepcopy(config)}},
        {'topic':'camera_metadata','source_stamp':1.,'payload':camera},
        {'topic':'vision_quality','source_stamp':1.,'payload':{'status':[{'message':'detected','values':[
            {'key':k,'value':json.dumps(v)} for k,v in metrics.items()]}]}}]


class CameraEvidenceTests(unittest.TestCase):
    def test_calibrated_rgb_identity_quality_is_separate_from_native_ack(self):
        result=oracle.camera_checks(camera_fixture(),'episode')
        self.assertTrue(result['passed']);self.assertEqual(result['exact_calibrated_image_metadata_pairs'],1)
        self.assertAlmostEqual(result['inference_duration_p95_s'],.01)
        self.assertFalse(result['native_consumption_ack_claimed']);self.assertFalse(result['quality_is_probability'])

    def test_wrong_episode_calibration_missing_quality_and_pose_leakage_fail(self):
        for condition in ('episode','calibration','quality','pose_leakage'):
            records=camera_fixture()
            if condition=='episode':records[3]['payload']['status'][0]['values'][2]['value']='other'
            if condition=='calibration':records[2]['payload']['k'][0]=2.
            if condition=='quality':records.pop()
            if condition=='pose_leakage':records[3]['payload']['status'][0]['values'].append({'key':'car_pose','value':'[0,0,0]'})
            with self.subTest(condition=condition):self.assertFalse(oracle.camera_checks(records,'episode')['passed'])


class FaultEvidenceTests(unittest.TestCase):
    def fixture(self):
        records,_,events=docking_fixture()
        config={'schema':1,'kind':'replay_identity','duration_wall_s':0.,'delay_wall_s':0.,'delay_source_s':0.}
        status={'config':config,'native_goal_uuid':'01'*16,'trigger_wall_time':100.15,'started_wall_time':100.3,
                'replay_packets':6,'counts':{'triggers':1,'input':12,'output':12,'dropped':0,'mutated':6}}
        for record in records:
            if record['topic']=='physics':
                record['payload']['source']['manifest']={'observation_faults':config,'station_perception':{'mode':'perturbed'}}
                record['payload']['observation_faults']=copy.deepcopy(status)
        reasons={'sequence and source time must advance together':2,'observation episode mismatch':1,
                 'observation frame_id mismatch':1,'observation station_id mismatch':1,'observation manifest_sha256 mismatch':1}
        next(r for r in records if r['topic']=='http_state')['payload']['station_perception']={'rejection_reason_counts':reasons}
        windows=oracle.extra_checks(records,Path('/nonexistent'),'episode',scope='dock',allow_initial_episode=True)['windows']
        return records,events,windows

    def test_actual_trigger_replay_packets_and_rejections_required_together(self):
        records,events,windows=self.fixture()
        self.assertTrue(oracle.fault_checks(records,events,windows)['passed'])
        for condition in ('zero_packets','wrong_uuid','missing_reason','before_task','no_trigger'):
            changed=copy.deepcopy(records)
            last=next(r for r in reversed(changed) if r['topic']=='physics')['payload']['observation_faults']
            if condition=='zero_packets':last['replay_packets']=0;last['counts']['mutated']=0
            if condition=='wrong_uuid':last['native_goal_uuid']='02'*16
            if condition=='before_task':last['started_wall_time']=99.
            if condition=='no_trigger':last['counts']['triggers']=0
            if condition=='missing_reason':next(r for r in changed if r['topic']=='http_state')['payload']['station_perception']['rejection_reason_counts'].pop('observation frame_id mismatch')
            with self.subTest(condition=condition):self.assertFalse(oracle.fault_checks(changed,events,windows)['passed'])

    def rgb_fixture(self, root):
        """Independent image bytes and producer artifacts are synthetic evidence."""
        from PIL import Image
        records,events,windows=self.fixture()
        camera=camera_fixture();expected={'scene_sha256':'a'*64,'manifest_sha256':'b'*64,'episode_id':'episode'}
        config={'schema':1,'kind':'short_occlusion','duration_wall_s':.1,'delay_wall_s':0.,'delay_source_s':0.}
        for record in records:
            if record['topic']!='physics':continue
            record['payload']['source'].update(expected)
            record['payload']['source']['manifest']={'observation_faults':config,'station_perception':{'mode':'vision'},
                'station_camera':camera[0]['payload']['source']['manifest']['station_camera']}
            record['payload']['observation_faults'].update(config=config,episode_id='episode',started_monotonic=40.,
                started_source_stamp=1.,counts={'triggers':1,'input':0,'output':0,'dropped':0,'mutated':0})
        rgb=root/'runtime'/'vision'/'rgb';rgb.mkdir(parents=True)
        path=rgb/'vision-episode-1.png';image=Image.new('RGB',(640,480),(40,40,40));image.save(path)
        camera[1]['payload'].update(step=1920,data_size=640*480*3,data_sha256=hashlib.sha256(image.tobytes()).hexdigest())
        camera[3]['payload']['status'][0]['values'][4]['value']='40050000000'
        camera[-1]['payload']['header']=copy.deepcopy(camera[1]['payload']['header'])
        camera[-1]['payload']['header']['frame_id']='base_footprint'
        fields={**expected,'sequence':1,'stamp':1.,'detected':False,'reason':'not_detected'}
        camera[-1]['payload']['status'][0]['values']=[{'key':key,'value':json.dumps(value)} for key,value in fields.items()]
        records.extend(camera[1:])
        frame={**fields,'occluded':True,'capture_steady_ns':40_050_000_000}
        detector={**fields,'relative':None,'covariance':None,'rgb_file':str(path)}
        artifacts={'renderer':[frame],'detector':[detector],'directory':str(rgb.parent),
                   'missing':[],'read_errors':{},'readback':'complete'}
        return records,events,windows,artifacts

    def test_rgb_occlusion_requires_same_rendered_frame_and_independent_image_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            records,events,windows,artifacts=self.rgb_fixture(Path(temp))
            result=oracle.fault_checks(records,events,windows,artifacts=artifacts)
            self.assertTrue(result['passed'])
            proof=result['rejection_coverage']['same_frame_rgb_evidence']
            self.assertEqual(proof['same_frame_not_detected_count'],1)
            self.assertEqual(proof['independent_rgb_hash_verified_count'],1)
            self.assertFalse(proof['complete_rgb_pairing_claimed'])

    def test_unrelated_miss_stale_frame_other_identity_or_changed_pixels_cannot_prove_occlusion(self):
        for condition in ('missing_artifacts','not_occluded','sequence','stamp','episode','manifest','outside_window','capture_metadata',
                          'stale_miss','quality_stale','quality_header','different_pixels','missing_png'):
            with self.subTest(condition=condition),tempfile.TemporaryDirectory() as temp:
                records,events,windows,artifacts=self.rgb_fixture(Path(temp))
                if condition=='missing_artifacts':artifacts=None
                elif condition=='not_occluded':artifacts['renderer'][0]['occluded']=False
                elif condition=='sequence':artifacts['renderer'][0]['sequence']=2
                elif condition=='stamp':artifacts['renderer'][0]['stamp']+=1e-9
                elif condition=='episode':artifacts['renderer'][0]['episode_id']='old'
                elif condition=='manifest':artifacts['renderer'][0]['manifest_sha256']='c'*64
                elif condition=='outside_window':artifacts['renderer'][0]['capture_steady_ns']=40_101_000_000
                elif condition=='capture_metadata':next(r for r in records if r['topic']=='camera_metadata')['payload']['status'][0]['values'][4]['value']='40040000000'
                elif condition=='stale_miss':artifacts['detector'][0]['reason']='camera_capture_stale'
                elif condition=='quality_stale':
                    for pair in next(r for r in records if r['topic']=='vision_quality')['payload']['status'][0]['values']:
                        if pair['key']=='reason':pair['value']=json.dumps('camera_capture_stale')
                elif condition=='quality_header':next(r for r in records if r['topic']=='vision_quality')['payload']['header']['stamp']['nanosec']=1
                elif condition=='different_pixels':next(r for r in records if r['topic']=='camera_image')['payload']['data_sha256']='0'*64
                elif condition=='missing_png':Path(artifacts['detector'][0]['rgb_file']).unlink()
                self.assertFalse(oracle.fault_checks(records,events,windows,artifacts=artifacts)['passed'])

    def test_unsampled_image_hash_is_unknown_without_claiming_complete_pairing(self):
        with tempfile.TemporaryDirectory() as temp:
            records,events,windows,artifacts=self.rgb_fixture(Path(temp))
            records=[r for r in records if r['topic']!='camera_image']
            result=oracle.fault_checks(records,events,windows,artifacts=artifacts)
            self.assertTrue(result['passed'])
            proof=result['rejection_coverage']['same_frame_rgb_evidence']
            self.assertEqual(proof['independent_rgb_hash_verified_count'],0)
            self.assertEqual(proof['independent_rgb_hash_unknown_count'],1)

    def test_fixed_layout_artifact_reader_preserves_missing_and_partial_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);observer=root/'observer';observer.mkdir()
            self.assertEqual(oracle.camera_artifacts(observer)['readback'],'missing')
            _,_,_,artifacts=self.rgb_fixture(root)
            camera=Path(artifacts['directory'])/'camera.jsonl';vision=camera.with_name('vision.jsonl')
            camera.write_text(json.dumps(artifacts['renderer'][0])+'\n{partial')
            vision.write_text(json.dumps(artifacts['detector'][0])+'\n')
            result=oracle.camera_artifacts(observer)
            self.assertEqual(result['readback'],'partial');self.assertEqual(result['read_errors'],{'camera.jsonl':1})
            self.assertEqual(len(result['renderer']),1)
            self.assertEqual(result['sha256']['camera.jsonl'],hashlib.sha256(camera.read_bytes()).hexdigest())

    def test_camera_sampling_gaps_are_counts_not_complete_coverage(self):
        records=camera_fixture();extra=copy.deepcopy(records[3]);extra['source_stamp']=2.
        extra['payload']['header']['stamp']['sec']=2
        extra['payload']['status'][0]['values'][3]['value']='2';records.append(extra)
        result=oracle.camera_checks(records,'episode')
        self.assertTrue(result['passed']);self.assertEqual(result['unmatched_image_info_metadata_count'],1)
        self.assertEqual(result['expected_camera_sample_coverage'],'unknown')
        self.assertFalse(result['complete_rgb_pairing_claimed'])


class PlantGuardTelemetryTests(unittest.TestCase):
    def records(self,states):
        return [{'topic':'physics','source_stamp':stamp,'received_wall_time':100.+stamp,
                 'payload':{'docking_guard':{'enabled':enabled,'tripped':tripped,
                     'method':'ideal plant velocity guard','hardware_validated':False,'margin_m':.01}}}
                for stamp,enabled,tripped in states]
    def events(self):
        return [{'kind':'dock_started','task_id':'task','wall_time':100.},
                {'kind':'dock_finished','task_id':'task','wall_time':101.}]

    def test_enabled_guard_with_zero_intervention_is_reported_separately(self):
        result=oracle.plant_guard_telemetry(self.records([(0.,False,False),(.02,True,False),(.04,True,False),(.06,False,False)]),self.events())
        window=result['windows'][0]
        self.assertEqual(window['enabled_sample_count'],2);self.assertEqual(window['tripped_sample_count'],0)
        self.assertEqual(window['observed_enable_transitions'],1);self.assertEqual(window['observed_disable_transitions'],1)
        self.assertFalse(window['plant_assistance_observed']);self.assertFalse(window['pure_vision_precision_claimed'])
        self.assertEqual(window['hardware_validated_values'],[False]);self.assertNotIn('passed',result)

    def test_single_intervention_and_source_duration_do_not_bridge_a_gap(self):
        result=oracle.plant_guard_telemetry(self.records([(0.,True,False),(.02,True,True),(.04,True,True),(.30,True,True),(.32,False,False)]),self.events())
        window=result['windows'][0]
        self.assertEqual(window['observed_trip_transitions'],1);self.assertEqual(window['tripped_sample_count'],3)
        self.assertAlmostEqual(window['tripped_observed_contiguous_source_duration_s'],.02)
        self.assertEqual(window['source_gap_or_nonadvance_count'],1);self.assertTrue(window['plant_assistance_observed'])

    def test_carry_in_trip_is_not_counted_as_a_new_event_and_outside_window_is_excluded(self):
        records=self.records([(-.02,True,False),(0.,True,True),(.02,True,True),(1.02,False,False)])
        window=oracle.plant_guard_telemetry(records,self.events())['windows'][0]
        self.assertEqual(window['physics_sample_count'],2);self.assertTrue(window['initial_sample_tripped'])
        self.assertEqual(window['observed_trip_transitions'],0)
        self.assertAlmostEqual(window['tripped_observed_contiguous_source_duration_s'],.02)


if __name__ == '__main__':
    unittest.main()
