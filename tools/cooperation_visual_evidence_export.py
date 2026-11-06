#!/usr/bin/env python3
"""Project recorded visual delivery evidence; never render physics or rescore.

Only RGB-D observations feed the model evidence section. Recorded truth is read
separately for milestone display, not supplied back to perception or control.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

from cooperation_timing import import_run, number, obj, read_json
from cooperation_comparison import project_case

SCHEMA = 'fishbot.visual-chain.v1'
DEPTH_RANGE_M = (.05, 1.5)


def json_lines(path, warnings):
    if path is None or not Path(path).is_file():
        return []
    rows = []
    try:
        with Path(path).open() as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        rows.append(row)
                except ValueError:
                    warnings.append(f'{Path(path).name}: malformed line skipped')
    except OSError as error:
        warnings.append(f'{Path(path).name}: {type(error).__name__}')
    return rows


def safe_name(value):
    return re.sub(r'[^A-Za-z0-9_.-]', '_', str(value))[:180] or 'unknown'


def camera_candidate(selected, camera):
    """Convert only the actually selected pose, not the highest scoring guess."""
    import numpy as np
    matrix = np.asarray(camera.get('T_station_camera'), dtype=float)
    pose = np.asarray(selected.get('pose_station'), dtype=float)
    if matrix.shape != (4, 4) or pose.shape != (4, 4) or not np.isfinite([matrix, pose]).all():
        raise ValueError('selected pose or camera transform is not finite 4x4')
    result = np.linalg.inv(matrix) @ pose
    row = obj(selected.get('selected'))
    return {'index': row.get('index'), 'score': number(row.get('score')),
            'origin': row.get('origin'), 'pose_camera': result.tolist(),
            'frame': camera.get('frame_id'), 'score_is_success_probability': False}


def save_depth(source, output):
    """Fixed optical-Z meter legend; never normalize to this frame's extrema."""
    import numpy as np
    from PIL import Image, ImageDraw
    depth = np.load(source, allow_pickle=False)
    if depth.ndim != 2:
        raise ValueError('depth must be a 2D optical-Z array')
    valid = np.isfinite(depth) & (depth >= DEPTH_RANGE_M[0]) & (depth <= DEPTH_RANGE_M[1])
    value = np.clip(np.nan_to_num((depth-DEPTH_RANGE_M[0])/(DEPTH_RANGE_M[1]-DEPTH_RANGE_M[0])), 0., 1.)
    rgb = np.stack([value, 1.-np.abs(2.*value-1.), 1.-value], axis=-1)
    rgb[~valid] = 0
    image = Image.fromarray(np.uint8(rgb*255))
    canvas = Image.new('RGB', (max(image.width, 320), image.height+32), '#ffffff')
    canvas.paste(image, (0, 0))
    ImageDraw.Draw(canvas).text((5, image.height+7), 'Optical Z: 0.05 .. 1.50 m; invalid=black', fill='#172d44')
    canvas.save(output)
    return {'kind': 'optical_z_m', 'min_m': .05, 'max_m': 1.5, 'invalid': 'black',
            'per_frame_normalization': False}


def save_overlay(rgb, selected, camera, output):
    import numpy as np
    from PIL import Image, ImageDraw
    pose = np.asarray(selected['pose_camera'], dtype=float)
    K = np.asarray(camera['k'], dtype=float).reshape(3, 3)
    if not np.isfinite(K).all():
        raise ValueError('camera intrinsics are not finite')
    points = [pose[:3, 3], *[pose[:3, 3]+pose[:3, i]*.04 for i in range(3)]]
    def pixel(point):
        if point[2] <= .001:
            return None
        p = K @ point
        return tuple(float(value) for value in p[:2]/p[2])
    projected = [pixel(point) for point in points]
    image = Image.open(rgb).convert('RGB'); draw = ImageDraw.Draw(image)
    origin = projected[0]
    if origin is None:
        raise ValueError('selected candidate is behind the optical camera')
    for endpoint, color in zip(projected[1:], ('#f04e4e', '#39c67b', '#4998ff')):
        if endpoint is not None:
            draw.line([origin, endpoint], fill=color, width=3)
    # A 4 cm symbolic grasp span illustrates the selected frame, not a new
    # candidate or a claim about the physical SO101 aperture.
    jaw = [pixel(pose[:3, 3]+pose[:3, 0]*v) for v in (-.02, .02)]
    if all(p is not None for p in jaw):
        draw.line(jaw, fill='#ffd23f', width=3)
    draw.ellipse((origin[0]-4, origin[1]-4, origin[0]+4, origin[1]+4), outline='#ffffff', width=2)
    draw.text((6, 6), f"Selected #{selected['index']}; score is not probability", fill='#ffd23f', stroke_width=1, stroke_fill='#172d44')
    image.save(output)


def read_queries(observations, warnings):
    queries = []
    for folder in sorted((observations/'query-receipts').glob('*')):
        if not folder.is_dir():
            continue
        events = json_lines(folder/'stages.jsonl', warnings)
        cleanup = read_json(folder/'cleanup.json', []) if (folder/'cleanup.json').exists() else {}
        started = next((row for row in events if row.get('stage') == 'query_started'), {})
        queries.append({'id': started.get('query_id', folder.name),
            'stages': [{k: row.get(k) for k in ('stage', 'elapsed_wall_s', 'elapsed_stage_wall_s', 'error_type', 'candidate_index', 'phase') if k in row} for row in events],
            'outcome': cleanup.get('outcome', 'deadline_observed' if any(r.get('stage') == 'query_deadline_reached' for r in events) else 'not_observed'),
            'timeout_s': number(started.get('wall_budget_s')),
            'arm_id': started.get('arm_id'), 'cargo_id': started.get('cargo_id'),
            'episode_id': started.get('episode_id'), 'source_sequence': started.get('source_sequence')})
    return queries


def bound_case(observation, cases):
    matches = [case for case in cases if case.get('episode_id') == observation.get('episode_id')
        and case.get('entity_binding', {}).get('cargo_id') == observation.get('cargo_id')
        and observation.get('arm_id') in (case.get('entity_binding', {}).get('pickup_arm_id'),
                                        case.get('entity_binding', {}).get('unload_arm_id'))]
    return matches[0] if len(matches) == 1 else None


def original_gate(run, case, phase, milestone, warnings):
    """Read the selected named attempt's gate; never borrow the primary alias."""
    index = case.get('_order_index')
    if index is None:
        return {}, None
    scores = sorted((run/f'order-{index}'/'observer').glob('score-*.json'))
    for path in reversed(scores):
        score = read_json(path, warnings)
        named = obj(score.get('business_delivery_acceptance')).get('attempts', [])
        matches = [r for r in named if r.get('task_id') == case['task_id']
                   and obj(r.get('business_delivery')).get('cargo_id') == case['entity_binding'].get('cargo_id')]
        if len(matches) == 1:
            attempt = matches[0]
            if phase == 'load':
                load = obj(attempt.get('original_k_load_and_transport'))
                key = 'actual_lift_and_two_tip_forces' if milestone == 'lift' else 'released_full_footprint_supported_and_relative_rest'
                gate = obj(load.get(key))
                if number(gate.get('first_pass_stamp')) is None:
                    # Delivery-prefix gates can be empty before arrival. Display the
                    # same named attempt's original pickup observations separately.
                    deliveries = obj(attempt.get('task_delivery_acceptance')).get('attempts', [])
                    same_episode = [row for row in deliveries if row.get('task_id') == case['task_id']
                        and row.get('episode_id') == case.get('episode_id') and case.get('episode_id')]
                    observed = obj(obj(attempt.get('phase_evidence')).get('pickup_and_transport_observed'))
                    if len(same_episode) == 1 and number(obj(observed.get(key)).get('first_pass_stamp')) is not None:
                        return {**obj(observed.get(key)), 'evidence_scope': 'original_named_attempt_pickup_observed_not_delivery_success'}, number(observed.get('cargo_baseline_z_m'))
                return gate, number(load.get('cargo_baseline_z_m'))
            key = 'physical_unload_lift' if milestone == 'lift' else 'shelf_home_rest_through_cleanup'
            return obj(attempt.get(key)), None
        if not case.get('named_entities'):
            attempts = [r for r in score.get('full_attempts', []) if r.get('task_id') == case['task_id']]
            if len(attempts) == 1:
                attempt = attempts[0]
                key = 'actual_lift_and_two_tip_forces' if milestone == 'lift' else 'released_full_footprint_supported_and_relative_rest'
                return obj(attempt.get(key)), number(attempt.get('cargo_baseline_z_m'))
    return {}, None


def milestone(run, case, projection, observation, phase, kind, index, overview, folder, url, warnings):
    gate, baseline = original_gate(run, case, phase, kind, warnings)
    target = number(gate.get('first_pass_stamp'))
    if not gate or target is None:
        warnings.append(f'{kind}: original task-bound physical gate missing or not passed')
        return None
    labels = ({'arm_lift', 'arm_transport'} if kind == 'lift' else {'arm_release', 'arm_retreat', 'cargo_settle', 'arm_home'}) if phase == 'load' else ({'unload_grasp', 'unload_transport'} if kind == 'lift' else {'unload_transport', 'unloaded', 'completed'})
    spans = [s for s in case['spans'] if s.get('label') in labels and number(s.get('start_source_s')) is not None and number(s.get('end_source_s')) is not None]
    frames = [row for row in index if obj(row.get('metadata')).get('episode_id') == observation.get('episode_id')
        and number(obj(row.get('metadata')).get('stamp')) is not None
        and number(observation.get('stamp')) is not None
        and obj(row.get('metadata'))['stamp'] >= max(number(observation.get('stamp')), target)
        and obj(row.get('metadata'))['stamp'] - target <= 1.0
        and any(s['start_source_s'] <= obj(row['metadata'])['stamp'] <= s['end_source_s'] for s in spans)]
    selected = min(frames, key=lambda r: abs(obj(r['metadata'])['stamp']-target)) if frames else None
    image = None
    actual_stamp = obj(selected.get('metadata')).get('stamp') if selected else target
    if selected and overview and Path(overview).is_file():
        try:
            destination = folder/(kind+'.jpg')
            subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y', '-i', str(overview),
                '-vf', f"select=eq(n\\,{int(selected['video_frame'])})", '-vsync', '0', '-frames:v', '1', str(destination)],
                check=True, timeout=45, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            image = url+destination.name
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            warnings.append(f'{kind}: actual overview extraction failed ({type(error).__name__})')
    else:
        warnings.append(f'{kind}: no actual overview frame inside the task-bound observed stage')
    points = projection.get('frames', [])
    observed = number(observation.get('stamp'))
    before = min(points, key=lambda p: abs(p['source_s']-observed)) if points and observed is not None else None
    after = min(points, key=lambda p: abs(p['source_s']-actual_stamp)) if points else None
    if baseline is None and before and before.get('cargo'):
        baseline = number(before['cargo'][2])
    measured = (number(after['cargo'][2])-baseline if after and after.get('cargo') and baseline is not None else None)
    value = {'source_s': actual_stamp, 'gate_source_s': target, 'image': image,
             'original_passed': gate.get('passed') if isinstance(gate.get('passed'), bool) else None,
             'source': 'existing task-bound physical oracle; image selected from actual sampled overview',
             'original_gate_scope': gate.get('evidence_scope', 'original_task_bound_gate'),
             'image_max_gate_source_delta_s': 1.0,
             'image_gate_source_delta_s': actual_stamp-target if selected else None,
             'video_frame': selected.get('video_frame') if selected else None}
    if kind == 'lift':
        value['measured_lift_m'] = measured
        value['measurement_basis'] = 'recorded cargo Z minus original/observation baseline; not a new physical score'
    return value


def export(run, observations, output, *, overview=None, frame_index=None, public_prefix='/workbench/visual-chain/'):
    run, output = Path(run).resolve(), Path(output).resolve()
    warnings = []
    if output == run or run in output.parents:
        raise ValueError('export output must be outside original run')
    output.mkdir(parents=True, exist_ok=True)
    manifest = read_json(run/'manifest-used.json', warnings)
    observations = Path(observations) if observations else Path(obj(manifest.get('pretrained_grasp')).get('output_directory', run/'missing-observations'))
    report = import_run(run, output/'timing-import')
    frame_rows = json_lines(frame_index, warnings)
    cases = report['cases']; projections = {}
    for i, case in enumerate(cases, 1):
        case['_order_index'] = i
        stream = output/'timing-import'/case['trajectory']['stream_ref']
        points = (json.loads(line) for line in stream.open()) if stream.is_file() else []
        projections[case['id']] = project_case(case, points, label=case['label'], manifest=manifest)
    entries = []
    for source in sorted(observations.glob('*/observation.json')):
        item_warnings = []
        observation = read_json(source, item_warnings); camera = read_json(source.parent/'camera.json', item_warnings)
        identifier = safe_name(source.parent.name); folder = output/identifier; folder.mkdir(exist_ok=True)
        url = public_prefix.rstrip('/')+'/'+identifier+'/'
        case = bound_case(observation, cases)
        if case is None:
            item_warnings.append('No unique original task matches episode, arm and cargo; milestones remain unknown')
        phase = 'load' if observation.get('arm_id') == (case['entity_binding'].get('pickup_arm_id') if case else 'load') else 'unload'
        images = {key: None for key in ('rgb', 'depth', 'mask', 'grasp_overlay')}
        for key in ('rgb', 'mask'):
            path = source.parent/(key+'.png')
            if path.is_file():
                try:
                    shutil.copyfile(path, folder/path.name); images[key] = url+path.name
                except OSError as error:
                    item_warnings.append(f'{key}: original copy failed ({type(error).__name__})')
            else:
                item_warnings.append(f'{key}: original PNG missing')
        depth_legend = None
        try:
            depth_legend = save_depth(source.parent/'depth.npy', folder/'depth.png'); images['depth'] = url+'depth.png'
        except (ImportError, OSError, ValueError) as error:
            item_warnings.append(f'depth: {type(error).__name__}')
        cloud = {'frame': observation.get('frame'), 'xyz': [], 'source_point_count': observation.get('point_count')}
        try:
            import numpy as np
            points = np.load(source.parent/'points.npy', allow_pickle=False)
            valid = points.ndim == 2 and points.shape[1] == 3 and np.isfinite(points).all()
            if valid:
                stride = max(1, math.ceil(len(points)/2048))
                cloud.update(xyz=points[::stride].tolist(), display_subsample_stride=stride)
            else:
                item_warnings.append('points: invalid XYZ; no synthetic cloud substituted')
        except (ImportError, OSError, ValueError) as error:
            item_warnings.append(f'points: {type(error).__name__}')
        candidate = None
        selected = read_json(source.parent/'selected-candidate.json', []) if (source.parent/'selected-candidate.json').is_file() else {}
        if selected:
            try:
                identity = obj(selected.get('observation'))
                if not identity or any(identity.get(k) != observation.get(k) for k in ('episode_id', 'sequence', 'arm_id', 'cargo_id')):
                    raise ValueError('selected candidate receipt does not match observation identity')
                candidate = camera_candidate(selected, camera)
                if images['rgb']:
                    save_overlay(source.parent/'rgb.png', candidate, camera, folder/'grasp-overlay.png'); images['grasp_overlay'] = url+'grasp-overlay.png'
            except (ImportError, KeyError, TypeError, ValueError, OSError) as error:
                item_warnings.append(f'selected candidate projection: {type(error).__name__}')
        else:
            item_warnings.append('Selected-candidate receipt missing; highest score not substituted')
        inference_path = source.parent/'inference/report.json'
        inference = read_json(inference_path, []) if inference_path.is_file() else {}
        source_report = None
        if inference:
            try:
                shutil.copyfile(inference_path, folder/'model-report.json'); source_report = url+'model-report.json'
            except OSError as error:
                item_warnings.append(f'model report: copy failed ({type(error).__name__})')
        else:
            item_warnings.append('Actual inference report missing; model loading does not prove inference')
        milestones = {kind: milestone(run, case, projections[case['id']], observation, phase, kind, frame_rows,
            overview, folder, url, item_warnings) if case else None for kind in ('lift', 'placement')}
        entries.append({'id': identifier, 'task_id': case.get('task_id') if case else None,
            'arm_id': observation.get('arm_id'), 'cargo_id': observation.get('cargo_id'), 'phase': phase,
            'observation': observation, 'images': images, 'depth_legend': depth_legend, 'points': cloud,
            'selected': candidate, 'inference': {'status': inference.get('status', 'not_observed'),
                'request_wall_s': number(inference.get('inference_request_wall_s')) if inference.get('inference_runtime') != 'standalone_cuda' else number(inference.get('inference_s')),
                'total_s': number(inference.get('elapsed_s')), 'candidate_count': inference.get('candidate_count'),
                'source_report': source_report}, 'milestones': milestones,
            'task_original_passed': case['original_verdict'].get('original_score_passed') if case else None,
            'warnings': list(dict.fromkeys(item_warnings))})
    if not entries:
        warnings.append('No recorded RGB-D observation directories found; visual chain is empty, not passed')
    value = {'schema': SCHEMA, 'run_id': report['source_run_id'], 'scene_id': manifest.get('factory_delivery', {}).get('id'),
             'new_execution': False, 'rescored': False, 'entries': entries,
             'queries': read_queries(observations, warnings), 'warnings': list(dict.fromkeys(warnings)),
             'scope': 'actual recorded observations; model scores are not success probabilities; milestones use independent original scores'}
    (output/'visual-chain.json').write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=Path)
    parser.add_argument('--observations', type=Path)
    parser.add_argument('--overview', type=Path)
    parser.add_argument('--frame-index', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--public-prefix', default='/workbench/visual-chain/')
    args = parser.parse_args(argv)
    value = export(args.run, args.observations, args.output, overview=args.overview,
                   frame_index=args.frame_index, public_prefix=args.public_prefix)
    print(json.dumps({'output': str(args.output/'visual-chain.json'), 'entries': len(value['entries']),
                      'queries': len(value['queries']), 'warnings': value['warnings']}))


if __name__ == '__main__':
    main()
