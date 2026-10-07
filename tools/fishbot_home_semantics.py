#!/usr/bin/env python3
"""Bounded Chinese tasks and RGB-only active observation for a synthetic home.

This is a named-place grammar and a blue-marker visual rule, not general natural
language understanding or general object recognition. No ROS or scene state is
read here. Battery interruption and physical navigation belong to the runner.
"""

import copy
import math
import re

import numpy as np

from fishbot_inspection_vision import analyze_rgb, _components


TARGETS = ('red_box', 'indicator')
GRAMMAR = 'named_places_zh_v1'


class TaskParseError(ValueError):
    """The task or semantic-place configuration is outside the declared grammar."""


def _places(semantic):
    if not isinstance(semantic, dict) or not isinstance(semantic.get('places'), dict):
        raise TaskParseError('semantic must contain a places object')
    result, names = {}, {}
    for place_id, source in semantic['places'].items():
        if not isinstance(place_id, str) or not place_id or not isinstance(source, dict):
            raise TaskParseError('each place needs a nonempty string id and an object')
        if source.get('id', place_id) != place_id:
            raise TaskParseError('place id must agree with its places key')
        name = source.get('name')
        aliases = source.get('aliases', [])
        if not isinstance(name, str) or not name.strip() or not isinstance(aliases, list):
            raise TaskParseError('each place needs a name and an aliases list')
        if source.get('target') not in TARGETS:
            raise TaskParseError('place target must be red_box or indicator')
        views = source.get('views')
        if not isinstance(views, list) or not 1 <= len(views) <= 3:
            raise TaskParseError('each place needs one to three observation views')
        normalized = []
        for pose in views:
            if (not isinstance(pose, (list, tuple)) or len(pose) != 3
                    or any(isinstance(v, bool) or not isinstance(v, (int, float))
                           or not math.isfinite(v) for v in pose)):
                raise TaskParseError('each view must be finite [x, y, yaw]')
            normalized.append([float(v) for v in pose])
        if len({tuple(view) for view in normalized}) != len(normalized):
            raise TaskParseError('candidate observation views must be distinct')
        result[place_id] = {'place_id': place_id, 'name': name.strip(),
                            'views': normalized, 'target': source['target'],
                            'question': source.get('question')}
        for alias in [name, place_id, *aliases]:
            if not isinstance(alias, str) or not alias.strip():
                raise TaskParseError('place aliases must be nonempty strings')
            alias = re.sub(r'\s+', '', alias)
            if alias in names and names[alias] != place_id:
                raise TaskParseError('a place alias identifies more than one place')
            names[alias] = place_id
    if not result:
        raise TaskParseError('at least one named place is required')
    return result, names


def parse_task(command: str, semantic: dict) -> dict:
    """Parse ordered, explicit requests such as the example below.

    去工具架找红色盒子，看看门口指示灯，然后回来

    Supported targets: 红色盒子/红盒子/红盒 and 指示灯/指示灯状态/灯状态.
    Clauses use 去/到 + place + 找/看看, or 看看 + place + target.
    Commas, semicolons, 然后, 再, 接着 and 最后 separate clauses. A final
    回来/回家/返回/返回起点 requests return home. Unconsumed text is rejected.
    """
    if not isinstance(command, str) or not command.strip():
        raise TaskParseError('task must be a nonempty string')
    places, aliases = _places(semantic)
    text = re.sub(r'\s+', '', command).strip('。.!！')
    if text.startswith('请'):
        text = text[1:]
    clauses = [part for part in re.split(r'[，,；;]|然后|接着|最后|再', text) if part]
    if not clauses:
        raise TaskParseError('task has no supported observation clause')
    patterns = (
        (r'(?:去|到)?(.+?)(?:找|寻找)(红色盒子|红盒子|红盒)', 'red_box'),
        (r'(?:去|到)(.+?)(?:看看|查看|检查|看)(指示灯状态|指示灯|灯状态)', 'indicator'),
        (r'(?:看看|查看|检查|看)(.+?)(?:的)?(指示灯状态|指示灯|灯状态)', 'indicator'),
    )
    steps, return_home = [], False
    for index, clause in enumerate(clauses):
        if clause in ('回来', '回家', '返回', '返回起点'):
            if index != len(clauses) - 1 or not steps:
                raise TaskParseError('return home must follow all observation clauses')
            return_home = True
            continue
        matched = None
        for pattern, target in patterns:
            match = re.fullmatch(pattern, clause)
            if match:
                place_alias = match.group(1).removesuffix('的')
                if place_alias not in aliases:
                    raise TaskParseError('unknown named place: ' + place_alias)
                place = places[aliases[place_alias]]
                question = ('蓝框标记区域里有红色盒子吗？' if target == 'red_box'
                            else '蓝框标记区域里的指示灯是什么状态？')
                matched = {'step_id': f'step-{len(steps) + 1}',
                           'place_id': place['place_id'], 'name': place['name'],
                           'target': target, 'question': question,
                           'views': copy.deepcopy(place['views']), 'source_clause': clause}
                break
        if matched is None:
            raise TaskParseError('unsupported task clause or target: ' + clause)
        steps.append(matched)
    if not steps or len(steps) > 12:
        raise TaskParseError('task must contain one to twelve observations')
    return {'grammar': GRAMMAR, 'command': command, 'steps': steps,
            'return_home': return_home,
            'scope': 'fixed Chinese named-place grammar; synthetic blue-marker RGB recognition'}


def analyze_observation(rgb: np.ndarray, target: str) -> dict:
    """Classify actual RGB for a requested target; never accept expected labels.

    red_box additionally requires a filled rectangular red component. A red
    circular lamp is therefore not called a box. Absence only describes the
    verified marked region, not the entire room or hidden space.
    """
    if target not in TARGETS:
        raise ValueError('unsupported visual target; choose red_box or indicator')
    result = analyze_rgb(rgb)
    result['evidence'] = dict(result['evidence'])
    result['target'] = target
    result['recognizer'] = 'synthetic_blue_marker_rgb_v1'
    state = result['state']
    if state == 'unknown':
        result['outcome'] = 'unknown'
        return result
    if target == 'indicator':
        result['outcome'] = 'found'
        return result
    if state in ('empty', 'green'):
        result['outcome'] = 'not_found'
        result['reason'] = 'verified marked region contains no detected red box; hidden space is not assessed'
        return result
    x0, y0, x1, y1 = result['evidence']['roi_bbox']
    region = rgb[y0:y1, x0:x1].astype(np.float32)
    r, g, b = region[:, :, 0], region[:, :, 1], region[:, :, 2]
    red_mask = (r >= 70) & (r >= 1.6 * g) & (r >= 1.5 * b)
    components = list(_components(red_mask))
    if not components:
        result.update(outcome='unknown', reason='red component cannot be verified at original resolution')
        return result
    count, box = max(components, key=lambda item: item[0])
    bx0, by0, bx1, by1 = box
    width, height = bx1 - bx0, by1 - by0
    fill = count / (width * height)
    result['evidence'].update({'red_object_bbox': [x0 + bx0, y0 + by0, x0 + bx1, y0 + by1],
                               'red_object_fill': fill, 'red_object_aspect': width / height})
    if min(width, height) >= 6 and 0.4 <= width / height <= 2.5 and fill >= 0.88:
        result.update(outcome='found', reason='filled red rectangular target inside the verified synthetic blue marker')
    else:
        result.update(outcome='unknown', reason='red color is visible but rectangular box shape is not established')
    return result


def next_observation(step: dict, observations: list, max_views: int = 3) -> dict:
    """Choose a deterministic untried view or return a terminal task result.

    The runner supplies one record per completed capture, after three-frame
    consensus. A low-battery navigation interruption adds no observation; the
    same view is selected after resume. No navigation or commands occur here.
    """
    if not isinstance(max_views, int) or isinstance(max_views, bool) or not 1 <= max_views <= 3:
        raise ValueError('max_views must be an integer from one to three')
    if not isinstance(step, dict) or not isinstance(step.get('views'), list) or not step['views']:
        raise ValueError('step must contain observation views')
    if not isinstance(observations, list):
        raise TypeError('observations must be a list')
    limit = min(max_views, len(step['views']))
    used = set()
    for record in observations:
        if not isinstance(record, dict):
            raise ValueError('each observation must be an object')
        index = record.get('view_index')
        if (not isinstance(index, int) or isinstance(index, bool)
                or not 0 <= index < limit or index in used):
            raise ValueError('observation view indices must be unique and within the bound')
        used.add(index)
        outcome = record.get('outcome')
        if outcome not in ('found', 'not_found', 'unknown'):
            raise ValueError('observation outcome must be found, not_found, or unknown')
        if outcome in ('found', 'not_found'):
            frames = record.get('frames')
            if (not isinstance(frames, list) or len(frames) != 3
                    or any(not isinstance(frame, dict) or frame.get('outcome') != outcome
                           or frame.get('state') != record.get('state') for frame in frames)):
                return {'status': 'failed', 'view_index': index,
                        'reason': 'terminal observation lacks three agreeing RGB frame results'}
            return {'status': 'complete' if outcome == 'found' else 'not_found',
                    'view_index': index, 'reason': record.get('reason', outcome)}
    for index in range(limit):
        if index not in used:
            return {'status': 'observe', 'view_index': index,
                    'view': copy.deepcopy(step['views'][index]),
                    'reason': 'initial view' if not used else 'previous view was unknown; try another viewpoint'}
    return {'status': 'failed', 'view_index': None,
            'reason': 'all bounded views remain unknown; absence cannot be claimed'}
