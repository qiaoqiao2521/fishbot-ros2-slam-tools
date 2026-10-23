"""Construct the native launch scope without starting ROS nodes or processes."""
import json
import os
from pathlib import Path
import subprocess
import unittest

PROJECT = Path(__file__).resolve().parents[2]
RUNTIME = Path(os.environ.get('FISHBOT_SO101_PYTHON',
                             str(Path.home()/'.cache/so101-colab/planning-venv/bin/python')))


class CooperationLaunchTests(unittest.TestCase):
    def test_dock_velocity_uses_existing_smoother_and_collision_monitor_input(self):
        code = r'''
import json,os,runpy,sys,tempfile
from pathlib import Path
sys.path.append('/usr/lib/python3/dist-packages')
import yaml
from launch import LaunchContext
from launch.actions import GroupAction,IncludeLaunchDescription,TimerAction
from launch.actions import ExecuteProcess
from launch_ros.actions import Node,SetRemap
from launch.utilities import perform_substitutions
module=runpy.run_path(sys.argv[1]+'/tools/cooperation.launch.py')
with tempfile.TemporaryDirectory() as directory:
 p=Path(directory)/'manifest.json'
 nav=Path(directory)/'nav.yaml'
 nav.write_text(yaml.safe_dump({'amcl':{'ros__parameters':{'set_initial_pose':True,
   'initial_pose':{'x':-1.3,'y':-1.77,'yaw':.1}}}}))
 p.write_text(json.dumps({'world_xml':'/unused/world.xml','localization_map_yaml':'/unused/localization.yaml',
                         'collision_map_yaml':'/unused/collision.yaml','nav2_yaml':str(nav)}))
 context=LaunchContext()
 context.launch_configurations.update({'domain':'114','manifest':str(p),'python':sys.executable,
     'output':'/unused/output','port':'9086'})
 actions=module['start'](context)
 def additional_env(process):
  return {perform_substitutions(context,k):perform_substitutions(context,v)
          for k,v in (process.additional_env or [])}
 owned=[a for a in actions if isinstance(a,ExecuteProcess) and not isinstance(a,Node)]
 assert len(owned)==2 and all(not additional_env(a) for a in owned)
 context.launch_configurations['publication_mode']='asynchronous'
 asynchronous=module['start'](context)
 owned=[a for a in asynchronous if isinstance(a,ExecuteProcess) and not isinstance(a,Node)]
 assert all(additional_env(a)=={'RMW_FASTRTPS_PUBLICATION_MODE':'ASYNCHRONOUS'} for a in owned)
 assert all(not additional_env(a) for a in asynchronous if isinstance(a,Node))
 context.launch_configurations['publication_mode']='source'
 def simulation_cmd(actions):
  process=next(a for a in actions if isinstance(a,ExecuteProcess) and not isinstance(a,Node))
  return [perform_substitutions(context,part) for part in process.cmd]
 assert '--state-log' not in simulation_cmd(actions)
 command=simulation_cmd(actions)
 assert command[command.index('--manifest')+1]==str(p.resolve())
 assert '--no-overview-render' not in command
 assert '--queued-ros-dispatch' not in command
 original=json.loads(p.read_text());headless=dict(original,render_overview=False,queued_ros_dispatch=True)
 p.write_text(json.dumps(headless))
 headless_command=simulation_cmd(module['start'](context))
 assert '--no-overview-render' in headless_command
 assert '--queued-ros-dispatch' in headless_command
 assert headless_command[headless_command.index('--frame-dir')+1]==str(Path('/unused/output/frames'))
 p.write_text(json.dumps(original))
 context.launch_configurations['record_state']='true'
 configured=simulation_cmd(module['start'](context))
 assert configured[configured.index('--state-log-hz')+1]=='2'
 assert configured[configured.index('--state-log-max-bytes')+1]=='8388608'
 assert configured[configured.index('--state-log-backups')+1]=='3'
 context.launch_configurations['record_state']='invalid'
 try:module['start'](context)
 except RuntimeError:pass
 else:raise AssertionError('invalid logging profile admitted')
 context.launch_configurations['record_state']='false'
 nodes=[a for a in actions if isinstance(a,Node)]
 context.environment.update(os.environ)
 for node in nodes:node._perform_substitutions(context)
 assert {node.node_name.rsplit('/',1)[-1] for node in nodes}=={'map_server','amcl','cooperation_collision_map_server'},[node.node_name for node in nodes]
 # Inspect resolved parameters without running a launch service. Every
 # localization node has one native lifecycle owner, not a competing manager.
 for node in nodes:
  parameters=node._Node__expanded_parameter_arguments
  assert parameters and parameters[-1][1] is True
  native=yaml.safe_load(Path(parameters[-1][0]).read_text())['/**']['ros__parameters']
  assert native['autostart_node'] is True and native['use_sim_time'] is True
  if node.node_name.rsplit('/',1)[-1]=='amcl':
   original=yaml.safe_load(Path(parameters[0][0]).read_text())['amcl']['ros__parameters']
   assert original['set_initial_pose'] is True and original['initial_pose']['yaw']==.1
 timers=[a for a in actions if isinstance(a,TimerAction)]
 groups=[a for timer in timers for a in timer.actions if isinstance(a,GroupAction)]
 assert len(groups)==1
 children=groups[0].get_sub_entities()
 remaps=[a for a in children if isinstance(a,SetRemap)]
 assert len(remaps)==1 and any(isinstance(a,IncludeLaunchDescription) for a in children)
 # SetRemap only changes this in-memory LaunchContext. No launch service runs.
 remaps[0].execute(context)
 print('RESULT_JSON:'+json.dumps(context.launch_configurations['ros_remaps']))
 runtime=Path(directory)/'old-runtime'
 (runtime/'tasks').mkdir(parents=True)
 ledger=runtime/'tasks'/'task.json'
 ledger.write_text('preserve corrupt old ledger')
 context.launch_configurations['output']=str(runtime)
 try:
  module['start'](context)
 except RuntimeError as error:
  assert '不能复用旧物理回合' in str(error)
 else:
  raise AssertionError('Old runtime admitted')
 assert ledger.read_text()=='preserve corrupt old ledger'
 # Exercise the vision-only helper import and environment without ROS startup.
 context.launch_configurations['output']='/unused/vision-output'
 manifest=json.loads(p.read_text());manifest.update(station_perception={'mode':'vision'},station_camera={},render_overview=False)
 p.write_text(json.dumps(manifest))
 actions=module['start'](context)
 processes=[a for a in actions if isinstance(a,ExecuteProcess) and not isinstance(a,Node)]
 assert len(processes)==3
 assert '--no-overview-render' in simulation_cmd(actions)
 # Optional J100 fusion uses the existing upstream EKF, retaining the old nodes.
 ekf=Path(directory)/'ekf.yaml';ekf.write_text('ekf_filter_node:\n  ros__parameters:\n    use_sim_time: true\n')
 manifest['localization']={'enabled':True,'ekf_yaml':str(ekf)}
 p.write_text(json.dumps(manifest))
 actions=module['start'](context)
 nodes=[a for a in actions if isinstance(a,Node)]
 for node in nodes:node._perform_substitutions(context)
 assert 'ekf_filter_node' in {node.node_name.rsplit('/',1)[-1] for node in nodes}
 assert len(nodes)==4
'''
        shell = 'source "$1/tools/fishbot_mujoco_env.sh" && exec "$2" -B -c "$3" "$1"'
        environment = dict(os.environ, FISHBOT_MUJOCO_DOMAIN_ID='114')
        environment['PYTHONPATH']=''  # Reproduce ros2 launch without a tools import path.
        result = subprocess.run(['bash', '-c', shell, 'cooperation-launch-dry', str(PROJECT),
                                 str(RUNTIME), code], env=environment, text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        rules = json.loads(result.stdout.rsplit('RESULT_JSON:', 1)[1])
        self.assertEqual(rules, [['docking_server:cmd_vel', '/cmd_vel_nav']])


if __name__ == '__main__':
    unittest.main()
