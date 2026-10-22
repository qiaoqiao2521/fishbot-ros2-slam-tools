"""Actual compiled geometry: clear approach and an occupied spawn, no ROS."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[2]
PYTHON = Path.home()/'.cache/so101-colab/planning-venv/bin/python'


class GeometryTests(unittest.TestCase):
    def test_rotated_boxes_keep_positive_clearance_across_aabb_contact(self):
        code = r'''
import json,math,sys
import numpy as np
sys.path.insert(0,sys.argv[1]+'/tools')
import mujoco
from cooperation_geometry_check import pair_clearance
yaw=.7144845128932502
xml=f"""<mujoco><worldbody>
<geom name="car" type="box" pos=".6702008874948888 -2.412933979264536 .15"
 size=".244 .222795 .1" quat="{math.cos(yaw/2)} 0 0 {math.sin(yaw/2)}"/>
<geom name="obstacle" type="box" pos=".35 -2.1 .25" size=".06 .15 .25"/>
</worldbody></mujoco>"""
m=mujoco.MjModel.from_xml_string(xml);d=mujoco.MjData(m)
a=m.geom('car').id;b=m.geom('obstacle').id;rows=[]
for offset in (0.,-.002,.002):
 m.geom_pos[a,0]=.6702008874948888+offset;mujoco.mj_forward(m,d)
 extent=sum(np.abs(d.geom_xmat[i].reshape(3,3))@m.geom_size[i] for i in (a,b))
 gap=float(np.linalg.norm(np.maximum(np.abs(d.geom_xpos[a]-d.geom_xpos[b])-extent,0)))
 rows.append({'aabb_gap':gap,'lower':pair_clearance(m,d,a,b),
  'native':float(mujoco.mj_geomDistance(m,d,a,b,.2,None))})
m.geom_pos[a]=m.geom_pos[b];mujoco.mj_forward(m,d)
print(json.dumps({'rows':rows,'overlap':pair_clearance(m,d,a,b)}))
'''
        run = subprocess.run([str(PYTHON), '-B', '-c', code, str(PROJECT)],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
        result = json.loads(run.stdout)
        self.assertLess(result['rows'][0]['aabb_gap'], 1e-6)
        self.assertEqual(result['rows'][1]['aabb_gap'], 0.)
        # Analytic face separation, independent of the unstable legacy query.
        for row, expected in zip(result['rows'],
                (.07078132591540687, .06947086973785377, .07209178209295997)):
            self.assertAlmostEqual(row['lower'], expected, places=8)
        self.assertLessEqual(result['overlap'], 0.)

    def test_separated_rotated_box_uses_conservative_bound_and_keeps_overlap_rejected(self):
        code = r'''
import json,math,sys
from unittest.mock import patch
sys.path.insert(0,sys.argv[1]+'/tools')
import mujoco
from cooperation_geometry_check import pair_clearance
yaw=2.2938613026211185
xml=f"""
<mujoco><option><flag nativeccd="disable"/></option><worldbody>
<geom name="tray" type="box" pos=".01851943867418969 -1.930307601625479 .162"
 size=".06 .06 .001" quat="{math.cos(yaw/2)} 0 0 {math.sin(yaw/2)}"/>
<geom name="obstacle" type="box" pos=".35 -2.1 .25" size=".06 .15 .25"/>
</worldbody></mujoco>
"""
m=mujoco.MjModel.from_xml_string(xml);d=mujoco.MjData(m);mujoco.mj_forward(m,d)
a=m.geom('tray').id;b=m.geom('obstacle').id
raw=float(mujoco.mj_geomDistance(m,d,a,b,.2,None))
with patch.object(mujoco,'mj_geomDistance',side_effect=AssertionError('disjoint boxes need no native query')):
 separated=pair_clearance(m,d,a,b)
 capped=pair_clearance(m,d,a,b,.01)
m.geom_pos[b]=m.geom_pos[a];mujoco.mj_forward(m,d)
overlap=pair_clearance(m,d,a,b)
print(json.dumps({'raw':raw,'separated':separated,'capped':capped,'overlap':overlap,
 'version':mujoco.__version__}))
'''
        run = subprocess.run([str(PYTHON), '-B', '-c', code, str(PROJECT)],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
        result = json.loads(run.stdout)
        self.assertGreater(result['separated'], .18)
        self.assertLess(result['separated'], .20)
        self.assertAlmostEqual(result['capped'], .01)
        self.assertLessEqual(result['overlap'], 0.)

    def test_original_collision_model_certifies_clear_path_and_rejects_occupied_spawn(self):
        code = r'''
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/tools')
import mujoco
from cooperation_scene import build_scene
from cooperation_geometry_check import check,SceneGeometry
project=Path(sys.argv[1]);output=Path(sys.argv[2])
manifest=build_scene(project.parent/'so101',project,output)
path=output/'scene-manifest.json'
manifest['staging_pose']=[manifest['dock_pose'][0]+.7,manifest['dock_pose'][1],manifest['dock_pose'][2]]
path.write_text(json.dumps(manifest))
clear=check(path)
query=SceneGeometry(manifest)
goals={name:query.check_pose(dict(zip(('x','y','yaw'),pose))) for name,pose in (
    ('default',[0.,-2.,0.]),('alternate',[.7,-2.,0.]),('outside',[4.5,0.,0.]))}
model=mujoco.MjModel.from_xml_path(manifest['world_xml'])
occupied=model.geom('approach_obstacle').pos[:2].tolist()
goals['occupied']=query.check_pose(dict(zip(('x','y','yaw'),[*occupied,0.])))
manifest['spawn']=model.geom('approach_obstacle').pos[:2].tolist()
manifest['spawn_yaw']=0.
path.write_text(json.dumps(manifest))
blocked=check(path)
print(json.dumps({'clear':clear,'blocked':blocked,'goals':goals}))
'''
        with tempfile.TemporaryDirectory() as temp:
            run=subprocess.run([str(PYTHON),'-B','-c',code,str(PROJECT),temp],
                               capture_output=True,text=True,timeout=90)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            result=json.loads(run.stdout)
        self.assertTrue(result['clear']['passed'])
        self.assertGreater(result['clear']['certified_margin_m'],0.)
        self.assertGreater(result['clear']['collision_pair_count'],0)
        self.assertFalse(result['clear']['robot_geometry_shrunk'])
        self.assertFalse(result['blocked']['passed'])
        self.assertLess(result['blocked']['minimum_sampled_clearance_m'],0.)
        for name in ('default','alternate'):
            self.assertTrue(result['goals'][name]['passed'])
            self.assertFalse(result['goals'][name]['path_validated'])
            self.assertFalse(result['goals'][name]['arrival_validated'])
            self.assertGreater(result['goals'][name]['collision_pair_count'],0)
        self.assertFalse(result['goals']['outside']['passed'])
        self.assertEqual(result['goals']['outside']['reason'],'footprint_outside_scene_bounds')
        self.assertFalse(result['goals']['occupied']['passed'])
        self.assertEqual(result['goals']['occupied']['reason'],'original_geometry_collision')


if __name__ == '__main__': unittest.main()
