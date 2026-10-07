#!/usr/bin/env python3
"""Render recorded home-simulation observations and battery events as local HTML."""

from html import escape
import json
import math
from pathlib import Path

from fishbot_inspection_vision import _photo_url, _route_svg


def _text(value):
    if value is None:
        return '未记录'
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return escape(str(value), quote=True)


def _battery_svg(history):
    points = []
    if not isinstance(history, list):
        return ''
    for sample in history:
        try:
            stamp, soc = float(sample[0]), float(sample[1])
            if math.isfinite(stamp) and math.isfinite(soc) and 0 <= soc <= 1:
                points.append((stamp, soc))
        except (TypeError, ValueError, IndexError, KeyError):
            continue
    if len(points) < 2:
        return ''
    start, end = min(p[0] for p in points), max(p[0] for p in points)
    duration = max(end - start, .001)
    polyline = ' '.join(f'{40 + (stamp - start) / duration * 800:.2f},{165 - soc * 140:.2f}'
                        for stamp, soc in points)
    return (f'<svg viewBox="0 0 880 205" role="img" aria-label="记录的仿真电量变化">'
            '<path d="M40 25V165H840" fill="none" stroke="#8b99a9"/>'
            '<text x="3" y="30" font-size="12">100%</text><text x="15" y="169" font-size="12">0%</text>'
            f'<polyline points="{polyline}" fill="none" stroke="#247a63" stroke-width="3"/>'
            f'<text x="40" y="194" font-size="12">{start:.2f} 仿真秒</text>'
            f'<text x="700" y="194" font-size="12">{end:.2f} 仿真秒</text></svg>')


def save_home_report(report: dict, output_dir: Path) -> Path:
    """Write index.html without inferring missing mission or charging success.

    Expected keys: overall_status, task, plan, steps, events, trajectory,
    battery_history, recharge_cycles, final_stationary, elapsed_s and
    scene_provenance. Each step has observations; each observation may contain
    view_index, outcome, state, reason and three captured frame records.
    All user/data text is escaped. Images must be inside the output directory.
    """
    if not isinstance(report, dict):
        raise TypeError('report must be an object')
    for key in ('steps', 'events'):
        if not isinstance(report.get(key, []), list):
            raise TypeError(key + ' must be a list')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    labels = {'found': '已观察到', 'not_found': '标记区域内未找到',
              'unknown': '无法判断', 'failed': '失败', 'pending': '待执行'}
    cards, route_goals = [], []
    for index, step in enumerate(report.get('steps', []), 1):
        if not isinstance(step, dict):
            raise TypeError('each step must be an object')
        observations = step.get('observations', [])
        if not isinstance(observations, list):
            raise TypeError('step observations must be a list')
        state = step.get('outcome', 'pending')
        state = state if isinstance(state, str) and state in labels else 'unknown'
        views = []
        for observation in observations:
            if not isinstance(observation, dict):
                raise TypeError('each observation must be an object')
            view_index = observation.get('view_index')
            outcome = observation.get('outcome', 'unknown')
            photos = []
            frames = observation.get('frames', [])
            if not isinstance(frames, list):
                raise TypeError('observation frames must be a list')
            for number, frame in enumerate(frames, 1):
                if not isinstance(frame, dict):
                    raise TypeError('each frame must be an object')
                url = _photo_url(frame.get('photo'), output_dir)
                image = (f'<img src="{escape(url, quote=True)}" alt="第 {index} 站视角 {_text(view_index)} 第 {number} 帧">'
                         if url else '<p class="missing">无有效本地照片</p>')
                photos.append(f'''<figure>{image}<figcaption>第 {number} 帧 · {_text(frame.get('state'))}
<br>拍摄时间：{_text(frame.get('capture_stamp'))} 仿真秒
<details><summary>此帧证据与拍摄位姿</summary><pre>{_text({k: v for k, v in frame.items() if k != 'photo'})}</pre></details>
</figcaption></figure>''')
            if not photos:
                photos.append('<p class="missing">此视角没有保存图像，不能确认观察结果。</p>')
            views.append(f'''<section class="observation"><h3>视角 {_text(view_index)}：{_text(labels.get(outcome, outcome))}</h3>
<p>{_text(observation.get('reason'))}</p><div class="photos">{''.join(photos)}</div>
<details><summary>此视角动作与状态</summary><pre>{_text({k: v for k, v in observation.items() if k != 'frames'})}</pre></details></section>''')
        goal = step.get('goal')
        if goal is None and step.get('views'):
            goal = step['views'][0]
        if goal is not None:
            route_goals.append({'goal': goal})
        cards.append(f'''<article class="card"><div class="card-head"><h2>{index}. {_text(step.get('name', step.get('place_id')))}</h2>
<span class="badge {state}">{labels[state]}</span></div><p>{_text(step.get('question', step.get('target')))}</p>
<p class="meta">任务完成标记：{_text(step.get('completed'))} · 目标类型：{_text(step.get('target'))}</p>
{''.join(views) or '<p class="missing">尚无观察记录。</p>'}</article>''')
    events = []
    for event in report.get('events', []):
        if not isinstance(event, dict):
            raise TypeError('each event must be an object')
        details = {key: value for key, value in event.items() if key not in ('event', 'stamp', 'wall_elapsed')}
        events.append(f'''<li><strong>{_text(event.get('event'))}</strong>
<span class="meta"> · {_text(event.get('stamp'))} 仿真秒 · 墙钟经过 {_text(event.get('wall_elapsed'))} 秒</span>
<pre>{_text(details)}</pre></li>''')
    stationary = report.get('final_stationary')
    stop_ok = isinstance(stationary, dict) and stationary.get('verified') is True
    summary = f'''<section class="card"><h2>完成与电池证据</h2>
<p>任务状态：<strong>{_text(report.get('overall_status'))}</strong> · 耗时：{_text(report.get('elapsed_s'))} 秒
 · <span class="badge {'found' if stop_ok else 'failed'}">{'已验证停稳' if stop_ok else '停稳未验证'}</span></p>
{_battery_svg(report.get('battery_history'))}
<details><summary>充电循环、返航与最终停车记录</summary>
<pre>{_text({'recharge_cycles': report.get('recharge_cycles'), 'return_home': report.get('return_home'), 'final_stationary': stationary})}</pre></details>
</section>'''
    errors = ''
    if report.get('error') or report.get('cleanup_errors'):
        errors = f'<section class="errors"><h2>失败或收尾异常</h2><pre>{_text(report.get("error"))}</pre><pre>{_text(report.get("cleanup_errors"))}</pre></section>'
    overview = report.get('overview', 'overview.png')
    url = _photo_url(overview, output_dir)
    overview_html = ''
    if url and isinstance(overview, (str, Path)) and (output_dir / overview).is_file():
        overview_html = f'<section class="card"><h2>场景与地图来源</h2><img class="overview" src="{escape(url, quote=True)}" alt="场景概览"><pre>{_text(report.get("scene_provenance"))}</pre></section>'
    else:
        overview_html = f'<section class="card"><h2>场景与地图来源</h2><pre>{_text(report.get("scene_provenance"))}</pre></section>'
    route = _route_svg({'trajectory': report.get('trajectory'), 'stations': route_goals,
                        'return_home': report.get('return_home', {})})
    html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; style-src 'unsafe-inline'">
<title>FishBot 家庭场景仿真闭环</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f5f7;color:#172536;font:16px/1.6 system-ui,sans-serif}}
main{{max-width:1100px;margin:auto;padding:30px 22px}}h1{{font-size:28px;margin:0 0 10px}}h2{{font-size:21px;margin:0 0 12px}}h3{{font-size:17px;margin:10px 0}}
.scope,.meta{{color:#556678}}.card,.route{{background:white;border:1px solid #dce3e9;border-radius:12px;padding:20px;margin:18px 0}}
.card-head{{display:flex;justify-content:space-between;align-items:center;gap:15px;flex-wrap:wrap}}.card-head h2{{margin:0}}
.badge{{display:inline-block;padding:3px 10px;border-radius:20px;font-size:14px;background:#edf0f4;color:#445465}}
.found{{background:#dbf1e6;color:#185e3b}}.not_found{{background:#fff0cc;color:#795816}}.unknown,.failed{{background:#ffe4e1;color:#aa2925}}
.observation{{border-top:1px solid #e0e6eb;padding-top:8px;margin-top:16px}}.photos{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}}
figure{{margin:0;min-width:0}}img{{display:block;width:100%;height:auto;border-radius:6px}}figcaption{{font-size:13px;padding-top:6px;color:#526170}}
pre{{font:12px/1.55 ui-monospace,monospace;white-space:pre-wrap;overflow-wrap:anywhere;margin:5px 0}}
details{{font-size:14px;margin-top:10px}}summary{{cursor:pointer}}svg{{display:block;width:100%;height:auto}}.overview{{max-height:650px;object-fit:contain}}
.errors{{padding:20px;background:#ffe8e4;border-left:4px solid #b5332b}}.missing{{padding:15px;background:#f0f2f5;color:#5d6a7a}}
.timeline{{padding-left:24px}}.timeline li{{padding:8px 0;border-bottom:1px solid #e5e9ee}}
@media(max-width:650px){{main{{padding:18px 12px}}.card{{padding:15px}}.photos{{grid-template-columns:1fr}}h1{{font-size:24px}}}}
</style></head><body><main><h1>FishBot 家庭场景仿真闭环</h1>
<p><strong>指令：</strong>{_text(report.get('task'))}</p>
<p class="scope">受限中文地点语法；蓝框合成目标的 RGB 像素识别。电池、返航和充电均为仿真验证。未知区域补全属于场景假设，不代表实测住宅结构或实车验收。</p>
{errors}{summary}{overview_html}{route}{''.join(cards)}
<section class="card"><h2>任务、电池与充电事件时间线</h2><ol class="timeline">{''.join(events) or '<li>未记录事件。</li>'}</ol></section>
<details><summary>解析后的受限任务计划</summary><pre>{_text(report.get('plan'))}</pre></details>
</main></body></html>'''
    path = output_dir / 'index.html'
    path.write_text(html, encoding='utf-8')
    return path
