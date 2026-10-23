#!/usr/bin/env python3
"""Observe a held ROS/MuJoCo loop, without navigation or actuator publishers."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def main(manifest_file, output_dir):
    os.environ.update(ROS_DOMAIN_ID='144', ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST', ROS_LOCALHOST_ONLY='1')
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Imu, LaserScan, PointCloud2
    from std_msgs.msg import String
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
    process=None;error=None
    try:
        with (output/'sim.log').open('w') as log:
            process=subprocess.Popen([sys.executable,'-B','tools/cooperation_sim.py','--scene',manifest['world_xml'],
                '--manifest',manifest_file,'--domain','144','--duration','22','--no-overview-render',
                '--queued-ros-dispatch','--timing-log',str(output/'loop-timing.json')],
                start_new_session=True,stdout=log,stderr=subprocess.STDOUT)
            deadline=time.monotonic()+50
            while process.poll() is None and time.monotonic()<deadline:rclpy.spin_once(node,timeout_sec=.05)
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)
    finally:
        if process is not None and process.poll() is None:
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
    timing_file=output/'loop-timing.json'
    timing=json.loads(timing_file.read_text()) if timing_file.is_file() else None
    physics=metrics['physics']
    passed=bool(not error and process is not None and process.returncode==0 and timing
        and not timing.get('finalization_errors') and holds and all(holds)
        and physics['messages']>100 and physics['source_per_wall']>=.95
        and all(m['messages']>20 for m in metrics.values()) and shape=={(16,360)})
    result={'kind':'f1_held_ros_capacity','capacity_passed':passed,'task_acceptance':False,
        'navigation_goals':0,'actuator_topics_published':False,'all_observed_hold':bool(holds and all(holds)),
        'scope':'simulator plus independent ROS observer, not full-stack or transport acceptance',
        'metrics':metrics,'cloud_shapes':sorted(shape),'sim_returncode':process.returncode if process else None,
        'process_stopped':process is not None and process.poll() is not None,'error':error,
        'timing':timing,'sensor_compute':manifest.get('sensor_compute')}
    (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result),flush=True)


if __name__=='__main__':main(*sys.argv[1:])
