#!/usr/bin/env python3
"""Inject RGB-only pretrained inference into the existing inspection mission."""
import argparse
import hashlib
from concurrent.futures import ThreadPoolExecutor
from html import escape
import json
import os
from pathlib import Path
import select
import subprocess
import sys

from fishbot_inspection import main as inspection_main, fresh
from fishbot_inspection_vision import _photo_url, _route_svg


def aggregate(frames, station):
    """Only model detections vote. A miss remains unknown, never asserted absence."""
    label=station['label']
    votes=sum(any(d['label']==label for d in f['evidence']['detections']) for f in frames)
    return dict(state='present' if votes>=2 else 'unknown',label=label,votes=votes,
                reason=f'{label}: {votes}/{len(frames)} fresh frames contain a model detection')


def all_frames(station):
    return station.get('frames',[])+station.get('alternate_view',{}).get('frames',[])


def verify_age_evidence(evidence):
    """Recompute recorded ages within each clock domain, using the original limit."""
    try:
        import math
        source,stamp=evidence['source_clock_s'],evidence['source_stamp_s']
        received,steady=evidence['received_steady_time'],evidence['capture_steady_time']
        return (evidence['limit_s']==.6 and evidence['min_source_age_s']==-.05
                and fresh(stamp,received,source,steady)
                and math.isclose(evidence['source_age_s'],source-stamp,abs_tol=1e-9)
                and math.isclose(evidence['receipt_age_s'],steady-received,abs_tol=1e-9))
    except (KeyError,TypeError,ValueError):
        return False


def score_fixture(report):
    """Post-hoc fixture acceptance; these expectations never enter the detector."""
    stations={s['name']:s for s in report.get('stations',[])}
    checks={'source_unchanged':report.get('runtime_provenance',{}).get('source_unchanged') is True,
            'fixture_unchanged':report.get('fixture_provenance',{}).get('files_match_recorded_sha256') is True,
            'mission_completed':report.get('overall_status') in ('completed','completed_with_unknown')
            and not report.get('cleanup_errors')}
    for name in ('cup','laptop'):
        station=stations.get(name,{})
        checks[name+'_detected']=station.get('state')=='present' and aggregate(
            station.get('frames',[]),{'label':name})['state']=='present'
    hidden=stations.get('occluded-cup',{})
    checks['occluded_primary_unknown']=hidden.get('primary_state',hidden.get('state'))=='unknown'
    alternate=hidden.get('alternate_view',{})
    checks['alternate_view_recovers']=alternate.get('state')=='present' and aggregate(
        alternate.get('frames',[]),{'label':'cup'})['state']=='present'
    absent=stations.get('absent-cup',{})
    checks['absent_not_hallucinated']=bool(all_frames(absent)) and absent.get('state')=='unknown' and not any(
        d['label']=='cup' for f in all_frames(absent) for d in f['evidence']['detections'])
    checks['navigation_and_return']=len(stations)==4 and all(
        s.get('action',{}).get('status')==4 and s.get('stationary',{}).get('verified') is True
        for s in stations.values()) and report.get('return_home',{}).get('completed') is True
    checks['all_views_recorded']=len(stations)==4 and all(len(s.get('frames',[]))==3 for s in stations.values()) and all(
        len(stations.get(name,{}).get('alternate_view',{}).get('frames',[]))==3
        and stations[name]['alternate_view'].get('action',{}).get('status')==4
        and stations[name]['alternate_view'].get('stationary',{}).get('verified') is True
        for name in ('occluded-cup','absent-cup'))
    frames=[f for s in stations.values() for f in all_frames(s)]
    checks['all_capture_ages_fresh']=len(frames)==18 and all(
        verify_age_evidence(f.get('capture_freshness',{})) for f in frames)
    checks['model_inputs_match_captures']=len(frames)==18 and all(
        isinstance(f.get('sha256'),str) and len(f['sha256'])==64
        and f['evidence'].get('input_sha256')==f['sha256'] for f in frames)
    checks['fresh_final_stop']=all(verify_age_evidence(report.get('final_stationary',{}).get(key,{}))
                                   for key in ('truth_freshness','odom_freshness'))
    checks['final_stop']=report.get('final_stationary',{}).get('verified') is True
    return dict(checks=checks,passed=all(checks.values()),
        scope='Synthetic fixture scoring; no claim that a visual miss proves physical absence.')


def save_report(report, output):
    sections=[]
    for station in report.get('stations',[]):
        pictures=[]
        for frame in all_frames(station):
            photo=_photo_url(frame['photo'],output)
            if photo is None or not (output/frame['photo']).is_file():
                raise ValueError('Report frame must reference an existing local capture')
            evidence=frame['evidence'];w,h=evidence['width'],evidence['height']
            boxes=[]
            for d in evidence['detections']:
                x0,y0,x1,y1=d['xyxy'];label=escape(f'{d["label"]} {d["confidence"]:.2f}')
                boxes.append(f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="none" stroke="#f4c542" stroke-width="2"/>'
                    f'<text x="{x0}" y="{max(15,y0-5)}" fill="#f4c542" font-size="16">{label}</text>')
            view='alternate' if frame in station.get('alternate_view',{}).get('frames',[]) else 'primary'
            pictures.append(f'<figure><svg viewBox="0 0 {w} {h}"><image href="{photo}" width="{w}" height="{h}"/>{"".join(boxes)}</svg>'
                f'<figcaption>{view} · RGB source {frame["capture_stamp"]:.3f}s · pose {escape(str(frame["pose"]))} · '
                f'推理 {evidence["wall_ms"]:.1f}ms · SHA {frame["sha256"][:12]} · '
                f'freshness {escape(str(frame.get("capture_freshness","not recorded")))}</figcaption></figure>')
        sections.append(f'<article><h2>{escape(station["name"])} · {escape(station["state"])}</h2>'
            f'<p>{escape(station.get("reason",""))} · primary: {escape(station.get("primary_state",station["state"]))} · '
            f'alternate: {escape(station.get("alternate_view",{}).get("state","not requested"))}</p>{"".join(pictures)}</article>')
    html='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>FishBot 通用物体巡检</title>'
    html+='<style>body{font:16px/1.6 system-ui;max-width:1100px;margin:24px auto;padding:16px;color:#243347;background:#f5f7fa}article{background:white;padding:18px;margin:20px 0}figure{display:inline-block;width:46%;margin:1%}svg{width:100%}code{overflow-wrap:anywhere}</style>'
    html+=f'<h1>FishBot RGB 预训练物体巡检</h1><p>任务状态：{escape(report["overall_status"])}。未检测到物体保留 unknown，不能证明缺席。</p>'
    html+=f'<p>模型：<code>{escape(json.dumps(report.get("detector",{}),ensure_ascii=False))}</code></p><a href="report.json">原始报告</a>'
    if report.get('error'):html+='<p>失败：'+escape(report['error'])+'</p>'
    if report.get('cleanup_errors'):html+='<p>清理失败：'+escape(str(report['cleanup_errors']))+'</p>'
    if 'fixture_provenance' in report:
        html+='<p>人工选择的合成 fixture，不能当作现实精度基准。</p><code>'+escape(json.dumps(
            report['fixture_provenance'].get('fixture_selection',{}),ensure_ascii=False))+'</code>'
    html+=_route_svg(report)+''.join(sections)
    if 'object_acceptance' in report:html+='<h2>合成场景评分</h2><code>'+escape(json.dumps(report['object_acceptance'],ensure_ascii=False))+'</code>'
    (output/'index.html').write_text(html,encoding='utf-8')


class Worker:
    def __init__(self, python, model, output, device='cpu'):
        self.output=Path(output);self.counter=0;self.executor=None;self.child=None
        self.inputs=self.output/'inference-inputs';self.inputs.mkdir()
        self.log=(self.output/'detector.log').open('w')
        env=os.environ.copy();env['YOLO_CONFIG_DIR']=str(Path.home()/'.cache/fishbot/object-inspection/ultralytics')
        # Detection runs in its existing local ML environment, not the ROS interpreter.
        env.pop('PYTHONPATH',None)
        try:
            self.child=subprocess.Popen([str(python),'-u',str(Path(__file__).with_name('fishbot_object_infer.py')),
                '--model',str(model),'--device',device,'--worker'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.log,
                text=True,env=env)
            ready=self.read(30)
            if ready.get('ready') is not True:raise RuntimeError('Detector did not become ready')
            self.metadata=ready['model']
            self.executor=ThreadPoolExecutor(max_workers=1)
        except BaseException:
            self.close()
            raise

    def read(self, timeout=15):
        if not select.select([self.child.stdout],[],[],timeout)[0]:
            raise TimeoutError('Pretrained detector response timed out')
        line=self.child.stdout.readline()
        if not line:raise RuntimeError(f'Detector exited; inspect {self.output/"detector.log"}')
        result=json.loads(line)
        if result.get('error'):raise RuntimeError(result['error'])
        return result

    def predict(self, rgb):
        from PIL import Image
        self.counter+=1;image=self.inputs/f'frame-{self.counter:04}.png'
        Image.fromarray(rgb).save(image)
        self.child.stdin.write(json.dumps({'image':str(image)})+'\n');self.child.stdin.flush()
        result=self.read()
        return dict(state='detected' if result['detections'] else 'unknown',
                    reason='pretrained model detections',evidence=result)

    def predict_async(self,rgb):
        return self.executor.submit(self.predict,rgb)

    def close(self):
        if self.child is not None:
            self.child.stdin.close()
            try:self.child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.child.terminate()
                try:self.child.wait(timeout=3)
                except subprocess.TimeoutExpired:self.child.kill();self.child.wait(timeout=3)
            self.child.stdout.close()
        self.log.close()
        if self.executor is not None:self.executor.shutdown(wait=False,cancel_futures=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--python',type=Path,required=True);p.add_argument('--model',type=Path,required=True)
    p.add_argument('--route',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--goal-timeout',type=float,default=90);p.add_argument('--device',default='cpu')
    a=p.parse_args();output=a.output.resolve();output.mkdir(parents=True,exist_ok=True)
    if (output/'report.json').exists():p.error('Use a new report directory')
    worker=Worker(a.python,a.model,output,a.device)
    def persist(report,directory):report['detector']=worker.metadata;save_report(report,directory)
    try:
        inspection_main(['--route',str(a.route),'--output',str(output),'--goal-timeout',str(a.goal_timeout)],
            domain='101',observation_fn=worker.predict_async,report_fn=persist,aggregate_fn=aggregate,
            station_count=4,capture_timeout=30.,vision_method='Actual pretrained YOLO11n COCO inference from onboard RGB only')
    finally:worker.close()
    report=json.loads((output/'report.json').read_text());report['detector']=worker.metadata
    runtime_provenance=output/'runtime-provenance.json'
    if runtime_provenance.is_file():
        runtime=json.loads(runtime_provenance.read_text())
        root=Path(__file__).resolve().parents[1]
        runtime['source_unchanged']=bool(runtime.get('source_sha256')) and all(
            hashlib.sha256((root/name).read_bytes()).hexdigest()==digest
            for name,digest in runtime['source_sha256'].items())
        report['runtime_provenance']=runtime
    provenance=a.route.parent/'provenance.json'
    if provenance.is_file():
        fixture=json.loads(provenance.read_text())
        fixture['files_match_recorded_sha256']=all(
            hashlib.sha256((a.route.parent/name).read_bytes()).hexdigest()==fixture.get(key)
            for name,key in [('scene.xml','scene_sha256'),('route.json','route_sha256')])
        profile=fixture.get('navigation_profile',{})
        fixture['files_match_recorded_sha256'] &= bool(profile) and (
            hashlib.sha256((a.route.parent/'nav2.yaml').read_bytes()).hexdigest()==profile.get('generated_sha256'))
        report['fixture_provenance']=fixture
    report['object_acceptance']=score_fixture(report)
    (output/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    save_report(report,output)
    print(json.dumps({'passed':report['object_acceptance']['passed'],'report':str(output/'index.html')}))
    return 0 if report['object_acceptance']['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
