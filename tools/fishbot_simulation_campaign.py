"""Expand the existing suite, or keep one navigation stack warm for a soak."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import signal
import subprocess
import sys
import time

from fishbot_simulation_suite import (ROOT, SCRIPTS, domain_is_empty, execute_case_with_startup_retry,
    finish_process, interrupt_suite, read_json, selected_environment, write_json)
from fishbot_simulation_report import analyze_case, save_suite_report


def random_cases(seed, count):
    """Distinct reproducible scene seeds; retain each seed with its realized inputs."""
    if not 1 <= count <= 200:
        raise ValueError('case count must be in [1, 200]')
    cases = []
    for index in range(count):
        scene_seed = seed + index
        rng = random.Random(scene_seed)
        gap = index % 4 == 3
        case = dict(name=f'{index+1:02d}-seed-{scene_seed}', seed=scene_seed, domain=102,
                    kind='scan_gap' if gap else 'navigation',
                    target=[round(rng.uniform(1.20, 1.40), 3), round(rng.uniform(-.10, .10), 3), 0.],
                    door_width_m=round(rng.uniform(.36, .46), 3),
                    initial_yaw_rad=round(rng.uniform(-.25, .25), 3))
        if gap:
            case.update(scan_gap_s=round(rng.uniform(.65, 1.), 3),
                        scan_trigger_distance_m=round(rng.uniform(.10, .25), 3))
        cases.append(case)
    return cases


def fresh_checkpoint(sample, observed_at, maximum_age=.25):
    fields = ('steady_time', 'ros_now', 'stamp', 'x', 'y', 'yaw', 'linear_speed', 'angular_speed')
    if (not isinstance(sample, dict) or not math.isfinite(observed_at)
            or any(not isinstance(sample.get(key), (int, float))
                   or not math.isfinite(sample[key]) for key in fields)):
        return False
    return (0 <= observed_at-sample['steady_time'] <= maximum_age
            and -.05 <= sample['ros_now']-sample['stamp'] <= maximum_age)


def leg_recording(recording, start, checkpoint):
    """Use the recorder's independently observed clocks, never the final source stamp as now."""
    end = checkpoint['observed_steady_time']
    return dict(recording, truth=[sample for sample in recording.get('truth', [])
                                 if start-.5 <= sample['steady_time'] <= end],
                events=[event for event in recording.get('events', [])
                        if start-.5 <= event['steady_time'] <= end],
                final_steady_time=end, final_ros_now=checkpoint.get('truth', {}).get('ros_now'))


def events_for_leg(events, start, checkpoint):
    """Associate only observed finite timestamps; keep untimed events at run scope."""
    end = checkpoint['observed_steady_time']
    return [event for event in events if isinstance(event, dict)
            and isinstance(event.get('steady_time'), (int, float))
            and not isinstance(event['steady_time'], bool)
            and math.isfinite(event['steady_time'])
            and start-.5 <= event['steady_time'] <= end]


def resource_sample(launch_pid):
    """Observe only the launch's owned process group; no unrelated process inspection."""
    members = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdigit():
            continue
        try:
            fields = (directory/'stat').read_text().rsplit(')', 1)[1].split()
            if int(fields[2]) != launch_pid:  # state, ppid, process group
                continue
            rss_pages = int((directory/'statm').read_text().split()[1])
            members.append(dict(pid=int(directory.name), state=fields[0],
                                rss_bytes=rss_pages*os.sysconf('SC_PAGE_SIZE'),
                                fd_count=len(list((directory/'fd').iterdir()))))
        except (OSError, ValueError, IndexError):
            continue
    return dict(steady_time=time.monotonic(), launch_pid=launch_pid, members=members,
                process_count=len(members), rss_bytes=sum(m['rss_bytes'] for m in members),
                fd_count=sum(m['fd_count'] for m in members))


def source_receipt():
    sources = [Path(__file__), ROOT/'tools/fishbot_simulation_suite.py',
               ROOT/'tools/fishbot_simulation_report.py', ROOT/'tools/fishbot_passage_goal.py',
               ROOT/'tools/fishbot_passage_sim.launch.py', ROOT/'tools/fishbot_sim_scan_relay.py',
               ROOT/'tools/fishbot_passage.launch.py', ROOT/'tools/config/fishbot_passage_nav.yaml',
               ROOT/'tools/config/fishbot_model_geometry.yaml',
               SCRIPTS/'verify_stack.py', SCRIPTS/'wait_ready.py']
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    return dict(source_revision=revision, source_sha256={str(p.relative_to(ROOT)):
                hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})


def save_progress(report, output):
    report['passed_count'] = sum(case['status'] == 'passed' for case in report['cases'])
    report['first_attempt_passed_count'] = sum(case.get('first_attempt_passed', False)
                                              for case in report['cases'])
    report['startup_restart_count'] = sum(case.get('startup_restart_count', 0)
                                          for case in report['cases'])
    write_json(output/'report.json', report)
    save_suite_report(report, output)


def run_random(report, output, seed, count, env):
    report['case_count'] = count
    for case in random_cases(seed, count):
        print('Running '+case['name'], flush=True)
        result = execute_case_with_startup_retry(case, output/case['name'], env)
        report['cases'].append(result)
        print(case['name']+': '+result['status'], flush=True)
        save_progress(report, output)
        if result.get('case', {}).get('interrupted'):
            raise KeyboardInterrupt


def run_soak(report, output, duration, env):
    streams, children, legs, resources = [], [], [], []
    launch = recorder = goal_process = None
    failure = None
    started = None
    active_leg = None
    def start(command, label):
        stream = (output/(label+'.log')).open('w')
        streams.append(stream)
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream,
            stderr=subprocess.STDOUT, start_new_session=True)
        children.append(child)
        return child
    report['soak'] = dict(requested_duration_s=duration, required_duration_s=1800,
                          launch_count=0, operator_reset_count=0, completed_goal_count=0,
                          qualified_30_minutes=False, resources=resources)
    try:
        domain_is_empty()
        launch = start(['ros2', 'launch', str(ROOT/'tools/fishbot_passage_sim.launch.py'),
                        'ros_domain_id:=96', 'output_dir:='+str(output),
                        'door_width_m:=0.40', 'initial_yaw_rad:=0', 'timing_profile:=tolerant',
                        'localization:=amcl'], 'launch')
        report['soak'].update(launch_count=1, launch_pid=launch.pid)
        recorder = start([sys.executable, '-B', str(ROOT/'tools/fishbot_simulation_suite.py'),
                          '--collect', str(output/'recording.json'), '--require-amcl'], 'recorder')
        deadline = time.monotonic()+55
        while not (output/'ready.json').exists():
            if launch.poll() is not None or recorder.poll() is not None:
                raise RuntimeError('Warm stack exited before readiness')
            if time.monotonic() >= deadline:
                raise TimeoutError('Warm stack readiness exceeded 55 seconds; no restart')
            time.sleep(.1)
        started = time.monotonic()
        report['soak']['ready_steady_time'] = started
        resources.append(resource_sample(launch.pid))
        last_resource = started
        while time.monotonic()-started < duration:
            index = len(legs)+1
            target = [1.25, 0., 0.] if index % 2 else [0., 0., math.pi]
            case = dict(name=f'{index:03d}-warm-'+('outbound' if index % 2 else 'return'),
                        kind='navigation', domain=96, target=target,
                        door_width_m=.40, initial_yaw_rad=0., launch_pid=launch.pid,
                        timing_profile='tolerant')
            directory = output/case['name']
            directory.mkdir(mode=0o700)
            began = time.monotonic()
            goal_process = start([sys.executable, '-B', str(ROOT/'tools/fishbot_passage_goal.py'),
                '--domain', '96', '--use-sim-time', '--execute', '--timeout', '90',
                '--timing-profile', 'tolerant',
                '--target', *map(str, target), '--output', str(directory/'goal.json')], case['name'])
            # Admit the attempted Goal before waiting. A lost stack/result must
            # remain in the denominator, without spawning a replacement.
            active_leg = dict(case=case, start=began, goal={})
            legs.append(active_leg)
            report['soak']['attempted_goal_count'] = len(legs)
            deadline = time.monotonic()+110
            while goal_process.poll() is None:
                if launch.poll() is not None or recorder.poll() is not None:
                    raise RuntimeError('Owned warm stack exited during navigation; no restart')
                now = time.monotonic()
                if now-last_resource >= 10:
                    resources.append(resource_sample(launch.pid))
                    last_resource = now
                if now >= deadline:
                    raise TimeoutError('Warm goal exceeded 110 seconds; no resend')
                time.sleep(.1)
            case['command_returncode'] = goal_process.returncode
            time.sleep(1)  # Independent fresh physics after terminal result.
            observed = time.monotonic()
            sample = read_json(output/'latest-truth.json', {})
            checkpoint = dict(observed_steady_time=observed, truth=sample)
            write_json(directory/'checkpoint.json', checkpoint)
            goal = read_json(directory/'goal.json', {})
            active_leg.update(checkpoint=checkpoint, goal=goal)
            report['soak']['completed_goal_count'] = sum(
                leg['goal'].get('goal_accepted') is True
                and leg['goal'].get('action_status') in (4, 5, 6) for leg in legs)
            print(case['name']+': action '+str(goal.get('action_status'))+
                  ', elapsed '+str(round(observed-started, 1))+'s', flush=True)
            if (case['command_returncode'] != 0 or not goal.get('completed')
                    or not goal.get('stationary_feedback') or not fresh_checkpoint(sample, observed)
                    or math.hypot(sample['x']-target[0], sample['y']-target[1]) > .15
                    or abs(math.atan2(math.sin(sample['yaw']-target[2]),math.cos(sample['yaw']-target[2]))) > .30):
                raise RuntimeError('Warm goal or fresh stationary checkpoint failed; preserving original result')
            report['soak']['observed_duration_s'] = observed-started
            save_progress(report, output)
            active_leg = None
        if launch.poll() is not None or recorder.poll() is not None:
            raise RuntimeError('Warm process exited before final observation')
        report['soak']['observed_duration_s'] = time.monotonic()-started
        resources.append(resource_sample(launch.pid))
    except (Exception, KeyboardInterrupt) as exc:
        failure = str(exc) or 'Soak interrupted'
        report['soak']['error'] = failure
        observed = time.monotonic()
        if started is not None:
            report['soak']['observed_duration_s'] = observed-started
        if active_leg is not None:
            directory = output/active_leg['case']['name']
            active_leg.setdefault('checkpoint', dict(observed_steady_time=observed,
                truth=read_json(output/'latest-truth.json', {})))
            active_leg['goal'] = read_json(directory/'goal.json', active_leg['goal'])
            active_leg['case']['execution_error'] = failure
            write_json(directory/'checkpoint.json', active_leg['checkpoint'])
    finally:
        cleanup = [finish_process(child) for child in reversed(children)]
        report['soak']['cleanup_complete'] = all(cleanup)
        for stream in streams:
            stream.close()
    recording = read_json(output/'recording.json', {})
    guard_events = [read_json(path) for path in sorted((output/'triggers/command_guard').glob('trigger-*.json'))]
    report['soak']['unassociated_guard_events'] = [event for event in guard_events
        if not any(events_for_leg([event], leg['start'], leg['checkpoint']) for leg in legs)]
    for leg in legs:
        case = leg['case']
        selected = leg_recording(recording, leg['start'], leg['checkpoint'])
        result = analyze_case(case, selected, leg['goal'],
                              events_for_leg(guard_events, leg['start'], leg['checkpoint']), [])
        result.update(artifact_directory=case['name'], first_attempt_passed=result['passed'],
                      startup_restart_count=0, wall_elapsed_s=leg['checkpoint']['observed_steady_time']-leg['start'])
        write_json(output/case['name']/'recording.json', selected)
        write_json(output/case['name']/'result.json', result)
        report['cases'].append(result)
    qualified = (not failure and report['soak'].get('observed_duration_s', 0) >= 1800
                 and report['soak']['launch_count'] == 1 and len(legs) >= 2
                 and report['soak']['cleanup_complete'] and all(case['passed'] for case in report['cases']))
    report['soak']['qualified_30_minutes'] = qualified
    report['case_count'] = len(legs)
    if failure or not report['soak']['cleanup_complete']:
        raise RuntimeError(failure or 'Warm process cleanup incomplete')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('random', 'soak'), required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--seed', type=int, default=1200)
    parser.add_argument('--count', type=int, default=20)
    parser.add_argument('--soak-seconds', type=float, default=1800)
    args = parser.parse_args()
    if not math.isfinite(args.soak_seconds) or not 15 <= args.soak_seconds <= 7200:
        parser.error('soak duration must be finite and in [15, 7200] seconds')
    random_cases(args.seed, args.count)
    domain = 96 if args.mode == 'soak' else 102
    env = selected_environment(domain)
    output = (args.output or Path.home()/'.cache/fishbot/simulation-campaigns'/
              (args.mode+'-'+time.strftime('%Y%m%d-%H%M%S'))).resolve()
    if output.is_relative_to(ROOT):
        parser.error('campaign output must be outside the source repository')
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    signal.signal(signal.SIGTERM, interrupt_suite)
    report = dict(schema_version=1, mode=args.mode, domain=domain, seed=args.seed,
                  cases=[], case_count=0, status='running', **source_receipt(),
                  scope='Synthetic simulation only; model and wireless hardware behavior are not inferred.')
    began = time.monotonic()
    try:
        if args.mode == 'random':
            run_random(report, output, args.seed, args.count, env)
        else:
            run_soak(report, output, args.soak_seconds, env)
        report['status'] = 'passed' if report['cases'] and all(c['passed'] for c in report['cases']) else 'failed'
    except KeyboardInterrupt:
        report['status'] = 'interrupted'
    except Exception as exc:
        report.update(status='failed', error=str(exc))
    report['wall_elapsed_s'] = time.monotonic()-began
    save_progress(report, output)
    print(str(output/'index.html'), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
