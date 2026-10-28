#!/usr/bin/env python3
"""Actual temporary Sidecar + HTTP + native planner/receipts, synthetic sensing; no flight."""
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from urllib.request import Request,urlopen
import uuid

sys.dont_write_bytecode=True
TOOLS=Path(__file__).resolve().parent


def run(output,domain):
    import rclpy
    from geometry_msgs.msg import TransformStamped
    from tf2_msgs.msg import TFMessage
    from rosgraph_msgs.msg import Clock
    from sensor_msgs.msg import PointCloud2
    from sensor_msgs_py.point_cloud2 import create_cloud_xyz32
    from std_msgs.msg import Header
    from http.server import ThreadingHTTPServer
    import threading
    sys.path.insert(0,str(TOOLS.parent/'workbench-review-tests'))
    from test_drone_command_revalidation_patch import copy_source,apply

    output.mkdir(parents=True,exist_ok=True)
    os.environ.update(DRONE_NATIVE_RECEIPTS='1',ROS_DOMAIN_ID=str(domain),ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
    events,errors=[],[]
    node=observer=server=worker=None
    result={'scope':'actual Sidecar/HTTP/native planner with ideal ROS poses, explicit cloud and synthetic camera/depth health',
            'sdk_started':False,'px4_started':False,'flight_accepted':False,'goals':[]}
    with tempfile.TemporaryDirectory() as directory:
        tmp=Path(directory);copy_source(tmp);apply(tmp,TOOLS/'patches/drone-command-epoch.patch')
        (tmp/'ego/planner.yaml').write_bytes(Path('/home/muqiao/dev/ros2/projects/drone/ego/planner.yaml').read_bytes())
        sys.path[:0]=[str(tmp/'ego'),'/home/muqiao/dev/ros2/projects/drone/ego',str(tmp)]
        spec=importlib.util.spec_from_file_location('sidecar_native_runtime',tmp/'ego/sidecar.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        main=next(n for n in ast.parse((tmp/'ego/sidecar.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='main')
        prefix=[]
        for statement in main.body:
            if isinstance(statement,ast.Expr) and isinstance(statement.value,ast.Call) and isinstance(statement.value.func,ast.Attribute) and statement.value.func.attr=='init':break
            prefix.append(statement)
        previous_argv=sys.argv;sys.argv=['sidecar','--no-bridge','--runtime',str(output/'runtime')]
        try:exec(compile(ast.Module(body=prefix,type_ignores=[]),'sidecar-parser','exec'),module.__dict__)
        finally:sys.argv=previous_argv
        rclpy.init(args=[])
        sim=10.
        try:
            node=module.Sidecar(module.args)
            spawn=node.spawn
            def selected_spawn(role,command):
                if role=='trajectory':
                    command=['/home/muqiao/.cache/ros2-drone/ros-ack-witness-build/drone_traj_lifetime_probe']+command[4:]+[
                        '-p','diagnostics/release_publisher_on_exit:=true']
                return spawn(role,command)
            node.spawn=selected_spawn
            observer=rclpy.create_node('sidecar_input_'+uuid.uuid4().hex[:8])
            clock=observer.create_publisher(Clock,'/clock',10)
            poses=observer.create_publisher(TFMessage,'/drone/gz/poses',10)
            cloud=observer.create_publisher(PointCloud2,'/grid_map/cloud',10)
            node.intrinsics=dict(fx=100.,fy=100.,cx=32.,cy=24.,width=64,height=48)
            node_class=next(n for n in main.body if isinstance(n,ast.ClassDef) and n.name=='Handler')
            module.__dict__['node']=node
            exec(compile(ast.Module(body=[node_class],type_ignores=[]),'actual-handler','exec'),module.__dict__)
            server=ThreadingHTTPServer(('127.0.0.1',0),module.Handler)
            worker=threading.Thread(target=lambda:server.serve_forever(poll_interval=.02),daemon=True);worker.start()
            result['http_port']=server.server_port

            def pump(predicate,seconds=12.):
                nonlocal sim
                until,next_input=time.monotonic()+seconds,0.
                while time.monotonic()<until:
                    now=time.monotonic()
                    if now>=next_input:
                        sim+=.02;ns=int(round(sim*1e9));c=Clock();c.clock.sec,c.clock.nanosec=divmod(ns,10**9)
                        clock.publish(c)
                        transform=TransformStamped();transform.header=Header(stamp=c.clock,frame_id='world')
                        transform.child_frame_id=module.args.model;transform.transform.translation.z=1.;transform.transform.rotation.w=1.
                        poses.publish(TFMessage(transforms=[transform]))
                        cloud.publish(create_cloud_xyz32(transform.header,[(5.,5.,1.)]))
                        # Deliberate input substitutions isolate the control/receipt path.
                        node.depth_stamp=sim;node.depth_wall=now
                        next_input=now+.02
                    rclpy.spin_once(node,timeout_sec=.005)
                    rclpy.spin_once(observer,timeout_sec=0.)
                    if predicate():return
                raise TimeoutError('actual Sidecar condition not reached: '+json.dumps(node.state()))

            pump(lambda:node.state()['ready'])
            # WAIT_TARGET is native evidence that the planner has consumed odometry.
            # The opt-in candidate must enforce this without a probe-only wait.
            result['startup_state']=node.state()
            result['owned_subscription_topics']=[s.topic_name for s in node.subscriptions]
            task=str(uuid.uuid4())
            for target in ([2.,0.,1.],[0.,2.,1.]):
                goal=str(uuid.uuid4());body=dict(x=target[0],y=target[1],z=target[2],task_id=task,goal_id=goal)
                request=Request(f'http://127.0.0.1:{server.server_port}/goal',json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                with urlopen(request,timeout=2.) as response:
                    status=response.status;reply=json.load(response)
                pump(lambda:node.state()['ready'] and node.setpoint is not None and node.setpoint.get('goal_id')==goal)
                with urlopen(f'http://127.0.0.1:{server.server_port}/state',timeout=2.) as response:state=json.load(response)
                result['goals'].append(dict(target=target,goal_id=goal,http_status=status,reply=reply,state=state))
            result['native_diagnostics']=node.native_receipts.diagnostics()
            result['components']=node.component_processes
            result['checks']=dict(two_actual_http_goals=len(result['goals'])==2,
                startup_has_native_odometry=result['startup_state']['planner_state']=='WAIT_TARGET',
                all_http_accepted=all(g['http_status']==202 for g in result['goals']),
                no_legacy_subscriptions=not set(result['owned_subscription_topics'])&{'/drone/ego/position_cmd','/drone/ego/bspline','/drone/ego/goal_ack'},
                all_goal_epochs_match=all(g['state']['setpoint']['command_epoch']==g['reply']['command_epoch'] for g in result['goals']),
                all_pva_have_cpp_receipts=all(all(g['state']['setpoint'].get('native_source',{}).get(k)
                    for k in ('ack','curve','position')) for g in result['goals']),
                pva_admitted=node.native_receipts.counts['admitted_position']>0)
        except Exception as error:
            errors.append(type(error).__name__+': '+str(error))
            if node:
                result['failure_state']=node.state();result['components']=getattr(node,'component_processes',{})
        finally:
            if server:server.shutdown();server.server_close()
            if worker:worker.join(timeout=2.)
            if node:
                try:node.close()
                except Exception as error:errors.append('cleanup: '+str(error))
                result['exits']=[dict(pid=p.pid,exit_code=p.poll(),absent=not Path('/proc/'+str(p.pid)).exists()) for p in node.processes]
                node.destroy_node()
            if observer:observer.destroy_node()
            rclpy.try_shutdown()
    result['errors']=errors
    result.setdefault('checks',{})['owned_native_exit_zero']=len(result.get('exits',[]))==3 and all(x['exit_code']==0 and x['absent'] for x in result['exits'])
    (output/'sidecar-native-probe.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(dict(output=str(output/'sidecar-native-probe.json'),
        checks=result['checks'],errors=errors,exits=result.get('exits',[])),indent=2))
    return int(bool(errors) or not all(result['checks'].values()))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--domain-id',type=int,default=188)
    args=p.parse_args();return run(args.output.resolve(),args.domain_id)


if __name__=='__main__':raise SystemExit(main())
