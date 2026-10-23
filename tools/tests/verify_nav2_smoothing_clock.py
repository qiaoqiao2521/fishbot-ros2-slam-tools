"""Native clock-only diagnostic; all velocity topics are private test remaps."""
import argparse,json,os,signal,subprocess,time
from pathlib import Path
import rclpy
from rclpy.parameter import Parameter,parameter_value_to_python
from rclpy.parameter_client import AsyncParameterClient
from lifecycle_msgs.srv import ChangeState
from lifecycle_msgs.msg import Transition
from rosgraph_msgs.msg import Clock
from builtin_interfaces.msg import Time
from geometry_msgs.msg import TwistStamped
from fishbot_simulation_suite import domain_is_empty


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not 0<=args.domain<=232:parser.error('--domain must be between 0 and 232')
    os.environ['ROS_DOMAIN_ID']=str(args.domain)
    os.environ['ROS_LOCALHOST_ONLY']='1'
    out=args.output.resolve();out.mkdir(parents=True,mode=0o700)
    domain_is_empty(timeout=5)
    rclpy.init(args=[])
    node=rclpy.create_node('smoother_clock_observer')
    clock=node.create_publisher(Clock,'/clock',10)
    command=node.create_publisher(TwistStamped,'/smoother_clock_probe/command',10)
    rows=[];begun=0.
    node.create_subscription(TwistStamped,'/smoother_clock_probe/output',lambda msg:rows.append({
     'source_stamp':msg.header.stamp.sec+msg.header.stamp.nanosec*1e-9,
     'elapsed_wall':time.monotonic()-begun,'v':msg.twist.linear.x,'w':msg.twist.angular.z}),1000)

    def value(future,timeout=5):
     rclpy.spin_until_future_complete(node,future,timeout_sec=timeout)
     if not future.done():raise TimeoutError('Native future unavailable')
     return future.result()
    def tick(seconds):
     sec,ns=divmod(round(seconds*1e9),1_000_000_000)
     clock.publish(Clock(clock=Time(sec=sec,nanosec=ns)))
    def slope(items,key):
     xs=[x['source_stamp'] for x in items];ys=[x[key] for x in items]
     mx=sum(xs)/len(xs);my=sum(ys)/len(ys)
     return sum((x-mx)*(y-my) for x,y in zip(xs,ys))/sum((x-mx)**2 for x in xs)
    results=[]
    try:
     for ros in (False,True):
      name='clock_ros_smoother' if ros else 'clock_wall_smoother'
      log=(out/(name+'.log')).open('x');params={'use_sim_time':True,'use_ros_time_for_smoothing':ros,
       'smoothing_frequency':20.,'enable_stamped_cmd_vel':True,
       'stamp_smoothed_velocity_with_smoothing_time':True,'velocity_timeout':1.,
       'max_velocity':[.06,0.,.1],'min_velocity':[-.06,0.,-.1],
       'max_accel':[.025,0.,.05],'max_decel':[-.025,0.,-.05]}
      args=['ros2','run','nav2_velocity_smoother','velocity_smoother','--ros-args','-r','__node:='+name,
            '-r','cmd_vel:=/smoother_clock_probe/command','-r','cmd_vel_smoothed:=/smoother_clock_probe/output']
      for k,v in params.items():args+=['-p',k+':='+json.dumps(v)]
      proc=subprocess.Popen(args,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
      try:
       lifecycle=node.create_client(ChangeState,'/'+name+'/change_state')
       if not lifecycle.wait_for_service(timeout_sec=8):raise RuntimeError('Native lifecycle unavailable')
       tick(5.)
       for _ in range(10):rclpy.spin_once(node,timeout_sec=.02)
       for transition in (Transition.TRANSITION_CONFIGURE,Transition.TRANSITION_ACTIVATE):
        request=ChangeState.Request();request.transition.id=transition
        if not value(lifecycle.call_async(request)).success:raise RuntimeError('Native lifecycle rejected transition')
       pc=AsyncParameterClient(node,'/'+name);pc.wait_for_services(timeout_sec=5)
       keys=list(params);actual=dict(zip(keys,[parameter_value_to_python(v) for v in value(pc.get_parameters(keys)).values]))
       rows.clear();begun=time.monotonic();next_tick=begun;changed=False
       while time.monotonic()-begun<6.4:
        wall=time.monotonic()-begun
        if time.monotonic()>=next_tick:
         source=5.+int((wall-min(max(wall-1.,0.),.4)-min(max(wall-3.3,0.),.3))/.02)*.01
         if not (1.<=wall<1.4 or 3.3<=wall<3.6):tick(source)
         sec,ns=divmod(round(source*1e9),1_000_000_000)
         msg=TwistStamped();msg.header.stamp=Time(sec=sec,nanosec=ns);msg.twist.linear.x=.06;msg.twist.angular.z=.1
         command.publish(msg);next_tick+=.02
        if wall>2.6 and not changed:
         reply=value(pc.set_parameters([Parameter('smoothing_frequency',value=25.)]));changed=all(x.successful for x in reply.results)
        rclpy.spin_once(node,timeout_sec=.001)
       early=[x for x in rows if .15<x['elapsed_wall']<.9]
       result={'ros_time':ros,'parameters':actual,'samples':list(rows),
         'early_source_v_accel':slope(early,'v'),'early_source_w_accel':slope(early,'w'),
         'clock_pause_outputs':sum(1 for x in rows if 1.06<x['elapsed_wall']<1.36),
         'dynamic_pause_outputs':sum(1 for x in rows if 3.36<x['elapsed_wall']<3.56),
         'dynamic_source_w_accel':slope([x for x in rows if 2.8<x['elapsed_wall']<3.2],'w') if ros else None,
         'dynamic_frequency_25hz_accepted':changed,'navigation_goals':0,'actuator_topic_published':False}
       result['diagnostic_passed']=(abs(result['early_source_v_accel']-(.025 if ros else .05))<.008 and
        abs(result['early_source_w_accel']-(.05 if ros else .10))<.016 and changed and
        (result['clock_pause_outputs']<=1 if ros else result['clock_pause_outputs']>=3) and
        (result['dynamic_pause_outputs']<=1 and abs(result['dynamic_source_w_accel']-.05)<.016
         if ros else result['dynamic_pause_outputs']>=2))
       results.append(result);print(json.dumps({k:v for k,v in result.items() if k not in ('samples','parameters')}),flush=True)
      finally:
       os.killpg(proc.pid,signal.SIGINT)
       try:proc.wait(timeout=5)
       except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=5)
       log.close()
    finally:
     node.destroy_node();rclpy.try_shutdown()
     (out/'result.json').write_text(json.dumps({'cases':results,'passed':len(results)==2 and all(x['diagnostic_passed'] for x in results)},indent=2)+'\n')

    domain_is_empty(timeout=5)
    return 0 if len(results)==2 and all(x['diagnostic_passed'] for x in results) else 1

if __name__ == '__main__':
    raise SystemExit(main())
