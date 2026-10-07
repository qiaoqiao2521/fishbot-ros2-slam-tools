#!/usr/bin/env python3
"""Classify blue inspection panels from RGB pixels and render local reports.

This recognizer is deliberately scoped to the virtual inspection scene. It
does not accept expected states, scene objects, ROS messages, or world poses.
"""

from html import escape
import json
import math
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import numpy as np
from PIL import Image


def _components(mask):
    """Yield pixel count and exclusive bounding box for each connected region."""
    remaining = mask.copy()
    height, width = mask.shape
    for y, x in zip(*np.nonzero(mask)):
        if not remaining[y, x]:
            continue
        remaining[y, x] = False
        pending = [(int(y), int(x))]
        count, x0, y0, x1, y1 = 0, int(x), int(y), int(x), int(y)
        while pending:
            cy, cx = pending.pop()
            count += 1
            x0, y0, x1, y1 = min(x0, cx), min(y0, cy), max(x1, cx), max(y1, cy)
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < height and 0 <= nx < width and remaining[ny, nx]:
                    remaining[ny, nx] = False
                    pending.append((ny, nx))
        yield count, (x0, y0, x1 + 1, y1 + 1)


def _enclosed_pixels(frame):
    """Find non-blue pixels sealed off from the bounding-box boundary."""
    outside = np.zeros(frame.shape, dtype=bool)
    height, width = frame.shape
    pending = []
    for y, x in ([(0, x) for x in range(width)] + [(height - 1, x) for x in range(width)]
                 + [(y, 0) for y in range(height)] + [(y, width - 1) for y in range(height)]):
        if not frame[y, x] and not outside[y, x]:
            outside[y, x] = True
            pending.append((y, x))
    while pending:
        y, x = pending.pop()
        for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
            if 0 <= ny < height and 0 <= nx < width and not frame[ny, nx] and not outside[ny, nx]:
                outside[ny, nx] = True
                pending.append((ny, nx))
    return ~frame & ~outside


def analyze_rgb(rgb: np.ndarray) -> dict:
    """Return green/red/empty/unknown with pixel evidence from uint8 RGB only.

    Invalid array types, channel counts, and empty images raise explicit errors.
    An absent, clipped, tiny, ambiguous, or nonstandard panel returns unknown.
    Bounding boxes use original image coordinates and exclusive right/bottom.
    """
    if not isinstance(rgb, np.ndarray):
        raise TypeError('rgb must be a numpy array')
    if rgb.dtype != np.uint8:
        raise TypeError('rgb must have dtype uint8')
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError('rgb must have shape H x W x 3')
    height, width = rgb.shape[:2]
    if height == 0 or width == 0:
        raise ValueError('rgb must not be empty')
    scale = min(1.0, 640.0 / max(height, width))
    small = np.asarray(Image.fromarray(rgb).resize(
        (max(1, round(width * scale)), max(1, round(height * scale))),
        Image.Resampling.NEAREST)) if scale < 1 else rgb
    sh, sw = small.shape[:2]
    pixels = small.astype(np.float32)
    red, green, blue = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    blue_mask = (blue >= 65) & (blue >= 1.45 * red) & (blue >= 1.25 * green)
    evidence = {'image_size': [width, height], 'analysis_size': [sw, sh],
                'blue_pixels': int(blue_mask.sum()), 'visible_blue_frame': False,
                'bbox': None, 'roi_bbox': None, 'candidate_count': 0}

    def result(state, reason):
        return {'state': state, 'reason': reason, 'evidence': evidence}

    def original_box(box):
        return [int(round(box[0] * width / sw)), int(round(box[1] * height / sh)),
                int(round(box[2] * width / sw)), int(round(box[3] * height / sh))]

    if min(sh, sw) < 24:
        return result('unknown', 'image too small to verify a panel')
    candidates = []
    for count, box in _components(blue_mask):
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        if min(bw, bh) < 24 or not 0.4 <= bw / bh <= 2.5:
            continue
        if x0 == 0 or y0 == 0 or x1 == sw or y1 == sh:
            continue
        if not 0.04 <= count / (bw * bh) <= 0.70:
            continue
        frame = blue_mask[y0:y1, x0:x1]
        tx, ty = max(2, round(bw * 0.22)), max(2, round(bh * 0.22))
        sides = [float(frame[:ty].any(axis=0).mean()),
                 float(frame[-ty:].any(axis=0).mean()),
                 float(frame[:, :tx].any(axis=1).mean()),
                 float(frame[:, -tx:].any(axis=1).mean())]
        if min(sides) < 0.65:
            continue
        interior = _enclosed_pixels(frame)
        iy, ix = np.nonzero(interior)
        if len(ix) < bw * bh * 0.20:
            continue
        rx0, ry0, rx1, ry1 = int(ix.min()), int(iy.min()), int(ix.max()) + 1, int(iy.max()) + 1
        roi_box = (x0 + rx0, y0 + ry0, x0 + rx1, y0 + ry1)
        roi = pixels[roi_box[1]:roi_box[3], roi_box[0]:roi_box[2]]
        interior = interior[ry0:ry1, rx0:rx1]
        dark_fraction = float((roi.max(axis=2)[interior] <= 65).mean())
        if dark_fraction < 0.40:
            continue
        candidates.append((box, roi_box, roi, interior, sides, dark_fraction))
    evidence['candidate_count'] = len(candidates)
    if not candidates:
        return result('unknown', 'no complete, sufficiently large blue frame with a dark inner panel')
    if len(candidates) != 1:
        return result('unknown', 'multiple visible panels; target is ambiguous')
    box, roi_box, roi, interior, sides, dark_fraction = candidates[0]
    evidence.update({'visible_blue_frame': True, 'bbox': original_box(box),
                     'roi_bbox': original_box(roi_box), 'frame_side_coverage': sides,
                     'dark_fraction': dark_fraction, 'roi_pixels': int(interior.sum())})
    r, g, b = roi[:, :, 0], roi[:, :, 1], roi[:, :, 2]
    red_mask = interior & (r >= 70) & (r >= 1.6 * g) & (r >= 1.5 * b)
    green_mask = interior & (g >= 65) & (g >= 1.5 * r) & (g >= 1.25 * b)
    red_count, green_count = int(red_mask.sum()), int(green_mask.sum())
    red_largest = max((c for c, _ in _components(red_mask)), default=0)
    green_largest = max((c for c, _ in _components(green_mask)), default=0)
    minimum_lamp = max(9, math.ceil(evidence['roi_pixels'] * 0.006))
    evidence.update({'red_pixels': red_count, 'green_pixels': green_count,
                     'red_largest_component': red_largest,
                     'green_largest_component': green_largest,
                     'minimum_lamp_pixels': minimum_lamp,
                     'other_bright_pixels': int((interior & (roi.max(axis=2) > 65)
                                                & ~red_mask & ~green_mask).sum())})
    red_present, green_present = red_largest >= minimum_lamp, green_largest >= minimum_lamp
    if red_present and green_present:
        return result('unknown', 'both red and green indicators are visible')
    if red_present and green_count < 3:
        return result('red', 'red indicator inside the verified panel')
    if green_present and red_count < 3:
        return result('green', 'green indicator inside the verified panel')
    if red_count >= 3 or green_count >= 3:
        return result('unknown', 'indicator is too small, fragmented, or has conflicting colors')
    if dark_fraction >= 0.90 and evidence['other_bright_pixels'] < 3:
        return result('empty', 'complete blue frame and dark inner panel; no visible indicator')
    return result('unknown', 'panel interior is not dark enough to confirm an empty position')


def _photo_url(value, output_dir):
    """Allow local report images only, with no traversal or remote URL."""
    if not isinstance(value, (str, Path)) or not str(value):
        return None
    raw = str(value)
    if '\\' in raw or '\x00' in raw or ':' in raw or '?' in raw or '#' in raw:
        return None
    photo = Path(raw)
    if photo.is_absolute():
        try:
            raw = str(photo.resolve().relative_to(output_dir.resolve()))
        except ValueError:
            return None
    parts = PurePosixPath(raw).parts
    if not parts or '..' in parts or raw.startswith('//'):
        return None
    if (output_dir / raw).resolve().is_relative_to(output_dir.resolve()):
        return quote(raw, safe='/')
    return None


def _route_svg(report):
    """Plot recorded simulation samples only; never invent a missing route."""
    def xy(value, offset=0):
        try:
            point = float(value[offset]), float(value[offset + 1])
            return point if all(math.isfinite(v) for v in point) else None
        except (TypeError, ValueError, IndexError, KeyError):
            return None

    raw = report.get('trajectory', [])
    if not isinstance(raw, list):
        return ''
    points = [point for item in raw if (point := xy(item, 1)) is not None]
    if len(points) < 2:
        return ''
    markers = []
    for index, station in enumerate(report.get('stations', []), 1):
        point = xy(station.get('goal')) if isinstance(station, dict) else None
        if point is not None:
            markers.append((str(index), point))
    home = report.get('return_home', {})
    point = xy(home.get('goal')) if isinstance(home, dict) else None
    if point is not None:
        markers.append(('家', point))
    all_points = points + [point for _, point in markers]
    x0, x1 = min(p[0] for p in all_points) - .2, max(p[0] for p in all_points) + .2
    y0, y1 = min(p[1] for p in all_points) - .2, max(p[1] for p in all_points) + .2
    scale = min(800 / (x1 - x0), 230 / (y1 - y0))
    left, top = (880 - (x1 - x0) * scale) / 2, (290 - (y1 - y0) * scale) / 2

    def screen(point):
        return left + (point[0] - x0) * scale, top + (y1 - point[1]) * scale

    polyline = ' '.join(f'{x:.2f},{y:.2f}' for x, y in map(screen, points))
    labels = []
    for label, point in markers:
        x, y = screen(point)
        labels.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="10" fill="white" stroke="#354b64"/>'
                      f'<text x="{x:.2f}" y="{y + 4:.2f}" text-anchor="middle" font-size="12">{escape(label)}</text>')
    end_x, end_y = screen(points[-1])
    return (f'<section class="route"><h2>已记录的仿真轨迹</h2>'
            f'<svg viewBox="0 0 880 310" role="img" aria-label="仿真运动轨迹与工位目标">'
            f'<polyline points="{polyline}" fill="none" stroke="#2863ab" stroke-width="3"/>'
            + ''.join(labels)
            + f'<circle cx="{end_x:.2f}" cy="{end_y:.2f}" r="4" fill="#bc312b"/>'
            f'<text x="20" y="304" font-size="12" fill="#526170">'
            f'蓝线：已记录轨迹；红点：末次位置；数字：工位目标；家：返航目标。'
            f'X {x0:.2f}…{x1:.2f} m / Y {y0:.2f}…{y1:.2f} m</text></svg></section>')


def save_report(report: dict, output_dir: Path) -> Path:
    """Write index.html from stations and overall_status/elapsed_s metadata.

    Each station may provide name, question, state, photo, capture_stamp, pose,
    action, reason, and evidence. Return-home, stop, and error evidence is shown.
    All supplied text is escaped. Photos must be
    relative to output_dir, or absolute files contained within that directory.
    """
    if not isinstance(report, dict) or not isinstance(report.get('stations', []), list):
        raise TypeError('report must be a dict containing a stations list')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    labels = {'green': '绿灯', 'red': '红灯', 'empty': '空位', 'unknown': '无法判断'}
    descriptions = {'green': '观察到绿色指示灯。', 'red': '观察到红色指示灯。',
                    'empty': '工位边框和内部清晰可见，没有亮起的指示灯。',
                    'unknown': '当前图像不足以确认工位状态。'}

    def text(value):
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        return escape(str(value) if value is not None else '未记录', quote=True)

    cards = []
    for index, station in enumerate(report.get('stations', []), 1):
        if not isinstance(station, dict):
            raise TypeError('each station must be a dict')
        name = text(station.get('name', f'工位 {index}'))
        state = station.get('state', 'unknown')
        safe_state = state if isinstance(state, str) and state in labels else 'unknown'
        photo = _photo_url(station.get('photo'), output_dir)
        photo_html = (f'<img src="{escape(photo, quote=True)}" alt="{name} 的巡检照片">'
                      if photo else '<div class="missing">未提供有效的本地照片</div>')
        stamp = station.get('capture_stamp')
        stamp_label = f'{stamp:.3f}' if isinstance(stamp, (int, float)) and math.isfinite(stamp) else stamp
        cards.append(f'''<article class="card">
<div class="card-head"><h2>{name}</h2><span class="badge {safe_state}">{labels[safe_state]}</span></div>
<p class="question">{text(station.get('question', '查看工位指示状态'))}</p>
{photo_html}
<p>{descriptions[safe_state]}</p>
<dl><dt>拍摄时间（仿真秒）</dt><dd>{text(stamp_label)}</dd></dl>
<details><summary>位置、动作和图像判断证据</summary><dl>
<dt>拍摄位置</dt><dd><pre>{text(station.get('pose'))}</pre></dd>
<dt>执行动作</dt><dd><pre>{text(station.get('action'))}</pre></dd></dl>
<p>{text(station.get('reason', ''))}</p><pre>{text(station.get('evidence', {}))}</pre></details>
</article>''')
    overall = report.get('overall_status', report.get('overall', report.get('status', '未记录')))
    overall_label = {'completed': '已完成', 'completed_with_unknown': '已返回，部分观察无法判断',
                     'failed': '未完成', 'interrupted': '已中断', 'running': '进行中'}.get(str(overall), overall)
    elapsed = report.get('elapsed_s', report.get('elapsed'))
    home = report.get('return_home', {})
    home = home if isinstance(home, dict) else {}
    stopped = report.get('final_stationary', {})
    stopped = stopped if isinstance(stopped, dict) else {}
    home_ok, stopped_ok = home.get('completed') is True, stopped.get('verified') is True
    home_label = '已完成' if home_ok else '未完成或未验证'
    stopped_label = '已验证停稳' if stopped_ok else '停稳未验证'
    errors = ''
    if report.get('error') or report.get('cleanup_errors'):
        errors = (f'<div class="errors"><h2>运行失败或收尾异常</h2>'
                  f'<pre>{text(report.get("error", ""))}</pre>'
                  f'<pre>{text(report.get("cleanup_errors", []))}</pre></div>')
    completion = f'''<section class="completion"><h2>返航与停止验收</h2>
<p><span class="badge {'green' if home_ok else 'red'}">返航：{home_label}</span>
<span class="badge {'green' if stopped_ok else 'red'}">{stopped_label}</span></p>
<details><summary>返航和停车证据</summary><dl>
<dt>返航动作</dt><dd><pre>{text(home.get('action'))}</pre></dd>
<dt>返航实际位置误差</dt><dd><pre>{text(home.get('physical_error'))}</pre></dd>
<dt>最终停稳反馈</dt><dd><pre>{text(stopped or None)}</pre></dd></dl></details></section>'''
    title = text(report.get('title', 'FishBot 虚拟视觉巡检'))
    html = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; style-src 'unsafe-inline'">
<title>{title}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f6f8;color:#17212b;font:16px/1.6 system-ui,sans-serif}}
main{{max-width:1180px;margin:auto;padding:36px 24px}}header{{margin-bottom:28px}}h1{{font-size:30px;margin:0 0 8px}}
.subtitle{{color:#516274;margin:0}}.summary{{display:flex;gap:24px;flex-wrap:wrap;margin-top:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px}}
.route,.completion{{background:white;border:1px solid #dce3ea;border-radius:14px;padding:18px;margin-bottom:20px}}
.route svg{{display:block;width:100%;height:auto}}.errors{{background:#ffe9e6;border-left:4px solid #b82b24;padding:18px;margin-bottom:20px}}
.card{{background:white;border:1px solid #dce3ea;border-radius:14px;padding:18px;min-width:0}}
.card-head{{display:flex;align-items:center;justify-content:space-between;gap:12px}}h2{{font-size:20px;margin:0}}
.badge{{border-radius:30px;padding:3px 11px;font-size:14px;white-space:nowrap;background:#eef1f5;color:#48596a}}
.green{{background:#e0f3e8;color:#126138}}.red{{background:#ffe4e3;color:#ad2622}}.empty{{background:#fff1cd;color:#775400}}
.question{{color:#516274}}img{{display:block;width:100%;height:auto;border-radius:8px;background:#e7edf2}}
.missing{{padding:50px 14px;text-align:center;background:#eef1f5;color:#607080;border-radius:8px}}
dl{{font-size:14px}}dt{{font-weight:600;margin-top:10px}}dd{{margin:2px 0 0;color:#526170}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.5 ui-monospace,monospace;margin:4px 0}}
details{{border-top:1px solid #e7edf2;padding-top:12px;font-size:14px}}summary{{cursor:pointer}}
footer{{color:#607080;font-size:13px;margin-top:24px}}
</style></head><body><main><header><h1>{title}</h1>
<p class="subtitle">RGB 图像判断 · MuJoCo 虚拟工位 · 每站保留照片与判断证据</p>
<div class="summary"><span>整体状态：<strong>{text(overall_label)}</strong></span>
<span>总耗时：<strong>{text(elapsed)}</strong> 秒</span><span>工位数：{len(cards)}</span></div></header>
{errors}{completion}
<section class="grid">{''.join(cards)}</section>
{_route_svg(report)}
<footer>“空位”仅在蓝框和黑色内板可见时成立。仿真巡检结果不代表实车验收。</footer>
</main></body></html>'''
    path = output_dir / 'index.html'
    path.write_text(html, encoding='utf-8')
    return path
