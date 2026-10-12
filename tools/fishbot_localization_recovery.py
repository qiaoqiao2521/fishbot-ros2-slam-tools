#!/usr/bin/env python3
"""Bounded MuJoCo/AMCL localization recovery and independent truth acceptance."""
from __future__ import annotations

import argparse
import html
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT/'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/scripts'
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fishbot_localization_quality import MapDistanceField, QualityGate, angle_difference, fresh_stationary_odom, quality_sample_fresh, recovery_quality_ready, resume_allowed
from fishbot_passage_goal import PendingGoal
from fishbot_simulation_suite import domain_is_empty, finish_process, write_json

AMCL_PROFILES = {'global':dict(laser_model_type='likelihood_field',sigma_hit=.08,z_hit=.99,z_rand=.01),
                 'tracking':dict(laser_model_type='likelihood_field_prob',sigma_hit=.05,z_hit=.95,z_rand=.05)}


def confirmed_profile_change(change):
    """A partial parameter mutation never authorizes another motion action."""
    try:
        expected = AMCL_PROFILES[change['profile']]
        return (change['state'] == 'confirmed' and change['requested_parameters'] == expected
                and change['parameter_service'] == '/amcl/set_parameters_atomically'
                and change['set_result'].get('successful') is True
                and set(change['readback']) == set(expected)
                and all((change['readback_types'][key] == 4 and change['readback'][key] == value)
                        if isinstance(value,str) else
                        (change['readback_types'][key] == 3 and math.isfinite(change['readback'][key])
                         and abs(change['readback'][key]-value) <= 1e-12)
                        for key,value in expected.items())
                and change['sent_steady_time'] <= change['set_ack_steady_time'] <= change['readback_steady_time']
                and change['sent_ros_now'] <= change['readback_ros_now']
                and fresh_stationary_odom(change['odom'],change['sent_steady_time'],change['sent_ros_now']))
    except (KeyError,TypeError,ValueError):
        return False


def select_transformed_scan(candidates,steady_now,ros_now,last_stamp,last_received,lookup):
    """Thin four-frame queue: use exact source time, never latest-TF substitution."""
    failures = []
    for row in reversed(candidates[-4:]):
        if (not 0 <= steady_now-row['steady_time'] <= .35 or not -.05 <= ros_now-row['stamp'] <= .35
                or last_stamp is not None and (row['stamp'] < last_stamp
                    or row['stamp'] == last_stamp and row['steady_time'] == last_received)):
            continue
        try:
            transforms = lookup(row)
            return row,transforms,failures
        except Exception as error:
            failures.append(dict(stamp=row['stamp'],received_steady_time=row['steady_time'],
                                 exception_type=type(error).__name__,exception=str(error)))
    return None,None,failures


def selected_environment(environ=None):
    env = dict(os.environ if environ is None else environ)
    if (env.get('ROS_DOMAIN_ID') != '99' or env.get('FISHBOT_MUJOCO_DOMAIN_ID') != '99'
            or env.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST'
            or env.get('ROS_STATIC_PEERS', '')):
        raise RuntimeError('Localization recovery requires explicit isolated domain 99 / LOCALHOST / no static peers')
    return env


def localization_error(sample, truth):
    """Score only actual paired samples; do not extrapolate missing truth."""
    if not sample or not truth:
        return None
    try:
        if len(sample['estimated_pose']) != 3:
            return None
        values = [sample['stamp'], sample['steady_time'], *sample['estimated_pose'],
                  truth['stamp'], truth['steady_time'], truth['x'], truth['y'], truth['yaw']]
        if (not all(map(math.isfinite, values)) or abs(sample['stamp']-truth['stamp']) > .15
                or abs(sample['steady_time']-truth['steady_time']) > .25):
            return None
        return dict(xy_m=math.dist(sample['estimated_pose'][:2], [truth['x'],truth['y']]),
                    yaw_rad=abs(angle_difference(sample['estimated_pose'][2], truth['yaw'])),
                    truth_stamp=truth['stamp'], estimate_stamp=sample['stamp'],
                    sample_age_s=abs(sample['steady_time']-truth['steady_time']))
    except (KeyError, TypeError, ValueError):
        return None


def initial_localization_error(data):
    """Bind initial-pose scoring to the raw first loss, before recovery begins."""
    try:
        index = data['initial_loss_quality_index']
        if type(index) is not int or index < 0:
            return None
        sample = data['quality'][index]
        started = data['recoveries'][0]['started_steady_time']
        if (not 0 <= started-sample['steady_time'] <= .25
                or not quality_sample_fresh(sample,sample['steady_time'],sample['ros_now'])
                or not confirmed_localization_loss(data,sample['steady_time'])):
            return None
        truth = min(data['truth'],key=lambda row:abs(row['stamp']-sample['stamp']))
        return localization_error(sample,truth)
    except (KeyError,IndexError,TypeError,ValueError):
        return None


def confirmed_observation_stop(data, action):
    """Recompute an owned behavior's stop from received raw odometry."""
    try:
        end,ros_now = action['stationary_confirmed_steady_time'],action['stationary_confirmed_ros_now']
        for collection in ('odometry','truth'):
            rows = [row for row in data.get(collection,[]) if action['terminal_steady_time'] <= row['steady_time'] <= end]
            tail = []
            for row in reversed(rows):
                if not fresh_stationary_odom(row,row['steady_time'],row['ros_now']):
                    break
                tail.append(row)
            if not (len(tail) >= 3 and end-tail[0]['steady_time'] <= .25
                    and -.05 <= ros_now-tail[0]['stamp'] <= .25
                    and tail[0]['steady_time']-tail[-1]['steady_time'] >= .7-1e-9
                    and tail[0]['stamp']-tail[-1]['stamp'] >= .7-1e-9
                    and all(0 < a['steady_time']-b['steady_time'] <= .25 and 0 < a['stamp']-b['stamp'] <= .25
                            for a,b in zip(tail,tail[1:]))):
                return False
        return True
    except (KeyError,TypeError,ValueError):
        return False


def observation_chain(data, recovery):
    """At most one initial Spin and one bounded BackUp; no unknown resend."""
    try:
        uuids = recovery['observation_action_uuids']
        actions = data.get('recovery_actions',[])+data.get('observation_actions',[])
        if (len(uuids) not in (1,2) or not all(isinstance(uuid,str) and uuid for uuid in uuids)
                or len(set(uuids)) != len(uuids) or uuids[0] != recovery['recovery_spin_uuid']):
            return None
        chain,previous = [],recovery['service_sent_steady_time']
        for index,uuid in enumerate(uuids):
            matches = [row for row in actions if row.get('uuid') == uuid]
            if len(matches) != 1:
                return None
            row = matches[0]
            expected = 'nav2_spin' if index == 0 else 'nav2_backup'
            if (row.get('type') != expected or row.get('accepted') is not True
                    or row.get('terminal_status') != 4 or row.get('error_code') != 0
                    or not previous <= row['sent_steady_time'] <= row['accepted_steady_time']
                    <= row['terminal_steady_time'] <= row['stationary_confirmed_steady_time']
                    or not confirmed_observation_stop(data,row)):
                return None
            if index == 0 and not (math.isfinite(row.get('angular_distance_traveled',math.nan))
                                  and row['angular_distance_traveled'] >= 5.8):
                return None
            if index == 1 and (row.get('requested_distance_m') != .10 or row.get('requested_speed_mps') != .04
                    or not math.isfinite(row.get('distance_traveled',math.nan)) or row['distance_traveled'] < .09):
                return None
            chain.append(row)
            previous = row['stationary_confirmed_steady_time']
        if recovery.get('quality_window_action_uuid') != uuids[-1]:
            return None
        return chain
    except (KeyError,TypeError,ValueError):
        return None


def confirmed_localization_loss(data,steady_time):
    """Unavailable transforms cannot supply time for genuine pose failure."""
    gate,latest = QualityGate(),None
    try:
        for row in data.get('quality',[]):
            if not steady_time-2. <= row['steady_time'] <= steady_time:
                continue
            score = row['score']
            if (not 0 <= row['steady_time']-row['amcl_received_steady_time'] <= .75
                    or not -.05 <= row['ros_now']-row['amcl_stamp'] <= .75):
                score = dict(valid=False,reason='stale_amcl_pose')
            latest = dict(steady_time=row['steady_time'],**gate.observe(score,row['covariance'],row['stamp'],
                row['scan_received_steady_time'],row['steady_time'],row['ros_now']))
        return bool(latest and 0 <= steady_time-latest['steady_time'] <= .25
                    and latest['localization_lost_current'])
    except (KeyError,TypeError,ValueError):
        return False


def recovered_quality_window(data, recovery):
    """Recompute health from raw clocks/scores/covariance, not summary flags."""
    try:
        start,end = recovery['quality_window_started_steady_time'],recovery['finished_steady_time']
        chain = observation_chain(data,recovery)
        if chain is None:
            return dict(passed=False,reason='observation_action_or_raw_stop_unknown')
        last_action = chain[-1]
        if (not last_action['stationary_confirmed_steady_time'] <= start <= end
                or recovery['quality_window_after_ros_stamp'] < last_action['stationary_confirmed_ros_now']):
            return dict(passed=False,reason='quality_window_precedes_last_observation_stop')
        canceled = recovery.get('canceled_action_uuid')
        if canceled:
            prior = [row for row in data.get('actions',[]) if row.get('uuid') == canceled]
            if (len(prior) != 1 or prior[0].get('terminal_status') not in (5,6)
                    or prior[0]['terminal_steady_time'] > recovery['service_sent_steady_time']):
                return dict(passed=False,reason='quality_window_precedes_owned_cancel')
        profile = data['profile_changes'][recovery['tracking_parameter_change_index']]
        if (profile.get('profile') != 'tracking' or not confirmed_profile_change(profile)
                or profile['readback_steady_time'] < last_action['stationary_confirmed_steady_time']
                or start < profile['readback_steady_time']
                or recovery['quality_window_after_ros_stamp'] < profile['readback_ros_now']):
            return dict(passed=False,reason='quality_window_precedes_confirmed_tracking_profile')
        gate = QualityGate()
        gate.reset(recovery['quality_window_after_ros_stamp'],profile['readback_steady_time'])
        rows = [row for row in data.get('quality',[]) if start <= row['steady_time'] <= end]
        previous,latest = None,None
        for row in rows:
            if previous and (row['steady_time']-previous['steady_time'] > .35
                             or row['stamp']-previous['stamp'] > .35):
                gate.good_since = None
            score = row['score']
            if (not 0 <= row['steady_time']-row['amcl_received_steady_time'] <= .75
                    or not -.05 <= row['ros_now']-row['amcl_stamp'] <= .75):
                score = dict(valid=False,reason='stale_amcl_pose')
            health = gate.observe(score,row['covariance'],row['stamp'],row['scan_received_steady_time'],
                                  row['steady_time'],row['ros_now'])
            latest = dict(row,score=score,**health)
            previous = row
        passed = recovery_quality_ready(gate,latest,end,recovery['finished_ros_now'])
        paired = [row for row in data.get('truth',[]) if latest is not None
                  and 0 <= end-row['steady_time'] <= .25
                  and -.05 <= recovery['finished_ros_now']-row['stamp'] <= .25]
        truth = min(paired,key=lambda row:abs(row['stamp']-latest['stamp'])) if paired else None
        actual_error = localization_error(latest,truth)
        passed = bool(passed and actual_error and actual_error['xy_m'] <= .20 and actual_error['yaw_rad'] <= .25)
        return dict(passed=passed,samples=len(rows),observation_action_uuids=[row['uuid'] for row in chain],truth_error=actual_error,
                    healthy_duration_s=None if gate.good_since is None else end-gate.good_since,
                    final_state=gate.state)
    except (KeyError,TypeError,ValueError,IndexError):
        return dict(passed=False,reason='missing_raw_quality_window')


def settle_owned_action(tracker, spin_once, is_stopped, steady_now=time.monotonic, timeout=5.):
    """Reuse late-ack cancellation intent, then require a known terminal stop.

    Cleanup gets its own bounded wall budget even after the mission deadline.
    Missing acknowledgement/result remains unknown; it never authorizes resend.
    """
    record = tracker.evidence
    if record.get('terminal_status') in (4,5,6) and record.get('stationary_after_terminal') is True:
        record['cleanup_confirmed'] = True
        return True
    started = steady_now()
    tracker.cancel()
    record['cleanup_cancel_intent'] = True
    stopped_since = None
    while steady_now()-started < timeout:
        spin_once()
        tracker.refresh()
        handle = tracker.handle
        if handle is not None and handle.accepted:
            record.update(accepted=True,uuid=bytes(handle.goal_id.uuid).hex())
            future = tracker.get_result()
            if future is not None and future.done():
                wrapped = future.result()
                if wrapped is not None:
                    record.update(terminal_status=int(wrapped.status),error_code=int(wrapped.result.error_code))
                    record.setdefault('terminal_steady_time',steady_now())
        elif handle is not None:
            record['cleanup_confirmed'] = True
            record['cleanup_reason'] = 'goal_rejected'
            return True
        if record.get('terminal_status') in (4,5,6) and is_stopped():
            if stopped_since is None:
                stopped_since = steady_now()
            if steady_now()-stopped_since >= .7:
                record.update(cleanup_confirmed=True,stationary_after_terminal=True)
                return True
        else:
            stopped_since = None
    record.update(cleanup_confirmed=False,cleanup_reason='acknowledgement_result_or_stop_unknown')
    return False


def analyze_recording(data):
    """Acceptance cannot be inferred from AMCL confidence or action success."""
    checks = {}
    def check(name, passed, evidence):
        checks[name] = dict(status='passed' if passed is True else 'failed', evidence=evidence)
    truth = data.get('truth', [])
    recoveries, actions = data.get('recoveries', []), data.get('actions', [])
    final = truth[-1] if truth else {}
    faults = data.get('faults', [])
    initial = initial_localization_error(data)
    check('initial_pose_really_wrong', bool(initial and initial.get('xy_m', 0) >= .5), initial)
    moving_fault = next((item for item in faults if item.get('kind') == 'moving_kidnap'), {})
    before, after = moving_fault.get('before', {}), moving_fault.get('after', {})
    check('fault_applied_during_fresh_motion', bool(moving_fault.get('service_success') is True
        and before.get('linear_speed', 0) > .025 and 0 <= moving_fault.get('steady_time', -1)-before.get('steady_time', 0) <= .25
        and abs(before.get('ros_now', math.inf)-before.get('stamp', -math.inf)) <= .25
        and all(key in before and key in after for key in ('x','y'))
        and math.dist([before['x'],before['y']],[after['x'],after['y']]) >= .6), moving_fault)
    recovery_valid = (len(recoveries) == 2 and all(
        item.get('state') == 'recovered' and item.get('detector_state') == 'lost'
        and item.get('global_service_acknowledged') is True and item.get('stopped_from_odom') is True
        and item.get('quality_state') == 'healthy' and item.get('fresh_post_service_pose') is True
        and 0 <= item.get('finished_steady_time',math.inf)-item.get('started_steady_time',-math.inf) <= 45.
        and item.get('started_steady_time',math.inf) <= item.get('service_sent_steady_time',-math.inf)
        <= item.get('service_ack_steady_time',-math.inf) <= item.get('finished_steady_time',-math.inf)
        and len(item.get('costmap_clears',[])) == 2
        and {clear.get('service') for clear in item.get('costmap_clears',[])} == {
            '/local_costmap/clear_entirely_local_costmap','/global_costmap/clear_entirely_global_costmap'}
        and all(item.get('quality_window_started_steady_time',math.inf) <= clear.get('sent_steady_time',-math.inf)
                <= clear.get('ack_steady_time',-math.inf) <= item.get('finished_steady_time',-math.inf)
                for clear in item.get('costmap_clears',[]))
        and item.get('truth_error') is not None and item['truth_error']['xy_m'] <= .20
        and item['truth_error']['yaw_rad'] <= .25 for item in recoveries))
    check('two_automatic_amcl_recoveries', bool(recovery_valid), recoveries)
    loss_windows = [confirmed_localization_loss(data,item.get('started_steady_time',math.inf)) for item in recoveries]
    check('raw_fresh_localization_loss_windows',len(loss_windows) == 2 and all(loss_windows),loss_windows)
    changes = data.get('profile_changes',[])
    profile_valid = (len(recoveries) == 2 and len(changes) == 4 and [row.get('profile') for row in changes]
                     == ['global','tracking','global','tracking'] and all(map(confirmed_profile_change,changes)))
    if profile_valid:
        for index,item in enumerate(recoveries):
            global_change,tracking_change = changes[index*2:index*2+2]
            profile_valid = bool(profile_valid and item.get('global_parameter_change_index') == index*2
                and item.get('tracking_parameter_change_index') == index*2+1
                and item.get('started_steady_time',math.inf) <= global_change['sent_steady_time']
                <= global_change['readback_steady_time'] <= item.get('service_sent_steady_time',-math.inf)
                and tracking_change['readback_steady_time'] <= item.get('quality_window_started_steady_time',-math.inf))
    check('official_parameter_profiles_confirmed',profile_valid,changes)
    quality_windows = [recovered_quality_window(data,item) for item in recoveries]
    check('raw_post_service_quality_windows',len(quality_windows) == 2
          and all(item['passed'] for item in quality_windows),quality_windows)
    spins = data.get('recovery_actions', [])
    spin_valid = len(spins) == 2 and all(item.get('type') == 'nav2_spin'
        and item.get('accepted') is True and item.get('uuid')
        and item.get('terminal_status') == 4 and item.get('error_code') == 0
        and item.get('stationary_after_terminal') is True
        and item.get('angular_distance_traveled', 0) >= 5.8 for item in spins)
    check('official_spin_sampling_and_confirmed_stop', bool(spin_valid), spins)
    chains = [observation_chain(data,item) for item in recoveries]
    listed = [row['uuid'] for chain in chains if chain for row in chain]
    observed = spins+data.get('observation_actions',[])
    check('bounded_official_observation_and_raw_stop',len(chains) == 2 and all(chains)
          and len(listed) == len(observed) and len(set(listed)) == len(listed),
          dict(chains=[[row['uuid'] for row in chain] if chain else None for chain in chains],actions=observed))
    identity = (len(actions) == 2 and all(a.get('accepted') is True and a.get('uuid') for a in actions)
                and actions[0]['uuid'] != actions[1]['uuid']
                and actions[0].get('terminal_status') == 5 and actions[1].get('terminal_status') == 4
                and actions[1].get('error_code') == 0 and actions[0].get('target') == actions[1].get('target')
                and actions[0].get('terminal_steady_time', math.inf) < actions[1].get('sent_steady_time', -math.inf)
                and len(recoveries) == 2 and recoveries[1].get('canceled_action_uuid') == actions[0]['uuid']
                and recoveries[1].get('finished_steady_time', math.inf) <= actions[1].get('sent_steady_time', -math.inf))
    check('known_cancel_then_same_semantic_goal', bool(identity), actions)
    target = data.get('target', [])
    finite = bool(truth) and all(all(math.isfinite(item.get(key, math.nan)) for key in
        ('stamp','steady_time','x','y','yaw','linear_speed','angular_speed')) for item in truth)
    measured_start = data.get('measurement_started', math.inf)
    start_index = next((i for i,t in enumerate(truth) if t['steady_time'] >= measured_start), len(truth)) if finite else 0
    active = truth[max(0,start_index-1):] if finite else []
    advancing = len(active) >= 3 and all(0 < b['stamp']-a['stamp'] <= .30 and
        0 < b['steady_time']-a['steady_time'] <= .30 for a,b in zip(active,active[1:]))
    fresh = finite and 0 <= data.get('final_steady_time', math.inf)-final['steady_time'] <= .25 and \
        -.05 <= data.get('final_ros_now', math.inf)-final['stamp'] <= .25
    check('fresh_continuous_independent_truth', bool(finite and advancing and fresh),
          dict(samples=len(active), finite=finite, advancing=advancing, fresh=fresh))
    tail = []
    for item in reversed(active):
        if item['linear_speed'] >= .005 or item['angular_speed'] >= .02:
            break
        tail.append(item)
    stopped = len(tail) >= 3 and tail[0]['stamp']-tail[-1]['stamp'] >= .7
    error = None
    if finite and len(target) == 3:
        error = dict(xy_m=math.dist([final['x'],final['y']],target[:2]),
                     yaw_rad=abs(angle_difference(final['yaw'],target[2])))
    check('final_goal_pose_and_physical_stop', bool(error and error['xy_m'] <= .15
        and error['yaw_rad'] <= .30 and stopped), dict(error=error, stopped=stopped))
    check('no_synthetic_tf_or_truth_decision', data.get('map_to_odom_owner') == 'AMCL'
          and data.get('truth_decision_input') is False, dict(owner=data.get('map_to_odom_owner'),
                                                           truth_decision_input=data.get('truth_decision_input')))
    check('execution_and_cleanup', data.get('error') is None and data.get('cleanup_complete') is True
          and data.get('action_cleanup_complete') is True,
          dict(error=data.get('error'), cleanup_complete=data.get('cleanup_complete'),
               action_cleanup_complete=data.get('action_cleanup_complete')))
    check('shared_case_deadline', 0 <= data.get('mission_finished_steady_time',math.inf)
          -data.get('case_started_steady_time',-math.inf) <= 240.
          and data.get('mission_finished_steady_time',math.inf) <= data.get('case_deadline_steady_time',-math.inf),
          dict(started=data.get('case_started_steady_time'),finished=data.get('mission_finished_steady_time'),
               deadline=data.get('case_deadline_steady_time')))
    passed = all(item['status'] == 'passed' for item in checks.values())
    return dict(domain=99, status='passed' if passed else 'failed', passed=passed, checks=checks,
        metrics=dict(elapsed_s=data.get('elapsed_s'), final_error=error,
                     recovery_times_s=[r.get('duration_s') for r in recoveries],
                     action_uuids=[a.get('uuid') for a in actions]),
        trajectory=[[t['stamp'],t['x'],t['y']] for t in truth if all(k in t for k in ('stamp','x','y'))])


def save_report(report, data, directory):
    from fishbot_inspection_vision import _route_svg
    directory = Path(directory)
    route = _route_svg(dict(trajectory=report['trajectory'],stations=[dict(goal=data.get('target'))]))
    rows = ''.join('<tr><td>'+html.escape(name)+'</td><td>'+html.escape(item['status'])+'</td><td><pre>'+
                   html.escape(str(item['evidence']))+'</pre></td></tr>' for name,item in report['checks'].items())
    timeline = ''.join('<li>'+html.escape(f"{item.get('steady_time',0)-data.get('measurement_started',0):.3f}s {item.get('event')} {item.get('reason','')}")+'</li>'
                       for item in data.get('events', []))
    text = f'''<!doctype html><meta charset="utf-8"><title>AMCL localization recovery</title>
<style>body{{max-width:1200px;margin:2rem auto;font:16px system-ui;color:#172336}}table{{border-collapse:collapse;width:100%}}
td,th{{padding:.6rem;border:1px solid #ccd6e3;vertical-align:top}}pre{{white-space:pre-wrap;max-height:18rem;overflow:auto}}
svg{{max-width:100%;height:auto}}a{{color:#1565c0}}</style><h1>AMCL 定位恢复 · {report['status']}</h1>
<p>domain99 · 独立 MuJoCo 真值评分 · 错误初始位姿 → 官方全局重定位 → 行驶中搬车 → 确认取消 → 重定位 → 恢复原目标。</p>
<p>仅合成静态场景。动态物体遮挡和真实传感器噪声的恢复能力尚未由本例证明。AMCL 随机采样没有固定种子。</p>
<p><a href="recording.json">完整记录</a> · <a href="result.json">验收结果</a> · <a href="launch.log">原始启动日志</a> ·
<a href="fixture/provenance.json">模型和地图来源</a></p>{route}
<h2>独立验收</h2><table><tr><th>检查</th><th>结果</th><th>证据</th></tr>{rows}</table>
<h2>动作时间线</h2><ol>{timeline}</ol>'''
    (directory/'index.html').write_text(text, encoding='utf-8')


def runtime_node(map_path, data):
    """ROS imports remain inside execution; offline checks create no participant."""
    import rclpy
    from geometry_msgs.msg import PoseWithCovarianceStamped, TwistStamped
    from nav_msgs.msg import Path as NavPath
    from nav2_msgs.msg import CollisionMonitorState
    from nav2_msgs.srv import ClearEntireCostmap
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from std_srvs.srv import Empty
    from std_msgs.msg import Bool
    sys.path.insert(0, str(SCRIPTS))
    from verify_stack import Probe

    class LocalizationProbe(Probe):
        def __init__(self):
            super().__init__(SimpleNamespace(mode='sensors', odom='/odom',scan='/scan',
                truth='/ground_truth/free_joint_states',cmd='/cmd_vel'))
            self.field = MapDistanceField.from_yaml(map_path)
            self.gate = QualityGate()
            self.amcl = self.amcl_wall = None
            self.scan_wall = self.odom_wall = None
            self.quality_scans,self.tf_failed_keys = [],set()
            self.last_quality_stamp = None
            self.last_quality_scan_wall = None
            self.latest_quality = None
            self.nomotion_pending = None
            self.nomotion_sent = self.nomotion_last = 0.
            self.nomotion_count = 0
            self.active_handle = self.active_result = self.active_record = None
            self.action_trackers,self.owned_action_clients = [],[]
            self.global_client = self.create_client(Empty, '/reinitialize_global_localization')
            self.nomotion_client = self.create_client(Empty, '/request_nomotion_update')
            self.clear_clients = [self.create_client(ClearEntireCostmap, '/'+n+'/clear_entirely_'+n)
                                  for n in ('local_costmap','global_costmap')]
            self.kidnap_client = None
            self.create_subscription(PoseWithCovarianceStamped,'/amcl_pose',self.on_amcl,
                QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                           durability=DurabilityPolicy.TRANSIENT_LOCAL))
            self.create_subscription(TwistStamped,'/cmd_vel_nav',self.on_nav_command,10)
            self.create_subscription(TwistStamped,'/cmd_vel_smoothed',
                lambda msg:self.record_command(msg,'smoothed_commands'),10)
            self.create_subscription(TwistStamped,'/cmd_vel',
                lambda msg:self.record_command(msg,'base_commands'),10)
            self.create_subscription(CollisionMonitorState,'/collision_monitor_state',self.on_collision_monitor,10)
            self.create_subscription(Bool,'/is_rotating_to_heading',self.on_rotation_mode,10)
            self.create_subscription(NavPath,'/plan',self.on_plan,10)
            self.create_subscription(NavPath,'/received_global_plan',self.on_controller_plan,10)

        def on_nav_command(self, msg):
            self.record_command(msg,'navigation_commands')

        def record_command(self, msg, collection):
            data.setdefault(collection,[]).append(dict(
                steady_time=time.monotonic(),ros_now=self.get_clock().now().nanoseconds*1e-9,
                stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,
                linear_speed=msg.twist.linear.x,angular_speed=msg.twist.angular.z))

        def on_collision_monitor(self, msg):
            # CollisionMonitorState has no header; correlation uses receipt
            # time and cannot prove the source timestamp of the decision.
            data.setdefault('collision_monitor_observations',[]).append(dict(
                steady_time=time.monotonic(),ros_now=self.get_clock().now().nanoseconds*1e-9,
                source_stamp=None,action_type=int(msg.action_type),polygon_name=msg.polygon_name))

        def on_rotation_mode(self, msg):
            data.setdefault('rotation_modes',[]).append(dict(
                steady_time=time.monotonic(),ros_now=self.get_clock().now().nanoseconds*1e-9,
                rotating_to_heading=msg.data))

        def on_plan(self, msg):
            self.record_plan(msg,'navigation_plans')

        def on_controller_plan(self, msg):
            self.record_plan(msg,'controller_received_plans')

        def record_plan(self, msg, collection):
            end = msg.poses[-1].pose if msg.poses else None
            data.setdefault(collection,[]).append(dict(
                steady_time=time.monotonic(),ros_now=self.get_clock().now().nanoseconds*1e-9,
                stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,
                frame=msg.header.frame_id,poses=len(msg.poses),
                endpoint=None if end is None else [end.position.x,end.position.y,
                    math.atan2(2*(end.orientation.w*end.orientation.z+end.orientation.x*end.orientation.y),
                               1-2*(end.orientation.y**2+end.orientation.z**2))]))

        def on_amcl(self, msg):
            self.amcl, self.amcl_wall = msg, time.monotonic()
            data.setdefault('amcl_pose_samples',[]).append(dict(
                steady_time=self.amcl_wall,ros_now=self.get_clock().now().nanoseconds*1e-9,
                stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,
                pose=self.transform_pose(SimpleNamespace(transform=SimpleNamespace(
                    translation=msg.pose.pose.position,rotation=msg.pose.pose.orientation))),
                covariance=list(map(float,[msg.pose.covariance[index] for index in (0,7,35)]))))

        def on_scan(self, msg):
            self.scan_wall = time.monotonic()
            self.quality_scans.append(dict(message=msg,steady_time=self.scan_wall,
                stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9))
            self.quality_scans = self.quality_scans[-4:]
            data.setdefault('scan_measurements',[]).append(dict(
                steady_time=self.scan_wall,ros_now=self.get_clock().now().nanoseconds*1e-9,
                stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,frame=msg.header.frame_id,
                angle_min=msg.angle_min,angle_increment=msg.angle_increment,
                range_min=msg.range_min,range_max=msg.range_max,
                ranges=[float(value) if math.isfinite(value) else None for value in msg.ranges],
                nonfinite_ranges=[[index,str(float(value))] for index,value in enumerate(msg.ranges) if not math.isfinite(value)]))
            super().on_scan(msg)

        def on_odom(self, msg):
            self.odom_wall = time.monotonic()
            super().on_odom(msg)
            data.setdefault('odometry',[]).append(dict(self.odom_sample(),
                ros_now=self.get_clock().now().nanoseconds*1e-9))

        def on_truth(self, msg):
            super().on_truth(msg)
            if self.truth is not None and self.truth_time == msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9:
                p,q,t = self.truth.pose.pose.position,self.truth.pose.pose.orientation,self.truth.twist.twist
                data['truth'].append(dict(steady_time=time.monotonic(),stamp=self.truth_time,
                    ros_now=self.get_clock().now().nanoseconds*1e-9,x=p.x,y=p.y,z=p.z,
                    yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z)),
                    linear_speed=math.hypot(t.linear.x,t.linear.y),angular_speed=abs(t.angular.z)))

        def event(self, event, **values):
            item = dict(event=event,steady_time=time.monotonic(),ros_time=self.get_clock().now().nanoseconds*1e-9,**values)
            data['events'].append(item)
            print(event+': '+str(values),flush=True)
            return item

        def poll_nomotion(self):
            now = time.monotonic()
            if self.nomotion_pending is not None:
                if self.nomotion_pending.done():
                    self.nomotion_pending.result()
                    self.nomotion_pending = None
                elif now-self.nomotion_sent > 2:
                    self.nomotion_client.remove_pending_request(self.nomotion_pending)
                    self.nomotion_pending.cancel()
                    self.nomotion_pending = None
                    raise TimeoutError('AMCL no-motion update response timed out')
            # AMCL performs normal motion-triggered updates itself. Only force
            # scans while fresh wheel odometry actually confirms no motion.
            stopped_sample = self.odom_sample()
            ros_now = self.get_clock().now().nanoseconds*1e-9
            if (self.nomotion_pending is None and now-self.nomotion_last >= .3
                    and fresh_stationary_odom(stopped_sample, now, ros_now)
                    and self.nomotion_client.service_is_ready()):
                self.nomotion_pending = self.nomotion_client.call_async(Empty.Request())
                self.nomotion_sent = self.nomotion_last = now
                self.nomotion_count += 1
                data.setdefault('nomotion_updates',[]).append(dict(steady_time=now,ros_now=ros_now,
                    odom=stopped_sample))

        @staticmethod
        def transform_pose(transform):
            p,q = transform.transform.translation,transform.transform.rotation
            return [p.x,p.y,math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))]

        def observe_quality(self):
            if self.scan is None or self.amcl is None:
                return
            now,ros_now = time.monotonic(),self.get_clock().now().nanoseconds*1e-9
            def lookup(row):
                msg = row['message']
                return (self.buffer.lookup_transform('map',msg.header.frame_id,rclpy.time.Time.from_msg(msg.header.stamp)),
                        self.buffer.lookup_transform('map','base_footprint',rclpy.time.Time.from_msg(msg.header.stamp)))
            candidate,transforms,failures = select_transformed_scan(self.quality_scans,now,ros_now,
                self.last_quality_stamp,self.last_quality_scan_wall,lookup)
            for failure in failures:
                key = (failure['stamp'],failure['received_steady_time'])
                if key not in self.tf_failed_keys:
                    self.tf_failed_keys.add(key)
                    data.setdefault('transform_unavailable',[]).append(dict(failure,steady_time=now,ros_now=ros_now,
                        scan_source_age_s=ros_now-failure['stamp'],scan_receipt_age_s=now-failure['received_steady_time'],
                        amcl_stamp=self.amcl.header.stamp.sec+self.amcl.header.stamp.nanosec*1e-9,
                        amcl_received_steady_time=self.amcl_wall))
            self.tf_failed_keys &= {(row['stamp'],row['steady_time']) for row in self.quality_scans}
            if candidate is None:
                if self.latest_quality is not None:
                    fresh = quality_sample_fresh(self.latest_quality,now,ros_now)
                    if not fresh:
                        newest = self.quality_scans[-1]
                        score = dict(valid=False,reason='missing_scan_transform' if failures else 'stale_scan')
                        health = self.gate.observe(score,self.latest_quality['covariance'],
                                                  newest['stamp'],newest['steady_time'],now,ros_now)
                        self.latest_quality = dict(self.latest_quality,steady_time=now,
                            stamp=newest['stamp'],estimated_pose=None,map_to_laser_pose=None,
                            scan_received_steady_time=newest['steady_time'],ros_now=ros_now,score=score,**health)
                        data['quality'].append(self.latest_quality)
                return
            msg,stamp,received = candidate['message'],candidate['stamp'],candidate['steady_time']
            transform,base = transforms
            score = self.field.score(msg.ranges,msg.angle_min,msg.angle_increment,
                                    msg.range_min,msg.range_max,self.transform_pose(transform))
            amcl_stamp = self.amcl.header.stamp.sec+self.amcl.header.stamp.nanosec*1e-9
            if now-self.amcl_wall > .75 or not -.05 <= ros_now-amcl_stamp <= .75:
                score = dict(valid=False,reason='stale_amcl_pose')
            cov = self.amcl.pose.covariance
            quality = self.gate.observe(score,[cov[0],cov[7],cov[35]],stamp,received,now,ros_now)
            self.latest_quality = dict(steady_time=now,stamp=stamp,estimated_pose=self.transform_pose(base),
                                       map_to_laser_pose=self.transform_pose(transform),
                                       scan_received_steady_time=received,
                                       covariance=list(map(float,[cov[0],cov[7],cov[35]])),score=score,
                                       amcl_stamp=amcl_stamp,amcl_source_age_s=ros_now-amcl_stamp,
                                       amcl_received_steady_time=self.amcl_wall,
                                       amcl_receipt_age_s=now-self.amcl_wall,ros_now=ros_now,**quality)
            data['quality'].append(self.latest_quality)
            self.last_quality_stamp = stamp
            self.last_quality_scan_wall = received

        def fresh_truth(self):
            self.snapshot()
            latest = data['truth'][-1]
            if (time.monotonic()-latest['steady_time'] > .25
                    or abs(self.get_clock().now().nanoseconds*1e-9-latest['stamp']) > .25):
                raise RuntimeError('Independent truth is not fresh for benchmark scoring/injection')
            return dict(latest)

        def score_truth(self):
            if self.latest_quality is None:
                return None
            if time.monotonic()-self.latest_quality['steady_time'] > .25:
                return None
            return localization_error(self.latest_quality,self.fresh_truth())

        def odom_sample(self):
            if self.odom is None or self.odom_wall is None:
                return None
            stamp = self.odom.header.stamp.sec+self.odom.header.stamp.nanosec*1e-9
            t = self.odom.twist.twist
            return dict(stamp=stamp,steady_time=self.odom_wall,
                        linear_speed=math.hypot(t.linear.x,t.linear.y),angular_speed=t.angular.z)

        def odom_stopped(self):
            return fresh_stationary_odom(self.odom_sample(),time.monotonic(),
                                        self.get_clock().now().nanoseconds*1e-9)
    return LocalizationProbe()


def run_mission(node, startup, executor, data, args):
    import rclpy
    from geometry_msgs.msg import PoseStamped
    from nav2_msgs.action import BackUp, NavigateToPose, Spin
    from nav2_msgs.srv import ClearEntireCostmap
    from mujoco_ros2_control_msgs.msg import FreeJointState
    from mujoco_ros2_control_msgs.srv import SetFreeJointState
    from std_srvs.srv import Empty
    from rclpy.action import ActionClient
    from rcl_interfaces.srv import GetParameters, SetParametersAtomically

    deadline = args.case_started_steady_time+args.timeout
    recovery_deadline = None
    data['case_deadline_steady_time'] = deadline
    def budget_timeout(limit):
        until = min(deadline,recovery_deadline) if recovery_deadline is not None else deadline
        remaining = until-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Localization shared recovery/case deadline expired')
        return min(limit,remaining)
    def quality_ready():
        return recovery_quality_ready(node.gate,node.latest_quality,time.monotonic(),
                                      node.get_clock().now().nanoseconds*1e-9)
    def spin(seconds=.05):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            budget_timeout(seconds)
            if not rclpy.ok():
                raise TimeoutError('Localization benchmark total deadline expired')
            executor.spin_once(timeout_sec=.03)
            startup.update_lifecycle()
            node.poll_nomotion()
            node.observe_quality()
    def wait(future, timeout):
        until = time.monotonic()+budget_timeout(timeout)
        while not future.done() and time.monotonic() < until:
            spin()
        if not future.done():
            raise TimeoutError('ROS response unresolved; no automatic goal resend')
        budget_timeout(timeout)
        return future.result()
    def wait_stop(timeout=6, duration=.75):
        until, since, first_stamp = time.monotonic()+budget_timeout(timeout),None,None
        while time.monotonic() < until:
            spin()
            if node.odom_stopped():
                if since is None:
                    since,first_stamp = time.monotonic(),node.odom_times[-1]
                if time.monotonic()-since >= duration and node.odom_times[-1]-first_stamp >= duration-.05:
                    return True
            else:
                since = first_stamp = None
        raise RuntimeError('Fresh wheel odometry did not confirm continuous stop')
    def finish_action():
        wrapper = wait(node.active_result,8)
        record = node.active_record
        record.update(terminal_status=int(wrapper.status),error_code=int(wrapper.result.error_code),
                      terminal_steady_time=time.monotonic(),error_message=wrapper.result.error_msg)
        node.event('action_terminal',uuid=record['uuid'],status=record['terminal_status'],error_code=record['error_code'])
        return record
    def cancel_action():
        if node.active_result.done():
            return finish_action()
        node.event('cancel_sent',uuid=node.active_record['uuid'])
        budget_timeout(5)
        response = wait(node.active_handle.cancel_goal_async(),5)
        if not any(bytes(g.goal_id.uuid).hex() == node.active_record['uuid'] for g in response.goals_canceling):
            if not node.active_result.done():
                raise RuntimeError('Cancellation did not acknowledge the owned action UUID')
        return finish_action()
    def sample_observation(kind='spin'):
        action_type = Spin if kind == 'spin' else BackUp
        client = ActionClient(node,action_type,kind)
        node.owned_action_clients.append(client)
        try:
            if not client.wait_for_server(timeout_sec=budget_timeout(3)):
                raise RuntimeError('Official Nav2 observation behavior is not available')
            budget_timeout(5)
            goal = action_type.Goal()
            record = dict(type='nav2_'+kind,accepted=False,sent_steady_time=time.monotonic())
            if kind == 'spin':
                goal.target_yaw = 2*math.pi
                goal.time_allowance.sec = 20
                record.update(requested_yaw=2*math.pi,angular_distance_traveled=0.)
                data['recovery_actions'].append(record)
            else:
                now,ros_now = time.monotonic(),node.get_clock().now().nanoseconds*1e-9
                cm = startup.lifecycle.get('collision_monitor')
                scan_stamp = node.scan.header.stamp.sec+node.scan.header.stamp.nanosec*1e-9 if node.scan else -math.inf
                record.update(odom_before=node.odom_sample(),scan_stamp_before=scan_stamp,
                    scan_received_before=node.scan_wall,ros_now_before=ros_now,collision_monitor_state=cm)
                if (not fresh_stationary_odom(record['odom_before'],now,ros_now)
                        or node.scan_wall is None or not 0 <= now-node.scan_wall <= .25
                        or not -.05 <= ros_now-scan_stamp <= .25 or cm is None or cm[0] != 3
                        or not 0 <= now-cm[1] <= 2.):
                    raise RuntimeError('BackUp requires fresh stopped odometry, scan and active collision monitor')
                goal.target.x,goal.speed,goal.time_allowance.sec = .10,.04,6
                record.update(requested_distance_m=.10,requested_speed_mps=.04,distance_traveled=0.)
                data.setdefault('observation_actions',[]).append(record)
            tracker = PendingGoal(record)
            node.action_trackers.append(tracker)
            def feedback(message):
                key = 'angular_distance_traveled' if kind == 'spin' else 'distance_traveled'
                record[key] = float(getattr(message.feedback,key))
            budget_timeout(5)
            handle = wait(tracker.track(client.send_goal_async(goal,feedback_callback=feedback)),5)
            if handle is None or not handle.accepted:
                raise RuntimeError('Official Nav2 observation action was rejected')
            record.update(accepted=True,uuid=bytes(handle.goal_id.uuid).hex(),accepted_steady_time=time.monotonic())
            node.event('recovery_'+kind+'_accepted',uuid=record['uuid'])
            result = wait(tracker.get_result(),25 if kind == 'spin' else 8)
            record.update(terminal_status=int(result.status),error_code=int(result.result.error_code),
                          error_message=result.result.error_msg,terminal_steady_time=time.monotonic())
            if record['terminal_status'] != 4 or record['error_code'] != 0:
                raise RuntimeError('Recovery observation failed: '+str(record))
            record['stationary_after_terminal'] = wait_stop()
            record.update(stationary_confirmed_steady_time=time.monotonic(),
                          stationary_confirmed_ros_now=node.get_clock().now().nanoseconds*1e-9)
            node.event('recovery_'+kind+'_terminal',uuid=record['uuid'],status=record['terminal_status'],
                       traveled=record.get('angular_distance_traveled',record.get('distance_traveled')))
            return record
        except BaseException:
            if 'tracker' in locals():
                tracker.cancel()
            raise
    def set_amcl_profile(profile):
        change = dict(profile=profile,requested_parameters=dict(AMCL_PROFILES[profile]),
                      parameter_service='/amcl/set_parameters_atomically',
                      state='requested',sent_steady_time=time.monotonic(),
                      sent_ros_now=node.get_clock().now().nanoseconds*1e-9,odom=node.odom_sample())
        data.setdefault('profile_changes',[]).append(change)
        if not fresh_stationary_odom(change['odom'],change['sent_steady_time'],change['sent_ros_now']):
            change['state'] = 'failed'
            raise RuntimeError('AMCL profile change requires fresh stationary wheel odometry')
        setter = node.create_client(SetParametersAtomically,'/amcl/set_parameters_atomically')
        getter = node.create_client(GetParameters,'/amcl/get_parameters')
        try:
            if not setter.wait_for_service(timeout_sec=budget_timeout(2.)) or not getter.wait_for_service(timeout_sec=budget_timeout(2.)):
                raise RuntimeError('Official AMCL parameter services are unavailable')
            change.update(sent_steady_time=time.monotonic(),sent_ros_now=node.get_clock().now().nanoseconds*1e-9,
                          odom=node.odom_sample())
            if not fresh_stationary_odom(change['odom'],change['sent_steady_time'],change['sent_ros_now']):
                raise RuntimeError('Stationary source expired before the AMCL parameter request')
            names = list(change['requested_parameters'])
            parameters = [rclpy.parameter.Parameter(name=name,value=change['requested_parameters'][name]).to_parameter_msg()
                          for name in names]
            budget_timeout(3)
            response = wait(setter.call_async(SetParametersAtomically.Request(parameters=parameters)),3.)
            change.update(set_result=dict(successful=response.result.successful,reason=response.result.reason),
                          set_ack_steady_time=time.monotonic())
            if not response.result.successful:
                raise RuntimeError('Atomic AMCL parameter change failed; do not resume motion')
            budget_timeout(3)
            response = wait(getter.call_async(GetParameters.Request(names=names)),3.)
            change.update(readback={name:value.string_value if value.type == 4 else value.double_value
                                    for name,value in zip(names,response.values)},
                          readback_types={name:value.type for name,value in zip(names,response.values)},
                          readback_steady_time=time.monotonic(),readback_ros_now=node.get_clock().now().nanoseconds*1e-9,
                          state='confirmed')
            if len(response.values) != len(names) or not confirmed_profile_change(change):
                raise RuntimeError('AMCL parameter readback differs from the requested profile')
            node.gate.reset(change['readback_ros_now'],change['readback_steady_time'])
            node.latest_quality = None
            node.last_quality_stamp = node.last_quality_scan_wall = None
            node.event('amcl_profile_confirmed',profile=profile,readback=change['readback'])
            return change
        except BaseException as error:
            change.update(state='failed',error=f'{type(error).__name__}: {error}')
            raise
        finally:
            node.destroy_client(setter)
            node.destroy_client(getter)

    def recover(reason):
        nonlocal recovery_deadline
        started = time.monotonic()
        recovery_deadline = min(deadline,started+45.)
        try:
            recover_impl(reason,started)
        finally:
            recovery_deadline = None

    def recover_impl(reason,started):
        item = dict(reason=reason,detector_state=node.gate.state,started_steady_time=started,
                    recovery_deadline_steady_time=recovery_deadline,
                    state='recovering',global_service_acknowledged=False,stopped_from_odom=False)
        data['recoveries'].append(item)
        node.event('localization_lost',reason=reason,quality=node.latest_quality)
        prior = None
        if node.active_record is not None:
            prior = cancel_action()
            if prior['terminal_status'] not in (5,6):
                raise RuntimeError('Owned goal did not cancel/abort before recovery; do not resume')
            item['canceled_action_uuid'] = prior['uuid']
        item['stopped_from_odom'] = wait_stop()
        if prior is not None:
            prior['stationary_after_terminal'] = True
        node.event('physical_stop_confirmed_from_odom',reason=reason)
        item['global_parameter_change_index'] = len(data.get('profile_changes',[]))
        set_amcl_profile('global')
        if not node.global_client.wait_for_service(timeout_sec=budget_timeout(2)):
            raise RuntimeError('Official AMCL global relocalization service missing')
        item['service_sent_steady_time'] = time.monotonic()
        node.event('global_localization_requested',service='/reinitialize_global_localization')
        budget_timeout(5)
        wait(node.global_client.call_async(Empty.Request()),5)
        item['service_ack_steady_time'] = time.monotonic()
        item['global_service_acknowledged'] = True
        after_stamp = node.get_clock().now().nanoseconds*1e-9
        node.gate.reset(after_stamp)
        node.event('global_localization_acknowledged')
        # Stationary resampling alone may collapse onto the nearest initial
        # particle. Reuse official guarded Nav2 rotation to add scan diversity
        # and motion-model samples, with known ownership and bounded duration.
        spin_record = sample_observation()
        item['recovery_spin_uuid'] = spin_record['uuid']
        item['observation_action_uuids'] = [spin_record['uuid']]
        item['quality_window_action_uuid'] = spin_record['uuid']
        after_stamp = node.get_clock().now().nanoseconds*1e-9
        node.gate.reset(after_stamp)
        item.update(quality_window_after_ros_stamp=after_stamp,
                    quality_window_started_steady_time=time.monotonic())
        until,next_log = recovery_deadline,time.monotonic()+5
        probe_until = min(until,time.monotonic()+2.)
        while not quality_ready() and time.monotonic() < probe_until:
            spin()
        if not quality_ready():
            item['active_observation_trigger'] = dict(steady_time=time.monotonic(),quality=node.latest_quality,
                                                      reason='initial_observation_not_continuously_healthy')
            backup_record = sample_observation('backup')
            item['observation_action_uuids'].append(backup_record['uuid'])
            item['quality_window_action_uuid'] = backup_record['uuid']
            after_stamp = backup_record['stationary_confirmed_ros_now']
            node.gate.reset(after_stamp,backup_record['stationary_confirmed_steady_time'])
            node.latest_quality = None
            node.last_quality_stamp = node.last_quality_scan_wall = None
            item.update(quality_window_after_ros_stamp=after_stamp,
                        quality_window_started_steady_time=backup_record['stationary_confirmed_steady_time'])
        while not quality_ready() and time.monotonic() < until:
            spin()
            if time.monotonic() >= next_log:
                node.event('localization_waiting',quality=node.latest_quality)
                next_log = time.monotonic()+5
        if not quality_ready():
            raise RuntimeError('AMCL did not recover within the shared 45s budget')
        # The broad model recovered the global hypothesis. Reuse the already
        # validated narrower tracking profile without reinitializing particles.
        item['tracking_parameter_change_index'] = len(data.get('profile_changes',[]))
        tracking = set_amcl_profile('tracking')
        after_stamp = tracking['readback_ros_now']
        item.update(quality_window_after_ros_stamp=after_stamp,
                    quality_window_started_steady_time=tracking['readback_steady_time'])
        while not quality_ready() and time.monotonic() < until:
            spin()
        if not quality_ready():
            raise RuntimeError('Fresh post-profile quality did not authorize tracking')
        for client in node.clear_clients:
            if not client.wait_for_service(timeout_sec=budget_timeout(2)):
                raise RuntimeError('Official costmap clear service unavailable after recovery')
            budget_timeout(4)
            clear = dict(service=client.srv_name,sent_steady_time=time.monotonic())
            item.setdefault('costmap_clears',[]).append(clear)
            wait(client.call_async(ClearEntireCostmap.Request()),4)
            clear['ack_steady_time'] = time.monotonic()
        spin(.5)
        while not quality_ready() and time.monotonic() < until:
            spin()
        if not quality_ready():
            raise RuntimeError('Latest localization evidence is not healthy after costmap clearing')
        budget_timeout(1)
        item.update(quality_state=node.gate.state,fresh_post_service_pose=node.latest_quality['stamp'] > after_stamp,
                    finished_steady_time=time.monotonic(),finished_ros_now=node.get_clock().now().nanoseconds*1e-9,
                    state='recovered',truth_error=node.score_truth())
        item['duration_s'] = item['finished_steady_time']-item['started_steady_time']
        # Truth scoring is recorded after the decision; it never decides whether
        # to resume. Acceptance can therefore reject a confident wrong recovery.
        node.event('localization_recovered',quality=node.latest_quality,truth_error=item['truth_error'],duration_s=item['duration_s'])
        if prior and not resume_allowed(prior,node.odom_stopped(),node.gate.state,item['global_service_acknowledged']):
            raise RuntimeError('Resume ownership boundary is not satisfied')
    def send_goal():
        if not quality_ready():
            raise RuntimeError('Current continuous localization quality does not authorize a new goal')
        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = node.get_clock().now().to_msg()
        goal.pose.pose.position.x,goal.pose.pose.position.y = args.target[:2]
        goal.pose.pose.orientation.z,goal.pose.pose.orientation.w = math.sin(args.target[2]/2),math.cos(args.target[2]/2)
        record = dict(target=list(args.target),sent_steady_time=time.monotonic(),accepted=False)
        data['actions'].append(record)
        tracker = PendingGoal(record)
        node.action_trackers.append(tracker)
        budget_timeout(10)
        pending = tracker.track(node.client.send_goal_async(goal))
        handle = wait(pending,10)
        if handle is None or not handle.accepted:
            raise RuntimeError('Nav2 rejected recovery benchmark goal')
        record.update(accepted=True,uuid=bytes(handle.goal_id.uuid).hex(),accepted_steady_time=time.monotonic())
        node.active_handle,node.active_result,node.active_record = handle,tracker.get_result(),record
        node.event('goal_accepted',uuid=record['uuid'],target=record['target'])

    until,last_log = time.monotonic()+55,0.
    while time.monotonic() < until:
        spin()
        reason = startup.reason()
        if reason is None and node.global_client.service_is_ready() and node.client.server_is_ready() and node.latest_quality is not None:
            node.fresh_truth()
            break
        if time.monotonic()-last_log >= 5:
            print('Startup gate: '+str(reason),flush=True)
            last_log = time.monotonic()
    else:
        raise TimeoutError('Localization startup readiness timed out before any goal')
    data['startup'] = dict(lifecycle={key:list(value) for key,value in startup.lifecycle.items()},reason=startup.reason())
    parameter_client = node.create_client(GetParameters,'/controller_server/get_parameters')
    try:
        if not parameter_client.wait_for_service(timeout_sec=budget_timeout(2.)):
            raise RuntimeError('Controller parameter readback is unavailable')
        budget_timeout(3)
        expected = {'FollowPath.stateful':True,'FollowPath.desired_linear_vel':.08,
                    'FollowPath.rotate_to_heading_angular_vel':.25,'FollowPath.max_angular_accel':2.,
                    'general_goal_checker.xy_goal_tolerance':.03,'general_goal_checker.yaw_goal_tolerance':.10,
                    'general_goal_checker.stateful':True}
        response = wait(parameter_client.call_async(GetParameters.Request(names=list(expected))),3.)
        if (len(response.values) != len(expected) or any(
                (value.type != 1 or value.bool_value is not target) if isinstance(target,bool) else
                (value.type != 3 or not math.isfinite(value.double_value) or abs(value.double_value-target) > 1e-12)
                for target,value in zip(expected.values(),response.values))):
            raise RuntimeError('Controller rate/stateful/goal-tolerance readback does not match the fixture')
        data['startup']['controller_parameter_readback'] = dict(
            steady_time=time.monotonic(),ros_now=node.get_clock().now().nanoseconds*1e-9,
            service='/controller_server/get_parameters',
            values={name:value.bool_value if value.type == 1 else value.double_value
                    for name,value in zip(expected,response.values)},
            types={name:value.type for name,value in zip(expected,response.values)})
    finally:
        node.destroy_client(parameter_client)
    data['measurement_started'] = time.monotonic()
    data['startup_pose_error_snapshot'] = node.score_truth()
    until = time.monotonic()+8
    while not node.latest_quality.get('localization_lost_current') and time.monotonic() < until:
        spin()
    if not node.latest_quality.get('localization_lost_current'):
        raise RuntimeError('Wrong initial pose did not automatically trigger localization quality loss')
    data['initial_loss_quality_index'] = len(data['quality'])-1
    initial_truth = min(data['truth'],key=lambda row:abs(row['stamp']-node.latest_quality['stamp']))
    data['initial_error'] = localization_error(node.latest_quality,initial_truth)
    recover('wrong_initial_pose')
    send_goal()
    start = node.fresh_truth()
    injected = False
    while not node.active_result.done():
        spin()
        # Benchmark trigger uses fresh truth to place a controlled fault. The
        # quality gate has no access to this pose or to the injection event.
        actual = node.fresh_truth()
        if not injected and math.dist([start['x'],start['y']],[actual['x'],actual['y']]) >= .35 and actual['linear_speed'] > .025:
            for name,types in node.get_service_names_and_types():
                if 'mujoco_ros2_control_msgs/srv/SetFreeJointState' in types:
                    node.kidnap_client = node.create_client(SetFreeJointState,name)
                    break
            if node.kidnap_client is None or not node.kidnap_client.wait_for_service(timeout_sec=budget_timeout(2)):
                raise RuntimeError('MuJoCo body-state service unavailable for controlled simulation fault')
            body = FreeJointState()
            body.name = 'base_footprint'
            body.pose.pose.position.x,body.pose.pose.position.y = 1.8,2.4
            body.pose.pose.position.z = actual['z']
            body.pose.pose.orientation.z,body.pose.pose.orientation.w = math.sin(.5),math.cos(.5)
            request = SetFreeJointState.Request()
            request.free_joints = [body]
            fault = dict(kind='moving_kidnap',steady_time=time.monotonic(),before=actual,
                         requested_pose=[1.8,2.4,1.],body='base_footprint',service_name=node.kidnap_client.srv_name)
            data['faults'].append(fault)
            budget_timeout(3)
            response = wait(node.kidnap_client.call_async(request),3)
            fault.update(service_success=response.success,service_message=response.message)
            if not response.success:
                raise RuntimeError('MuJoCo rejected controlled relocation: '+response.message)
            spin(.15)
            fault['after'] = node.fresh_truth()
            node.event('moving_kidnap_applied',before=fault['before'],after=fault['after'])
            injected = True
        if injected and node.latest_quality.get('localization_lost_current'):
            recover('moving_kidnap_detected_from_scan_map')
            send_goal()
            break
    if not injected or len(data['recoveries']) != 2:
        if node.active_result.done():
            finish_action()
        raise RuntimeError('Moving fault did not produce automatic loss/recovery before the goal ended')
    while not node.active_result.done():
        spin()
        if node.latest_quality.get('localization_lost_current'):
            raise RuntimeError('Localization lost again after the bounded single recovery')
    final_action = finish_action()
    if final_action['terminal_status'] != 4 or final_action['error_code'] != 0:
        raise RuntimeError('Recovered navigation did not succeed')
    wait_stop(duration=1.)
    final_action['stationary_after_terminal'] = True
    spin(.2)
    node.fresh_truth()
    data['nomotion_update_count'] = node.nomotion_count
    budget_timeout(1)
    data['mission_finished_steady_time'] = time.monotonic()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path.home()/'.cache/fishbot/localization-recovery'/time.strftime('%Y%m%d-%H%M%S'))
    parser.add_argument('--timeout',type=float,default=240.)
    parser.add_argument('--target',type=float,nargs=3,default=[-2.4,-2.,0.])
    args = parser.parse_args()
    if not 120 <= args.timeout <= 360 or not all(map(math.isfinite,args.target)):
        parser.error('Use finite target values and timeout120..360 seconds')
    env = selected_environment()
    output = args.output.expanduser().resolve()
    if output.exists() or output.is_relative_to(ROOT):
        parser.error('--output must be a new directory outside the repository')
    output.mkdir(parents=True)
    data = dict(domain=99,target=args.target,truth=[],quality=[],events=[],actions=[],recoveries=[],faults=[],recovery_actions=[],
                map_to_odom_owner='AMCL',truth_decision_input=False,error=None,cleanup_complete=False,
                action_cleanup_complete=False)
    launched = node = startup = executor = None
    started = time.monotonic()
    args.case_started_steady_time = started
    data['case_started_steady_time'] = started
    try:
        # Existing graph check/cleanup helpers work in the explicit selected
        # domain and never contact domain0 or the running domain93 web service.
        domain_is_empty()
        with (output/'launch.log').open('w') as log:
            launched = subprocess.Popen(['ros2','launch',str(ROOT/'tools/fishbot_localization_sim.launch.py'),
                'ros_domain_id:=99','output_dir:='+str(output/'fixture')],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        until = time.monotonic()+20
        while not (output/'fixture/map.yaml').is_file() and time.monotonic() < until:
            if launched.poll() is not None:
                raise RuntimeError('Localization launch exited before generating the fixture')
            time.sleep(.1)
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from lifecycle_msgs.srv import GetState
        sys.path.insert(0,str(SCRIPTS))
        from wait_ready import Readiness
        rclpy.init()
        node = runtime_node(output/'fixture/map.yaml',data)
        startup = Readiness(True)
        for name in ('map_server','planner_server'):
            startup.lifecycle_clients[name] = startup.create_client(GetState,'/'+name+'/get_state')
        executor = SingleThreadedExecutor()
        executor.add_node(node)
        executor.add_node(startup)
        run_mission(node,startup,executor,data,args)
    except (Exception,KeyboardInterrupt) as error:
        data['error'] = f'{type(error).__name__}: {error}'
        print(data['error'],file=sys.stderr,flush=True)
    finally:
        data['mission_finished_steady_time'] = time.monotonic()
        if node is not None:
            data['nomotion_update_count'] = node.nomotion_count
            cleanup_results = []
            for tracker in node.action_trackers:
                try:
                    cleanup_results.append(settle_owned_action(tracker,
                        lambda:executor.spin_once(timeout_sec=.05),node.odom_stopped))
                except Exception as cleanup_error:
                    tracker.evidence.setdefault('cleanup_errors',[]).append(str(cleanup_error))
                    cleanup_results.append(False)
            data['action_cleanup_complete'] = all(cleanup_results)
            data['final_steady_time'] = time.monotonic()
            data['final_ros_now'] = node.get_clock().now().nanoseconds*1e-9
            # Shutdown the owned launch group even if action acceptance/result
            # is uncertain. No retry or replay occurs after a goal was sent.
        data['cleanup_complete'] = finish_process(launched)
        if executor is not None:
            executor.shutdown()
        if startup is not None:
            startup.destroy_node()
        if node is not None:
            for client in node.owned_action_clients:
                client.destroy()
            node.destroy_node()
            rclpy.try_shutdown()
        data['elapsed_s'] = time.monotonic()-started
        write_json(output/'recording.json',data)
        result = analyze_recording(data)
        write_json(output/'result.json',result)
        save_report(result,data,output)
    print(str(output/'index.html'),flush=True)
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
