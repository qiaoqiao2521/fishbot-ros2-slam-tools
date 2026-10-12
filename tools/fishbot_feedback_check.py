"""Run existing feedback regressions without creating ROS nodes or installing tools."""
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
PYTHON_GROUPS = {
    'control': tuple(ROOT / 'tools/tests' / name for name in (
        'test_command_guard.py', 'test_passage_goal.py', 'test_passage_config.py',
        'test_passage_replay.py', 'test_passage_timing_tree.py',
        'test_sim_scan_relay.py', 'test_simulation_suite.py', 'test_simulation_report.py')),
    'mission': (ROOT / 'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/tests'
                / 'test_mission_bridge.py',),
}


def exit_status(groups):
    if any(group['status'] == 'failed' for group in groups):
        return 1
    return 0 if groups and all(group['status'] == 'passed' for group in groups) else 2


def python_group(name):
    suite = unittest.TestSuite()
    missing, import_errors = [], []
    output = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        for index, path in enumerate(PYTHON_GROUPS[name]):
            try:
                spec = importlib.util.spec_from_file_location(f'feedback_{name}_{index}', path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
            except ModuleNotFoundError as exc:
                missing.append({'file': str(path.relative_to(ROOT)), 'dependency': exc.name})
            except Exception as exc:
                import_errors.append({'file': str(path.relative_to(ROOT)), 'error': str(exc)})
        result = unittest.TextTestRunner(stream=output, verbosity=1).run(suite)
    skipped = [{'test': test.id(), 'reason': reason} for test, reason in result.skipped]
    failures = [{'test': test.id(), 'error': detail[-4000:]}
                for test, detail in result.failures + result.errors]
    status = ('failed' if failures or import_errors else
              'partial' if skipped or missing or not result.testsRun else 'passed')
    return {'group': name, 'status': status, 'tests_run': result.testsRun,
            'skipped': skipped, 'missing_dependencies': missing,
            'failures': failures, 'import_errors': import_errors,
            'output': output.getvalue()[-6000:]}


def run_python(name):
    # Setup affects this child process only. These tests never initialize ROS.
    setup = Path('/opt/ros/jazzy/setup.bash')
    command = ['/usr/bin/python3', '-B', str(Path(__file__).resolve()), '--python-group', name]
    if setup.is_file():
        shell = '''set -e
source /opt/ros/jazzy/setup.bash
if [[ "$1" == mission && -d "${FISHBOT_MUJOCO_RUNTIME:-$2/workspaces/fishbot_mujoco_ws/.runtime}/opt/ros/jazzy" ]]; then
    source "$2/tools/fishbot_mujoco_env.sh"
fi
exec /usr/bin/python3 -B "$2/tools/fishbot_feedback_check.py" --python-group "$1"
'''
        command = ['bash', '-c', shell, 'fishbot-feedback', name, str(ROOT)]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        report = json.loads(result.stdout)
        if result.returncode != exit_status([report]):
            raise ValueError('group exit status does not match its report')
        return report
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {'group': name, 'status': 'failed', 'error': str(exc),
                'output': result.stderr[-4000:] if 'result' in locals() else ''}


def frontend_group():
    directory = ROOT / 'apps/fishbot-control-station/frontend'
    npm = shutil.which('npm')
    missing = ([] if npm else ['npm'])
    if not (directory / 'node_modules/.bin/vitest').is_file():
        missing.append('existing frontend node_modules/.bin/vitest')
    if missing:
        return {'group': 'frontend', 'status': 'partial', 'missing_dependencies': missing}
    with tempfile.TemporaryDirectory(prefix='fishbot-feedback-vitest-') as temporary:
        output_file = Path(temporary) / 'result.json'
        command = [npm, 'test', '--', 'src/lib/simulation.test.ts',
                   '--reporter=json', '--outputFile=' + str(output_file)]
        try:
            result = subprocess.run(command, cwd=directory, capture_output=True,
                                    text=True, timeout=120)
            data = json.loads(output_file.read_text()) if output_file.is_file() else {}
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            return {'group': 'frontend', 'status': 'failed', 'error': str(exc)}
    tests = data.get('numTotalTests', 0)
    skipped = data.get('numPendingTests', 0) + data.get('numTodoTests', 0)
    status = ('failed' if result.returncode or not data.get('success') else
              'partial' if skipped or not tests else 'passed')
    return {'group': 'frontend', 'status': status, 'tests_run': tests,
            'passed': data.get('numPassedTests', 0), 'skipped_count': skipped,
            'failed_count': data.get('numFailedTests', 0),
            'output': (result.stdout + result.stderr)[-4000:]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-group', choices=PYTHON_GROUPS, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.python_group:
        report = python_group(args.python_group)
        print(json.dumps(report, ensure_ascii=False))
        return exit_status([report])
    groups = [run_python(name) for name in PYTHON_GROUPS]
    groups.append(frontend_group())
    code = exit_status(groups)
    print(json.dumps({'status': {0: 'passed', 1: 'failed', 2: 'partial'}[code],
                      'scope': 'offline regression; no physical simulation or hardware acceptance',
                      'groups': groups}, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
