"""Run isolated MuJoCo cases through existing launch, Goal, and replay tools."""
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
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/scripts'


def case_matrix(seed):
    rng = random.Random(seed)
    target = [1.25, 0.0, 0.0]
    return [
        dict(name='01-doorway', kind='navigation', target=target, door_width_m=.36, initial_yaw_rad=0),
        dict(name='02-varied-doorway', kind='navigation', target=target,
             door_width_m=round(rng.uniform(.40, .44), 3), initial_yaw_rad=round(rng.uniform(-.12, .12), 3)),
        dict(name='03-continuous-route', kind='route', target=target, door_width_m=.40, initial_yaw_rad=0,
             route=[[.30, 0., 0.], [.95, 0., 0.], target]),
        dict(name='04-moving-scan-gap', kind='scan_gap', target=target, door_width_m=.40,
             initial_yaw_rad=0, scan_gap_s=.9, scan_trigger_distance_m=.15),
        dict(name='05-cancel-moving-goal', kind='cancel', target=target, door_width_m=.40,
             initial_yaw_rad=0, cancel_distance_m=.25),
        dict(name='06-old-command-and-timeout', kind='motion'),
    ]


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix+'.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    os.replace(temporary, path)


def read_json(path, default=None):
    if not Path(path).is_file():
        return default
    return json.loads(Path(path).read_text())


def selected_environment(domain=96):
    env = os.environ.copy()
    if domain not in (96, 102):
        raise RuntimeError('Suite collectors support isolated domains 96 and 102 only')
    if env.get('ROS_DOMAIN_ID') != str(domain) or env.get('FISHBOT_MUJOCO_DOMAIN_ID') != str(domain):
        raise RuntimeError('Suite domain '+str(domain)+' must be explicitly selected')
    if env.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST':
        raise RuntimeError('Suite requires LOCALHOST discovery')
    if env.get('ROS_STATIC_PEERS', ''):
        raise RuntimeError('Suite requires empty static peers')
    env['ROS_STATIC_PEERS'] = ''
    return env


def domain_is_empty(timeout=5):
    # Query the selected domain directly; do not use the shared ros2 CLI daemon.
    import rclpy
    rclpy.init()
    node = rclpy.create_node('fishbot_suite_domain_check_'+str(os.getpid()))
    deadline = time.monotonic() + timeout
    others = []
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.15)
            others = [name for name in node.get_node_names() if name != node.get_name()]
            if others:
                raise RuntimeError('Domain '+os.environ.get('ROS_DOMAIN_ID', '96')+' already contains nodes: '
                                   + ', '.join(sorted(set(others))))
        return
    finally:
        node.destroy_node()
        rclpy.shutdown()


def finish_process(process):
    """Only stop this runner's process group; always reap its launch parent."""
    if process is None:
        return True
    for sig, timeout in ((signal.SIGINT, 12), (signal.SIGTERM, 4), (signal.SIGKILL, 2)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=timeout)
            # A launch parent may finish before its children; finish the owned group too.
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                return True
            deadline = time.monotonic()+timeout
            while time.monotonic() < deadline:
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    return True
                time.sleep(.1)
        except subprocess.TimeoutExpired:
            continue
    return False


def collect(path, require_guard, require_amcl=False):
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.signals import SignalHandlerOptions
    from diagnostic_msgs.msg import DiagnosticArray
    from nav2_msgs.msg import CollisionMonitorState
    from geometry_msgs.msg import PolygonStamped
    from lifecycle_msgs.srv import GetState
    from nav_msgs.msg import OccupancyGrid
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    sys.path.insert(0, str(SCRIPTS))
    from verify_stack import Probe
    from wait_ready import Readiness
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    done = []
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: done.append(True))
    data = {'domain': int(os.environ['ROS_DOMAIN_ID']), 'truth': [], 'events': [], 'association':
            'CM state has no timestamp; truth, scans and CM are associated by local receipt time only.',
            'operator_reset_count': 0,
            'reset_count_source': 'Suite launches an empty isolated domain and never invokes reset; counts suite calls only.'}

    class Recorder(Probe):
        def __init__(self):
            super().__init__(SimpleNamespace(mode='sensors', odom='/odom', scan='/scan',
                                            truth='/ground_truth/free_joint_states', cmd='/cmd_vel'))
            self.guard = None
            self.last_guard = None
            self.scan_received = self.odom_received = None
            self.last_ros_now = None
            self.clock_advanced_wall = None
            self.map_observation = None
            self.create_subscription(OccupancyGrid, '/map', self.on_map,
                QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                           durability=DurabilityPolicy.TRANSIENT_LOCAL))
            self.create_subscription(DiagnosticArray, '/fishbot_command_guard/diagnostics', self.on_guard, 1)
            self.create_subscription(CollisionMonitorState, '/collision_monitor_state', self.on_cm, 1)
            for topic in ('/passage_stop_polygon', '/passage_slow_polygon', '/local_costmap/published_footprint'):
                self.create_subscription(PolygonStamped, topic, lambda msg, key=topic: self.on_polygon(key, msg), 1)

        def on_scan(self, msg):
            self.scan_received = time.monotonic()
            super().on_scan(msg)

        def on_map(self, msg):
            info, origin = msg.info, msg.info.origin.position
            if (msg.header.frame_id != 'map' or info.width <= 0 or info.height <= 0
                    or len(msg.data) != info.width*info.height
                    or not all(math.isfinite(value) for value in (info.resolution, origin.x, origin.y))
                    or info.resolution <= 0 or not any(value == 0 for value in msg.data)):
                self.map_observation = None
                return
            self.map_observation = dict(steady_time=time.monotonic(), frame_id=msg.header.frame_id,
                width=info.width, height=info.height, resolution=info.resolution, origin=[origin.x, origin.y])

        def on_odom(self, msg):
            self.odom_received = time.monotonic()
            super().on_odom(msg)

        def on_truth(self, msg):
            previous_updates = self.truth_updates
            super().on_truth(msg)
            if self.truth is None or self.truth_updates == previous_updates or self.truth_time != (
                    msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9):
                return
            p, q = self.truth.pose.pose.position, self.truth.pose.pose.orientation
            linear, angular = self.planar_speed()
            sample = dict(steady_time=time.monotonic(), stamp=self.truth_time, x=p.x, y=p.y,
                          yaw=math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z)),
                          linear_speed=linear, angular_speed=angular,
                          ros_now=self.get_clock().now().nanoseconds*1e-9)
            if all(math.isfinite(value) for value in sample.values()):
                data['truth'].append(sample)

        def on_guard(self, msg):
            status = next((s for s in msg.status if s.name == 'fishbot_command_guard'), None)
            if status is None:
                return
            self.guard = (time.monotonic(), status)
            if status.message != self.last_guard:
                self.last_guard = status.message
                data['events'].append(dict(kind='guard', steady_time=time.monotonic(), reason=status.message,
                    stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,
                    values={v.key: v.value for v in status.values}))

        def on_cm(self, msg):
            data['events'].append(dict(kind='collision_monitor', steady_time=time.monotonic(),
                                       action_type=int(msg.action_type), polygon_name=msg.polygon_name))

        def on_polygon(self, topic, msg):
            if not msg.polygon.points:
                return
            # Latest real polygon per topic is enough; no synthetic reconstruction.
            data.setdefault('polygons', {})[topic] = dict(steady_time=time.monotonic(), frame_id=msg.header.frame_id,
                stamp=msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,
                points=[[p.x, p.y] for p in msg.polygon.points])

    node = Recorder()
    startup = None
    if require_guard:
        # Reuse the readiness lifecycle/TF gate; the synthetic fixture has no AMCL.
        startup = Readiness(False)
        startup.nav = True
        startup.lifecycle_clients = {name: startup.create_client(GetState, '/'+name+'/get_state')
            for name in ('map_server', 'controller_server', 'planner_server', 'bt_navigator', 'collision_monitor')
                        + (('amcl',) if require_amcl else ())}
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    if startup is not None:
        executor.add_node(startup)
    last_ready_log = 0.
    ready = False
    try:
        while not done:
            executor.spin_once(timeout_sec=.05)
            if startup is not None:
                startup.update_lifecycle()
            now = time.monotonic()
            ros_now = node.get_clock().now().nanoseconds*1e-9
            if node.last_ros_now is not None and ros_now > node.last_ros_now:
                node.clock_advanced_wall = now
            node.last_ros_now = ros_now
            if not ready and startup is not None and now-last_ready_log >= 5:
                print('Startup gate: '+str(startup.reason()), flush=True)
                last_ready_log = now
            if data['truth']:
                latest = dict(data['truth'][-1], ros_now=ros_now)
                write_json(path.parent / 'latest-truth.json', latest)
            if not ready and node.truth is not None and node.scan is not None and node.odom is not None:
                try:
                    node.snapshot()
                    ros_now = node.get_clock().now().nanoseconds*1e-9
                    sensors_fresh = all(-.05 <= ros_now-stamp <= .5 for stamp in
                                        (node.scan_times[-1], node.odom_times[-1]))
                    sensors_fresh = sensors_fresh and all(received is not None and 0 <= now-received <= .5
                        for received in (node.scan_received, node.odom_received, node.clock_advanced_wall))
                    guard_ok = (not require_guard or
                        node.guard is not None and now-node.guard[0] < 1 and node.client.server_is_ready()
                        and not node.guard[1].message.startswith('latched:') and startup.reason() is None
                        and node.map_observation is not None)
                    if guard_ok and sensors_fresh:
                        write_json(path.parent / 'ready.json', {'steady_time': now,
                            'lifecycle': startup.lifecycle if startup is not None else {},
                            'map': node.map_observation})
                        ready = True
                except RuntimeError:
                    pass
    finally:
        data['final_steady_time'] = time.monotonic()
        data['final_ros_now'] = node.get_clock().now().nanoseconds*1e-9
        write_json(path, data)
        executor.shutdown()
        if startup is not None:
            startup.destroy_node()
        node.destroy_node()
        rclpy.shutdown()


def execute_case(case, directory, env):
    started = time.monotonic()
    domain = str(env.get('ROS_DOMAIN_ID', '96'))
    case['domain'] = int(domain)
    directory.mkdir(mode=0o700)
    processes, streams = [], []
    def start(command, label):
        stream = (directory / (label+'.log')).open('w')
        streams.append(stream)
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        processes.append(child)
        return child
    launch = recorder = goal_process = None
    error = None
    execution = dict(phase='domain_check', domain_empty=False, goal_process_started=False)
    try:
        domain_is_empty()
        execution.update(domain_empty=True, phase='startup')
        if case['kind'] == 'motion':
            launch_command = ['ros2', 'launch', 'fishbot_mujoco', 'sim.launch.py', 'ros_domain_id:='+domain,
                              'headless:=true', 'rviz:=false', 'nav:=false', 'bridge:=false', 'obstacle:=false']
        else:
            launch_command = ['ros2', 'launch', str(ROOT/'tools/fishbot_passage_sim.launch.py'),
                'ros_domain_id:='+domain, 'output_dir:='+str(directory),
                'door_width_m:='+str(case['door_width_m']), 'initial_yaw_rad:='+str(case['initial_yaw_rad']),
                'timing_profile:='+('tolerant' if case['kind'] == 'scan_gap' else 'strict'),
                'scan_gap_s:='+str(case.get('scan_gap_s', 0)),
                'scan_trigger_distance_m:='+str(case.get('scan_trigger_distance_m', .15))]
        launch = start(launch_command, 'launch')
        recorder = start([sys.executable, '-B', str(Path(__file__).resolve()), '--collect',
                          str(directory/'recording.json'), '--domain', domain, '--require-guard',
                          'false' if case['kind'] == 'motion' else 'true'], 'recorder')
        deadline = time.monotonic()+55
        while not (directory/'ready.json').is_file():
            if launch.poll() is not None or recorder.poll() is not None:
                raise RuntimeError('Simulation or recorder exited before readiness; inspect case logs')
            if time.monotonic() > deadline:
                execution['startup_failure_kind'] = 'readiness_timeout'
                raise TimeoutError('Simulation readiness exceeded 55 seconds')
            time.sleep(.1)
        if case['kind'] == 'motion':
            command = [sys.executable, str(SCRIPTS/'verify_stack.py'), 'motion', '--output', str(directory/'motion.json')]
        else:
            command = [sys.executable, str(ROOT/'tools/fishbot_passage_goal.py'), '--domain', domain,
                '--use-sim-time', '--execute', '--timeout', '90', '--output', str(directory/'goal.json'),
                '--timing-profile', 'tolerant' if case['kind'] == 'scan_gap' else 'strict']
            if case['kind'] == 'route':
                write_json(directory/'route.json', case['route'])
                command += ['--route-file', str(directory/'route.json')]
            else:
                command += ['--target', *map(str, case['target'])]
        # Mark this before spawning: even an uncertain spawn must never resend a Goal.
        execution.update(phase='command', goal_process_started=True)
        goal_process = start(command, 'goal')
        deadline = time.monotonic()+110
        cancel_sent = False
        while goal_process.poll() is None:
            if launch.poll() is not None or recorder.poll() is not None:
                raise RuntimeError('Simulation or truth recorder exited while goal was active')
            if case['kind'] == 'cancel' and not cancel_sent:
                sample = read_json(directory/'latest-truth.json', {})
                receive_age = time.monotonic()-sample.get('steady_time', -math.inf)
                source_age = sample.get('ros_now', math.inf)-sample.get('stamp', 0)
                if (sample.get('x', 0) >= case['cancel_distance_m'] and sample.get('linear_speed', 0) > .005
                        and 0 <= receive_age <= .25 and -.05 <= source_age <= .25):
                    goal_process.send_signal(signal.SIGINT)
                    cancel_sent = True
                    case['cancel_trigger'] = dict(steady_time=time.monotonic(), truth=sample)
            if time.monotonic() > deadline:
                raise TimeoutError('Case execution exceeded 110 seconds')
            time.sleep(.1)
        case['command_returncode'] = goal_process.returncode
        case['cancel_sent_while_moving'] = cancel_sent
        execution['phase'] = 'completed'
        # Keep the independent truth clock running after the client's terminal result.
        time.sleep(1)
    except Exception as exc:
        error = str(exc)
    except KeyboardInterrupt:
        error = 'Suite interrupted; owned processes were stopped'
        case['interrupted'] = True
    finally:
        cleanup = [finish_process(child) for child in (goal_process, recorder, launch)]
        execution['cleanup_complete'] = all(cleanup)
        if not execution['cleanup_complete']:
            error = '; '.join(value for value in (error, 'Owned process group cleanup did not complete') if value)
        for stream in streams:
            stream.close()
    try:
        from fishbot_simulation_report import analyze_case
        guard_events = [read_json(p) for p in sorted((directory/'triggers/command_guard').glob('trigger-*.json'))]
        relay = directory/'scan-relay.jsonl'
        relay_events = [json.loads(line) for line in relay.read_text().splitlines()] if relay.is_file() else []
        report = analyze_case(case, read_json(directory/'recording.json', {}), read_json(directory/'goal.json', {}),
                              guard_events, relay_events, motion=read_json(directory/'motion.json'))
        # Reuse the established scan/TF/zone renderer for trigger-level inspection.
        if guard_events:
            replay = subprocess.run([sys.executable, str(ROOT/'tools/fishbot_passage_replay.py'),
                *map(str, sorted((directory/'triggers/command_guard').glob('trigger-*.json'))),
                '--output-dir', str(directory/'replay')], cwd=ROOT, env=env, capture_output=True, text=True, timeout=25)
            report['replay_returncode'] = replay.returncode
            if replay.returncode:
                report['replay_error'] = (replay.stdout+replay.stderr)[-1500:]
                report.update(status='failed', passed=False)
                report.setdefault('checks', {})['trigger_replay'] = {'status':'failed','evidence':report['replay_error']}
    except Exception as exc:
        report = dict(name=case['name'], kind=case['kind'], case=case, status='failed', passed=False,
                      metrics={}, trajectory=[], goal={}, limitations=['Evidence analysis did not complete.'],
                      checks={'evidence_analysis': {'status':'failed','evidence':str(exc)}})
        error = '; '.join(value for value in (error, 'Evidence analysis failed: '+str(exc)) if value)
    if error:
        report.update(status='failed', passed=False, error=error)
        report.setdefault('checks', {})['runner_completed'] = {'status':'failed','evidence':error}
    report['execution'] = execution
    report['artifact_directory'] = directory.name
    report['wall_elapsed_s'] = time.monotonic()-started
    write_json(directory/'result.json', report)
    return report


def startup_retry_allowed(result, directory):
    """Retry only an observed stationary startup timeout, before any command process."""
    execution = result.get('execution', {})
    case = result.get('case', {})
    if (result.get('status') != 'failed' or execution.get('phase') != 'startup'
            or execution.get('startup_failure_kind') != 'readiness_timeout'
            or execution.get('domain_empty') is not True
            or execution.get('cleanup_complete') is not True
            or execution.get('goal_process_started') is not False
            or case.get('interrupted') or 'command_returncode' in case
            or any((directory/name).exists() for name in ('goal.json', 'motion.json', 'ready.json'))):
        return False
    try:
        recording = read_json(directory/'recording.json', {})
        truth = recording.get('truth', [])
        if len(truth) < 2 or not all(isinstance(recording.get(key), (float, int))
                and math.isfinite(recording[key]) for key in ('final_steady_time','final_ros_now')):
            return False
        fields = ('steady_time', 'stamp', 'x', 'y', 'yaw', 'linear_speed', 'angular_speed')
        if any(not all(isinstance(sample.get(key), (int, float)) and math.isfinite(sample[key])
                       for key in fields) for sample in truth):
            return False
        origin = truth[0]
        if (not 0 <= recording['final_steady_time']-truth[-1]['steady_time'] <= .25
                or not -.05 <= recording['final_ros_now']-truth[-1]['stamp'] <= .25
                or any(not 0 < right[key]-left[key] <= .3
                       for left, right in zip(truth, truth[1:]) for key in ('steady_time','stamp'))):
            return False
        return all(abs(sample['linear_speed']) < .005 and abs(sample['angular_speed']) < .02
                   and math.hypot(sample['x']-origin['x'], sample['y']-origin['y']) < .01
                   and abs(math.atan2(math.sin(sample['yaw']-origin['yaw']),
                                      math.cos(sample['yaw']-origin['yaw']))) < .02
                   for sample in truth)
    except (ValueError, TypeError, KeyError, OSError):
        return False


def execute_case_with_startup_retry(case, directory, env):
    started = time.monotonic()
    first = execute_case(dict(case), directory, env)
    result = first
    attempts = [dict(artifact_directory=directory.name, status=first['status'], error=first.get('error'),
                     wall_elapsed_s=first.get('wall_elapsed_s'))]
    if startup_retry_allowed(first, directory):
        retry_directory = directory.with_name(directory.name+'-startup-retry-1')
        print(case['name']+': stationary startup timed out before any command; one cold restart', flush=True)
        result = execute_case(dict(case), retry_directory, env)
        attempts.append(dict(artifact_directory=retry_directory.name, status=result['status'], error=result.get('error'),
                             wall_elapsed_s=result.get('wall_elapsed_s')))
    result.update(first_attempt_passed=first['status']=='passed', startup_restart_count=len(attempts)-1,
                  startup_attempts=attempts, total_wall_elapsed_s=time.monotonic()-started)
    # Keep the first failed result untouched; annotate only the selected final attempt.
    write_json(directory.parent/result['artifact_directory']/'result.json', result)
    return result


def interrupt_suite(_signum, _frame):
    # SIGTERM must unwind finally blocks even though launch children have their own sessions.
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='new external directory; default ~/.cache/fishbot/simulation-suites')
    parser.add_argument('--seed', type=int, default=12)
    parser.add_argument('--cases', nargs='+', help='select named cases from the fixed acceptance matrix')
    parser.add_argument('--collect', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--require-guard', choices=('true', 'false'), default='true', help=argparse.SUPPRESS)
    parser.add_argument('--domain', type=int, default=96, choices=(96, 102), help=argparse.SUPPRESS)
    parser.add_argument('--require-amcl', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.collect and args.domain != 96:
        parser.error('The regular suite uses domain 96; use the campaign for domain 102')
    env = selected_environment(args.domain)
    if args.collect:
        collect(args.collect, args.require_guard == 'true', args.require_amcl)
        return 0
    signal.signal(signal.SIGTERM, interrupt_suite)
    cases = case_matrix(args.seed)
    if args.cases:
        known = {case['name'] for case in cases}
        if set(args.cases)-known:
            parser.error('unknown cases: ' + ', '.join(sorted(set(args.cases)-known)))
        cases = [case for case in cases if case['name'] in args.cases]
    output = (args.output or Path.home()/'.cache/fishbot/simulation-suites'/('suite-'+time.strftime('%Y%m%d-%H%M%S'))).resolve()
    if output.is_relative_to(ROOT):
        parser.error('suite output must be outside the source repository')
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    sources = [Path(__file__), ROOT/'tools/fishbot_passage_goal.py', ROOT/'tools/fishbot_passage_sim.launch.py',
               ROOT/'tools/fishbot_sim_scan_relay.py', ROOT/'tools/fishbot_simulation_report.py',
               SCRIPTS/'verify_stack.py', SCRIPTS/'wait_ready.py']
    revision = subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
    report = dict(schema_version=1, domain=96, seed=args.seed, status='running', cases=[], case_count=len(cases),
        source_revision=revision, source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                                                for p in sources if p.is_file()},
        scope='Synthetic MuJoCo acceptance only; no physical robot or wireless-stack acceptance.')
    from fishbot_simulation_report import save_suite_report
    started = time.monotonic()
    try:
        for case in cases:
            print('Running '+case['name'], flush=True)
            result = execute_case_with_startup_retry(case, output/case['name'], env)
            report['cases'].append(result)
            print(case['name']+': '+result['status'], flush=True)
            report['status'] = 'running'
            report['wall_elapsed_s'] = time.monotonic()-started
            write_json(output/'report.json', report)
            save_suite_report(report, output)
            if result.get('case', {}).get('interrupted'):
                raise KeyboardInterrupt
    except KeyboardInterrupt:
        report['status'] = 'interrupted'
    except Exception as exc:
        report.update(status='failed', error=str(exc))
    else:
        report['status'] = 'passed' if report['cases'] and all(c['status']=='passed' for c in report['cases']) else 'failed'
    report['passed_count'] = sum(case['status']=='passed' for case in report['cases'])
    report['first_attempt_passed_count'] = sum(case.get('first_attempt_passed', False) for case in report['cases'])
    report['startup_restart_count'] = sum(case.get('startup_restart_count', 0) for case in report['cases'])
    report['case_count'] = len(cases)
    report['wall_elapsed_s'] = time.monotonic()-started
    write_json(output/'report.json', report)
    save_suite_report(report, output)
    print(str(output/'index.html'), flush=True)
    return 0 if report['status']=='passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
