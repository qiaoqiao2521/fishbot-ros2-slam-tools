#!/usr/bin/env python3
"""Native smoother plus recorded-state physics: old header versus fresh stop targets."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def main(manifest_file, fixture_file, output_dir):
    os.environ.update(ROS_DOMAIN_ID='147',FISHBOT_MUJOCO_DOMAIN_ID='147',
        ROS_LOCALHOST_ONLY='1',ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST')
    import rclpy
    from builtin_interfaces.msg import Time
    from geometry_msgs.msg import TwistStamped
    from lifecycle_msgs.srv import ChangeState
    from lifecycle_msgs.msg import Transition
    from rclpy.parameter_client import AsyncParameterClient
    from rclpy.parameter import parameter_value_to_python
    from rosgraph_msgs.msg import Clock
    from cooperation_sim import Physics
    from cooperation_core import cargo_retained,stopped
    from fishbot_simulation_suite import domain_is_empty
    from f1_compute import restore
    from ament_index_python.packages import get_package_prefix
    prefix=Path(get_package_prefix('nav2_velocity_smoother'))
    executable=prefix/'lib/nav2_velocity_smoother/velocity_smoother'
    manifest=json.loads(Path(manifest_file).read_text());fixture=json.loads(Path(fixture_file).read_text())
    output=Path(output_dir);output.mkdir(parents=True,exist_ok=True)
    domain_is_empty(timeout=5);rclpy.init(args=[])
    node=rclpy.create_node('terminal_stop_native_observer')
    clock=node.create_publisher(Clock,'/clock',10)
    def stamp(value):
        sec,ns=divmod(round(value*1e9),1_000_000_000)
        return Time(sec=sec,nanosec=ns)
    def tick(value):clock.publish(Clock(clock=stamp(value)))
    def resolve(future):
        rclpy.spin_until_future_complete(node,future,timeout_sec=8)
        if not future.done():raise TimeoutError('Native response unavailable')
        return future.result()
    cases=[]
    try:
        for fresh in (False,True):
            name='terminal_fresh' if fresh else 'terminal_old'
            physics=Physics(Path(manifest['world_xml']),manifest=Path(manifest_file))
            restore(physics,fixture);physics.data.time=12.
            physics.wheels.set_hold(False)
            command=node.create_publisher(TwistStamped,'/'+name+'/in',10)
            accepted=[];rejected=[];recording=False;native_rows=[]
            def receive(msg):
                native_rows.append({'t':msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,
                                    'v':msg.twist.linear.x,'w':msg.twist.angular.z})
                if not recording:return
                try:
                    physics.wheels.accept(msg.twist.linear.x,msg.twist.angular.z,time.monotonic(),
                        source_stamp=native_rows[-1]['t'],sim_now=physics.data.time)
                    accepted.append(dict(native_rows[-1],at=float(physics.data.time)))
                except ValueError as exc:
                    rejected.append({'at':float(physics.data.time),'reason':str(exc),**native_rows[-1]})
            sub=node.create_subscription(TwistStamped,'/'+name+'/out',receive,1000)
            params={'use_sim_time':True,'use_ros_time_for_smoothing':True,'smoothing_frequency':50.,
                'enable_stamped_cmd_vel':True,'stamp_smoothed_velocity_with_smoothing_time':False,
                'velocity_timeout':1.,'feedback':'OPEN_LOOP','scale_velocities':True,
                'max_velocity':[.06,0.,.1],'min_velocity':[-.06,0.,-.1],
                'max_accel':[.025,0.,.05],'max_decel':[-.025,0.,-.05]}
            args=[str(executable),'--ros-args','-r','__node:='+name,
                  '-r','cmd_vel:=/'+name+'/in','-r','cmd_vel_smoothed:=/'+name+'/out']
            for key,value in params.items():args+=['-p',key+':='+json.dumps(value)]
            process=life=None
            try:
                with (output/(name+'.log')).open('w') as log:
                    process=subprocess.Popen(args,start_new_session=True,stdout=log,stderr=subprocess.STDOUT)
                    life=node.create_client(ChangeState,'/'+name+'/change_state')
                    if not life.wait_for_service(timeout_sec=10):raise TimeoutError('Native lifecycle unavailable')
                    for value in (Transition.TRANSITION_CONFIGURE,Transition.TRANSITION_ACTIVATE):
                        req=ChangeState.Request();req.transition.id=value
                        if not resolve(life.call_async(req)).success:raise RuntimeError('Native lifecycle rejected')
                    pc=AsyncParameterClient(node,'/'+name);pc.wait_for_services(timeout_sec=5)
                    actual=dict(zip(params,[parameter_value_to_python(p) for p in resolve(pc.get_parameters(list(params))).values]))
                    maps=[line for line in Path('/proc/'+str(process.pid)+'/maps').read_text().splitlines()
                          if 'nav2_velocity_smoother' in line]
                    begun=time.monotonic();next_tick=begun
                    while time.monotonic()-begun<4.:
                        source=10.+min((time.monotonic()-begun)*.5,2.)
                        if time.monotonic()>=next_tick:
                            tick(source);msg=TwistStamped();msg.header.stamp=stamp(source)
                            msg.twist.linear.x=.03;command.publish(msg);next_tick+=.04
                        rclpy.spin_once(node,timeout_sec=.001)
                    if not native_rows or abs(native_rows[-1]['v']-.03)>.001:
                        raise RuntimeError('Native warmup did not establish the recorded .03 m/s target')
                    physics.wheels.accept(.03,0.,time.monotonic(),source_stamp=12.,sim_now=12.)
                    stop=TwistStamped();stop.header.stamp=stamp(12.);command.publish(stop);tick(12.)
                    recording=True;rows=[];floor_gaps_500hz=0;begun=time.monotonic()
                    for step in range(1500):
                        if step%10==0:
                            tick(float(physics.data.time))
                            if fresh:
                                stop=TwistStamped();stop.header.stamp=stamp(float(physics.data.time));command.publish(stop)
                        for _ in range(2):rclpy.spin_once(node,timeout_sec=0.)
                        physics.step()
                        floor_gaps_500hz+=not physics.contacts['cargo_tray_floor_contact']
                        if step%10==9:
                            raw=physics.state();rows.append({'t':raw['stamp'],'retained':cargo_retained(raw),
                                'floor':raw['cargo_tray_floor_contact'],'force_n':raw['cargo_tray_floor_normal_force_n'],
                                'stopped':stopped(raw),'speed':raw['car']['speed'],'ctrl':raw['ctrl'][6:]})
                        remaining=begun+(step+1)*.004-time.monotonic()
                        if remaining>0:time.sleep(remaining)
                    cases.append({'fresh_terminal_zero_targets':fresh,'parameters':actual,'native_maps':maps,
                        'accepted':accepted,'rejected':rejected,'samples':rows,
                        'retention_failures':sum(not r['retained'] for r in rows),
                        'floor_contact_gaps_500hz':floor_gaps_500hz,
                        'rejection_count':len(rejected),'final_stopped':all(r['stopped'] for r in rows[-36:]),
                        'wall_s':time.monotonic()-begun})
            finally:
                if process is not None and process.poll() is None:
                    os.killpg(process.pid,signal.SIGINT)
                    try:process.wait(timeout=8)
                    except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=5)
                node.destroy_subscription(sub);node.destroy_publisher(command)
                if life is not None:node.destroy_client(life)
    finally:
        node.destroy_node();rclpy.try_shutdown()
        result={'kind':'f1_native_terminal_stop_ab','task_acceptance':False,'navigation_goals':0,
            'actuator_topics_published':False,'fixture_origin':fixture.get('origin'),
            'boundary':'Reconstructed observation state with reset solver warmstart; not a full delivery replay.',
            'cases':cases,'passed':len(cases)==2 and all(c['native_maps'] for c in cases) and cases[0]['rejection_count']>0
                and cases[0]['floor_contact_gaps_500hz']>0 and cases[1]['floor_contact_gaps_500hz']==0
                and cases[1]['rejection_count']==0 and cases[1]['retention_failures']==0 and cases[1]['final_stopped']}
        result['timestamp_contract_passed']=(len(cases)==2 and cases[0]['rejection_count']>0
                                              and cases[1]['rejection_count']==0)
        result['reconstructed_physical_failure_reproduced']=(bool(cases)
            and (cases[0]['retention_failures']>0 or cases[0]['floor_contact_gaps_500hz']>0))
        (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    domain_is_empty(timeout=5)
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main(*sys.argv[1:]))
