#!/usr/bin/env python3
"""Observe a held ROS/MuJoCo loop, without navigation or actuator publishers."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def main(manifest_file, output_dir, mode='simulator', domain='144', port='9114'):
    os.environ.update(ROS_DOMAIN_ID=domain,FISHBOT_MUJOCO_DOMAIN_ID=domain,
                      ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',ROS_LOCALHOST_ONLY='1')
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Imu, LaserScan, PointCloud2
    from std_msgs.msg import String
    from cooperation_acceptance import lifecycle_active,stop_owned_launch,owned_processes,ensure_port_available
    from cooperation_workflow import LocalBridge
    from fishbot_simulation_suite import domain_is_empty
    full=mode=='full'
    if full:ensure_port_available(int(port))
    domain_is_empty(timeout=5)
    manifest=json.loads(Path(manifest_file).read_text())
    output=Path(output_dir);output.mkdir(parents=True,exist_ok=True)
    rclpy.init();node=rclpy.create_node('f1_capacity_observer')
    rows={name:[] for name in ('physics','scan','cloud','imu')}
    shape=set();holds=[]
    def observe(name,message):
        if name=='physics':
            value=json.loads(message.data);stamp=value['stamp'];holds.append(value['car_hold'])
        else:
            stamp=message.header.stamp.sec+message.header.stamp.nanosec*1e-9
            if name=='cloud':shape.add((message.height,message.width))
        rows[name].append((stamp,time.monotonic()))
    subscriptions=[node.create_subscription(kind,topic,lambda msg,n=name:observe(n,msg),qos_profile_sensor_data)
        for name,kind,topic in [('physics',String,'/cooperation/physics_state'),
            ('scan',LaserScan,'/scan'),('cloud',PointCloud2,'/sensors/lidar3d/points'),('imu',Imu,'/imu')]]
    process=None;error=None;ready=None;cleanup={'errors':[]};usage=[];startup_errors=[];sample_complete=False
    def cpu_snapshot():
        result={}
        for pid,identity in owned_processes(process.pid).items():
            try:
                fields=Path('/proc/'+str(pid)+'/stat').read_text().rsplit(')',1)[1].split()
                result[str(pid)]={'ticks':int(fields[11])+int(fields[12]),'starttime':identity,
                                 'name':Path('/proc/'+str(pid)+'/comm').read_text().strip()}
            except (OSError,ValueError,IndexError):continue
        return result
    try:
        with (output/'sim.log').open('w') as log:
            command=[sys.executable,'-B','tools/cooperation_sim.py','--scene',manifest['world_xml'],
                '--manifest',manifest_file,'--domain',domain,'--duration','22','--no-overview-render',
                '--queued-ros-dispatch','--timing-log',str(output/'loop-timing.json')]
            if full:
                command=['ros2','launch','tools/cooperation.launch.py','manifest:='+manifest_file,
                    'python:='+sys.executable,'output:='+str(output/'runtime'),'domain:='+domain,'port:='+port,
                    'publication_mode:=asynchronous']
            process=subprocess.Popen(command,
                start_new_session=True,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+(75 if full else 50);sample_end=None;next_get=0.
            bridge=LocalBridge('http://127.0.0.1:'+port,timeout=1.) if full else None
            while process.poll() is None and time.monotonic()<deadline:
                rclpy.spin_once(node,timeout_sec=.02)
                if full and ready is None and time.monotonic()>next_get:
                    next_get=time.monotonic()+1.
                    try:state=bridge.state()
                    except (RuntimeError,OSError,ValueError) as exc:
                        reason=type(exc).__name__+': '+str(exc)
                        if reason not in startup_errors:
                            startup_errors[:]=[*startup_errors[-3:],reason]
                            print('WARNING: readiness pending:',reason,flush=True)
                        continue
                    if (state.get('ready') is True and state.get('domain')==int(domain)
                            and lifecycle_active(state.get('native_lifecycle',{}))):
                        ready=state
                        for values in rows.values():values.clear()
                        shape.clear();holds.clear();sample_end=time.monotonic()+22.
                        usage.append({'monotonic':time.monotonic(),'processes':cpu_snapshot()})
                if sample_end is not None and time.monotonic()>=sample_end:
                    usage.append({'monotonic':time.monotonic(),'processes':cpu_snapshot()});sample_complete=True;break
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)
    finally:
        if full and process is not None:
            stop_owned_launch(process,cleanup)
        elif process is not None and process.poll() is None:
            os.killpg(process.pid,signal.SIGINT)
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=5)
        node.destroy_node();rclpy.try_shutdown()
    metrics={}
    for name,values in rows.items():
        span=values[-1][0]-values[0][0] if len(values)>1 else 0.
        wall=values[-1][1]-values[0][1] if len(values)>1 else 0.
        metrics[name]={'messages':len(values),'source_span_s':span,'received_monotonic_span_s':wall,
            'source_hz':(len(values)-1)/span if span else None,
            'source_per_wall':span/wall if wall else None,
            'max_source_gap_s':max((b[0]-a[0] for a,b in zip(values,values[1:])),default=None)}
    timing_file=output/('runtime/loop-timing.json' if full else 'loop-timing.json')
    timing=json.loads(timing_file.read_text()) if timing_file.is_file() else None
    physics=metrics['physics']
    passed=bool(not error and process is not None and process.returncode==0 and timing
        and not timing.get('finalization_errors') and not cleanup['errors'] and (not full or sample_complete)
        and holds and all(holds)
        and physics['messages']>100 and physics['source_per_wall']>=.95
        and all(m['messages']>20 for m in metrics.values()) and shape=={(16,360)})
    result={'kind':'f1_held_ros_capacity','capacity_passed':passed,'task_acceptance':False,
        'navigation_goals':0,'actuator_topics_published':False,'all_observed_hold':bool(holds and all(holds)),
        'scope':('held complete ROS stack plus observer' if full else 'simulator plus independent ROS observer')
            +'; not transport acceptance',
        'metrics':metrics,'cloud_shapes':sorted(shape),'sim_returncode':process.returncode if process else None,
        'process_stopped':process is not None and process.poll() is not None,'error':error,
        'timing':timing,'sensor_compute':manifest.get('sensor_compute'),'native_ready_snapshot':ready,
        'cleanup':cleanup,'process_cpu_samples':usage,'clock_ticks_per_s':os.sysconf('SC_CLK_TCK'),
        'startup_errors':startup_errors,'full_sample_completed':sample_complete,'domain':int(domain),'port':int(port)}
    (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)


if __name__=='__main__':main(*sys.argv[1:])
