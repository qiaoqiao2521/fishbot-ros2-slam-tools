#!/usr/bin/python3
"""Safety cases for the external actor independent of ROS scheduling."""
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('obstacle_controller',ROOT/'scripts'/'obstacle_controller.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def item(x,y):
    return SimpleNamespace(pose=SimpleNamespace(pose=SimpleNamespace(position=SimpleNamespace(x=x,y=y))))


class ActorSafety(unittest.TestCase):
    def setUp(self):
        self.boxes = []
        for geom in ET.parse(ROOT/'mjcf'/'arena.xml').getroot().find('worldbody').findall('geom'):
            if geom.get('type')=='box':
                pos,size = geom.get('pos').split(),geom.get('size').split()
                self.boxes.append(tuple(map(float,(pos[0],pos[1],size[0],size[1]))))

    def test_fixture_route_avoids_car_and_fixed_boxes(self):
        start,target,robot = (-0.7,-0.7),(2.8,1.7),(0.0,0.0)
        path = MODULE.safe_path(start,target,self.boxes,robot)
        self.assertIsNotNone(path)
        self.assertLess(len(path),10, 'A* cells should collapse to checked straight segments')
        previous = start
        for following in path:
            for index in range(51):
                point = tuple(a+(b-a)*index/50 for a,b in zip(previous,following))
                self.assertGreaterEqual(math.dist(point,robot),MODULE.ROBOT_CLEARANCE)
                for x,y,hx,hy in self.boxes:
                    # Independent physical envelope assertion, not the planner's grid cost.
                    self.assertTrue(abs(point[0]-x)>hx+MODULE.ACTOR_RADIUS or
                                    abs(point[1]-y)>hy+MODULE.ACTOR_RADIUS)
            previous = following
        self.assertEqual(path[-1],target)

    def test_goal_inside_fixture_rejected(self):
        self.assertIsNone(MODULE.safe_path((-0.7,-0.7),(1.3,0.5),self.boxes,(0,0)))

    def test_new_robot_on_previous_route_blocks_next_step(self):
        self.assertFalse(MODULE.segment_clear((-.7,-.7),(-.6,-.7),self.boxes,(-.4,-.7)))

    def test_shorter_forward_candidate_avoids_central_fixture(self):
        robot = item(0,.12)
        robot.pose.pose.orientation = SimpleNamespace(w=1.0,x=0.0,y=0.0,z=0.0)
        probe = SimpleNamespace(robot=robot,actor=item(-.7,-.7),boxes=self.boxes,
                                xy=MODULE.ObstacleController.xy)
        path = MODULE.ObstacleController.staging_path(probe)
        self.assertIsNotNone(path)
        self.assertAlmostEqual(path[-1][0],.65)
        self.assertGreaterEqual(math.dist(path[-1],(0,.12)),MODULE.ROBOT_CLEARANCE)

    def test_frozen_clock_cannot_be_fresh_even_with_new_messages(self):
        probe = SimpleNamespace(robot=item(0,0),actor=item(-.7,-.7),truth_stamp=5.0,
            truth_wall=100.0,clock_advanced_wall=98.0,
            robot_sample=(5.0,100.0),actor_sample=(5.0,100.0),
            get_clock=lambda:SimpleNamespace(now=lambda:SimpleNamespace(nanoseconds=5_000_000_000)))
        with patch.object(MODULE.time,'monotonic',return_value=100.1):
            self.assertFalse(MODULE.ObstacleController.fresh(probe))
        probe.clock_advanced_wall=100.0
        with patch.object(MODULE.time,'monotonic',return_value=100.1):
            self.assertTrue(MODULE.ObstacleController.fresh(probe))

    def test_only_external_actor_has_freejoint_and_laser_height(self):
        actor = ET.parse(ROOT/'mjcf'/'arena.xml').getroot().find("worldbody/body[@name='moving_obstacle']")
        self.assertIsNotNone(actor.find('freejoint'))
        geom = actor.find('geom')
        center,height = float(actor.get('pos').split()[2]),float(geom.get('size').split()[2])
        self.assertLess(center-height,.167)
        self.assertGreater(center+height,.167)
        self.assertNotEqual(geom.get('contype'),'0')
        self.assertNotEqual(geom.get('conaffinity'),'0')

    def test_async_command_gap_moves_at_bounded_real_time_speed(self):
        commanded = []
        probe = SimpleNamespace(pending=None,last_tick=100.15,last_move_wall=100.0,
            state='moving',phase='insert',path=[(.8,-.7)],actor=item(0,-.7),robot=item(0,0),
            cycle_start=99.0,boxes=self.boxes,message='test',
            fresh=lambda:True,xy=MODULE.ObstacleController.xy,
            write_actor=lambda point:commanded.append(point),
            publisher=SimpleNamespace(publish=lambda message:None))
        with patch.object(MODULE.time,'monotonic',return_value=100.20):
            MODULE.ObstacleController.tick(probe)
        self.assertEqual(len(commanded),1)
        # 200 ms since the previous write must not be mistaken for one 50 ms tick;
        # a hard 10 cm pose-step bound still applies to any delayed service.
        self.assertAlmostEqual(commanded[0][0],.10)
        self.assertLessEqual(math.dist((0,-.7),commanded[0]),.10+1e-9)

    def test_live_return_corner_does_not_skip_inside_fixture_margin(self):
        actual,corner,next_corner = (1.920291643,-.071890406),(1.9,-.1),(.7,-.1)
        self.assertFalse(MODULE.segment_clear(actual,next_corner,self.boxes,(0,.12)))
        self.assertTrue(MODULE.segment_clear(actual,corner,self.boxes,(0,.12)))
        commanded = []
        probe = SimpleNamespace(pending=None,last_tick=100.15,last_move_wall=100.0,
            state='returning',phase='return',path=[corner,next_corner],
            actor=item(*actual),robot=item(0,.12),cycle_start=99.0,boxes=self.boxes,message='test',
            fresh=lambda:True,xy=MODULE.ObstacleController.xy,
            write_actor=lambda point:commanded.append(point),
            publisher=SimpleNamespace(publish=lambda message:None))
        with patch.object(MODULE.time,'monotonic',return_value=100.20):
            MODULE.ObstacleController.tick(probe)
        self.assertEqual(probe.path,[corner,next_corner])
        self.assertEqual(commanded,[corner])

    def test_millimetre_corner_tolerance_still_checks_next_segment(self):
        actual,corner,next_corner = (1.902,-.097),(1.9,-.1),(.7,-.1)
        self.assertLess(math.dist(actual,corner),.004)
        self.assertFalse(MODULE.segment_clear(actual,next_corner,self.boxes,(0,.12)))
        commanded = []
        probe = SimpleNamespace(pending=None,last_tick=100.15,last_move_wall=100.0,
            state='returning',phase='return',path=[corner,next_corner],
            actor=item(*actual),robot=item(0,.12),cycle_start=99.0,boxes=self.boxes,message='test',
            fresh=lambda:True,xy=MODULE.ObstacleController.xy,
            write_actor=lambda point:commanded.append(point),
            publisher=SimpleNamespace(publish=lambda message:None))
        with patch.object(MODULE.time,'monotonic',return_value=100.20):
            MODULE.ObstacleController.tick(probe)
        self.assertEqual(probe.path,[corner,next_corner])
        self.assertEqual(commanded,[corner])


if __name__=='__main__':
    unittest.main()
