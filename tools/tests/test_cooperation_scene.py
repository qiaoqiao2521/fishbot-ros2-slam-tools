"""Compile/contact/query regressions in the existing SO101 Python runtime.

The public fixture requires the sibling SO101 checkout and its planning venv.
Set FISHBOT_SO101_PYTHON to an equivalent runtime when testing elsewhere.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[2]
RUNTIME = Path(os.environ.get("FISHBOT_SO101_PYTHON",
                             str(Path.home() / ".cache/so101-colab/planning-venv/bin/python")))


class CooperationSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        code = r'''
import ast, hashlib, json, math, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1]+'/tools')
import mujoco
import numpy as np
from scipy.spatial import ConvexHull
from cooperation_scene import build_scene
from cooperation_arm import ArmPlanner
project=Path(sys.argv[1]); out=Path(sys.argv[2])
# Reuse the existing geometric predicate without importing its unrelated YAML CLI.
replay=ast.parse((project/'tools/fishbot_passage_replay.py').read_text())
distance=next(node for node in replay.body if isinstance(node,ast.FunctionDef) and node.name=='polygon_distance')
exec(compile(ast.Module(body=[distance],type_ignores=[]),'<existing-polygon-distance>','exec'))
manifest=build_scene(project.parent/'so101', project, out)
p=ArmPlanner(manifest); model=p.common; data=mujoco.MjData(model)
data.qpos[:6]=p.home; data.ctrl[:6]=p.home
dx,dy,yaw=manifest['dock_pose']
data.qpos[13:20]=[dx,dy,.002,np.cos(yaw/2),0,0,np.sin(yaw/2)]
mujoco.mj_forward(model,data)
fixed_tray_center=(data.xpos[model.body('cargo_tray').id]-p.station)[:2].copy()

# The footprint comes from compiled geometry, rather than a duplicated tray size.
footprint=np.asarray(manifest['car_footprint_xy']);hull=ConvexHull(footprint)
corners=np.asarray(manifest['car_footprint_tray_corners_xy'])
source_points=np.asarray(manifest['car_footprint_source_points_xy'])
angles=np.arange(3600)*2*np.pi/3600
circle=.13*np.column_stack((np.cos(angles),np.sin(angles)))
def contained(points):return bool(np.all(points@hull.equations[:,:2].T+hull.equations[:,2]<=1e-12))

obstacle=model.geom('approach_obstacle').id
signs=np.array([[x,y,z] for x in (-1,1) for y in (-1,1) for z in (-1,1)])
obstacle_vertices=((signs*model.geom_size[obstacle])@data.geom_xmat[obstacle].reshape(3,3).T+data.geom_xpos[obstacle])[:,:2]
obstacle_xy=obstacle_vertices[ConvexHull(obstacle_vertices).vertices].tolist()
def sweep_clearance(points,dock):
    staging=np.asarray(dock)+[.7,0.]
    vertices=np.vstack((points+staging,points+np.asarray(dock)))
    swept=vertices[ConvexHull(vertices).vertices].tolist()
    return min([polygon_distance(point,obstacle_xy) for point in swept]+
               [polygon_distance(point,swept) for point in obstacle_xy])
old_dock=(p.station[:2]+[.20,.16]).tolist()
old_tray_corners=corners+[0.,.04]
old_points=np.vstack((source_points[:64],old_tray_corners))
old_footprint=old_points[ConvexHull(old_points).vertices]
old_sweep=sweep_clearance(old_footprint,old_dock)
new_sweep=sweep_clearance(footprint,manifest['dock_pose'][:2])
old_center_distance=min(polygon_distance([x,old_dock[1]],obstacle_xy)
    for x in np.linspace(old_dock[0],old_dock[0]+.7,1001))
for _ in range(1000): mujoco.mj_step(model,data)
before=[data.qpos.copy(),data.qvel.copy(),data.ctrl.copy()]
prepared=p.prepare_approach(data.qpos[:6],car_pose=data.qpos[13:20])
snapshot={'qpos':data.qpos.copy(),'qvel':data.qvel.copy(),'ctrl':data.ctrl.copy()}
try: p.prepare_transport(snapshot)
except RuntimeError as error: negative=str(error)
else: raise RuntimeError('A payload on the pick floor must not admit transport')
target_geom=model.geom('target_collision').id
contacts=[(model.geom(c.geom1).name,model.geom(c.geom2).name) for c in data.contact]
allowed=[pair for pair in contacts if set(pair)=={'pick_floor','target_collision'}]
target_joint=model.joint('target_free').id
query=mujoco.MjData(p.rig);mujoco.mj_forward(p.rig,query)
actual_floor=query.geom_xpos[p.rig.geom('place_floor').id]+p.station
tray_world=data.xpos[model.body('cargo_tray').id]
local_up=data.xmat[model.body('cargo_tray').id].reshape(3,3)@np.array([0,0,.001])
sources_ok=all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest
               for path,digest in manifest['source_sha256'].items())
result={'layout':[model.nq,model.nv,model.nu],'target_free':int(model.jnt_type[target_joint])==int(mujoco.mjtJoint.mjJNT_FREE),
        'weld_count':model.neq,'mocap_count':model.nmocap,'target_mass':float(model.body('grasp_target').mass[0]),
        'jaw_force':model.actuator_forcerange[5].tolist(),'noslip':model.opt.noslip_iterations,
        'object_contact_count':len(allowed),'arm_invalid':p.evaluate(data.qpos[:6]),
        'max_speed':float(np.max(np.abs(data.qvel))),'sources_ok':sources_ok,
        'approach_exact':prepared['planning']['exact_solution'],
        'direct_blocked':not prepared['direct_approach']['valid'],
        'descent_valid':prepared['descent']['valid'],'ascent_valid':prepared['ascent']['valid'],
        'query_preserved_live':all(np.array_equal(old,current) for old,current in zip(before,[data.qpos,data.qvel,data.ctrl])),
        'negative_transport':negative,'actual_tray_error':float(np.linalg.norm(actual_floor-tray_world-local_up)),
        'wheel_mass':[float(model.body(name).mass[0]) for name in ['left_wheel_link','right_wheel_link']],
        'laser_xy':model.body('laser_link').pos[:2].tolist(),
        'display_groups':[int(model.geom(name).group[0]) for name in ['target_collision','floor','worktable']],
        'camera_present':model.camera('cooperation_overview').id>=0,
        'fixed_tray_center_arm_xy':fixed_tray_center.tolist(),
        'dock_pose':manifest['dock_pose'],'tray_offset':manifest['tray_offset'],
        'footprint_frame':manifest['car_footprint_frame'],'footprint_points':len(footprint),
        'original_circle_contained':contained(circle),'source_points_contained':contained(source_points),
        'actual_tray_corners_contained':contained(corners),'actual_tray_corner_count':len(corners),
        'old_layout':{'dock':old_dock,'tray_offset':[.04,-.02,.067],
                      'center_to_obstacle_m':old_center_distance,'swept_clearance_m':old_sweep},
        'new_layout':{'dock':manifest['dock_pose'][:2],'tray_offset':manifest['tray_offset'],
                      'swept_clearance_m':new_sweep},'unchanged_footprint_padding_m':.01}
print('RESULT_JSON:'+json.dumps(result))
'''
        result = subprocess.run([str(RUNTIME), "-B", "-c", code, str(PROJECT), cls.temp.name],
                                text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError(f"Cooperation model probe failed:\n{result.stdout}\n{result.stderr}")
        cls.evidence = json.loads(result.stdout.rsplit("RESULT_JSON:", 1)[1])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_common_model_preserves_free_object_and_source_contact_limits(self):
        evidence = self.evidence
        self.assertEqual(evidence["layout"], [22, 20, 8])
        self.assertTrue(evidence["target_free"])
        self.assertEqual(evidence["weld_count"], 0)
        self.assertEqual(evidence["mocap_count"], 0)
        self.assertEqual(evidence["jaw_force"], [-.15, .15])
        self.assertEqual(evidence["noslip"], 10)
        self.assertEqual(evidence["target_mass"], .01)
        self.assertEqual(evidence["wheel_mass"], [.2, .2])
        self.assertEqual(evidence["laser_xy"], [-.065, 0.])
        self.assertTrue(evidence["sources_ok"])
        self.assertEqual(evidence["display_groups"], [0, 0, 0])
        self.assertTrue(evidence["camera_present"])

    def test_static_scene_settles_without_arm_collision(self):
        self.assertEqual(self.evidence["object_contact_count"], 4)
        self.assertLess(self.evidence["max_speed"], 1e-5)
        self.assertTrue(self.evidence["arm_invalid"]["valid"], self.evidence["arm_invalid"])

    def test_approach_reuses_exact_ompl_and_queries_keep_live_state(self):
        for field in ("approach_exact", "direct_blocked", "descent_valid", "ascent_valid",
                      "query_preserved_live"):
            self.assertTrue(self.evidence[field], field)

    def test_transport_rejects_air_grasp_and_freezes_actual_car_geometry(self):
        self.assertIn("no dual-finger contact", self.evidence["negative_transport"])
        self.assertLess(self.evidence["actual_tray_error"], 1e-8)

    def test_dock_and_tray_shift_preserves_the_fixed_arm_delivery_center(self):
        evidence=self.evidence
        self.assertEqual(evidence['dock_pose'],[-1.8,-1.8,0.])
        self.assertEqual(evidence['tray_offset'],[.04,-.06,.067])
        for actual,expected in zip(evidence['fixed_tray_center_arm_xy'],[.24,.14]):
            self.assertAlmostEqual(actual,expected,places=10)

    def test_complete_footprint_encloses_compiled_tray_corners_and_original_circle(self):
        evidence=self.evidence
        self.assertEqual(evidence['footprint_frame'],'base_footprint')
        self.assertGreaterEqual(evidence['footprint_points'],3)
        self.assertEqual(evidence['actual_tray_corner_count'],40)
        self.assertTrue(evidence['original_circle_contained'])
        self.assertTrue(evidence['source_points_contained'])
        self.assertTrue(evidence['actual_tray_corners_contained'])

    def test_new_straight_docking_sweep_clears_original_collision_padding(self):
        evidence=self.evidence
        self.assertEqual(evidence['old_layout']['dock'],[-1.8,-1.84])
        self.assertAlmostEqual(evidence['old_layout']['center_to_obstacle_m'],.132,places=10)
        padding=evidence['unchanged_footprint_padding_m']
        self.assertLess(evidence['old_layout']['swept_clearance_m'],padding)
        self.assertGreater(evidence['new_layout']['swept_clearance_m'],padding)


if __name__ == "__main__":
    unittest.main()
