#!/usr/bin/env python3
"""Compare existing simulation evidence; never run ROS or apply a candidate."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time

from recursia_verdict import verdict

ROOT = Path(__file__).resolve().parents[1]
MUJOCO = 'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/'
ORACLES = ('tools/fishbot_simulation_report.py', 'tools/config/fishbot_model_geometry.yaml',
           'tools/fishbot_passage_sim.launch.py', MUJOCO+'mjcf/passage.xml',
           MUJOCO+'mjcf/fishbot.xml', MUJOCO+'mjcf/arena.xml', MUJOCO+'config/plugins.yaml',
           MUJOCO+'launch/sim.launch.py')
CORE_SOURCES = (*ORACLES, 'tools/fishbot_simulation_suite.py',
                'tools/fishbot_passage_goal.py',
                'tools/fishbot_sim_scan_relay.py', 'tools/config/fishbot_passage_nav.yaml',
                'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/scripts/verify_stack.py',
                'workspaces/fishbot_mujoco_ws/src/fishbot_mujoco/scripts/wait_ready.py')
RUNTIME_FIELDS = {'command_returncode', 'cancel_trigger', 'cancel_sent_while_moving', 'interrupted'}
SHA = re.compile(r'^[0-9a-f]{64}$')
REVISION = re.compile(r'^[0-9a-f]{40}$')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError('Duplicate JSON key: '+key)
        result[key] = value
    return result


def load(path):
    path = Path(path)
    if path.stat().st_size > 64*1024**2:
        raise ValueError('JSON input exceeds 64 MiB: '+str(path))
    return json.loads(path.read_text(), object_pairs_hook=_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON: '+value)))


def safe_output(path, value):
    """Exclusive creation protects previous evidence and private runtime paths."""
    path = Path(path).resolve()
    if path.is_relative_to(ROOT):
        raise ValueError('Runtime evidence output must be outside the source repository')
    with path.open('x', encoding='utf-8') as stream:
        import os
        os.chmod(path, 0o600)
        stream.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def canonical(value):
    """Preserve JSON value types: bool/int equality cannot weaken frozen inputs."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def validate_panel(panel):
    if not isinstance(panel, dict) or panel.get('schema_version') != 1:
        raise ValueError('Selection panel schema_version must be 1')
    if not isinstance(panel.get('panel_id'), str) or not panel['panel_id'].strip():
        raise ValueError('Selection panel needs a panel_id')
    if panel.get('mode') not in ('suite', 'random') or type(panel.get('seed')) is not int:
        raise ValueError('Panel requires suite/random mode and integer seed; soak is not a paired panel')
    cases = panel.get('cases')
    if not isinstance(cases, list) or not 1 <= len(cases) <= 200:
        raise ValueError('Panel requires 1 to 200 predeclared cases')
    names = []
    for item in cases:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not item['name']:
            raise ValueError('Each panel case needs a name')
        inputs, budget = item.get('inputs'), item.get('budget')
        if (not isinstance(inputs, dict) or inputs.get('name') != item['name']
                or inputs.get('kind') not in ('navigation', 'route', 'scan_gap', 'cancel', 'motion')
                or inputs.get('domain') != (96 if panel['mode'] == 'suite' else 102)
                or RUNTIME_FIELDS.intersection(inputs)):
            raise ValueError('Panel inputs must be full declared isolated case inputs: '+item['name'])
        if panel['mode'] == 'random' and type(inputs.get('seed')) is not int:
            raise ValueError('Random panel case needs its realized scene seed')
        if (not isinstance(budget, dict)
                or not {'startup_timeout_s', 'command_timeout_s', 'command_watchdog_s', 'startup_max_retries'} <= budget.keys()
                or any(not _finite(value) or value < 0 for key, value in budget.items()
                       if not (key == 'command_timeout_s' and value is None))):
            raise ValueError('Panel case needs explicit nonnegative execution budget: '+item['name'])
        names.append(item['name'])
    if len(set(names)) != len(names):
        raise ValueError('Panel case names must be unique')
    sources = panel.get('source_files')
    required = set(CORE_SOURCES)
    if panel['mode'] == 'random':
        required.add('tools/fishbot_simulation_campaign.py')
    if (not isinstance(sources, list) or any(not isinstance(path, str) or not path
            or Path(path).is_absolute() or '..' in Path(path).parts for path in sources)
            or len(set(sources)) != len(sources) or not required <= set(sources)):
        raise ValueError('Panel source_files must include the existing runner, oracle, geometry and behavior sources')
    thresholds = panel.get('thresholds')
    if (not isinstance(thresholds, dict) or type(thresholds.get('min_new_successes')) is not int
            or thresholds['min_new_successes'] < 1 or type(thresholds.get('max_lost_successes')) is not int
            or thresholds['max_lost_successes'] != 0):
        raise ValueError('Require min_new_successes >=1 and max_lost_successes=0')
    return panel


def snapshot(panel_path, source_root, report_path, phase, before_path=None):
    """Observe actual source boundaries. These receipts are evidence, not signatures."""
    # The before boundary starts before source reads. Filesystem mtimes may lag
    # the wall clock by a scheduler tick; taking it after all reads is too late.
    began_wall_ns = time.time_ns()
    panel = validate_panel(load(panel_path))
    source_root, report_path = Path(source_root).resolve(), Path(report_path).resolve()
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=source_root, capture_output=True,
                              text=True, check=True).stdout.strip()
    if not REVISION.fullmatch(revision):
        raise ValueError('Source checkout needs a concrete Git revision')
    hashes = {}
    for relative in panel['source_files']:
        path = (source_root/relative).resolve()
        if not path.is_relative_to(source_root) or not path.is_file():
            raise ValueError('Source path missing or escapes checkout: '+relative)
        hashes[relative] = digest(path)
    result = dict(schema_version=1, producer='fishbot_stack_gate.snapshot/1', phase=phase,
                  observed_wall_ns=began_wall_ns if phase == 'before' else time.time_ns(),
                  panel_sha256=digest(panel_path),
                  report_path=str(report_path), source_root=str(source_root),
                  source_revision=revision, source_sha256=hashes)
    if phase == 'before':
        if report_path.exists() or before_path:
            raise ValueError('Before snapshot requires a new absent report path and no --before')
        result['report_was_absent'] = True
    elif phase == 'after':
        if not before_path or not report_path.is_file():
            raise ValueError('After snapshot requires completed report and --before receipt')
        before = load(before_path)
        if (not isinstance(before, dict) or before.get('phase') != 'before' or before.get('report_path') != str(report_path)
                or before.get('panel_sha256') != result['panel_sha256']):
            raise ValueError('Before receipt does not bind this panel and report')
        result.update(before_sha256=digest(before_path), report_sha256=digest(report_path),
                      report_mtime_ns=report_path.stat().st_mtime_ns)
    else:
        raise ValueError('Unknown snapshot phase')
    return result


def report_cases(report, panel, label, reasons):
    raw = report.get('cases')
    if not isinstance(raw, list):
        raise ValueError(label+' report needs cases list')
    names = [case.get('name') for case in raw if isinstance(case, dict)]
    if len(names) != len(raw) or any(not isinstance(name, str) for name in names) or len(set(names)) != len(names):
        raise ValueError(label+' report cases need unique string names')
    wanted = {case['name'] for case in panel['cases']}
    if set(names) != wanted or type(report.get('case_count')) is not int or report['case_count'] != len(wanted):
        reasons.append(label+': incomplete or extra cases compared with frozen panel')
    if report.get('status') not in ('passed', 'failed'):
        reasons.append(label+': report is not a completed run')
    elif report['status'] != ('passed' if raw and all(case.get('passed') is True for case in raw) else 'failed'):
        reasons.append(label+': overall status inconsistent with original cases')
    if type(report.get('seed')) is not int or report['seed'] != panel['seed'] or report.get('mode', 'suite') != panel['mode']:
        reasons.append(label+': run seed/mode differs from panel')
    if report.get('domain') != (96 if panel['mode'] == 'suite' else 102):
        reasons.append(label+': run domain differs from isolated panel')
    indexed = {case['name']: case for case in raw}
    outcomes = {}
    for item in panel['cases']:
        case = indexed.get(item['name'])
        if case is None:
            outcomes[item['name']] = None
            continue
        inputs = case.get('case')
        if (not isinstance(inputs, dict)
                or canonical({k: v for k, v in inputs.items() if k not in RUNTIME_FIELDS}) != canonical(item['inputs'])):
            reasons.append(label+': realized inputs differ for '+item['name'])
        if canonical(case.get('execution_budget')) != canonical(item['budget']):
            reasons.append(label+': execution budget unverified for '+item['name'])
        checks = case.get('checks')
        states = [value.get('status') for value in checks.values() if isinstance(value, dict)] if isinstance(checks, dict) else []
        valid = (bool(states) and len(states) == len(checks)
                 and all('evidence' in value for value in checks.values())
                 and all(state in ('passed', 'failed', 'unknown') for state in states))
        expected = valid and all(state == 'passed' for state in states)
        if not valid or 'unknown' in states:
            reasons.append(label+': missing/unknown original checks for '+item['name'])
            outcomes[item['name']] = None
        elif (type(case.get('passed')) is not bool or case['passed'] != expected
              or case.get('status') != ('passed' if expected else 'failed')):
            reasons.append(label+': original case verdict inconsistent for '+item['name'])
            outcomes[item['name']] = None
        else:
            outcomes[item['name']] = expected
        if not isinstance(case.get('execution'), dict) or case['execution'].get('cleanup_complete') is not True:
            reasons.append(label+': owned execution cleanup unverified for '+item['name'])
    if (type(report.get('passed_count')) is not int
            or report['passed_count'] != sum(case.get('passed') is True for case in raw)):
        reasons.append(label+': original passed_count inconsistent')
    return outcomes


def receipt_check(report, report_path, panel_path, panel, before_path, after_path, label, reasons):
    if not before_path or not after_path:
        reasons.append(label+': no before/after source and selection freeze receipts (legacy diagnostic only)')
        return None
    before, after = load(before_path), load(after_path)
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError(label+': boundary receipts must be JSON objects')
    for phase, receipt in (('before', before), ('after', after)):
        if (receipt.get('schema_version') != 1 or receipt.get('producer') != 'fishbot_stack_gate.snapshot/1'
                or receipt.get('phase') != phase or receipt.get('panel_sha256') != digest(panel_path)
                or receipt.get('report_path') != str(Path(report_path).resolve())
                or type(receipt.get('observed_wall_ns')) is not int):
            reasons.append(label+': '+phase+' receipt does not bind panel/run')
    if (before.get('report_was_absent') is not True or after.get('before_sha256') != digest(before_path)
            or after.get('report_sha256') != digest(report_path)
            or after.get('report_mtime_ns') != Path(report_path).stat().st_mtime_ns
            or type(before.get('observed_wall_ns')) is not int or type(after.get('observed_wall_ns')) is not int
            or after['observed_wall_ns'] <= before['observed_wall_ns']
            or not before['observed_wall_ns'] <= Path(report_path).stat().st_mtime_ns <= after['observed_wall_ns']):
        reasons.append(label+': before/after chronology or actual report hash unverified')
    hashes = before.get('source_sha256')
    if (not isinstance(hashes, dict) or set(hashes) != set(panel['source_files'])
            or any(not isinstance(value, str) or not SHA.fullmatch(value) for value in hashes.values())
            or hashes != after.get('source_sha256')
            or before.get('source_root') != after.get('source_root')
            or not isinstance(before.get('source_revision'), str) or not REVISION.fullmatch(before['source_revision'])
            or before.get('source_revision') != after.get('source_revision')
            or before.get('source_revision') != report.get('source_revision')):
        reasons.append(label+': executed source boundary changed or is incomplete')
        return None
    reported = report.get('source_sha256')
    if (not isinstance(reported, dict) or not set(CORE_SOURCES) <= reported.keys()
            or any(hashes.get(key) != value for key, value in reported.items())):
        reasons.append(label+': runner source receipt does not match observed snapshot')
    return hashes


def compare(panel_path, parent_path, candidate_path, receipts=None):
    panel = validate_panel(load(panel_path))
    parent, candidate = load(parent_path), load(candidate_path)
    if not isinstance(parent, dict) or not isinstance(candidate, dict):
        raise ValueError('Reports must be JSON objects')
    reasons = []
    outcomes = [report_cases(report, panel, label, reasons)
                for report, label in ((parent, 'parent'), (candidate, 'candidate'))]
    for name in {case['name'] for case in panel['cases']}:
        paired = [next((case for case in report['cases'] if case['name'] == name), {})
                  for report in (parent, candidate)]
        if all(isinstance(case.get('checks'), dict) for case in paired) and set(paired[0]['checks']) != set(paired[1]['checks']):
            reasons.append('Original check set differs between parent and candidate: '+name)
    receipts = receipts or {}
    hashes = [receipt_check(report, path, panel_path, panel,
                receipts.get(label+'_before'), receipts.get(label+'_after'), label, reasons)
              for report, path, label in ((parent, parent_path, 'parent'), (candidate, candidate_path, 'candidate'))]
    if all(hashes):
        for path in ORACLES:
            if hashes[0][path] != hashes[1][path]:
                reasons.append('Candidate changed immutable original oracle/geometry: '+path)
    comparable = {name for name in outcomes[0] if all(type(result[name]) is bool for result in outcomes)}
    original = verdict({name: {'success': outcomes[0][name]} for name in sorted(comparable)},
                       {name: {'success': outcomes[1][name]} for name in sorted(comparable)}, failure_class=None)
    if len(comparable) != len(panel['cases']):
        reasons.append('Every declared case must have known paired original verdicts')
    if len(original['gained_tasks']) < panel['thresholds']['min_new_successes']:
        reasons.append('Insufficient new actual task successes')
    if original['regressed_tasks']:
        reasons.append('An original successful case was lost')
    accepted = not reasons and original['accepted']
    return dict(schema_version=1, mechanism='Recursia-inspired paired evidence gate',
                gate_accepted=accepted, mode='admissible_comparison' if accepted else 'rejected_diagnostic',
                panel_id=panel['panel_id'], panel_sha256=digest(panel_path),
                parent_report_sha256=digest(parent_path), candidate_report_sha256=digest(candidate_path),
                declared_case_count=len(panel['cases']), known_pair_count=len(comparable),
                parent_success_count=sum(value is True for value in outcomes[0].values()),
                candidate_success_count=sum(value is True for value in outcomes[1].values()),
                original_verdict=original, rejection_reasons=reasons,
                source_boundary_receipts_present=all(hashes),
                stage_progress='diagnostic only; not task success', applied=False,
                limitations=['Local receipts are observations, not cryptographic attestations.',
                             'Source hashes are observed before and after; continuous immutability is not proved.',
                             'Declared source boundaries do not attest every installed native binary or dependency.',
                             'No live process, ROS domain, physics, threshold or candidate source is modified.',
                             'Public Recursia simulation runtime is not deployed.'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    gate = commands.add_parser('compare', help='read reports; missing freeze evidence rejects promotion')
    gate.add_argument('--panel', type=Path, required=True)
    gate.add_argument('--parent', type=Path, required=True)
    gate.add_argument('--candidate', type=Path, required=True)
    gate.add_argument('--output', type=Path, required=True)
    for label in ('parent', 'candidate'):
        for phase in ('before', 'after'):
            gate.add_argument('--'+label+'-'+phase, type=Path)
    observe = commands.add_parser('snapshot', help='observe source and frozen selection before/after existing runner')
    observe.add_argument('--panel', type=Path, required=True)
    observe.add_argument('--source-root', type=Path, default=ROOT)
    observe.add_argument('--report', type=Path, required=True)
    observe.add_argument('--phase', choices=('before', 'after'), required=True)
    observe.add_argument('--before', type=Path)
    observe.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'compare':
            names = [label+'_'+phase for label in ('parent', 'candidate') for phase in ('before', 'after')]
            receipt_paths = {name: getattr(args, name) for name in names}
            if any(receipt_paths.values()) and not all(receipt_paths.values()):
                raise ValueError('Supply all four source boundary receipts, or none for legacy diagnostic')
            result = compare(args.panel, args.parent, args.candidate, receipt_paths)
            code = 0 if result['gate_accepted'] else 1
        else:
            result = snapshot(args.panel, args.source_root, args.report, args.phase, args.before)
            code = 0
        safe_output(args.output, result)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return code
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(json.dumps({'error': str(exc), 'gate_accepted': False, 'applied': False}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
