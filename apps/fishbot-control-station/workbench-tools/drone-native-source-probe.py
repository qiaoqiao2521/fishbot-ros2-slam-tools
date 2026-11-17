#!/usr/bin/env python3
"""Reproduce source/ID reuse with ROS publishers and native traj_server; no vehicle."""
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
import uuid

sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parent


def producer(name, prefix):
    import rclpy
    from geometry_msgs.msg import Point
    from std_msgs.msg import String
    from traj_utils.msg import Bspline
    rclpy.init()
    node = rclpy.create_node(name)
    ack = node.create_publisher(String, prefix+'/ack', 10)
    curve = node.create_publisher(Bspline, prefix+'/bspline', 10)
    try:
        deadline = time.monotonic()+5.
        while time.monotonic() < deadline and (curve.get_subscription_count() < 3 or ack.get_subscription_count() < 2):
            rclpy.spin_once(node, timeout_sec=.02)
        for line in sys.stdin:
            request = json.loads(line)
            if request.get('ack'):
                ack.publish(String(data=str(request.get('stamp_ns',123))+':0'))
            msg = Bspline()
            msg.order, msg.traj_id, msg.start_time.sec = 3, 1, 10
            msg.knots = [-30., -20., -10., 0., 10., 20., 30., 40., 50., 60.]
            msg.pos_pts = [Point(x=request['offset']+.2*i, y=0., z=1.) for i in range(6)]
            curve.publish(msg)
            rclpy.spin_once(node, timeout_sec=.02)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


def run(output, domain, source_graph_guard=False, native_receipts=False):
    import rclpy
    from rosgraph_msgs.msg import Clock
    from std_msgs.msg import String
    from traj_utils.msg import Bspline
    from quadrotor_msgs.msg import PositionCommand
    sys.path.insert(0, str(TOOLS.parent/'workbench-review-tests'))
    import test_drone_command_epoch_patch as epochs
    from test_drone_ack_curve_buffer import AckHarness
    import test_drone_command_validity as original
    import types

    output.mkdir(parents=True, exist_ok=True)
    os.environ.update(ROS_DOMAIN_ID=str(domain), ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
    prefix = '/drone_source_probe_'+uuid.uuid4().hex[:10]
    events, owned, handles, stages, errors = [], [], [], [], []
    queued_check = None
    epochs.CommandEpochPatch.setUpClass()
    fixture = epochs.CommandEpochPatch()
    h = AckHarness(fixture, output/'sidecar')
    source_graph_guard = source_graph_guard or native_receipts
    if native_receipts:
        h.node.command_epoch.native_receipts_enabled=True
        h.node.active_goal=h.node.setpoint=None
    sim = 10.15
    rclpy.init()
    node = rclpy.create_node('source_observer_'+uuid.uuid4().hex[:8])
    clock = node.create_publisher(Clock, prefix+'/clock', 10)
    if source_graph_guard:
        h.node.command_epoch.source_graph_enabled=True
        h.node.source_expected_nodes={'ack':'expected_source','bspline':'expected_source','position':'traj_server'}
        mapping={'/drone/ego/goal_ack':'ack','/drone/ego/bspline':'bspline','/drone/ego/position_cmd':'position'}
        h.node.get_publishers_info_by_topic=lambda topic: node.get_publishers_info_by_topic(prefix+'/'+mapping[topic])
        for name,method in original.methods(fixture.root/'ego/sidecar.py',
            'Sidecar',('observe_source_graph','invalidate_command_source','consume_native_receipts'),h.node.state.__func__.__globals__).items():
            setattr(h.node,name,types.MethodType(method,h.node))

    def record(kind, **fields):
        item = dict(kind=kind, host_monotonic_ns=time.monotonic_ns(), **fields)
        events.append(item)
        return item

    def callback(kind):
        def receive(msg, info):
            if kind == 'ack':
                body = {'data': msg.data}
                if not native_receipts:h.node.on_goal_ack(msg)
            elif kind == 'bspline':
                body = {'traj_id': msg.traj_id, 'order': msg.order,
                    'start_sim_s': msg.start_time.sec+msg.start_time.nanosec*1e-9,
                    'knots': list(msg.knots), 'control_points': [[p.x,p.y,p.z] for p in msg.pos_pts]}
                if not native_receipts:h.node.on_bspline(msg)
            else:
                body = {'trajectory_id': msg.trajectory_id,
                    'stamp_sim_s': msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,
                    **{key: [getattr(getattr(msg,key),axis) for axis in ('x','y','z')]
                       for key in ('position','velocity','acceleration')}, 'yaw': msg.yaw}
                if not native_receipts:h.node.on_command(msg)
            field = info.get if isinstance(info,dict) else lambda key: getattr(info,key,None)
            record(kind, message=body, source_timestamp=field('source_timestamp'),
                publication_sequence_number=field('publication_sequence_number'),
                sidecar_setpoint=copy.deepcopy(h.node.setpoint))
        return receive

    subs = [node.create_subscription(typ,prefix+'/'+kind,callback(kind),50)
            for kind,typ in [('ack',String),('bspline',Bspline),('position',PositionCommand)]]

    def start(role, argv, stdin=False):
        handle = (output/(role+'.log')).open('w'); handles.append(handle)
        process = subprocess.Popen(argv,stdout=handle,stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE if stdin else subprocess.DEVNULL,text=True)
        owned.append((role,process))
        record('process_start',role=role,pid=process.pid,
            start_ticks=Path(f'/proc/{process.pid}/stat').read_text().rsplit(') ',1)[1].split()[19],argv=argv)
        return process

    def stop(role, process):
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try: process.wait(timeout=3.)
            except subprocess.TimeoutExpired: process.terminate(); process.wait(timeout=3.)
        if process.stdin: process.stdin.close()
        record('process_exit',role=role,pid=process.pid,exit_code=process.returncode,
               proc_absent=not Path(f'/proc/{process.pid}').exists())

    def pump(predicate, seconds=5.):
        nonlocal sim
        deadline, next_clock = time.monotonic()+seconds, 0.
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now >= next_clock:
                sim += .02; h.clock.sim = sim
                # Explicitly synthetic healthy sensing isolates source admission
                # from the unchanged depth/odometry freshness gates.
                h.node.odom_stamp = h.node.depth_stamp = sim
                stamp = int(round(sim*1e9)); msg = Clock()
                msg.clock.sec, msg.clock.nanosec = divmod(stamp,10**9)
                clock.publish(msg); next_clock = now+.02
            rclpy.spin_once(node,timeout_sec=.005)
            if native_receipts:h.node.consume_native_receipts()
            if predicate is not None and predicate(): return
        if predicate is not None:
            raise TimeoutError('source probe condition not observed')

    def graph():
        return {kind: [dict(node_name=e.node_name,endpoint_gid=bytes(e.endpoint_gid).hex())
            for e in node.get_publishers_info_by_topic(prefix+'/'+kind)]
            for kind in ('ack','bspline','position')}

    def publish_stage(label, process, offset, source_name, ack=False, stamp_ns=123, keep=True):
        begin = time.monotonic_ns()
        process.stdin.write(json.dumps({'offset':offset,'ack':ack,'stamp_ns':stamp_ns})+'\n'); process.stdin.flush()
        adopt = not source_graph_guard or label in ('expected_source','new_goal_after_restart')
        pump(lambda: any(e['kind']=='position' and e['host_monotonic_ns']>=begin and
            offset <= e['message']['position'][0] < offset+2. and
            (not adopt or native_receipts and h.node.setpoint is not None and offset <= h.node.setpoint['position'][0] < offset+2. or
             e['sidecar_setpoint'] is not None and e['sidecar_setpoint']['position']==e['message']['position'])
            for e in events))
        pump(lambda: any(e['node_name']==source_name for e in graph()['bspline']))
        state=h.node.state()
        stage=dict(label=label,offset=offset,begin_host_ns=begin,end_host_ns=time.monotonic_ns(),
            graph=graph(),setpoint=copy.deepcopy(h.node.setpoint),sidecar_state=state,
            active_goal=copy.deepcopy(h.node.active_goal))
        if keep:stages.append(stage)
        return stage

    try:
        binary = Path('/home/muqiao/.cache/ros2-drone/ros-ack-witness-build')
        witness_args=[str(binary/'drone_ros_ack_witness'),'--ros-args','-p','prefix:='+prefix]
        if native_receipts:witness_args+=['-p','emit_heartbeat:=true']
        witness=start('witness',witness_args)
        if native_receipts:
            spec=importlib.util.spec_from_file_location('native_ingress',fixture.root/'native_receipts.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            h.node.native_receipts=module.NativeReceipts(output/'witness.log')
            h.node.native_receipts.process=witness
        start('trajectory',[str(binary/'drone_traj_lifetime_probe'),'--ros-args','-p','use_sim_time:=true',
            '-p','traj_server/time_forward:=0.6','-p','diagnostics/release_publisher_on_exit:=true',
            '-r','/clock:='+prefix+'/clock',
            '-r','planning/bspline:='+prefix+'/bspline','-r','/position_cmd:='+prefix+'/position'])
        a = start('producer_a',[sys.executable,__file__,'--producer-name','expected_source','--prefix',prefix],True)
        if source_graph_guard:
            pump(lambda: all(len(graph()[kind])==1 and graph()[kind][0]['node_name']==name
                for kind,name in h.node.source_expected_nodes.items()))
            h.node.observe_source_graph()
        if native_receipts:
            pump(lambda:h.node.native_receipts.reason() is None)
            reply=fixture.post(h.node,'/goal',dict(x=5.,y=0.,z=1.,task_id='task-A',goal_id='goal-A'))
            if reply[0][0]!=202:raise RuntimeError('Native ingress startup was not ready')
        publish_stage('expected_source',a,0.,'expected_source',True,h.node.goal_stamp_ns)
        b = start('producer_b',[sys.executable,__file__,'--producer-name','other_source','--prefix',prefix],True)
        publish_stage('second_source_same_id',b,10.,'other_source')
        stop('producer_b',b)
        b2 = start('producer_b_restarted',[sys.executable,__file__,'--producer-name','other_source','--prefix',prefix],True)
        publish_stage('restarted_source_same_name_and_id',b2,20.,'other_source')
        stop('producer_b_restarted',b2)
        stop('producer_a',a)
        a2 = start('producer_a_restarted',[sys.executable,__file__,'--producer-name','expected_source','--prefix',prefix],True)
        publish_stage('expected_source_restarted_without_new_goal_ack',a2,30.,'expected_source')
        if source_graph_guard:
            if native_receipts:
                # Graph discovery can precede the C++ subscriber's actual match.
                pump(lambda:h.node.native_receipts.reason() is None)
            reply=fixture.post(h.node,'/goal',dict(x=5.,y=0.,z=1.,task_id='task-A',goal_id='goal-B'))
            if reply[0][0]!=202:raise RuntimeError('Restored source did not allow a fresh goal')
            publish_stage('new_goal_after_restart',a2,30.,'expected_source',True,h.node.goal_stamp_ns)
        if native_receipts:
            queued = start('producer_queued',[sys.executable,__file__,'--producer-name','other_source','--prefix',prefix],True)
            publish_stage('queue_source',queued,40.,'other_source',keep=False)
            wire=[json.loads(line) for line in (output/'witness.log').read_text().splitlines() if line.startswith('{')]
            packet=next(r for r in reversed(wire) if r['kind']=='bspline' and r['message']['control_points'][0][0]==40.)
            stop('producer_queued',queued)
            pump(lambda:all(len(graph()[k])==1 and graph()[k][0]['node_name']==v for k,v in h.node.source_expected_nodes.items())
                 and h.node.native_receipts.reason() is None)
            reply=fixture.post(h.node,'/goal',dict(x=5.,y=0.,z=1.,task_id='task-A',goal_id='goal-C'))
            if reply[0][0]!=202:raise RuntimeError('Healthy source did not admit goal-C')
            fresh=publish_stage('new_goal_after_restart',a2,30.,'expected_source',True,h.node.goal_stamp_ns,False)
            old_epoch=h.node.command_epoch.token
            age_ns=time.monotonic_ns()-packet['host_monotonic_ns']
            # Controlled delayed delivery of the ORIGINAL C++ envelope. Neither
            # its receipt/source time nor its GID/sequence is rewritten.
            h.node.native_receipts.feed(h.node,copy.deepcopy(packet))
            queued_check=dict(scope='controlled delayed delivery, not observed network reordering',
                packet=packet,age_ns=age_ns,graph=graph(),fresh_goal_point=fresh['setpoint'],
                active_goal_after=copy.deepcopy(h.node.active_goal),point_after=copy.deepcopy(h.node.setpoint),
                epoch_changed=h.node.command_epoch.token!=old_epoch,last_error=h.node.native_receipts.last_error)
        pump(None, .2)
    except Exception as error:
        errors.append(type(error).__name__+': '+str(error))
    finally:
        stopped={e['pid'] for e in events if e['kind']=='process_exit'}
        for role,process in reversed(owned):
            if process.pid not in stopped:
                try: stop(role,process)
                except Exception as error: errors.append('cleanup '+role+': '+str(error))
        node.destroy_node(); rclpy.try_shutdown()
        for handle in handles: handle.close()
        epochs.CommandEpochPatch.tearDownClass()
        (output/'ros-events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    receipts=[json.loads(line) for line in (output/'witness.log').read_text().splitlines() if line.startswith('{')]
    def matches(e):
        return [r for r in receipts if r['kind']==e['kind'] and
            (r['source_timestamp'],r['publication_sequence_number'])==
            (e['source_timestamp'],e['publication_sequence_number']) and r['message']==e['message']]
    curves=[]
    for stage in stages:
        selected=[e for e in events if e['kind']=='bspline' and
            stage['begin_host_ns']<=e['host_monotonic_ns']<=stage['end_host_ns'] and
            e['message']['control_points'][0][0]==stage['offset']]
        joined=[r for e in selected for r in matches(e)]
        curves.append(dict(label=stage['label'],count=len(selected),cpp_matches=len(joined),
            gids=sorted({r['publisher_gid'] for r in joined})))
    result={'scope':'real ROS publisher processes and native trajectory server; synthetic curves and Sidecar state',
        'source_graph_guard':source_graph_guard,
        'native_receipts':native_receipts,
        'source_provenance_verified':False,'flight_accepted':False,'sdk_started':False,'px4_started':False,
        'errors':errors,'stages':stages,'curve_receipts':curves,'checks':{
            'all_stages':len(stages)==(5 if source_graph_guard else 4),
            'full_curve_receipts_join':bool(curves) and all(c['count']==c['cpp_matches']==1 for c in curves),
            'four_distinct_curve_publishers':len(curves)>3 and len({g for c in curves for g in c['gids']})==4,
            'native_position_publisher_unchanged':len(stages)>3 and len({e['endpoint_gid'] for s in stages for e in s['graph']['position']})==1,
            'all_native_exit_zero':len(owned)==(7 if native_receipts else 6) and
                {p.pid for _,p in owned}=={e['pid'] for e in events if e['kind']=='process_exit'} and
                all(e['exit_code']==0 and e['proc_absent'] for e in events if e['kind']=='process_exit')}}
    if source_graph_guard:
        result['checks'].update(
            expected_source_admitted=bool(stages) and stages[0]['setpoint'] is not None,
            observed_faults_clear_old_goal=len(stages)==5 and all(s['setpoint'] is None and s['active_goal'] is None for s in stages[1:4]),
            fresh_goal_ack_readmits_expected_source=len(stages)==5 and stages[4]['setpoint'] is not None and stages[4]['setpoint']['goal_id']=='goal-B')
        if native_receipts:
            result['native_receipt_diagnostics']=h.node.native_receipts.diagnostics()
            result['queued_source_check']=queued_check
            result['checks']['native_ingress_admitted_pva']=h.node.native_receipts.counts['admitted_position']>0
            result['checks']['fresh_queued_source_rejected_after_graph_recovery']=bool(queued_check) and (
                0 <= queued_check['age_ns'] <= 2_000_000_000 and queued_check['fresh_goal_point'] is not None and
                queued_check['fresh_goal_point']['goal_id']=='goal-C' and queued_check['point_after'] is None and
                queued_check['active_goal_after'] is None and queued_check['epoch_changed'] and
                queued_check['last_error']=='native_receipt_source_mismatch_bspline')
    else:
        result['checks'].update(
            same_goal_label_incorrectly_inherited=len(stages)==4 and len({(s['setpoint']['task_id'],s['setpoint']['goal_id']) for s in stages})==1,
            sidecar_ready_with_synthetic_healthy_inputs=len(stages)==4 and all(s['sidecar_state']['ready'] for s in stages))
    (output/'native-source-probe.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return int(bool(errors) or not all(result['checks'].values()))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--domain-id',type=int,default=186)
    parser.add_argument('--producer-name')
    parser.add_argument('--prefix')
    parser.add_argument('--source-graph-guard',action='store_true')
    parser.add_argument('--native-receipts',action='store_true')
    args=parser.parse_args()
    if args.producer_name:
        return producer(args.producer_name,args.prefix)
    if args.output is None: parser.error('--output is required for the probe')
    return run(args.output.resolve(),args.domain_id,args.source_graph_guard,args.native_receipts)


if __name__=='__main__':raise SystemExit(main())
