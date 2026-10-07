"""Exercise the two actual pure domain gates without importing or starting ROS."""
import ast
from pathlib import Path
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]/'scripts'


def load_gate(filename):
    path = SCRIPTS/filename
    tree = ast.parse(path.read_text(), filename=str(path))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == 'validate_sim_domain')
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['validate_sim_domain']


class SimulationDomainTests(unittest.TestCase):
    def setUp(self):
        self.gates = [load_gate(name) for name in ('wait_ready.py', 'obstacle_controller.py')]

    def test_existing_default_93_remains_valid(self):
        for gate in self.gates:
            gate({'ROS_DOMAIN_ID': '93', 'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST'})

    def test_explicit_selected_domain_must_match(self):
        for gate in self.gates:
            for domain in ('1', '96', '232'):
                gate({'FISHBOT_MUJOCO_DOMAIN_ID': domain, 'ROS_DOMAIN_ID': domain,
                      'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST'})
            for selected, actual in (('93', '96'), ('96', '93'), ('96', ''), (None, '96')):
                env = {'ROS_DOMAIN_ID': actual, 'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST'}
                if selected is not None:
                    env['FISHBOT_MUJOCO_DOMAIN_ID'] = selected
                with self.subTest(selected=selected, actual=actual), self.assertRaises(SystemExit):
                    gate(env)

    def test_real_out_of_range_and_malformed_domains_are_rejected(self):
        for gate in self.gates:
            for domain in ('0', '00', '-1', '233', '96.0', ' 96', '+96', '', '９６'):
                with self.subTest(domain=domain), self.assertRaises(SystemExit):
                    gate({'FISHBOT_MUJOCO_DOMAIN_ID': domain, 'ROS_DOMAIN_ID': domain,
                          'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST'})

    def test_non_loopback_discovery_is_rejected(self):
        for gate in self.gates:
            for discovery in ('SUBNET', 'SYSTEM_DEFAULT', 'localhost', ''):
                with self.subTest(discovery=discovery), self.assertRaises(SystemExit):
                    gate({'FISHBOT_MUJOCO_DOMAIN_ID': '96', 'ROS_DOMAIN_ID': '96',
                          'ROS_AUTOMATIC_DISCOVERY_RANGE': discovery})


if __name__ == '__main__':
    unittest.main()
