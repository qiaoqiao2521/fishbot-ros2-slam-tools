#!/usr/bin/env python3
"""Run independent scene cases through existing launch, lidar helper and owner.

The selected simulation cases run by default. --prepare-only writes editable
inputs without ROS. An unavailable dependency or failed case never blocks the
remaining selected cases. Owned launch process groups are always cleaned.
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import warnings

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS/(name+'.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validation = load_tool('fishbot_scene_validation')


def selected_environment(domain, output):
    if not 1 <= int(domain) <= 232:
        raise ValueError('Select a nonzero simulation domain')
    env = os.environ.copy()
    env.update(ROS_DOMAIN_ID=str(domain), FISHBOT_MUJOCO_DOMAIN_ID=str(domain),
               ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST', ROS_LOCALHOST_ONLY='1', ROS_STATIC_PEERS='')
    if env.get('RMW_IMPLEMENTATION') == 'rmw_cyclonedds_cpp' and not env.get('CYCLONEDDS_URI'):
        path = Path(output)/f'cyclonedds-domain-{domain}.xml'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('<CycloneDDS><Domain Id="'+str(domain)+'"><General><Interfaces>'
            '<NetworkInterface name="lo"/></Interfaces><AllowMulticast>false</AllowMulticast>'
            '</General><SharedMemory><Enable>false</Enable></SharedMemory></Domain></CycloneDDS>\n')
        env['CYCLONEDDS_URI'] = path.as_uri()
    return env


def stop_owned_group(process):
    """Signal only the launch group created by this campaign, and reap it."""
    if process is None:
        return True
    for sig, timeout in ((signal.SIGINT,12.),(signal.SIGTERM,4.),(signal.SIGKILL,2.)):
        try:
            os.killpg(process.pid,sig)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            continue
        until = time.monotonic()+timeout
        while time.monotonic() < until:
            try:
                os.killpg(process.pid,0)
            except ProcessLookupError:
                return True
            time.sleep(.1)
    return False


def empty_domain(env):
    probe = subprocess.run(['ros2','node','list','--no-daemon'],env=env,cwd=ROOT,
                           capture_output=True,text=True,timeout=10.)
    if probe.returncode:
        raise RuntimeError('ROS domain query unavailable: '+probe.stderr[-1000:])
    nodes = [line.strip() for line in probe.stdout.splitlines()
             if line.strip().startswith('/') and not line.strip().startswith('/_ros2cli_')]
    if nodes:
        raise RuntimeError('Selected domain already contains nodes; no existing runtime was replaced: '+', '.join(nodes))


def incomplete(case, reason):
    return {'id':case['id'],'label':case.get('label',case['id']),'expected':case.get('expected','delivered'),
        'business_result':'unknown','acceptance_result':'incomplete','reason':str(reason),'metrics':{},
        'task_id':None,'native_goal_id':None,'native_status':None}


def wait_runtime(api, domain, process, deadline):
    """One startup deadline from Popen, rather than nested full timeout windows."""
    last = 'runtime not yet listening'
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Owned launch exited before readiness; inspect launch.log')
        api.timeout = min(1.,max(.05,deadline-time.monotonic()))
        try:
            status, runtime, _ = api.request('GET','/sim-api/runtime')
            if status == 200 and runtime.get('domain') == domain:
                status,state,_ = api.request('GET','/sim-api/state')
                if status == 200 and state.get('domain') == domain and state.get('ready'):
                    return runtime
                last = state.get('reason','navigation not ready')
        except (OSError,ValueError) as error:
            last = str(error)
        time.sleep(.1)
    raise TimeoutError('Startup exceeded original deadline: '+last)


def lidar_probe(directory, env):
    path = Path(directory)/'lidar3d-probe.json'
    try:
        result = subprocess.run([sys.executable,str(TOOLS/'fishbot_lidar3d_probe.py'),
            '--timeout','15','--output',str(path)],env=env,cwd=ROOT,capture_output=True,text=True,timeout=20.)
        (Path(directory)/'lidar3d-probe.log').write_text(result.stdout+result.stderr)
        evidence = validation.read_json(path,{'status':'incomplete','reasons':['Probe produced no JSON']})
        evidence['process_returncode'] = result.returncode
        return evidence
    except (OSError,subprocess.TimeoutExpired,ValueError) as error:
        return {'status':'incomplete','reasons':[str(error)]}


def launch_arguments(case, lidar, domain, port):
    transform = lidar.get('static_transform',{})
    translation = transform.get('translation',[0.,0.,.035])
    return {'ros_domain_id':str(domain),'headless':'true','rviz':'false','bridge':'true',
        'obstacle':'false','bridge_port':str(port),'map':case['map'],'scene_path':lidar['scene'],
        'plugins_file':lidar['plugins'],'params_file':lidar['nav2'],'lidar3d_tf':'true',
        'lidar3d_parent':transform.get('parent_frame','laser_link'),
        'lidar3d_frame':transform.get('child_frame','lidar3d_link'),
        'lidar3d_x':str(translation[0]),'lidar3d_y':str(translation[1]),'lidar3d_z':str(translation[2])}


def run_campaign(config,output,*,selected=None,domain=130,port=9100,prepare_only=False):
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True,exist_ok=True)
    panel = validation.prepare_panel(config,output/'prepared')
    panel.update(domain=domain,api=f'http://127.0.0.1:{port}')
    panel['lidar'].update(profile='generic-16-line-3d',evidence=[])
    env = selected_environment(domain,output)
    # The observer and HTTP runner are children of this command, not shared host configuration.
    os.environ.update({key:env[key] for key in ('ROS_DOMAIN_ID','FISHBOT_MUJOCO_DOMAIN_ID',
        'ROS_AUTOMATIC_DISCOVERY_RANGE','ROS_LOCALHOST_ONLY','ROS_STATIC_PEERS')})
    if env.get('CYCLONEDDS_URI'):
        os.environ['CYCLONEDDS_URI'] = env['CYCLONEDDS_URI']
    lidar_helper = load_tool('fishbot_lidar3d')
    results = []
    for error in panel.get('preparation_errors',[]):
        case_id = error.get('case_id',f'case-{error.get("index",0)+1}')
        if selected and case_id not in selected:
            continue
        failed = {'id':case_id,'label':error.get('label',case_id),'expected':error.get('expected','unknown')}
        outcome = incomplete(failed,'Case preparation incomplete: '+error['error'])
        outcome.update(preparation_error=True,preparation_index=error.get('index'),cleanup_complete=True)
        results.append(outcome)
    if results:
        validation.save_report(panel,results,output)
    for case in panel['cases']:
        if selected and case['id'] not in selected:
            continue
        directory = output/(case['id']+'-'+time.strftime('%Y%m%dT%H%M%S')+'-'+str(time.time_ns()%1_000_000))
        directory.mkdir(parents=True,exist_ok=True)
        process = stream = None
        outcome = None
        try:
            case.update(domain=domain,api=panel['api'])
            lidar = lidar_helper.prepare(case['scene_path'],directory/'lidar3d',
                plugins_path=case.get('plugins_file'),nav2_path=case.get('params_file'),audit_contacts=True)
            case.update(scene_path=lidar['scene'],plugins_file=lidar['plugins'],params_file=lidar['nav2'])
            args = launch_arguments(case,lidar,domain,port)
            case['launch_arguments'] = args
            validation.write_json(directory/'case.json',case)
            validation.write_json(output/'panel.json',panel)
            if prepare_only:
                outcome = incomplete(case,'Prepared editable 3D scene; ROS not started')
                continue
            if not Path(lidar['library']).is_file():
                raise FileNotFoundError('Official 3D lidar library unavailable; did not fall back to 2D: '+lidar['library'])
            empty_domain(env)
            stream = (directory/'launch.log').open('w')
            command = ['ros2','launch','fishbot_mujoco','sim.launch.py']+[key+':='+value for key,value in args.items()]
            launched = time.monotonic()
            process = subprocess.Popen(command,env=env,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
            deadline = launched+float(config.get('startup_timeout_s',45.))
            runtime = wait_runtime(validation.MissionAPI(panel['api'],timeout=1.),domain,process,deadline)
            validation.write_json(directory/'runtime.json',runtime)
            probe = lidar_probe(directory,env)
            panel['lidar']['evidence'].append({'case_id':case['id'],'probe':probe,
                'path':str(directory/'lidar3d-probe.json')})
            # readiness already observed; run_case does a current read, without a second 45s startup budget.
            current = {**panel,'startup_timeout_s':max(.1,deadline-time.monotonic())}
            outcome = validation.run_case(case,current,directory/'mission',panel['api'],domain)
            outcome.setdefault('metrics',{})['lidar3d_probe'] = probe
            if probe.get('status') != 'complete':
                outcome['reason'] += '; 3D sensor/costmap evidence incomplete'
                if outcome['acceptance_result'] == 'passed':
                    outcome['acceptance_result'] = 'incomplete'
            outcome['runtime_instance_id'] = runtime.get('instance_id')
        except KeyboardInterrupt:
            outcome = incomplete(case,'Campaign interrupted; original attempt preserved')
            raise
        except Exception as error:
            warnings.warn(f'WARNING: {case["id"]}: {error}; continuing remaining independent cases')
            outcome = incomplete(case,error)
        finally:
            cleanup = stop_owned_group(process)
            if stream:
                stream.close()
            if outcome is None:
                outcome = incomplete(case,'Case did not return a result')
            outcome.update(artifact_directory=directory.name,cleanup_complete=cleanup)
            if not cleanup:
                outcome.update(acceptance_result='incomplete',reason=outcome['reason']+'; owned process cleanup unconfirmed')
            validation.write_json(directory/'result.json',outcome)
            results.append(outcome)
            validation.save_report(panel,results,output)
    validation.write_json(output/'panel.json',panel)
    return validation.save_report(panel,results,output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=TOOLS/'config/scene_validation.example.json')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--case','--cases',dest='cases',nargs='+')
    parser.add_argument('--domain',type=int,default=130)
    parser.add_argument('--port',type=int,default=9100)
    parser.add_argument('--source-map',type=Path)
    parser.add_argument('--prepare-only',action='store_true')
    args = parser.parse_args(argv)
    config = validation.load_config(args.config)
    if args.source_map:
        config['source_map'] = str(args.source_map.expanduser().resolve())
        config.pop('scene_path',None)
        config.pop('map',None)
    report = run_campaign(config,args.output,selected=args.cases,domain=args.domain,port=args.port,prepare_only=args.prepare_only)
    print(json.dumps({'report':str(args.output/'report.json'),'index':str(args.output/'index.html'),
        'cases':[{key:case[key] for key in ('id','business_result','acceptance_result')} for case in report['cases']]},ensure_ascii=False))
    return 0 if args.prepare_only or report['cases'] and all(case['acceptance_result']=='passed' for case in report['cases']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
