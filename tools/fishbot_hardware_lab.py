#!/usr/bin/env python3
"""Collect independent measured-map, chassis and adhesion evidence; never run ROS."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import warnings

TITLES = {'real_map':'真实场地图导航', 'new_base':'Jackal J100 四轮底盘', 'suction':'负压与墙面爬升'}
CASE_LABELS = {'ground_off':'地面未开泵：预期滑移', 'ground_on':'地面开泵：抗横推',
 'wall_on':'墙面持压保持', 'wall_pressure_loss':'墙面失压：预期脱落', 'wall_climb':'四轮沿墙上行'}


def section(kind, path):
    item = {'id':kind,'title':TITLES[kind],'status':'incomplete','basis':'尚无证据',
            'summary':'尚未提供本分项报告。','cases':[]}
    if path is None:
        return item
    path = Path(path).expanduser().resolve()
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw,dict):
            raise ValueError('Report must be an object')
    except (OSError,ValueError) as error:
        warnings.warn(f'WARNING: {kind}: {error}; keeping other sections')
        item['summary'] = str(error)
        return item
    source = raw.get('source') if isinstance(raw.get('source'),dict) else {}
    item.update(basis=str(source.get('basis','未声明来源')),source_report=str(path),
                limitations=raw.get('limitations',[]))
    cases = raw.get('cases',[])
    if not isinstance(cases,list):
        warnings.warn(f'WARNING: {kind}: cases is not an array; keeping source and other sections')
        cases = []
    for index, case in enumerate(cases):
        if not isinstance(case,dict):
            case = {'reason':'无法识别本条报告'}
        identifier = str(case.get('id',case.get('case',f'case-{index+1}')))
        status = case.get('acceptance_result',case.get('status','incomplete'))
        if status not in ('passed','failed','incomplete'):
            status = 'incomplete'
        if kind == 'suction':
            metrics = {key:value for key,value in case.items() if key not in
                       ('case','status','scope','checks','snapshots','trace')}
        else:
            metrics = dict(case['metrics']) if isinstance(case.get('metrics'),dict) else {}
            metrics.update(task_id=case.get('task_id'),native_goal_id=case.get('native_goal_id'),
                           native_status=case.get('native_status'),cleanup_complete=case.get('cleanup_complete'))
        item['cases'].append({'id':identifier,'label':str(case.get('label',CASE_LABELS.get(identifier,identifier))),
            'status':status,'reason':str(case.get('reason','符合本案例物理预期' if status=='passed' else '查看原始物理检查')),
            'metrics':metrics,'checks':case.get('checks',{}),
            'business_result':case.get('business_result')})
    states = [case['status'] for case in item['cases']]
    item['status'] = 'failed' if 'failed' in states else 'passed' if states and all(s=='passed' for s in states) else 'incomplete'
    passed = sum(s=='passed' for s in states)
    item['summary'] = f'{passed}/{len(states)} 个独立案例通过。' if states else '原报告没有案例。'
    if kind == 'real_map':
        item['summary'] += '二维实测布局；墙高与材质仍为仿真假设。'
    elif kind == 'new_base':
        item['summary'] += '官方几何/惯量；轮胎、地面及伺服参数未做真机标定。'
    else:
        item['summary'] += '原生接触吸附与降阶压强模型；失压脱落属于预期结果。'
    return item


def collect(*, real=None, base=None, suction=None, output):
    report = {'schema_version':1,'scope':'simulation','created_at':datetime.now(timezone.utc).isoformat(),
        'label':'真实场图、新底盘与负压实验',
        'sections':[section(kind,path) for kind,path in (('real_map',real),('new_base',base),('suction',suction))],
        'limitations':['三个分项分别验收，不代表新底盘已在真实房间爬壁运输。',
                       '地图保持私有；负压未做CFD、密封材料或真机标定。']}
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True,exist_ok=True)
    temporary = output/'report.json.tmp'
    temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    temporary.replace(output/'report.json')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real',type=Path)
    parser.add_argument('--base',type=Path)
    parser.add_argument('--suction',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    report = collect(real=args.real,base=args.base,suction=args.suction,output=args.output)
    print(json.dumps({'report':str(args.output/'report.json'),'sections':[
        {'id':s['id'],'status':s['status']} for s in report['sections']]},ensure_ascii=False))


if __name__ == '__main__':
    main()
