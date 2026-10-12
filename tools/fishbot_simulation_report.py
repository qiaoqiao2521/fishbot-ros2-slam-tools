#!/usr/bin/env python3
"""Assess recorded simulation evidence without starting ROS or moving a robot."""

from html import escape
import importlib.util
import json
import math
from pathlib import Path
from urllib.parse import quote


POSITION_TOLERANCE = .15
YAW_TOLERANCE = .30
LINEAR_STOP = .005
ANGULAR_STOP = .02
TRUTH_GAP = .30
TRUTH_AGE = .25


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _stopped(sample):
    return sample['linear_speed'] < LINEAR_STOP and sample['angular_speed'] < ANGULAR_STOP


def _duration(samples):
    if len(samples) < 2:
        return 0.
    return min(samples[-1]['steady_time'] - samples[0]['steady_time'],
               samples[-1]['stamp'] - samples[0]['stamp'])


def _stop_runs(samples):
    runs, current = [], []
    for sample in samples:
        if _stopped(sample):
            current.append(sample)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _ordered_visits(samples, route):
    visits, following = [], 0
    for sample in samples:
        if following >= len(route):
            break
        target = route[following]
        distance = math.hypot(sample['x'] - target[0], sample['y'] - target[1])
        if distance <= POSITION_TOLERANCE:
            visits.append({'index': following, 'steady_time': sample['steady_time'],
                           'stamp': sample['stamp'], 'distance_m': distance})
            following += 1
    return visits


def _json_safe(value):
    """Keep incomplete/nonfinite diagnostics renderable without inventing values."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def analyze_case(case, recording, goal, guard_events, relay_events, motion=None):
    """Require action evidence and independent truth; missing evidence cannot pass."""
    recording, goal = recording or {}, goal or {}
    guard_events, relay_events = guard_events or [], relay_events or []
    checks, metrics = {}, {}

    def check(name, condition, evidence=None):
        checks[name] = {'status': 'unknown' if condition is None else ('passed' if condition else 'failed'),
                        'evidence': _json_safe(evidence)}

    events = [dict(event) for event in recording.get('events', []) if isinstance(event, dict)]
    events += [dict(event, source='guard_trigger') for event in guard_events if isinstance(event, dict)]
    events += [dict(event, source='relay') for event in relay_events if isinstance(event, dict)]
    events.sort(key=lambda event: event.get('steady_time') if _finite(event.get('steady_time')) else math.inf)
    limitations = ['Pure simulation evidence; no hardware acceptance.',
                   'CollisionMonitorState has no source stamp or scan sequence. '
                   'Timeline and polygon associations use receive time, not an exact triggering scan.']
    kind = case.get('kind')
    returncode = case.get('command_returncode')
    expected_returncode = 1 if kind == 'cancel' else 0
    check('command_exit', returncode == expected_returncode
          if isinstance(returncode, int) and not isinstance(returncode, bool) else None,
          {'actual': returncode, 'expected': expected_returncode})
    raw = recording.get('truth', [])
    fields = ('steady_time', 'stamp', 'x', 'y', 'yaw', 'linear_speed', 'angular_speed')
    valid = isinstance(raw, list) and bool(raw) and all(
        isinstance(sample, dict) and all(_finite(sample.get(field)) for field in fields)
        and sample['linear_speed'] >= 0 and sample['angular_speed'] >= 0 for sample in raw)
    samples = raw if valid else []

    if kind == 'motion':
        # The existing probe independently checks moving physics and fresh truth.
        # Its report is deliberately not promoted to a navigation/guard result.
        motion = motion or {}
        check('motion_probe', motion.get('passed') is True if motion else None, motion.get('error'))
        drift = motion.get('stale_command_drift')
        check('old_command_rejected', drift <= .015 if _finite(drift) else None, drift)
        timeout = motion.get('stopped_after_seconds')
        check('command_timeout_brake', 0 <= timeout <= 1. if _finite(timeout) else None, timeout)
        linear, angular = motion.get('final_planar_speed'), motion.get('final_angular_speed')
        check('final_stopped', 0 <= linear < LINEAR_STOP and 0 <= angular < ANGULAR_STOP
              if _finite(linear) and _finite(angular) else None,
              {'linear_speed': linear, 'angular_speed': angular})
        post_drift = motion.get('post_timeout_drift')
        check('post_timeout_drift', 0 <= post_drift <= .015 if _finite(post_drift) else None, post_drift)
        displacement = motion.get('displacement')
        check('movement_observed', displacement >= .15 if _finite(displacement) else None, displacement)
        metrics.update(stale_command_drift_m=drift, stopped_after_s=timeout,
                       motion_distance_m=displacement, post_timeout_drift_m=post_drift)
        limitations.append('Motion case checks the existing diff-drive probe only; '
                           'it does not establish guard or navigation recovery.')
    else:
        check('truth_present_and_finite', valid if raw else None, {'sample_count': len(raw) if isinstance(raw, list) else 0})
        check('isolated_domain', recording.get('domain') == case.get('domain', 96)
              if recording.get('domain') is not None else None, recording.get('domain'))
        if samples:
            steady_gaps = [b['steady_time'] - a['steady_time'] for a, b in zip(samples, samples[1:])]
            stamp_gaps = [b['stamp'] - a['stamp'] for a, b in zip(samples, samples[1:])]
            advancing = bool(steady_gaps) and all(value > 0 for value in steady_gaps + stamp_gaps)
            check('truth_clock_advances', advancing, {'sample_count': len(samples)})
            sent = goal.get('goal_sent_steady_time')
            first_active = next((index for index, sample in enumerate(samples)
                                 if _finite(sent) and sample['steady_time'] >= sent), len(samples))
            # Keep the sample immediately before dispatch. A dropout straddling
            # dispatch belongs to the active window, even if its first edge is idle.
            window = samples[max(0, first_active - 1):] if _finite(sent) else samples
            active_steady_gaps = [b['steady_time'] - a['steady_time'] for a, b in zip(window, window[1:])]
            active_stamp_gaps = [b['stamp'] - a['stamp'] for a, b in zip(window, window[1:])]
            active_gaps = active_steady_gaps + active_stamp_gaps
            check('truth_window_continuous', advancing and bool(active_gaps)
                  and max(active_gaps) <= TRUTH_GAP + 1e-9,
                  {'window': 'one sample before Goal dispatch through final truth',
                   'max_steady_gap_s': max(active_steady_gaps, default=None),
                   'max_source_gap_s': max(active_stamp_gaps, default=None),
                   'whole_recording_max_steady_gap_s': max(steady_gaps, default=None),
                   'whole_recording_max_source_gap_s': max(stamp_gaps, default=None)})
            final_steady, final_ros = recording.get('final_steady_time'), recording.get('final_ros_now')
            receive_age = final_steady - samples[-1]['steady_time'] if _finite(final_steady) else None
            source_age = final_ros - samples[-1]['stamp'] if _finite(final_ros) else None
            check('truth_final_fresh', 0 <= receive_age <= TRUTH_AGE + 1e-9 and -.05 <= source_age <= TRUTH_AGE + 1e-9
                  if _finite(receive_age) and _finite(source_age) else None,
                  {'receive_age_s': receive_age, 'source_age_s': source_age})
            stopped_runs = _stop_runs(samples)
            tail = stopped_runs[-1] if stopped_runs and stopped_runs[-1][-1] is samples[-1] else []
            check('final_stopped', _duration(tail) >= .7 - 1e-9,
                  {'stationary_duration_s': _duration(tail), 'linear_speed': samples[-1]['linear_speed'],
                   'angular_speed': samples[-1]['angular_speed']})
            terminal = goal.get('terminal_steady_time')
            terminal_basis = 'action_terminal'
            if kind == 'cancel' and not _finite(terminal):
                terminal = samples[-1]['steady_time']
                terminal_basis = 'last_truth_after_cancel'
            check('goal_window_recorded', samples[0]['steady_time'] <= sent + TRUTH_GAP
                  and samples[-1]['steady_time'] >= terminal
                  if _finite(sent) and _finite(terminal) else None,
                  {'sent': sent, 'terminal': terminal, 'first_truth': samples[0]['steady_time'],
                   'last_truth': samples[-1]['steady_time'], 'terminal_basis': terminal_basis})
            active = [sample for sample in samples if not _finite(sent) or sample['steady_time'] >= sent]
            moving = [sample for sample in active if not _stopped(sample)]
            check('movement_observed', bool(moving), {'moving_samples': len(moving)})
            internal = [run for run in stopped_runs if moving
                        and run[0]['steady_time'] > moving[0]['steady_time']
                        and run[-1]['steady_time'] < moving[-1]['steady_time'] and _duration(run) >= .2 - 1e-9]
            metrics.update(motion_distance_m=sum(math.hypot(b['x'] - a['x'], b['y'] - a['y'])
                                                 for a, b in zip(active, active[1:])),
                           pause_count=len(internal), pause_total_duration_s=sum(_duration(run) for run in internal),
                           pauses=[{'started': run[0]['steady_time'], 'ended': run[-1]['steady_time'],
                                    'duration_s': _duration(run)} for run in internal],
                           final_truth=samples[-1], truth_sample_count=len(samples))
            elapsed_end = terminal if _finite(terminal) else samples[-1]['steady_time']
            metrics['elapsed_s'] = elapsed_end - sent if _finite(sent) else None
            metrics['elapsed_end_basis'] = terminal_basis
            accepted = goal.get('accepted_steady_time')
            metrics['goal_ack_wait_s'] = accepted - sent if _finite(accepted) and _finite(sent) else None
            route = case.get('route') or []
            target = case.get('target') or (route[-1] if route else goal.get('target'))
            target_valid = isinstance(target, (tuple, list)) and len(target) >= 3 and all(_finite(v) for v in target[:3])
            if kind in ('navigation', 'route', 'scan_gap'):
                if target_valid:
                    final = samples[-1]
                    position_error = math.hypot(final['x'] - target[0], final['y'] - target[1])
                    yaw_error = abs(math.atan2(math.sin(final['yaw'] - target[2]), math.cos(final['yaw'] - target[2])))
                    check('final_pose', position_error <= POSITION_TOLERANCE and yaw_error <= YAW_TOLERANCE,
                          {'position_error_m': position_error, 'yaw_error_rad': yaw_error})
                    metrics.update(final_error_m=position_error, final_yaw_error_rad=yaw_error)
                else:
                    check('final_pose', None, 'Target pose missing or malformed')
            if kind == 'route':
                route_valid = isinstance(route, list) and bool(route) and all(
                    isinstance(pose, (tuple, list)) and len(pose) == 3 and all(_finite(v) for v in pose) for pose in route)
                visits = _ordered_visits(active, route) if route_valid else []
                check('ordered_route_coverage', len(visits) == len(route) if route_valid else None,
                      {'visits': visits, 'requested_count': len(route) if isinstance(route, list) else None})
                metrics['ordered_visits'] = visits
        else:
            for name in ('truth_clock_advances', 'truth_window_continuous', 'truth_final_fresh',
                         'final_stopped', 'goal_window_recorded', 'movement_observed'):
                check(name, None)
            if kind in ('navigation', 'route', 'scan_gap'):
                check('final_pose', None)
            if kind == 'route':
                check('ordered_route_coverage', None)

        if kind in ('navigation', 'route', 'scan_gap'):
            action_ok = (goal.get('completed') is True and goal.get('stationary_feedback') is True
                         and goal.get('action_status') == 4 and goal.get('error_code') == 0
                         and not goal.get('cleanup_errors'))
            check('navigation_result', action_ok if goal else None,
                  {key: goal.get(key) for key in ('completed', 'stationary_feedback', 'action_status', 'error_code', 'cleanup_errors', 'error')})
        elif kind == 'cancel':
            canceled = goal.get('canceled') is True or goal.get('cancel_terminal_status') == 5
            check('canceled_terminal', canceled and goal.get('completed') is not True and not goal.get('cleanup_errors')
                  if goal else None, {key: goal.get(key) for key in ('canceled', 'cancel_terminal_status', 'completed', 'cleanup_errors')})
            trigger = case.get('cancel_trigger') or {}
            observed = trigger.get('truth') or {}
            triggered_at = trigger.get('steady_time')
            received = observed.get('steady_time')
            source_age = (observed['ros_now'] - observed['stamp']
                          if _finite(observed.get('ros_now')) and _finite(observed.get('stamp')) else None)
            receive_age = triggered_at - received if _finite(triggered_at) and _finite(received) else None
            trigger_speed = observed.get('linear_speed')
            valid_trigger = (case.get('cancel_sent_while_moving') is True and trigger_speed > LINEAR_STOP
                             and 0 <= receive_age <= TRUTH_AGE and -.05 <= source_age <= TRUTH_AGE)
            check('cancel_triggered_while_moving', valid_trigger
                  if all(_finite(v) for v in (trigger_speed, receive_age, source_age)) else None,
                  {'receive_age_s': receive_age, 'source_age_s': source_age, 'linear_speed': trigger_speed})
            terminal = goal.get('terminal_steady_time')
            check('cancel_precedes_terminal', terminal >= triggered_at
                  if _finite(terminal) and _finite(triggered_at) else None,
                  {'cancel_sent': triggered_at, 'terminal': terminal})
        else:
            check('supported_case', False, kind)

        if kind == 'scan_gap':
            starts = [event for event in relay_events if event.get('event') in ('gap_started', 'scan_gap_started')]
            ends = [event for event in relay_events if event.get('event') == 'scan_restored']
            start = starts[0] if starts else None
            end = next((event for event in ends if start and _finite(event.get('steady_time'))
                        and event['steady_time'] > start.get('steady_time', math.inf)), None)
            gap_valid = bool(start and end and _finite(start.get('steady_time')))
            check('scan_gap_recorded', gap_valid if relay_events else None, {'start': start, 'end': end})
            pauses = [event for event in guard_events if gap_valid and event.get('kind') == 'timing_pause'
                      and _finite(event.get('steady_time')) and start['steady_time'] <= event['steady_time'] <= end['steady_time'] + .5]
            pause = pauses[0] if pauses else None
            recovered = next((event for event in guard_events if pause and event.get('kind') == 'timing_recovered'
                              and _finite(event.get('steady_time')) and event['steady_time'] > pause['steady_time']
                              and event['steady_time'] >= end['steady_time']), None)
            check('guard_paused_then_recovered', bool(pause and recovered) if guard_events and gap_valid else None,
                  {'pause': pause, 'recovered': recovered})
            before = [sample for sample in samples if gap_valid and start['steady_time'] - .3 <= sample['steady_time'] <= start['steady_time']]
            trigger_speed = start.get('linear_speed_mps', start.get('speed')) if start else None
            if isinstance(trigger_speed, dict):
                trigger_speed = trigger_speed.get('linear_speed')
            check('gap_triggered_while_moving', bool(before) and any(not _stopped(sample) for sample in before)
                  and trigger_speed > LINEAR_STOP if _finite(trigger_speed) else None,
                  {'trigger_speed': trigger_speed, 'preceding_truth_samples': len(before)})
            during = [sample for sample in samples if gap_valid and recovered
                      and start['steady_time'] <= sample['steady_time'] <= recovered['steady_time']]
            stopped_duration = max((_duration(run) for run in _stop_runs(during)), default=0.)
            check('truth_braked_during_gap', stopped_duration >= .2 - 1e-9 if during else None,
                  {'longest_stationary_interval_s': stopped_duration})
            resumed = [sample for sample in samples if recovered and sample['steady_time'] > recovered['steady_time'] and not _stopped(sample)]
            check('truth_resumed_after_recovery', bool(resumed) if recovered and samples else None,
                  {'moving_samples_after_recovery': len(resumed)})
            resets = [event for event in events if 'reset' in str(event.get('kind', event.get('event', ''))).lower()]
            reset_count = recording.get('operator_reset_count')
            check('no_operator_reset', not resets and reset_count == 0 if reset_count is not None else None,
                  {'recorded_resets': len(resets), 'runner_reset_count': reset_count})
            count = goal.get('goal_send_count')
            check('same_goal_resumed', count == 1 if count is not None else None, {'goal_send_count': count})
            metrics.update(scan_gap_duration_s=end['steady_time'] - start['steady_time'] if gap_valid else None,
                           gap_stationary_duration_s=stopped_duration, reset_count=reset_count)
            limitations.append('Reset count covers this suite runner and recorded events; '
                               'it does not independently audit external service callers.')

    failures = [name for name, item in checks.items() if item['status'] == 'failed']
    unknown = [name for name, item in checks.items() if item['status'] == 'unknown']
    trajectory = [[sample['stamp'], sample['x'], sample['y']] for sample in samples]
    if kind == 'motion' and not trajectory:
        trajectory = (motion or {}).get('trajectory', [])
    metrics['reason_events'] = events
    return _json_safe({'name': case.get('name', 'unnamed'), 'kind': kind,
                       'status': 'passed' if checks and not failures and not unknown else 'failed',
                       'passed': bool(checks) and not failures and not unknown,
                       'case': case, 'checks': checks, 'metrics': metrics,
                       'failed_checks': failures, 'unknown_checks': unknown,
                       'error': goal.get('error') or (motion or {}).get('error'),
                       'trajectory': trajectory, 'goal': goal, 'limitations': limitations})


def _route_svg(report):
    """Reuse the inspection renderer, keeping this analysis module ROS-free."""
    source = Path(__file__).with_name('fishbot_inspection_vision.py')
    spec = importlib.util.spec_from_file_location('fishbot_suite_route_renderer', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._route_svg(report)


def save_suite_report(report, output_dir):
    """Render the existing suite evidence and only link files that actually exist."""
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cases = report.get('cases', [])
    passed = sum(case.get('status') == 'passed' for case in cases)
    planned = report.get('case_count', len(cases))
    if not isinstance(planned, int) or planned < len(cases):
        planned = len(cases)
    overall = report.get('status', 'unknown')
    first_passed = sum(case.get('first_attempt_passed', case.get('status') == 'passed') for case in cases)
    restarts = sum(case.get('startup_restart_count', 0) for case in cases)
    soak = report.get('soak')
    soak_html = ''
    if isinstance(soak, dict):
        samples = soak.get('resources', [])
        observed_rss = [sample.get('rss_bytes') for sample in samples if _finite(sample.get('rss_bytes'))]
        resource_text = ('RSS 首/末/峰值 '+ '/'.join(f'{value / 1024**2:.1f}' for value in
                         (observed_rss[0], observed_rss[-1], max(observed_rss)))+' MiB'
                         if observed_rss else '缺少资源样本')
        soak_html = (f'<article><h2>同进程连续运行</h2><p>launch PID：{escape(str(soak.get("launch_pid")))}；'
                     f'启动 {escape(str(soak.get("launch_count")))} 次；复位 {escape(str(soak.get("operator_reset_count")))} 次；'
                     f'观察 {escape(str(round(soak.get("observed_duration_s", 0), 3)))} 秒；'
                     f'动作收束 {escape(str(soak.get("completed_goal_count")))} 次。</p>'
                     f'<p>30 分钟独立验收：{"通过" if soak.get("qualified_30_minutes") is True else "未通过 / 尚未达到时长"}；'
                     f'{resource_text}。资源只统计本轮 launch 进程组；增量不直接等于泄漏。</p>'
                     '<p><a href="report.json">完整报告和资源样本</a>'
                     + (' · <a href="recording.json">连续物理真值</a>' if (output/'recording.json').is_file() else '')
                     + '</p></article>')
    rows, sections = [], []
    def metric_text(value):
        return f'{value:.3f}' if _finite(value) else '未知'
    for index, result in enumerate(cases):
        name, status = str(result.get('name', 'unnamed')), result.get('status', 'failed')
        case, metrics = result.get('case', {}), result.get('metrics', {})
        label = '通过' if status == 'passed' else '失败 / 证据不足'
        rows.append(f'<tr><td><a href="#case-{index}">{escape(name)}</a></td>'
                    f'<td>{escape(str(result.get("kind")))}</td><td>{label}</td>'
                    f'<td>{metric_text(metrics.get("elapsed_s"))}</td>'
                    f'<td>{metric_text(result.get("total_wall_elapsed_s", result.get("wall_elapsed_s")))}</td>'
                    f'<td>{escape(str(metrics.get("pause_count")))}</td>'
                    f'<td>{metric_text(metrics.get("pause_total_duration_s"))}</td></tr>')
        stations = [{'goal': pose} for pose in case.get('route', [])]
        target = case.get('target') or result.get('goal', {}).get('target')
        if not stations and target:
            stations = [{'goal': target}]
        plot = _route_svg({'trajectory': result.get('trajectory', []), 'stations': stations})
        if not plot:
            plot = '<p>缺少足够的真值轨迹；没有绘制推测路径。</p>'
        links = []
        for filename in ('goal.json', 'recording.json', 'motion.json', 'fixture-provenance.json',
                         'fixture/provenance.json', 'replay/index.html'):
            relative = Path(result.get('artifact_directory', name)) / filename
            candidate = (output / relative).resolve()
            if candidate.is_relative_to(output) and candidate.is_file():
                links.append(f'<a href="{quote(relative.as_posix(), safe="/")}">{escape(filename)}</a>')
        attempts = []
        for attempt in result.get('startup_attempts', []):
            artifact = Path(attempt['artifact_directory'])
            attempt_links = []
            for filename in ('result.json', 'launch.log', 'recorder.log'):
                relative = artifact / filename
                candidate = (output / relative).resolve()
                if candidate.is_relative_to(output) and candidate.is_file():
                    attempt_links.append(f'<a href="{quote(relative.as_posix(), safe="/")}">{escape(filename)}</a>')
            attempts.append(f'<li>{escape(artifact.name)}：{escape(str(attempt.get("status")))}；'
                            f'{metric_text(attempt.get("wall_elapsed_s"))} 秒；'
                            f'{escape(str(attempt.get("error") or ""))} {" · ".join(attempt_links)}</li>')
        attempt_html = '<details><summary>启动尝试记录</summary><ul>'+''.join(attempts)+'</ul></details>' if attempts else ''
        check_rows = ''.join(f'<tr><td>{escape(key)}</td><td>{escape(item.get("status", "unknown"))}</td>'
                             f'<td><code>{escape(json.dumps(item.get("evidence"), ensure_ascii=False, allow_nan=False))}</code></td></tr>'
                             for key, item in result.get('checks', {}).items())
        timeline = []
        sent = result.get('goal', {}).get('goal_sent_steady_time')
        for event in metrics.get('reason_events', []):
            stamp = event.get('steady_time')
            relative = stamp - sent if _finite(stamp) and _finite(sent) else None
            description = event.get('reason') or event.get('message') or event.get('event') or ''
            timeline.append(f'<tr><td>{escape(str(round(relative, 3) if relative is not None else stamp))}</td>'
                            f'<td>{escape(str(event.get("kind", event.get("source", "event"))))}</td>'
                            f'<td>{escape(str(description))}</td>'
                            f'<td>{escape(str(event.get("polygon_name", event.get("polygon", ""))))}</td>'
                            f'<td>{escape(str(event.get("action_type", "")))}</td></tr>')
        limits = ''.join(f'<li>{escape(str(item))}</li>' for item in result.get('limitations', []))
        sections.append(f'<article id="case-{index}"><h2>{escape(name)} · {label}</h2>'
                        f'<p>参数：<code>{escape(json.dumps(case, ensure_ascii=False, allow_nan=False))}</code></p>'
                        f'<p>证据：{" · ".join(links) or "没有可用的证据文件链接"}</p>{attempt_html}{plot}'
                        f'<details open><summary>验收检查</summary><table><thead><tr><th>检查</th><th>结果</th><th>实际证据</th></tr></thead>'
                        f'<tbody>{check_rows}</tbody></table></details><h3>事件时间线</h3>'
                        '<p>秒数相对 Goal 提交；没有时间戳的事件保留未知。CM 状态与扫描是异步近似关联。</p>'
                        '<table><thead><tr><th>时间 s</th><th>来源</th><th>原因</th><th>多边形</th><th>动作</th></tr></thead>'
                        f'<tbody>{"".join(timeline) or "<tr><td colspan=\"5\">没有记录到原因事件；不能推断没有停顿。</td></tr>"}</tbody></table>'
                        f'<details><summary>验收边界</summary><ul>{limits}</ul></details></article>')
    html = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>FishBot 仿真批量验收</title><style>'
            'body{font:16px/1.6 system-ui,sans-serif;max-width:1200px;margin:32px auto;padding:0 20px;color:#233348;background:#f4f7fa}'
            'article{background:white;border:1px solid #d1dbe4;border-radius:12px;padding:20px;margin:24px 0}'
            'table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:8px;border-bottom:1px solid #dfe6ed;vertical-align:top}'
            'code{overflow-wrap:anywhere;font-size:13px}svg{width:100%;height:auto}a{color:#245c9a}summary{cursor:pointer}h2{font-size:22px}'
            '</style><body><h1>FishBot 仿真批量验收</h1>'
            f'<p>整批状态：{escape(str(overall))}；已执行 {len(cases)}/{planned}；通过 {passed}/{planned}；'
            f'通过率 {passed / planned * 100 if planned else 0:.1f}%。'
            '失败与证据不足都计入未通过。运动探针与导航闭环分别判断。</p>'
            f'<p>首轮通过 {first_passed}/{planned}；启动重启 {restarts} 次。'
            '仅静止且尚未启动命令进程的就绪超时允许重启一次；已发任务不自动重发。失败尝试保留原始证据。</p>'
            f'<p>整批实际耗时 {metric_text(report.get("wall_elapsed_s"))} 秒。场景总耗时包含启动等待、重试、清理和回放。</p>{soak_html}'
            '<table><thead><tr><th>场景</th><th>类型</th><th>结果</th><th>Goal 耗时 s</th><th>场景总耗时 s</th><th>内部停顿次数</th><th>停顿总时长 s</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>{"".join(sections)}</body></html>')
    destination = output / 'index.html'
    destination.write_text(html, encoding='utf-8')
    return destination
