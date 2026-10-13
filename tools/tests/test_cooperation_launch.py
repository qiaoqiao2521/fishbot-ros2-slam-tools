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
import json,runpy,sys,tempfile
from pathlib import Path
sys.path.append('/usr/lib/python3/dist-packages')
from launch import LaunchContext
from launch.actions import GroupAction,IncludeLaunchDescription,TimerAction
from launch_ros.actions import SetRemap
module=runpy.run_path(sys.argv[1]+'/tools/cooperation.launch.py')
with tempfile.TemporaryDirectory() as directory:
 p=Path(directory)/'manifest.json'
 p.write_text(json.dumps({'world_xml':'/unused/world.xml','localization_map_yaml':'/unused/localization.yaml',
                         'collision_map_yaml':'/unused/collision.yaml','nav2_yaml':'/unused/nav2.yaml'}))
 context=LaunchContext()
 context.launch_configurations.update({'domain':'114','manifest':str(p),'python':sys.executable,
     'output':'/unused/output','port':'9086'})
 actions=module['start'](context)
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
'''
        shell = 'source "$1/tools/fishbot_mujoco_env.sh" && exec "$2" -B -c "$3" "$1"'
        environment = dict(os.environ, FISHBOT_MUJOCO_DOMAIN_ID='114')
        result = subprocess.run(['bash', '-c', shell, 'cooperation-launch-dry', str(PROJECT),
                                 str(RUNTIME), code], env=environment, text=True,
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        rules = json.loads(result.stdout.rsplit('RESULT_JSON:', 1)[1])
        self.assertEqual(rules, [['docking_server:cmd_vel', '/cmd_vel_nav']])


if __name__ == '__main__':
    unittest.main()
