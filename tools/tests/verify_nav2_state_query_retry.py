#!/usr/bin/env python3
"""Exercise stock and patched Nav2 with real delayed lifecycle services.

Explicit --execute and empty localhost-only domain 103 are required.
The fixture publishes no robot topic and sends no navigation command.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

TOOLS = Path(__file__).resolve().parents[1]
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
from fishbot_simulation_suite import domain_is_empty, finish_process, write_json


def fingerprint(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def wait_future(future, process, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if future.done():
            return future.result()
        if process.poll() is not None:
            raise RuntimeError('Manager exited before the service response.')
        time.sleep(.02)
    raise RuntimeError('Manager service response is unknown after the deadline.')


def manager_library(process, expected):
    maps = Path(f'/proc/{process.pid}/maps').read_text()
    libraries = {line.split(maxsplit=5)[-1] for line in maps.splitlines()
                 if 'libnav2_lifecycle_manager_core.so' in line}
    if len(libraries) != 1 or Path(next(iter(libraries))).resolve() != expected.resolve():
        raise RuntimeError(f'Manager loaded an unexpected library: {sorted(libraries)}')
    return fingerprint(next(iter(libraries)))


def run_case(output, name, executable, library, mode):
    import rclpy
    from lifecycle_msgs.srv import ChangeState, GetState
    from nav2_msgs.srv import ManageLifecycleNodes
    from rcl_interfaces.srv import GetParameters
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.context import Context
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.signals import SignalHandlerOptions

    domain_is_empty()
    directory = output / name
    directory.mkdir()
    fixture_name = f'query_fixture_{name}_{os.getpid()}'
    manager_name = f'query_manager_{name}_{os.getpid()}'
    state = {'id': 1, 'changes': [], 'queries': []}
    lock = threading.Lock()
    context = Context()
    rclpy.init(context=context, signal_handler_options=SignalHandlerOptions.NO)
    fixture = Node(fixture_name, context=context)
    controller = Node(f'query_verifier_{name}_{os.getpid()}', context=context)
    group = ReentrantCallbackGroup()

    def change_state(request, response):
        with lock:
            transition = request.transition.id
            previous = state['id']
            allowed = (previous, transition) in ((1, 1), (2, 3))
            if allowed:
                state['id'] = 2 if transition == 1 else 3
            state['changes'].append({'steady': time.monotonic(), 'epoch_ns': time.time_ns(),
                                     'transition': transition, 'previous': previous,
                                     'resulting': state['id'], 'success': allowed})
        response.success = allowed
        return response

    def get_state(request, response):
        del request
        with lock:
            index = len(state['queries']) + 1
            current_state = state['id']
            delay = 2.3 if mode == 'persistent_timeout' or index == 1 else 0.0
            event = {'index': index, 'arrival_steady': time.monotonic(),
                     'arrival_epoch_ns': time.time_ns(), 'state_snapshot': current_state,
                     'injected_delay_seconds': delay}
            state['queries'].append(event)
        if delay:
            time.sleep(delay)
        response.current_state.id = current_state
        response.current_state.label = {1: 'unconfigured', 2: 'inactive', 3: 'active'}[current_state]
        with lock:
            event['response_steady'] = time.monotonic()
            event['response_epoch_ns'] = time.time_ns()
            event['measured_callback_seconds'] = event['response_steady'] - event['arrival_steady']
        return response

    fixture.create_service(ChangeState, f'/{fixture_name}/change_state', change_state, callback_group=group)
    fixture.create_service(GetState, f'/{fixture_name}/get_state', get_state, callback_group=group)
    manage = controller.create_client(ManageLifecycleNodes, f'/{manager_name}/manage_nodes')
    parameters = controller.create_client(GetParameters, f'/{manager_name}/get_parameters')
    executor = MultiThreadedExecutor(num_threads=4, context=context)
    executor.add_node(fixture)
    executor.add_node(controller)
    spin_thread = threading.Thread(target=executor.spin, daemon=True)
    spin_thread.start()

    environment = dict(os.environ)
    environment['LD_LIBRARY_PATH'] = str(library.parent) + ':' + environment.get('LD_LIBRARY_PATH', '')
    environment['ROS_LOG_DIR'] = str(directory / 'ros-log')
    command = [str(executable), '--ros-args', '-r', f'__node:={manager_name}',
               '-p', 'autostart:=false', '-p', 'bond_timeout:=0.0',
               '-p', f'node_names:=[{fixture_name}]']
    inputs = {'mode': mode, 'command': command, 'domain': 103,
              'manager_executable': fingerprint(executable), 'expected_library': fingerprint(library),
              'fixture_source': fingerprint(__file__), 'rclpy_source': fingerprint(rclpy.__file__),
              'launch_steady': time.monotonic(), 'launch_epoch_ns': time.time_ns()}
    write_json(directory / 'startup-inputs.json', inputs)
    result = {'name': name, 'mode': mode, 'passed': False, 'inputs': inputs,
              'startup_rpc_calls': 0, 'cleanup_complete': False}
    process = None
    log_handle = None
    try:
        log_handle = (directory / 'manager.log').open('w')
        process = subprocess.Popen(command, env=environment, stdout=log_handle,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + 12
        while not manage.wait_for_service(timeout_sec=.2):
            if time.monotonic() > deadline or process.poll() is not None:
                raise RuntimeError('Manager STARTUP service did not become available.')
        result['loaded_library'] = manager_library(process, library)
        if not parameters.wait_for_service(timeout_sec=3):
            raise RuntimeError('Cannot read back manager startup parameters.')
        parameter_request = GetParameters.Request()
        parameter_request.names = ['autostart', 'bond_timeout', 'node_names']
        values = wait_future(parameters.call_async(parameter_request), process).values
        actual = {'autostart': values[0].bool_value,
                  'bond_timeout': values[1].double_value,
                  'node_names': list(values[2].string_array_value)}
        result['parameter_readback'] = actual
        if actual != {'autostart': False, 'bond_timeout': 0.0, 'node_names': [fixture_name]}:
            raise RuntimeError('Manager parameters differ from the controlled fixture.')
        request = ManageLifecycleNodes.Request()
        request.command = ManageLifecycleNodes.Request.STARTUP
        result['startup_rpc_calls'] += 1
        result['startup_request_steady'] = time.monotonic()
        response = wait_future(manage.call_async(request), process)
        result['startup_response_steady'] = time.monotonic()
        result['startup_success'] = bool(response.success)
    except Exception as error:
        result['error'] = str(error)
    finally:
        process_clean = finish_process(process)
        executor_clean = executor.shutdown(timeout_sec=6, wait_for_threads=True)
        spin_thread.join(timeout=2)
        fixture.destroy_node()
        controller.destroy_node()
        context.shutdown()
        if log_handle:
            log_handle.close()
        with lock:
            result['fixture'] = json.loads(json.dumps(state))
        result['cleanup_complete'] = process_clean and bool(executor_clean) and not spin_thread.is_alive()
        result['manager_exit_code'] = None if process is None else process.returncode

    log = (directory / 'manager.log').read_text() if (directory / 'manager.log').exists() else ''
    changes = result['fixture']['changes']
    queries = result['fixture']['queries']
    expected_success = name == 'patched_delay'
    expected_transitions = [1, 3] if expected_success else [1]
    expected_queries = 3 if expected_success else (2 if mode == 'persistent_timeout' else 1)
    checks = {
        'rpc_result_known': 'startup_success' in result,
        'rpc_result_expected': result.get('startup_success') == expected_success,
        'one_startup_rpc': result['startup_rpc_calls'] == 1,
        'no_transition_replay': [event['transition'] for event in changes] == expected_transitions,
        'all_transitions_succeeded': bool(changes) and all(event['success'] for event in changes),
        'query_count_expected': len(queries) == expected_queries,
        'first_real_callback_exceeded_two_seconds': bool(queries) and queries[0].get('measured_callback_seconds', 0) >= 2.3,
        'actual_library_bound': result.get('loaded_library') == inputs['expected_library'],
        'cleanup_complete': result['cleanup_complete'],
    }
    if expected_success:
        checks['second_query_before_first_response'] = len(queries) >= 2 and queries[1]['arrival_steady'] < queries[0].get('response_steady', 0)
        checks['second_query_not_delayed'] = len(queries) >= 2 and queries[1].get('measured_callback_seconds', 99) < .5
        checks['retry_log_and_active'] = 'attempt=1/2' in log and 'retry=true' in log and 'attempt=2/2' in log and 'Managed nodes are active' in log
        checks['no_abort_log'] = 'Aborting bringup' not in log
    else:
        checks['original_abort_path'] = (f'{fixture_name}/get_state service client: async_send_request failed.' in log
                                         and 'Aborting bringup' in log)
        if mode == 'persistent_timeout':
            checks['bounded_retry_log'] = 'attempt=2/2' in log and 'retry=false' in log
    result['checks'] = checks
    result['passed'] = not result.get('error') and all(checks.values())
    write_json(directory / 'result.json', result)
    print(f'{name}: {"PASS" if result["passed"] else "FAIL"}; transitions={expected_transitions} observed={[e["transition"] for e in changes]}; queries={len(queries)}', flush=True)
    domain_is_empty()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--domain', type=int, choices=[103], default=103)
    parser.add_argument('--output', type=Path)
    arguments = parser.parse_args()
    if not arguments.execute:
        parser.print_help()
        return 2
    if os.environ.get('ROS_DOMAIN_ID') != '103' or os.environ.get('ROS_LOCALHOST_ONLY') != '1':
        raise RuntimeError('Source fishbot_mujoco_env.sh with FISHBOT_MUJOCO_DOMAIN_ID=103 first.')
    if os.environ.get('ROS_STATIC_PEERS') or os.environ.get('ROS_AUTOMATIC_DISCOVERY_RANGE') != 'LOCALHOST':
        raise RuntimeError('Only localhost discovery without static peers is accepted.')
    output = (arguments.output or Path.home() / '.cache/fishbot/nav2-state-query-overlay' /
              time.strftime('fault-injection-%Y%m%d-%H%M%S')).resolve()
    if output == ROOT or ROOT in output.parents:
        raise RuntimeError('Save runtime evidence outside the repository.')
    output.mkdir(parents=True, exist_ok=False)
    prefix = Path(subprocess.check_output([str(TOOLS / 'fishbot_nav2_state_query_overlay.sh'), 'prefix'], text=True).strip())
    stock_executable = Path('/opt/ros/jazzy/lib/nav2_lifecycle_manager/lifecycle_manager')
    stock_library = Path('/opt/ros/jazzy/lib/libnav2_lifecycle_manager_core.so')
    patched_executable = prefix / 'lib/nav2_lifecycle_manager/lifecycle_manager'
    patched_library = prefix / 'lib/libnav2_lifecycle_manager_core.so'
    sources = {'patch': fingerprint(TOOLS / 'patches/nav2-1.3.13-state-query.patch'),
               'build_script': fingerprint(TOOLS / 'fishbot_nav2_state_query_overlay.sh'),
               'overlay_receipt': fingerprint(prefix.parent / 'receipt.json'),
               'stock_package': fingerprint('/opt/ros/jazzy/share/nav2_lifecycle_manager/package.xml')}
    results = []
    for name, executable, library, mode in [
        ('stock_delay', stock_executable, stock_library, 'first_timeout'),
        ('patched_delay', patched_executable, patched_library, 'first_timeout'),
        ('patched_persistent', patched_executable, patched_library, 'persistent_timeout')]:
        results.append(run_case(output, name, executable, library, mode))
    receipt = {'schema_version': 1, 'domain': 103, 'sources': sources, 'cases': results,
               'passed': len(results) == 3 and all(result['passed'] for result in results),
               'scope': 'Real lifecycle RPC fault injection; no navigation or original DDS root-cause claim.'}
    write_json(output / 'receipt.json', receipt)
    print(f'Receipt: {output / "receipt.json"}', flush=True)
    return 0 if receipt['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
