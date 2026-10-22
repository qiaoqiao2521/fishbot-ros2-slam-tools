#!/usr/bin/env python3
"""Static preflight or one owned two-phase control probe, without transport."""
import argparse,collections,copy,json,math,os,signal,socket,subprocess,sys,time,traceback,uuid,urllib.request
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from cooperation_acceptance import private_json,ensure_port_available,stop_owned_launch
from cooperation_core import ContinuousEvidence,car_pose,physical_quiet
from cooperation_geometry_check import SceneGeometry
from fishbot_simulation_suite import domain_is_empty
from cooperation_readiness import snapshot_active
from fishbot_scene_validation import NavigationDiagnostics


def isolation_clearance(config, map_path, goals):
 """Choose an uncluttered fixture; inflation is NOT a hard collision boundary."""
 import numpy as np
 from PIL import Image
 map_path=Path(map_path)
 meta=yaml.safe_load(map_path.read_text())
 if meta.get('mode','trinary')!='trinary':
  raise ValueError('probe supports trinary source maps only')
 image_path=Path(meta['image'])
 if not image_path.is_absolute():image_path=map_path.parent/image_path
 with Image.open(image_path) as image:
  pixels=np.asarray(image.convert('L'),dtype=float)
 occupancy=pixels/255. if meta.get('negate',0) else (255.-pixels)/255.
 rows,columns=np.where(occupancy>float(meta['occupied_thresh']))
 if not len(rows):raise ValueError('source map has no occupied cells to compare')
 resolution=float(meta['resolution']);ox,oy,angle=meta['origin']
 local_x=(columns+.5)*resolution
 local_y=(pixels.shape[0]-1-rows+.5)*resolution
 xs=ox+math.cos(angle)*local_x-math.sin(angle)*local_y
 ys=oy+math.sin(angle)*local_x+math.cos(angle)*local_y
 local=config['local_costmap']['local_costmap']['ros__parameters']
 global_=config['global_costmap']['global_costmap']['ros__parameters']
 inflation=max(float(costmap['inflation_layer']['inflation_radius'])
               for costmap in (local,global_))
 # Subtract half a cell diagonal: compare with cell area, not just its center.
 cell_radius=resolution/math.sqrt(2)
 checks={}
 for phase,goal in goals.items():
  distance=float(np.hypot(xs-goal['x'],ys-goal['y']).min())
  checks[phase]={'nearest_occupied_cell_center_m':distance,
   'occupied_cell_area_distance_lower_bound_m':distance-cell_radius,
   'fixture_clearance_required_m':inflation+.02,
   'fixture_clearance_passed':distance-cell_radius>inflation+.02,
   'native_collision_verdict':None,
   'scope':'fixture isolation preference; not Nav2 collision or path validation'}
 return checks


def declared_sweep(query, points):
 """Reuse original geometry over rotate/straight/rotate samples, no stepping."""
 footprint=query.manifest['car_footprint_xy']
 radius=max(math.hypot(*p) for p in footprint)
 minimum=.20;bound=0.;count=0;wall_clearance=math.inf;witness=None
 for start,end in zip(points,points[1:]):
  heading=math.atan2(end['y']-start['y'],end['x']-start['x'])
  turned={**start,'yaw':heading};arrived={**end,'yaw':heading}
  for a,b in ((start,turned),(turned,arrived),(arrived,end)):
   dyaw=math.atan2(math.sin(b['yaw']-a['yaw']),math.cos(b['yaw']-a['yaw']))
   distance=math.hypot(b['x']-a['x'],b['y']-a['y'])
   steps=max(1,math.ceil(distance/.01),math.ceil(abs(dyaw)/.05))
   bound=max(bound,(distance+radius*abs(dyaw))/(2*steps))
   for index in range(steps+1):
    f=index/steps
    pose={key:a[key]+f*(b[key]-a[key]) for key in ('x','y')}
    pose['yaw']=a['yaw']+f*dyaw
    check=query.check_pose(pose);count+=1
    if check.get('reason')=='scene_enclosure_geometry_unavailable':
     wall_clearance=-math.inf
    wall_clearance=min(wall_clearance,*(item['footprint_clearance_m']
                                       for item in check['scene_bounds']))
    if check['minimum_sampled_clearance_m']<minimum:
     minimum=check['minimum_sampled_clearance_m'];witness={'pose':pose,'pair':check['witness']}
 margin=minimum-bound
 return {'passed':wall_clearance>bound and margin>0,'minimum_sampled_clearance_m':minimum,
  'spacing_bound_m':bound,'certified_margin_m':margin,'sample_count':count,
 'witness':witness,'scope':'declared planar rotate-straight-rotate path only',
  'executed_nav2_path_validated':False,'physics_steps':0}


def phase_snapshot(node, entry, point):
 """Save observed data even if the result future never completes."""
 phase=entry['phase']
 entry['evidence_end_monotonic']=time.monotonic()
 entry['plan_publisher_gids']=sorted(node.gids[phase])
 entry['received_global_plans']=list(node.plan_messages[phase])
 entry['controller_commands']=list(node.commands[phase])
 entry['observed_message_counts']=dict(node.counts[phase])
 entry['samples_are_bounded']=True
 entry['retained_sample_counts']={'plans':len(node.plan_messages[phase]),
  'commands':len(node.commands[phase]),'physics':len(node.phase_samples[phase]),
  'amcl':len(node.amcl_samples[phase]),'transforms':len(node.transforms[phase])}
 entry['navigation_diagnostics']=node.navigation[phase].snapshot()
 entry['amcl_samples']=list(node.amcl_samples[phase])
 entry['transforms']=list(node.transforms[phase])
 entry['physical_samples']=list(node.phase_samples[phase])
 entry['controller_command_observed']=node.counts[phase]['nonzero_commands']>0
 entry['plan_receive_observed']=node.counts[phase]['plans']>0
 entry['no_forbidden_contacts_observed']=bool(node.counts[phase]['physics'] and
  node.counts[phase]['unsafe_or_missing_contact_samples']==0)
 entry['controller_instance_binding']=None
 if node.raw and node.phase==phase:
  pose=car_pose(node.raw);goal=point
  delta=math.atan2(math.sin(pose['yaw']-goal['yaw']),math.cos(pose['yaw']-goal['yaw']))
  entry['snapshot_truth_pose']=pose
  entry['truth_displacement_m']=math.hypot(pose['x']-entry['start_truth_pose']['x'],
                                         pose['y']-entry['start_truth_pose']['y'])
  entry['truth_goal_error']={'xy_m':math.hypot(pose['x']-goal['x'],pose['y']-goal['y']),
                             'yaw_rad':abs(delta)}
  entry['motion_observed']=entry['truth_displacement_m']>.02
 entry['control_loop_observed']=bool(entry['plan_receive_observed'] and
  entry['controller_command_observed'] and entry.get('motion_observed'))
 return entry


def attach_native_witness(report, path):
 """Attribute only actual DDS receipts in accepted goal windows."""
 events=[json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
 complete=not any(event.get('kind')=='overflow' for event in events)
 known={item['gid'] for item in report.get('plan_publishers',[])
        if item.get('node')=='controller_server'}
 phase_gids=[]
 for entry in report['goals']:
  start=entry.get('accepted_monotonic',math.inf)
  end=entry.get('evidence_end_monotonic',-math.inf)
  plans=[event for event in events if event.get('kind')=='plan' and
         start<=event['receive_monotonic']<=end]
  gids={event['publisher_gid'] for event in plans}
  phase_gids.append(gids)
  verified=bool(complete and len(gids)==1 and gids<=known and
                entry.get('control_loop_observed'))
  entry['native_plan_witness']={'plan_count':len(plans),'publisher_gids':sorted(gids),
   'complete':complete,'source':'rclcpp MessageInfo / rmw publisher_gid',
   'controller_endpoint_verified':verified}
  entry['controller_instance_binding']=({'publisher_gid':next(iter(gids)),
   'requested_behavior_tree':entry['requested_behavior_tree'],
   'basis':'exclusive native publisher in accepted goal window; explicit BT controller ID'}
   if verified else None)
 available=len(phase_gids)==2 and all(len(gids)==1 and gids<=known for gids in phase_gids)
 switched=bool(available and complete and phase_gids[0].isdisjoint(phase_gids[1]))
 report['phase_rpp_gid_switch_status']='observed' if switched else 'unverified'
 report['phase_rpp_activity_switch_observed']=switched
 report['native_plan_witness_complete']=complete
 report['native_plan_witness_events']=len(events)


def probe_goals(spawn, leg, heading_mode):
 """The aligned fixture isolates path tracking; fixed retains terminal turns."""
 staging={**copy.deepcopy(spawn),'x':spawn['x']-leg,'yaw':spawn['yaw']}
 default={**copy.deepcopy(spawn),'x':spawn['x']-2*leg,'yaw':spawn['yaw']+math.pi/2}
 if heading_mode=='aligned':
  staging['yaw']=default['yaw']=math.pi
 return staging,default


def compact_physics_sample(raw, received):
 """Keep identity in each sample; retain the large source manifest once per run."""
 return {'stamp':raw['stamp'],'car_hold':raw['car_hold'],
  'position':raw['car']['position'],'speed':raw['car']['speed'],
  'yaw_rate':raw['car']['yaw_rate'],'quaternion_wxyz':raw['car']['quaternion_wxyz'],
  'quiet':physical_quiet(raw),'episode_id':raw['source'].get('episode_id'),
  'car_forbidden_contact_count':raw.get('car_forbidden_contact_count'),
  'arm_forbidden_contact_count':raw.get('arm_forbidden_contact_count'),
  'receive_monotonic':received}


def record_phase_wait(node, entry, point, await_terminal, save):
 """Preserve this phase before a timeout propagates to native cancellation."""
 try:
  return await_terminal()
 finally:
  phase_snapshot(node,entry,point)
  save()

def readiness_ok(state,raw,pose_frame,action_ready,child_publishers):
 return bool(state.get("ready") is True and snapshot_active(state.get("native_lifecycle"))
  and raw and pose_frame=="map" and action_ready and child_publishers>0)

def fresh_pose_ok(stamp,previous,received,requested,source_now,wall_now):
 return all(math.isfinite(x) for x in (stamp,previous,received,requested,source_now,wall_now)) and (
  stamp>previous and received>=requested and 0<=source_now-stamp<=.5 and 0<=wall_now-received<=.5)


def phase_budget_reason(source_start, source_now, wall_start, wall_now,
                        max_source, max_wall):
 if source_now<source_start:return 'source clock moved backwards'
 if source_now-source_start>max_source:return 'source budget exceeded'
 if wall_now-wall_start>max_wall:return 'wall budget exceeded'
 return None

def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--manifest',type=Path,required=True)
 parser.add_argument('--output',type=Path,required=True)
 parser.add_argument('--domain',type=int,default=142)
 parser.add_argument('--port',type=int,default=9112)
 parser.add_argument('--leg-m',type=float,default=.25)
 parser.add_argument('--max-source-s',type=float,default=60.)
 parser.add_argument('--max-wall-s',type=float,default=70.)
 parser.add_argument('--heading-mode',choices=('fixed','aligned'),default='fixed',
  help='fixed reproduces terminal turns; aligned isolates tracking on the westward legs')
 parser.add_argument('--plan-witness-bin',type=Path,
  help='optional compiled read-only rclcpp DDS publisher witness')
 mode=parser.add_mutually_exclusive_group()
 mode.add_argument('--preflight-only',action='store_true',help='default: static checks without ROS')
 mode.add_argument('--run-native',action='store_true',help='run only in the allocated native resource window')
 args=parser.parse_args(argv)
 if not all(math.isfinite(value) and value>0 for value in (args.max_source_s,args.max_wall_s)):
  parser.error('both source and wall budgets must be positive finite numbers')
 out=args.output.resolve();out.mkdir(mode=0o700,parents=True,exist_ok=False)
 (out/'probe-source-start.py').write_text(Path(__file__).read_text());(out/'probe-source-start.py').chmod(0o600)
 manifest=json.loads(args.manifest.read_text());config=yaml.safe_load(Path(manifest['nav2_yaml']).read_text())
 c=config['controller_server']['ros__parameters']
 if not .20<=args.leg_m<=.30:
  raise ValueError('probe leg must exceed the 0.15m progress radius and remain <=0.30m')
 geometry=SceneGeometry(manifest)
 spawn_goal={'x':manifest['spawn'][0],'y':manifest['spawn'][1],
             'yaw':float(manifest.get('spawn_yaw',0.))}
 spawn={**geometry.check_pose(spawn_goal)['delivery_pose'],
        'z':float(geometry.base_height)}
 staging_goal,default_goal=probe_goals(spawn,args.leg_m,args.heading_mode)
 geometry_checks={'spawn':geometry.check_pose(spawn_goal),
  'staging_destination':geometry.check_pose(
    {'x':staging_goal['x'],'y':staging_goal['y'],'yaw':staging_goal['yaw']}),
  'default_destination':geometry.check_pose(
    {'x':default_goal['x'],'y':default_goal['y'],'yaw':default_goal['yaw']})}
 if not all(item['passed'] for item in geometry_checks.values()):
  raise RuntimeError('probe waypoints fail original full-body static geometry preflight')
 map_checks=isolation_clearance(config,manifest['collision_map_yaml'],
  {'staging':staging_goal,'default':default_goal})
 sweep=declared_sweep(geometry,[spawn,staging_goal,default_goal])
 preflight_passed=bool(sweep['passed'] and all(
  item['fixture_clearance_passed'] for item in map_checks.values()))
 report={'schema':1,'check_id':str(uuid.uuid4()),'scope':'native staging-controller motion and per-phase plan consumption only',
  'transport_task_started':False,'motion_accuracy_or_delivery_claimed':False,'passed':False,'errors':[],
  'probe_leg_m':args.leg_m,'probe_max_source_s':args.max_source_s,
  'probe_max_wall_s':args.max_wall_s,
  'probe_heading_mode':args.heading_mode,
  'native_plan_witness_requested':args.plan_witness_bin is not None,
  'probe_route':'open west corridor; controller isolation only, not factory delivery',
  'geometry_checks':geometry_checks,'map_inflation_checks':map_checks,
  'declared_sweep':sweep,'preflight_passed':preflight_passed,
  'planned_goals':{'staging':staging_goal,'default':default_goal},
  'domain':args.domain,'port':args.port,'manifest':str(args.manifest.resolve()),'goals':[],
  'source_start':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
 if not args.run_native or not preflight_passed:
  report.update(preflight_only=True,preflight_passed=preflight_passed,ros_initialized=False)
  private_json(out/'preflight.json',report)
  print(json.dumps({'check_id':report['check_id'],'preflight_passed':preflight_passed,
   'planned_goals':report['planned_goals'],'map_inflation_checks':map_checks},ensure_ascii=False))
  return 0 if preflight_passed else 1
 launch=node=executor=witness=None;handles=[];stream=None;witness_stream=witness_errors=None;started=time.monotonic()
 def save():private_json(out/'result.json',report,replace=(out/'result.json').exists())
 def spin_until(condition,timeout,description):
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   if launch is not None and launch.poll() is not None:raise RuntimeError('Owned launch exited '+str(launch.returncode)+'; inspect launch.log')
   executor.spin_once(timeout_sec=.02)
   value=condition()
   if value:return value
  raise TimeoutError(description)
 def future_value(future,timeout=10):return spin_until(lambda:future.done(),timeout,'native future timeout') and future.result()
 def source_stamp(header):return header.stamp.sec+header.stamp.nanosec/1e9
 def displacement(a,b):return math.hypot(a['x']-b['x'],a['y']-b['y'])
 def quiet():
  gate=ContinuousEvidence(.7,.1)
  def check():
   raw=node.raw
   return raw and gate.update(raw['stamp'],raw['car_hold'] is True and physical_quiet(raw))
  spin_until(check,10,'independent quiet/hold dwell unavailable')
  return {'source_stamp':node.raw['stamp'],'continuous_source_s':gate.last-gate.started,'car_hold':node.raw['car_hold']}
 def get_parameters(name,names):
  from rcl_interfaces.srv import GetParameters
  from rclpy.parameter import parameter_value_to_python
  client=node.create_client(GetParameters,'/'+name+'/get_parameters')
  if not client.wait_for_service(timeout_sec=10):raise TimeoutError('parameter service '+name)
  request=GetParameters.Request();request.names=names
  response=future_value(client.call_async(request))
  return dict(zip(names,[parameter_value_to_python(v) for v in response.values]))
 def restore_hold(timeout=3.):
  if node is None:return {'observed':False,'reason':'monitor unavailable'}
  previous=node.raw['stamp'] if node.raw else -math.inf
  end=time.monotonic()+timeout
  while time.monotonic()<end:
   try:node.hold_pub.publish(node.hold_message(True))
   except BaseException as error:
    return {'observed':False,'reason':type(error).__name__+': '+str(error)}
   executor.spin_once(timeout_sec=.02)
   if node.raw and node.raw['stamp']>previous and node.raw['car_hold'] is True:
    return {'observed':True,'source_stamp':node.raw['stamp'],
            'speed':node.raw['car']['speed'],'yaw_rate':node.raw['car']['yaw_rate']}
  return {'observed':False,'reason':'hold feedback not observed'}

 try:
  ensure_port_available(args.port)
  if args.domain in (107,114):raise RuntimeError('reserved domain')
  os.environ.update(ROS_DOMAIN_ID=str(args.domain),FISHBOT_COOP_DOMAIN=str(args.domain),FISHBOT_MUJOCO_DOMAIN_ID=str(args.domain),ROS_AUTOMATIC_DISCOVERY_RANGE='LOCALHOST',ROS_LOCALHOST_ONLY='1',ROS_STATIC_PEERS='')
  domain_is_empty(timeout=2)
  command=[str(ROOT/'tools/fishbot_cooperation.sh'),'run','manifest:='+str(args.manifest.resolve()),
   'output:='+str(out/'runtime'),'domain:='+str(args.domain),'port:='+str(args.port),'record_state:=false']
  stream=(out/'launch.log').open('x');os.chmod(stream.name,0o600)
  env=dict(os.environ,FISHBOT_COOP_PYTHON=os.environ.get('FISHBOT_COOP_PYTHON',sys.executable),FISHBOT_COOP_DOMAIN=str(args.domain),FISHBOT_MUJOCO_DOMAIN_ID=str(args.domain),ROS_DOMAIN_ID=str(args.domain))
  launch=subprocess.Popen(command,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
  report['launch_pid']=launch.pid;report['launch_command']=command;save()
  import rclpy
  from rclpy.node import Node
  from rclpy.parameter import Parameter
  from rclpy.executors import SingleThreadedExecutor
  from rclpy.qos import QoSProfile,ReliabilityPolicy,DurabilityPolicy,qos_profile_sensor_data
  from rclpy.action import ActionClient
  from std_msgs.msg import Bool
  from std_msgs.msg import String
  from geometry_msgs.msg import PoseWithCovarianceStamped
  from geometry_msgs.msg import TwistStamped
  from geometry_msgs.msg import PointStamped
  from nav_msgs.msg import Path as PathMessage, OccupancyGrid
  from tf2_msgs.msg import TFMessage
  from unique_identifier_msgs.msg import UUID
  from nav2_msgs.action import NavigateToPose
  from action_msgs.msg import GoalStatusArray
  from lifecycle_msgs.srv import GetState
  from std_srvs.srv import Empty
  from rosidl_runtime_py.convert import message_to_ordereddict
  rclpy.init(domain_id=args.domain)
  class Monitor(Node):
   def __init__(self):
    super().__init__('staging_motion_check',parameter_overrides=[Parameter('use_sim_time',value=True)])
    self.raw=self.pose=None;self.pose_received=0.;self.samples=collections.deque(maxlen=2000);self.phase='idle'
    self.gids=collections.defaultdict(set)
    self.plan_messages=collections.defaultdict(lambda:collections.deque(maxlen=2000))
    self.commands=collections.defaultdict(lambda:collections.deque(maxlen=2000))
    self.counts=collections.defaultdict(collections.Counter)
    self.phase_samples=collections.defaultdict(lambda:collections.deque(maxlen=4000))
    self.amcl_samples=collections.defaultdict(lambda:collections.deque(maxlen=2000))
    self.transforms=collections.defaultdict(lambda:collections.deque(maxlen=4000))
    self.navigation=collections.defaultdict(NavigationDiagnostics)
    hold_qos=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL,
     reliability=ReliabilityPolicy.RELIABLE)
    self.hold_pub=self.create_publisher(Bool,'/cooperation/car_hold',hold_qos)
    self.statuses={};self.first_phase={};self.subscriptions_owned=[]
    self.subscriptions_owned.append(self.create_subscription(String,'/cooperation/physics_state',self.physics,qos_profile_sensor_data))
    self.subscriptions_owned.append(self.create_subscription(PoseWithCovarianceStamped,'/amcl_pose',self.amcl,qos_profile_sensor_data))
    self.subscriptions_owned.append(self.create_subscription(PathMessage,'/received_global_plan',self.plan,
     QoSProfile(depth=10,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.VOLATILE)))
    self.subscriptions_owned.append(self.create_subscription(TwistStamped,'/cmd_vel_nav',self.command,
     QoSProfile(depth=100,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.VOLATILE)))
    for topic,kind in (('/plan',PathMessage),('/lookahead_point',PointStamped),
                       ('/local_costmap/costmap',OccupancyGrid)):
     self.subscriptions_owned.append(self.create_subscription(kind,topic,
      self.capture_callback(topic),qos_profile_sensor_data))
    self.subscriptions_owned.append(self.create_subscription(TFMessage,'/tf',self.tf,qos_profile_sensor_data))
    qos=QoSProfile(depth=20,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL)
    for topic in ('/navigate_to_pose/_action/status','/follow_path/_action/status'):
     self.subscriptions_owned.append(self.create_subscription(GoalStatusArray,topic,self.status_callback(topic),qos))
   def status_callback(self,topic):
    def callback(message):self.status(message,topic)
    return callback
   def amcl(self,message):
    self.pose=message;self.pose_received=time.monotonic()
    self.counts[self.phase]['amcl']+=1
    self.amcl_samples[self.phase].append({'message':message_to_ordereddict(message),
     'receive_monotonic':self.pose_received})
   def tf(self,message):
    for transform in message.transforms:
     if (transform.header.frame_id,transform.child_frame_id) in (
       ('map','odom'),('odom','base_footprint')):
      self.counts[self.phase]['transforms']+=1
      self.transforms[self.phase].append({'message':message_to_ordereddict(transform),
       'receive_monotonic':time.monotonic()})
   def capture_callback(self,topic):
    def callback(message):self.capture(topic,message)
    return callback
   def capture(self,topic,message):
    wall=time.monotonic();navigation=self.navigation[self.phase]
    if not navigation.accept(topic,wall):return
    try:
     if topic in ('/plan','/received_global_plan'):
      count=len(message.poses);stride=max(1,math.ceil(max(0,count-1)/511))
      poses=list(message.poses[::stride])
      if count and poses[-1] is not message.poses[-1]:poses.append(message.poses[-1])
      payload={'original_pose_count':count,'downsampled':len(poses)<count,
       'poses':[message_to_ordereddict(pose) for pose in poses]}
     elif topic=='/lookahead_point':
      payload={'point':[message.point.x,message.point.y,message.point.z]}
     else:
      count=len(message.data)
      payload={'info':message_to_ordereddict(message.info),'original_cell_count':count,
       'grid_omitted':count>100000,'data':list(message.data) if count<=100000 else None}
     navigation.append(topic,source_stamp(message.header),message.header.frame_id,wall,
      self.get_clock().now().nanoseconds/1e9,payload)
    except (ValueError,TypeError,AttributeError) as error:
     navigation.errors.append({'topic':topic,'steady_time':wall,'error':str(error)})
   def physics(self,message):
    raw=json.loads(message.data);self.raw=raw
    sample=compact_physics_sample(raw,time.monotonic())
    self.samples.append(sample);self.phase_samples[self.phase].append(sample)
    self.counts[self.phase]['physics']+=1
    if (sample['car_forbidden_contact_count']!=0 or
        sample['arm_forbidden_contact_count']!=0):
     self.counts[self.phase]['unsafe_or_missing_contact_samples']+=1
   @staticmethod
   def publisher_gid(info):
    gid=(info.get('publisher_gid') if isinstance(info,dict) else
         getattr(info,'publisher_gid',None))
    if isinstance(gid,(bytes,bytearray)):return gid.hex()
    if isinstance(gid,(list,tuple)) or type(gid).__name__=='array':
     return bytes(gid).hex()
    return 'unavailable:'+type(gid).__name__
   def plan(self,message,info):
    gid=self.publisher_gid(info);self.gids[self.phase].add(gid)
    self.counts[self.phase]['plans']+=1
    self.plan_messages[self.phase].append({'publisher_gid':gid,
     'poses':len(message.poses),'stamp':source_stamp(message.header),
     'receive_monotonic':time.monotonic()})
    self.capture('/received_global_plan',message)
   def command(self,message):
    self.counts[self.phase]['commands']+=1
    if abs(message.twist.linear.x)>.001 or abs(message.twist.angular.z)>.001:
     self.counts[self.phase]['nonzero_commands']+=1
    self.commands[self.phase].append({'stamp':source_stamp(message.header),'receive_monotonic':time.monotonic(),
     'linear_x':message.twist.linear.x,'angular_z':message.twist.angular.z})
   @staticmethod
   def hold_message(enabled):return Bool(data=enabled)
   def status(self,message,topic):
    for value in message.status_list:
     key=topic+':'+bytes(value.goal_info.goal_id.uuid).hex()
     self.first_phase.setdefault(key,self.phase);self.statuses.setdefault(key,[])
     if value.status not in self.statuses[key]:self.statuses[key].append(value.status)
  node=Monitor();executor=SingleThreadedExecutor();executor.add_node(node)
  client=ActionClient(node,NavigateToPose,'/navigate_to_pose')
  def ready():
   try:
    with urllib.request.urlopen('http://127.0.0.1:'+str(args.port)+'/coop-api/state',timeout=.5) as response:state=json.load(response)
   except (OSError,ValueError):return False
   candidate={'ready':state.get('ready'),'native_lifecycle':state.get('native_lifecycle'),'task':state.get('task')}
   ok=readiness_ok(state,node.raw,node.pose.header.frame_id if node.pose else None,client.server_is_ready(),
    node.count_publishers('/follow_path/_action/status'))
   if ok:report['readiness_state']=candidate
   return ok
  spin_until(ready,65,'native readiness unavailable')
  report['native_world_observed']=True
  report['initial_quiet']=quiet()
  lifecycle_clients={name:node.create_client(GetState,'/'+name+'/get_state')
   for name in ('controller_server','planner_server','bt_navigator')}
  def native_active():
   observed={}
   for name,lifecycle in lifecycle_clients.items():
    if not lifecycle.service_is_ready():return False
    state=future_value(lifecycle.call_async(GetState.Request()),3).current_state
    observed[name]={'id':state.id,'label':state.label}
   report['native_lifecycles']=observed
   return observed if all(value['id']==3 for value in observed.values()) else False
  spin_until(native_active,15,'native planner/controller/navigator not active')
  nomotion=node.create_client(Empty,'/request_nomotion_update')
  if not nomotion.wait_for_service(timeout_sec=5):raise TimeoutError('AMCL no-motion update unavailable')
  def fresh_amcl():
   previous=source_stamp(node.pose.header);requested=time.monotonic()
   future_value(nomotion.call_async(Empty.Request()),5)
   spin_until(lambda:node.pose is not None and fresh_pose_ok(source_stamp(node.pose.header),previous,
    node.pose_received,requested,node.get_clock().now().nanoseconds/1e9,time.monotonic()),10,
    'new AMCL scan update unavailable; no goal sent')
   return copy.deepcopy(node.pose),{'previous_stamp':previous,'new_stamp':source_stamp(node.pose.header),
    'receive_monotonic':node.pose_received,'requested_monotonic':requested,
    'source_now':node.get_clock().now().nanoseconds/1e9,'readback_monotonic':time.monotonic()}
  names=['controller_plugins','goal_checker_plugins']
  for prefix in ('FollowPath','StagingPath'):
   names += [prefix+'.'+key for key in ('plugin','stateful','desired_linear_vel','min_approach_linear_velocity',
    'max_angular_accel','rotate_to_heading_angular_vel','use_collision_detection')]
  for prefix in ('general_goal_checker','staging_goal_checker'):
   names += [prefix+'.'+key for key in ('plugin','stateful','xy_goal_tolerance','yaw_goal_tolerance')]
  names += ['progress_checker.'+key for key in ('required_movement_radius','required_movement_angle','movement_time_allowance')]
  expected={name:(c[name] if '.' not in name else c[name.split('.')[0]][name.split('.')[1]]) for name in names}
  actual=get_parameters('controller_server',names);report['controller_parameters']={'expected':expected,'actual':actual,'matches':expected==actual}
  report['navigator_parameters']=get_parameters('bt_navigator',['default_nav_to_pose_bt_xml'])
  if expected!=actual:raise RuntimeError('native controller parameters differ')
  report['initial_source_identity']=node.raw['source']
  report['plan_publishers']=[{'node':i.node_name,'gid':bytes(i.endpoint_gid).hex()} for i in node.get_publishers_info_by_topic('/received_global_plan')]
  report['plan_publisher_qos']=[{'node':i.node_name,'gid':bytes(i.endpoint_gid).hex(),
    'reliability':i.qos_profile.reliability.name,'durability':i.qos_profile.durability.name,
    'history':i.qos_profile.history.name,'depth':i.qos_profile.depth}
   for i in node.get_publishers_info_by_topic('/received_global_plan')]
  report['plan_subscription_qos']={'reliability':'RELIABLE','durability':'VOLATILE','history':'KEEP_LAST','depth':10}
  if args.plan_witness_bin is not None:
   witness_stream=(out/'native-plan-witness.jsonl').open('x')
   witness_errors=(out/'native-plan-witness.log').open('x')
   os.chmod(witness_stream.name,0o600);os.chmod(witness_errors.name,0o600)
   witness=subprocess.Popen([str(args.plan_witness_bin.resolve())],cwd=ROOT,env=env,
    stdout=witness_stream,stderr=witness_errors,start_new_session=True)
   report['native_plan_witness_pid']=witness.pid
   def witness_ready():
    if witness.poll() is not None:raise RuntimeError('native plan witness exited before readiness')
    return any(json.loads(line).get('kind')=='ready'
               for line in Path(witness_stream.name).read_text().splitlines(keepends=True)
               if line.endswith('\n'))
   spin_until(witness_ready,10,'native plan witness did not match both controller publishers')
  save()
  for phase,tree,point in (
    ('staging',manifest['staging_navigation_behavior_tree'],staging_goal),
    ('default',manifest['navigation_behavior_tree'],default_goal)):
   node.phase=phase
   report['readiness_state']=None
   spin_until(ready,15,'bridge not fully ready before '+phase)
   spin_until(native_active,10,'native lifecycle not active before '+phase)
   pose,amcl_update=fresh_amcl();start_pose=car_pose(node.raw)
   goal=NavigateToPose.Goal();goal.pose.header.frame_id='map';goal.pose.header.stamp=node.get_clock().now().to_msg()
   goal.pose.pose.position.x,goal.pose.pose.position.y=point['x'],point['y']
   goal.pose.pose.orientation.z,goal.pose.pose.orientation.w=math.sin(point['yaw']/2),math.cos(point['yaw']/2)
   goal.behavior_tree=tree
   entry={'phase':phase,'input_source':'declared map goals; AMCL navigation; truth for scoring','amcl_source_stamp':source_stamp(pose.header),
    'amcl_start_pose':message_to_ordereddict(pose),
    'amcl_nomotion_update':amcl_update,'lifecycle_before':copy.deepcopy(report['native_lifecycles']),
    'requested_behavior_tree':tree,'goal':message_to_ordereddict(goal),'started_wall_time':time.time(),
    'start_truth_pose':start_pose,'start_goal_distance_m':displacement(start_pose,point),
    'hold_release_requested':True}
   goal_uuid=UUID(uuid=list(uuid.uuid4().bytes))
   entry.update(uuid=bytes(goal_uuid.uuid).hex(),goal_request_sent=True)
   report['goals'].append(entry);save()
   handle=future_value(client.send_goal_async(goal,goal_uuid=goal_uuid),15)
   entry.update(accepted=handle.accepted,uuid=bytes(handle.goal_id.uuid).hex())
   if not handle.accepted:raise RuntimeError('native goal rejected (phase='+phase+'; readiness captured='+str(report['readiness_state'] is not None)+'; tree='+tree+')')
   result_future=handle.get_result_async();handles.append((handle,result_future,entry));save()
   entry['accepted_source_stamp']=node.raw['stamp'];entry['accepted_monotonic']=time.monotonic()
   node.hold_pub.publish(node.hold_message(False))
   def motion_progress():
    latest=car_pose(node.raw) if node.raw else start_pose
    return (displacement(latest,start_pose)>0 or node.commands[phase] or node.plan_messages[phase]
     or (node.raw and node.raw['stamp']-entry['amcl_source_stamp']>report['probe_max_source_s']))
   def await_terminal():
    spin_until(motion_progress,10,'goal produced neither motion nor plan/control evidence')
    def terminal_with_budget():
     reason=phase_budget_reason(entry['accepted_source_stamp'],node.raw['stamp'],
      entry['accepted_monotonic'],time.monotonic(),args.max_source_s,args.max_wall_s)
     if reason:raise TimeoutError(reason)
     return result_future.done()
    spin_until(terminal_with_budget,args.max_wall_s,'native result wall timeout')
    return result_future.result()
   reply=record_phase_wait(node,entry,point,await_terminal,save)
   entry.update(status=reply.status,result=message_to_ordereddict(reply.result),
    terminal=reply.status in (4,5,6),ended_wall_time=time.time())
   entry['truth_pose_at_terminal']=car_pose(node.raw)
   node.hold_pub.publish(node.hold_message(True))
   entry['independent_quiet']=quiet()
   phase_snapshot(node,entry,point)
   entry['end_truth_pose']=entry['snapshot_truth_pose'];save()
   if reply.status!=4:raise RuntimeError('native probe goal did not succeed (phase='+phase+')')
   save()
  node.phase='cleanup';report['final_quiet']=quiet()
  report['controller_parameters_after']=get_parameters('controller_server',names)
  report['parameters_unchanged']=actual==report['controller_parameters_after']
  report['native_statuses']=node.statuses;report['native_status_first_phase']=node.first_phase
  a,b=(node.gids['staging'],node.gids['default'])
  gid_values=a|b
  gid_available=bool(a and b and not any(value.startswith('unavailable:') for value in gid_values))
  report['phase_rpp_gid_switch_status']=('observed' if gid_available and a.isdisjoint(b)
    else 'unavailable' if not gid_available else 'shared')
  report['phase_rpp_activity_switch_observed']=(
    bool(a and b and a.isdisjoint(b)) if gid_available else None)
  report['phase_plan_receive_counts']={phase:counts['plans'] for phase,counts in node.counts.items()}
  report['phase_command_counts']={phase:counts['commands'] for phase,counts in node.counts.items()}
  report['phase_plan_consumption_observed']={
    phase:bool(node.counts[phase]['plans'] and node.counts[phase]['nonzero_commands'])
    for phase in ('staging','default')}
  report['two_native_rpp_publishers_observed']=sum(
    item.get('node')=='controller_server' for item in report.get('plan_publishers',[]))>=2
  report['independent_outer_success']=all(4 in node.statuses.get('/navigate_to_pose/_action/status:'+g['uuid'],[]) for g in report['goals'])
  report['independent_child_success_by_phase']={phase:any(4 in statuses and node.first_phase[key]==phase for key,statuses in node.statuses.items() if key.startswith('/follow_path/')) for phase in ('staging','default')}
  report['physical_samples']=list(node.samples)
  report['all_observed_car_hold']=all(s['car_hold'] for s in node.samples)
  report['post_release_motion_samples']=sum(not s['car_hold'] for s in node.samples)
  report['final_hold_restored']=bool(node.raw and node.raw['car_hold'] is True)
  report['passed']=all((len(report['goals'])==2,report['parameters_unchanged'],report['independent_outer_success'],
    all(report['independent_child_success_by_phase'].values()),
    report['two_native_rpp_publishers_observed'],
    all(report['phase_plan_consumption_observed'].values()),
    all(g.get('controller_commands') for g in report['goals']),
    all(g.get('no_forbidden_contacts_observed') for g in report['goals']),
    report['final_hold_restored'],
    all(g.get('motion_observed') is True for g in report['goals']),
    all(g.get('truth_goal_error',{}).get('xy_m',math.inf)<=.04 for g in report['goals']),
    all(g.get('truth_goal_error',{}).get('yaw_rad',math.inf)<=.05 for g in report['goals'])))
 except BaseException as error:
  report['errors'].append(type(error).__name__+': '+str(error));report['traceback']=traceback.format_exc()
 finally:
  if node is not None:
   try:node.hold_pub.publish(node.hold_message(True))
   except BaseException as error:report['errors'].append('hold request: '+str(error))
  for handle,future,entry in handles:
   if not future.done():
    try:
     entry['cleanup_cancel_requested']=True;future_value(handle.cancel_goal_async(),5)
     reply=future_value(future,10)
     entry.update(status=reply.status,result=message_to_ordereddict(reply.result),
      terminal=reply.status in (4,5,6),ended_wall_time=time.time())
    except BaseException as error:report['errors'].append('native cleanup: '+str(error))
  report['native_terminal_known']=all(entry.get('accepted') is False or entry.get('terminal') is True
   for entry in report['goals'] if entry.get('goal_request_sent'))
  try:
   report['cleanup_hold']=restore_hold()
   if node is not None:
    for entry in report['goals']:
     if entry['phase']==node.phase:
      phase_snapshot(node,entry,report['planned_goals'][entry['phase']])
    report['native_statuses']=node.statuses;report['native_status_first_phase']=node.first_phase
    report['physical_samples']=list(node.samples)
    report['phase_plan_receive_counts']={phase:counts['plans'] for phase,counts in node.counts.items()}
    report['phase_command_counts']={phase:counts['commands'] for phase,counts in node.counts.items()}
    report['final_hold_restored']=bool(node.raw and node.raw['car_hold'] is True)
    report['cleanup_quiet']=quiet()
  except BaseException as error:report['errors'].append('monitor cleanup: '+str(error))
  finally:
   if node is not None:
    close_errors=[]
    for name,close in (('detach',lambda:executor.remove_node(node)),
                       ('executor',executor.shutdown),('node',node.destroy_node),
                       ('context',rclpy.try_shutdown)):
     try:close()
     except BaseException as error:close_errors.append(name+': '+str(error))
    report['errors'].extend(close_errors)
    report['probe_context_closed']=not close_errors
  if launch is not None:
   try:report['owned_launch_stopped']=stop_owned_launch(launch,report)
   except BaseException as error:report['errors'].append('launch cleanup: '+str(error))
   report['retained_launch_pid']=launch.pid if launch.poll() is None else None
  if stream is not None:stream.close()
  if witness is not None:
   try:
    if witness.poll() is None:witness.send_signal(signal.SIGINT)
    witness.wait(timeout=5)
   except subprocess.TimeoutExpired:
    witness.kill();witness.wait(timeout=5)
   report['native_plan_witness_stopped']=witness.poll() is not None
  if witness_stream is not None:
   witness_stream.close();witness_errors.close()
   try:attach_native_witness(report,witness_stream.name)
   except (OSError,ValueError,KeyError,TypeError) as error:
    report['errors'].append('native plan witness: '+str(error))
   report['passed']=bool(report['passed'] and report.get('native_plan_witness_stopped') and
     report.get('phase_rpp_activity_switch_observed') is True and
     all(entry.get('controller_instance_binding') for entry in report['goals']))
  with socket.socket() as probe:report['owned_port_closed']=probe.connect_ex(('127.0.0.1',args.port))!=0
  report['elapsed_wall_s']=time.monotonic()-started
  report['source_end']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
  end_source=Path(__file__).read_text()
  (out/'probe-source-end.py').write_text(end_source);(out/'probe-source-end.py').chmod(0o600)
  report['probe_source_unchanged']=(out/'probe-source-start.py').read_text()==end_source
  report['passed']=bool(report['passed'] and report.get('owned_launch_stopped') and
   report['owned_port_closed'] and report['native_terminal_known'] and
   report.get('cleanup_hold',{}).get('observed') and report.get('cleanup_quiet') and
   report.get('probe_context_closed') and not report['errors'])
  save()
  print(json.dumps({k:report.get(k) for k in ('check_id','passed','errors','elapsed_wall_s','owned_launch_stopped','owned_port_closed','native_terminal_known','phase_rpp_activity_switch_observed')},ensure_ascii=False))
 return 0 if report['passed'] else 1


if __name__ == "__main__":
 raise SystemExit(main())
