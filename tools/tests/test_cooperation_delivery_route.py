"""Time estimates are planning evidence, never physical task acceptance."""
import math
import unittest

from cooperation_delivery_route import path_time_budget


class RouteBudgetTests(unittest.TestCase):
    def budget(self, paths):
        return path_time_budget(paths, linear_speed=.03, angular_speed=.05,
            linear_accel=.025, linear_decel=.025, angular_accel=.05, angular_decel=.05)

    def test_linear_angular_overlap_stops_and_reversals_are_separate(self):
        path=[{'x':0.,'y':0.,'yaw':0.}, {'x':.3,'y':0.,'yaw':.5},
              {'x':0.,'y':0.,'yaw':0.}]
        value=self.budget([path,path])
        self.assertAlmostEqual(value['kinematic_lower_bound_s'],40.)
        self.assertEqual([leg['direction_reversals'] for leg in value['legs']],[1,1])
        self.assertGreater(value['estimated_with_allowance_s'],40.)
        self.assertFalse(value['execution_upper_bound_claimed'])
        self.assertEqual(value['budget_wall_s'],120.)

    def test_yaw_wrap_is_not_a_full_turn_and_budget_can_be_impossible(self):
        path=[{'x':0.,'y':0.,'yaw':math.pi-.01}, {'x':4.,'y':0.,'yaw':-math.pi+.01}]
        value=self.budget([path])
        self.assertAlmostEqual(value['legs'][0]['absolute_yaw_change_rad'],.02)
        self.assertLess(value['estimated_headroom_s'],0.)

    def test_invalid_samples_do_not_silently_make_zero_time(self):
        for paths in ([[]],[[{'x':0.,'y':0.,'yaw':0.}]],
                      [[{'x':0.,'y':0.,'yaw':0.},{'x':math.nan,'y':0.,'yaw':0.}]]):
            with self.assertRaises(ValueError):self.budget(paths)


if __name__=='__main__':unittest.main()
