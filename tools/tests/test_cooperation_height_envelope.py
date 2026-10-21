"""Read-only geometry evidence from both real compiled cooperation vehicles."""
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class CompiledHeightEnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        project = Path(__file__).resolve().parents[2]
        runtime = Path(os.environ.get('FISHBOT_SO101_PYTHON', str(Path.home()/'.cache/so101-colab/planning-venv/bin/python')))
        code = r'''
import json,math,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1]+'/tools')
sys.path.append('/usr/lib/python3/dist-packages')
import mujoco,numpy as np
from cooperation_scene import build_scene
from cooperation_profiles import height_envelope,_geom_vertical_bounds
p,out=Path(sys.argv[1]),Path(sys.argv[2]);result={'version':mujoco.__version__,'vehicles':{}}
for name in ('fishbot','jackal_j100'):
    manifest=build_scene(p.parent/'so101',p,out/name,scene_profile={'vehicle':name,'sensors':'lidar3d'})
    model=mujoco.MjModel.from_xml_path(manifest['world_xml']);data=mujoco.MjData(model);mujoco.mj_forward(model,data)
    envelope=height_envelope(model,data,manifest,.01);corners=[]
    for component in envelope['compiled_collision_components']:
        geom=model.geom(component['name']).id
        if model.geom_type[geom]==mujoco.mjtGeom.mjGEOM_BOX:
            local=np.array([[x,y,z] for x in (-1,1) for y in (-1,1) for z in (-1,1)])*model.geom_size[geom]
            world=local@data.geom_xmat[geom].reshape(3,3).T+data.geom_xpos[geom]
            corners.append({'component':component['name'],'sampled_top':float(world[:,2].max()),'bound_top':component['top_world_m']})
    data.qpos[int(model.joint('base_free_joint').qposadr[0])+2]=-.008;mujoco.mj_forward(model,data)
    before=(data.qpos.copy(),data.qvel.copy(),data.ctrl.copy())
    mutated=height_envelope(model,data,manifest,.01)
    result['vehicles'][name]={'envelope':envelope,'box_corners':corners,'settled_cap_same':mutated==envelope,
        'query_preserved_live':all(np.array_equal(a,b) for a,b in zip(before,(data.qpos,data.qvel,data.ctrl)))}
model=mujoco.MjModel.from_xml_string('<mujoco><worldbody><body quat=".91 .1 .2 .3"><geom name="box" type="box" size=".1 .2 .3"/><geom name="cylinder" type="cylinder" size=".15 .25"/><geom name="sphere" type="sphere" size=".11"/></body></worldbody></mujoco>')
data=mujoco.MjData(model);mujoco.mj_forward(model,data);angles=np.linspace(0,2*math.pi,10001);support=[]
for name in ('box','cylinder','sphere'):
    geom=model.geom(name).id;bound=_geom_vertical_bounds(model,data,geom)
    if name=='box':local=np.array([[x*.1,y*.2,z*.3] for x in (-1,1) for y in (-1,1) for z in (-1,1)])
    elif name=='cylinder':local=np.vstack([np.column_stack((.15*np.cos(angles),.15*np.sin(angles),np.full(len(angles),z))) for z in (-.25,.25)])
    else:local=np.array([[0,0,.11]])@data.geom_xmat[geom].reshape(3,3)
    world=local@data.geom_xmat[geom].reshape(3,3).T+data.geom_xpos[geom]
    support.append({'name':name,'sampled_top':float(world[:,2].max()),'bound_top':bound['top_world_m']})
result['rotated_support']=support
print('RESULT_JSON:'+json.dumps(result))
'''
        run = subprocess.run([str(runtime), '-B', '-c', code, str(project), cls.temp.name],
                             capture_output=True, text=True, timeout=60)
        if run.returncode:
            raise RuntimeError('Compiled height probe failed:\n'+run.stdout+'\n'+run.stderr)
        cls.evidence = json.loads(run.stdout.rsplit('RESULT_JSON:', 1)[1])

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_both_real_models_enclose_all_collision_components(self):
        self.assertEqual(self.evidence['version'], '3.3.7')
        for name, data in self.evidence['vehicles'].items():
            with self.subTest(vehicle=name):
                result=data['envelope']
                self.assertGreater(len(result['compiled_collision_components']), 5)
                for component in result['compiled_collision_components']:
                    self.assertLessEqual(component['top_world_m'], result['max_obstacle_height_m'])
                for box in data['box_corners']:
                    self.assertAlmostEqual(box['sampled_top'], box['bound_top'])
                self.assertFalse(result['physical_geometry_changed'])
                self.assertFalse(result['physical_scoring_changed'])

    def test_j100_nominal_cap_includes_arbitrary_cargo_orientation(self):
        result=self.evidence['vehicles']['jackal_j100']['envelope']
        radius=math.sqrt(.009**2+.009**2+.008**2)
        self.assertAlmostEqual(result['tray_floor_top_world_m'], .2695)
        self.assertAlmostEqual(result['cargo']['arbitrary_orientation_radius_m'], radius)
        self.assertAlmostEqual(result['unpadded_top_world_m'], .2695+2*radius)
        self.assertAlmostEqual(result['max_obstacle_height_m'], .3095665927567458)
        self.assertAlmostEqual(result['nominal_base_footprint_world_z_m'], .002)

    def test_default_fishbot_uses_its_own_geometry_and_same_padding(self):
        fish=self.evidence['vehicles']['fishbot']['envelope']
        jackal=self.evidence['vehicles']['jackal_j100']['envelope']
        self.assertEqual(fish['vehicle_id'], 'fishbot')
        self.assertLess(fish['max_obstacle_height_m'], jackal['max_obstacle_height_m'])
        self.assertAlmostEqual(fish['max_obstacle_height_m']-fish['unpadded_top_world_m'], .01)

    def test_settled_data_cannot_reduce_nominal_cap_or_change_live_state(self):
        for name, data in self.evidence['vehicles'].items():
            with self.subTest(vehicle=name):
                self.assertTrue(data['settled_cap_same'])
                self.assertTrue(data['query_preserved_live'])

    def test_rotated_box_cylinder_and_sphere_bounds_cover_surface_samples(self):
        for sample in self.evidence['rotated_support']:
            with self.subTest(shape=sample['name']):
                self.assertLessEqual(sample['sampled_top'], sample['bound_top']+1e-12)
                self.assertLess(sample['bound_top']-sample['sampled_top'], 1e-6)


if __name__=='__main__': unittest.main()
