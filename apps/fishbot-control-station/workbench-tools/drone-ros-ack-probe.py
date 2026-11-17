#!/usr/bin/env python3
"""Native EGO + trajectory server with explicit synthetic ROS inputs; no vehicle."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid


def native_shutdown_clean(events):
    started={(e['role'],e['pid']) for e in events if e['kind']=='process_start'}
    exited={(e['role'],e['pid']):e for e in events if e['kind']=='process_exit'}
    return bool(started) and started==set(exited) and all(
        exited[key]['exit_code']==0 and exited[key]['proc_absent'] for key in started)


def audit_receipts(events, receipts, graph):
    """Join a Python observation to a C++ receipt; node discovery alone is insufficient."""
    checks={}
    for kind in ('ack','bspline','position'):
        seen=[e for e in events if e['kind']==kind]
        native=[e for e in receipts if e['kind']==kind]
        endpoints=graph.get(kind,[])
        gid=endpoints[0]['endpoint_gid'] if len(endpoints)==1 else None
        checks[kind+'_cpp_gid_matches_graph']=(bool(native) and gid is not None and
            all(e['publisher_gid']==gid for e in native))
        def key(e):
            return (e.get('source_timestamp'),e.get('publication_sequence_number'))
        pairs={key(e):e for e in native if type(e.get('source_timestamp')) is int and e['source_timestamp']>0
               and type(e.get('publication_sequence_number')) is int and e['publication_sequence_number']>=0}
        checks[kind+'_python_receipts_join_cpp']=(bool(seen) and all(key(e) in pairs and
            all(e['message'].get(k)==v for k,v in pairs[key(e)]['message'].items()) for e in seen))
    return checks


def run(output, workspace, domain_id, receipt_witness=None,
        trajectory_executable=None, release_trajectory_publisher=False):
    import rclpy
    from geometry_msgs.msg import PoseStamped
    from nav_msgs.msg import Odometry
    from rosgraph_msgs.msg import Clock
    from sensor_msgs.msg import PointCloud2
    from sensor_msgs_py.point_cloud2 import create_cloud_xyz32
    from std_msgs.msg import Header, String
    from traj_utils.msg import Bspline
    from quadrotor_msgs.msg import PositionCommand
    import yaml

    output.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex[:10]
    prefix = '/drone_ack_probe_'+token
    os.environ['ROS_DOMAIN_ID'] = str(domain_id)
    os.environ['ROS_AUTOMATIC_DISCOVERY_RANGE'] = 'LOCALHOST'
    names = {'planner': 'planner_'+token, 'trajectory': 'trajectory_'+token}
    topics = {k: prefix+'/'+k for k in ('goal','ack','bspline','position','state','odom','cloud')}
    config = yaml.safe_load(Path('/home/muqiao/dev/ros2/projects/drone/ego/planner.yaml').read_text())
    (output/'planner-runtime.yaml').write_text(yaml.safe_dump(config))
    events, processes, handles, errors = [], [], [], []
    started = time.monotonic()
    sim = 10.
    stream = (output/'ros-events.jsonl').open('w')
    def record(kind, **fields):
        event = dict(kind=kind, host_monotonic_ns=time.monotonic_ns(), harness_sim_s=sim, **fields)
        events.append(event)
        stream.write(json.dumps(event, allow_nan=False)+'\n')
        stream.flush()
        return event

    def callback(kind):
        def receive(msg, info):
            if kind in ('ack','state'):
                body = {'data': msg.data}
            elif kind == 'bspline':
                body = {'traj_id': msg.traj_id, 'order': msg.order,
                    'start_sim_s': msg.start_time.sec+msg.start_time.nanosec*1e-9,
                    'knots': list(msg.knots), 'control_points': [[p.x,p.y,p.z] for p in msg.pos_pts]}
            else:
                body = {'trajectory_id': msg.trajectory_id,
                    'stamp_sim_s': msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,
                    'position': [msg.position.x,msg.position.y,msg.position.z],
                    'velocity': [msg.velocity.x,msg.velocity.y,msg.velocity.z],
                    'acceleration': [msg.acceleration.x,msg.acceleration.y,msg.acceleration.z],
                    'yaw': msg.yaw, 'trajectory_flag': msg.trajectory_flag}
            # Jazzy's callback info is a dict on this installed rclpy build.
            field = info.get if isinstance(info, dict) else lambda key: getattr(info,key,None)
            gid=field('publisher_gid')
            record(kind, message=body, publisher_gid=None if gid is None else bytes(gid).hex(),
                callback_info_keys=sorted(info) if isinstance(info,dict) else None,
                source_timestamp=field('source_timestamp'), received_timestamp=field('received_timestamp'),
                publication_sequence_number=field('publication_sequence_number'))
        return receive

    rclpy.init()
    node = rclpy.create_node('observer_'+token)
    subs = [node.create_subscription(typ, topics[kind], callback(kind), 50)
        for kind,typ in [('ack',String),('bspline',Bspline),('position',PositionCommand),('state',String)]]
    clocks = node.create_publisher(Clock, '/clock', 10)
    odoms = node.create_publisher(Odometry, topics['odom'], 10)
    clouds = node.create_publisher(PointCloud2, topics['cloud'], 10)
    goals = node.create_publisher(PoseStamped, topics['goal'], 10)
    requested, graph = [], {}
    complete_at = None
    next_send = started
    try:
        planner = workspace/'install/ego_planner/lib/ego_planner/ego_planner_node'
        trajectory = trajectory_executable or workspace/'install/ego_planner/lib/ego_planner/traj_server'
        commands = [
            ('planner', [str(planner),'--ros-args','--params-file',str(output/'planner-runtime.yaml'),
                '-r','__node:='+names['planner'], '-r','/move_base_simple/goal:='+topics['goal'],
                '-r','planning/goal_ack:='+topics['ack'], '-r','planning/bspline:='+topics['bspline'],
                '-r','planning/state:='+topics['state'], '-r','odom_world:='+topics['odom'],
                '-r','grid_map/odom:='+topics['odom'], '-r','grid_map/cloud:='+topics['cloud']]),
            ('trajectory', [str(trajectory),'--ros-args','-p','use_sim_time:=true',
                '-p','traj_server/time_forward:=0.6','-r','__node:='+names['trajectory'],
                '-r','planning/bspline:='+topics['bspline'], '-r','/position_cmd:='+topics['position']])]
        if release_trajectory_publisher:
            commands[1][1].extend(['-p','diagnostics/release_publisher_on_exit:=true'])
        if receipt_witness is not None:
            commands.append(('receipt',[str(receipt_witness),'--ros-args','-p','prefix:='+prefix,
                '-r','__node:=receipt_'+token]))
        for role, argv in commands:
            handle=(output/('witness.jsonl' if role=='receipt' else role+'.log')).open('w'); handles.append(handle)
            stderr=subprocess.STDOUT
            if role=='receipt':
                stderr=(output/'receipt.log').open('w');handles.append(stderr)
            process=subprocess.Popen(argv,stdout=handle,stderr=stderr)
            processes.append((role,process))
            ticks=Path(f'/proc/{process.pid}/stat').read_text().rsplit(') ',1)[1].split()[19]
            record('process_start',role=role,pid=process.pid,start_ticks=ticks,argv=argv)
        while time.monotonic()-started < 12.:
            now=time.monotonic()
            if any(p.poll() is not None for _,p in processes):
                raise RuntimeError('An owned native node exited before the diagnostic completed')
            if now >= next_send:
                sim += .02
                clk=Clock();stamp_ns=int(round(sim*1e9));clk.clock.sec=stamp_ns//10**9;clk.clock.nanosec=stamp_ns%10**9
                clocks.publish(clk)
                odom=Odometry();odom.header=Header(stamp=clk.clock,frame_id='world')
                odom.pose.pose.position.z=1.;odom.pose.pose.orientation.w=1.
                odoms.publish(odom)
                clouds.publish(create_cloud_xyz32(odom.header,[(5.,5.,1.)]))
                next_send=now+.02
            rclpy.spin_once(node,timeout_sec=.005)
            bsplines=[e for e in events if e['kind']=='bspline']
            positions=[e for e in events if e['kind']=='position']
            ready=(goals.get_subscription_count() == 1 and len(node.get_publishers_info_by_topic(topics['ack'])) == 1
                   and len(node.get_publishers_info_by_topic(topics['bspline'])) == 1
                   and len(node.get_publishers_info_by_topic(topics['position'])) == 1)
            if receipt_witness is not None:
                ready = ready and node.count_subscribers(topics['ack']) >= 2 and node.count_subscribers(topics['bspline']) >= 3
            if not requested and ready and now-started > 1.4:
                requested.append((int(sim*1e9)+1,[2.,0.,1.]))
                goal=PoseStamped();stamp,target=requested[-1]
                goal.header=Header(frame_id='world');goal.header.stamp.sec=stamp//10**9;goal.header.stamp.nanosec=stamp%10**9
                goal.pose.position.x,goal.pose.position.y,goal.pose.position.z=target;goal.pose.orientation.w=1.
                goals.publish(goal);record('goal_sent',stamp_ns=stamp,target=target)
            elif len(requested)==1 and bsplines and positions:
                requested.append((int(sim*1e9)+2,[0.,2.,1.]))
                goal=PoseStamped();stamp,target=requested[-1]
                goal.header=Header(frame_id='world');goal.header.stamp.sec=stamp//10**9;goal.header.stamp.nanosec=stamp%10**9
                goal.pose.position.x,goal.pose.position.y,goal.pose.position.z=target;goal.pose.orientation.w=1.
                goals.publish(goal);record('goal_sent',stamp_ns=stamp,target=target)
            elif len(requested)==2:
                acks=[e for e in events if e['kind']=='ack' and e['message']['data'].split(':')[0]==str(requested[-1][0])]
                if acks:
                    floor=int(acks[0]['message']['data'].split(':')[1])
                    ids={e['message']['traj_id'] for e in bsplines if e['message']['traj_id'] > floor}
                    if any(e['message']['trajectory_id'] in ids for e in positions):
                        complete_at=now if complete_at is None else complete_at
                        if now-complete_at > .3: break
        for kind in ('ack','bspline','position'):
            graph[kind]=[dict(node_name=p.node_name,node_namespace=p.node_namespace,
                endpoint_gid=bytes(p.endpoint_gid).hex(),topic_type=p.topic_type)
                for p in node.get_publishers_info_by_topic(topics[kind])]
        checks={}
        for index,(stamp,target) in enumerate(requested):
            ack=[e for e in events if e['kind']=='ack' and e['message']['data'].split(':')[0]==str(stamp)]
            next_stamp_time=next((e['host_monotonic_ns'] for e in events if e['kind']=='goal_sent' and e['stamp_ns']!=stamp
                and e['host_monotonic_ns']>next(x['host_monotonic_ns'] for x in events if x['kind']=='goal_sent' and x['stamp_ns']==stamp)),10**30)
            curves=[] if not ack else [e for e in events if e['kind']=='bspline' and
                ack[0]['host_monotonic_ns']<=e['host_monotonic_ns']<next_stamp_time and
                e['message']['traj_id']>int(ack[0]['message']['data'].split(':')[1])]
            ids={e['message']['traj_id'] for e in curves}
            checks[f'goal_{index}_native_chain']=bool(ack and curves and any(
                e['kind']=='position' and e['message']['trajectory_id'] in ids for e in events))
        checks['two_goals']=len(requested)==2
        for kind,role in [('ack','planner'),('bspline','planner'),('position','trajectory')]:
            endpoints=graph[kind]
            checks[kind+'_one_expected_publisher']=(len(endpoints)==1 and endpoints[0]['node_name']==names[role])
    except Exception as error:
        errors.append(type(error).__name__+': '+str(error));checks={}
    finally:
        for role,process in reversed(processes):
            try:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                    try:process.wait(timeout=3.)
                    except subprocess.TimeoutExpired:
                        process.terminate();process.wait(timeout=3.)
                record('process_exit',role=role,pid=process.pid,exit_code=process.returncode,
                    proc_absent=not Path(f'/proc/{process.pid}').exists())
            except Exception as error:
                errors.append('cleanup '+role+': '+str(error))
        for handle in handles:handle.close()
        node.destroy_node();rclpy.shutdown();stream.close()
    receipt_checks={}
    if receipt_witness is not None:
        try:
            receipts=[json.loads(line) for line in (output/'witness.jsonl').read_text().splitlines()]
            receipt_checks=audit_receipts(events,receipts,graph)
        except Exception as error:
            errors.append('receipt audit: '+type(error).__name__+': '+str(error))
            receipt_checks={'cpp_receipts_readable':False}
        checks.update(receipt_checks)
    result={'scope':'native EGO/selected trajectory server and ROS transport; synthetic odometry, clock and explicit cloud',
        'trajectory_executable':str(trajectory), 'release_trajectory_publisher':release_trajectory_publisher,
        'domain_id':domain_id,'prefix':prefix,'publisher_graph':graph,'diagnostic_checks':checks,'errors':errors,
        'python_callback_publisher_gid_available':all(e['publisher_gid'] is not None for e in events if e['kind'] in ('ack','bspline','position')),
        'cpp_per_message_publisher_verified':bool(receipt_checks) and all(receipt_checks.values()),
        'source_provenance_verified':False, 'source_scope':'C++ receipts can identify publishers; native goal/session binding and live admission remain unproven',
        'flight_accepted':False,'px4_started':False,'sdk_started':False,'goals':requested,
        'processes_reaped':all(p.poll() is not None for _,p in processes),
        'native_shutdown_ok':native_shutdown_clean(events)}
    (output/'ros-ack-probe.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return int(bool(errors) or not checks or not all(checks.values()) or not result['processes_reaped'] or not result['native_shutdown_ok'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workspace',type=Path,default=Path('/home/muqiao/.cache/ros2-drone/ego_ws'))
    parser.add_argument('--domain-id',type=int,default=183)
    parser.add_argument('--receipt-witness',type=Path)
    parser.add_argument('--trajectory-executable',type=Path,
        help='Use an isolated copied trajectory server; default keeps the installed binary')
    parser.add_argument('--release-trajectory-publisher',action='store_true',
        help='Enable the optional publisher-release parameter on the copied server')
    args=parser.parse_args()
    return run(args.output.resolve(),args.workspace.resolve(),args.domain_id,args.receipt_witness,
        args.trajectory_executable,args.release_trajectory_publisher)

if __name__=='__main__':raise SystemExit(main())
