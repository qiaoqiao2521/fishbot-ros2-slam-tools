"""Apply only to temporary copies; never import Flight or start a vehicle."""
import ast
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]/'workbench-tools'
DRONE = Path('/home/muqiao/dev/ros2/projects/drone')
PX4 = Path('/home/muqiao/.cache/ros2-drone/PX4-Autopilot')
BASE = 'src/modules/mc_pos_control/'


def prepare(source, patchfile, destination):
    contents = patchfile.read_text()
    for name in re.findall(r'^--- a/(.+)$', contents, re.M):
        target = destination/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source/name, target)
    subprocess.run(['git', 'apply', '--check', '--whitespace=error-all', str(patchfile)], cwd=destination, check=True, capture_output=True)
    subprocess.run(['git', 'apply', str(patchfile)], cwd=destination, check=True, capture_output=True)


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def setpoint_function(path):
    tree = ast.parse(path.read_text())
    flight = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Flight')
    method = next(n for n in flight.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'setpoint')
    frames = module(DRONE/'frames.py', 'observation_frames')
    namespace = dict(enu_to_ned=frames.enu_to_ned, enu_yaw_to_ned_degrees=frames.enu_yaw_to_ned_degrees)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace['setpoint']


class SenderPatch(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        prepare(DRONE, TOOLS/'patches/drone-handoff-sender.patch', cls.root)
        cls.helper = module(cls.root/'handoff_observation.py', 'handoff_observation_test')
        cls.original = staticmethod(setpoint_function(DRONE/'flight.py'))
        cls.changed = staticmethod(setpoint_function(cls.root/'flight.py'))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    async def invoke(self, function, *, enabled, velocity, failure=None, broken_log=False):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.dict(os.environ, {'DRONE_TRACE_HANDOFF': '1' if enabled else '0'}):
                trace = self.helper.HandoffObservation.from_environment(output, 'task-A')
            if trace is not None and broken_log:
                trace.path = output # opening a directory must not change control
            owner = types.SimpleNamespace(origin=[10., -3., 2.], observer=types.SimpleNamespace(simulation_s=4.),
                handoff_observation=trace, command_position='previous', reference={'previous': True})
            calls = []
            async def sdk(*args):
                calls.append([list(value.values) for value in args])
                owner.observer.simulation_s = 4.2
                if failure is not None:
                    raise failure
            owner.drone = types.SimpleNamespace(offboard=types.SimpleNamespace(
                set_position_ned=sdk, set_position_velocity_acceleration_ned=sdk))
            class Value:
                def __init__(self, *values): self.values = values
            offboard = types.ModuleType('mavsdk_grpc.offboard')
            offboard.PositionNedYaw = offboard.VelocityNedYaw = offboard.AccelerationNed = Value
            sdkmodule = types.ModuleType('mavsdk_grpc')
            modules = {'mavsdk_grpc': sdkmodule, 'mavsdk_grpc.offboard': offboard}
            kwargs = dict(velocity=[.4, -.5, .6], acceleration=[.1, .2, -.3]) if velocity else {}
            if function is self.changed:
                kwargs['observation_context'] = {'goal_id': 'goal-A', 'trajectory_id': 7, 'command_stamp_sim_s': 3.95}
            caught = None
            with patch.dict(sys.modules, modules):
                try:
                    await function(owner, [11., -1., 4.], .3, **kwargs)
                except BaseException as error:
                    caught = error
            log = output/'handoff-sender.jsonl'
            rows = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return calls, owner.reference, owner.command_position, caught, rows, list(output.iterdir())

    async def test_default_off_creates_no_file_and_matches_original_both_modes(self):
        for velocity in [False, True]:
            old = await self.invoke(self.original, enabled=False, velocity=velocity)
            new = await self.invoke(self.changed, enabled=False, velocity=velocity)
            self.assertEqual(old[:4], new[:4])
            self.assertEqual(new[4:], ([], []))

    async def test_enabled_preserves_payload_reference_and_captures_both_clocks(self):
        for velocity in [False, True]:
            old = await self.invoke(self.original, enabled=False, velocity=velocity)
            new = await self.invoke(self.changed, enabled=True, velocity=velocity)
            self.assertEqual(old[:4], new[:4])
            start, returned = new[4]
            self.assertEqual([start['stage'], returned['stage']], ['rpc_start', 'rpc_return'])
            self.assertEqual([start['source_simulation_s'], returned['source_simulation_s']], [4., 4.2])
            self.assertEqual(new[1]['simulation_s'], 4.)
            self.assertLessEqual(start['host_monotonic_ns'], returned['host_monotonic_ns'])
            self.assertEqual(start['rpc_call_seq'], returned['rpc_call_seq'])
            self.assertEqual(start['trace_session_id'], returned['trace_session_id'])
            self.assertEqual(start['identity']['goal_id'], 'goal-A')
            self.assertEqual(start['sdk_payload_ned']['position'], [2., 1., -2.])
            self.assertEqual(start['sdk_payload_ned']['velocity'], [-.5, .4, -.6] if velocity else None)
            self.assertEqual(start['sdk_payload_ned']['acceleration'], [.2, .1, .3] if velocity else None)
            self.assertIsNone(start['source_epoch'])
            self.assertEqual(start['actual_execution_admission'], 'unqualified_observation')

    async def test_sdk_error_and_cancellation_propagate_without_reference_commit(self):
        for error in [RuntimeError('SDK failed'), asyncio.CancelledError()]:
            old = await self.invoke(self.original, enabled=False, velocity=True, failure=error)
            new = await self.invoke(self.changed, enabled=True, velocity=True, failure=error)
            self.assertEqual(old[:3], new[:3])
            self.assertIs(new[3], error)
            self.assertEqual(new[1], {'previous': True})
            self.assertEqual(new[4][-1]['stage'], 'rpc_error')
            self.assertEqual(new[4][-1]['exception_type'], type(error).__name__)

    async def test_io_failure_does_not_replace_success_error_or_cancellation(self):
        for error in [None, RuntimeError('SDK failed'), asyncio.CancelledError()]:
            old = await self.invoke(self.original, enabled=False, velocity=True, failure=error)
            new = await self.invoke(self.changed, enabled=True, velocity=True, failure=error, broken_log=True)
            self.assertEqual(old[:3], new[:3])
            self.assertIs(new[3], error)
            self.assertEqual(new[4], [])

    def test_sequence_and_nonfinite_observation_fail_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            trace = self.helper.HandoffObservation(Path(directory)/'trace.jsonl', 'task-A')
            trace.emit('rpc_start', trace.next_sequence(), float('nan'))
            trace.emit('rpc_start', trace.next_sequence(), 1.)
            rows = [json.loads(line) for line in trace.path.read_text().splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['rpc_call_seq'], 2)


class ControllerPatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        prepare(PX4, TOOLS/'patches/px4-handoff-consumption.patch', cls.root)
        if not shutil.which('g++'):
            raise RuntimeError('g++ required for controller branch equivalence check')
        cls.old = (PX4/BASE/'MulticopterPositionControl.cpp').read_text()
        cls.new = (cls.root/BASE/'MulticopterPositionControl.cpp').read_text()
        cls.executables = {}
        for name, source, enabled in [('original', cls.old, False), ('off', cls.new, False), ('on', cls.new, True)]:
            code = cls.harness(source, enabled)
            target = cls.root/name
            subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-x', 'c++', '-', '-o', str(target)],
                           input=code, text=True, capture_output=True, check=True)
            cls.executables[name] = target

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    @classmethod
    def harness(cls, source, enabled):
        # Compile the actual original/patched subscription and controller blocks.
        start = source.index('#ifdef DRONE_HANDOFF_OBSERVATION\n        position_control_handoff_s') if 'position_control_handoff_s handoff_observation' in source else source.index('\t\t_trajectory_setpoint_sub.update(&_setpoint);')
        subscription = source[start:source.index('\n\n\t\tadjustSetpointForEKFResets', start)]
        begin = source.index('\t\t\tconst hrt_abstime now = hrt_absolute_time();')
        end = source.index('\n\t\t\t// Publish attitude setpoint output', begin)
        block = source[begin:end]
        fields = []
        typemap = {'uint64': 'uint64_t', 'uint8': 'uint8_t', 'float32': 'float', 'bool': 'bool'}
        for line in (cls.root/'msg/PositionControlHandoff.msg').read_text().splitlines():
            line = line.split('#')[0].strip()
            if not line: continue
            kind, declaration = line.split(None, 1)
            m = re.fullmatch(r'(\w+)\[(\d+)\]', kind)
            if m: fields.append(f'{typemap[m[1]]} {declaration}[{m[2]}]{{}};')
            elif '=' in declaration: fields.append(f'static constexpr {typemap[kind]} {declaration};')
            else: fields.append(f'{typemap[kind]} {declaration}{{}};')
        prelude = r'''
#include <cstdint>
#include <cmath>
#include <iostream>
#include <vector>
#include <cstdlib>
using hrt_abstime = uint64_t;
constexpr uint64_t operator""_ms(unsigned long long n) { return n*1000; }
uint64_t hrt_absolute_time() {return 1000000;}
struct trajectory_setpoint_s {uint64_t timestamp{}; float position[3]{}, velocity[3]{}, acceleration[3]{}, yaw{};};
struct Local {float x=21,y=22,z=23,vx=24,vy=25,vz=26,acceleration[3]{27,28,29}; uint64_t timestamp{};};
struct Constraints {int one;float two,three;bool four;float five[1];};
struct Param {float get() const {return 1.f;}};
struct InputSub {bool fresh=true;bool update(trajectory_setpoint_s*) {return fresh;}};
struct Control {
    trajectory_setpoint_s input{}; std::vector<int> calls; int count=0, bits=0;
    bool update(float) {calls.push_back(int(input.timestamp)); return bits & (1<<count++);}
    void setInputSetpoint(const trajectory_setpoint_s &s) {input=s;}
    void setVelocityLimits(float,float,float) {}
    void getLocalPositionSetpoint(Local &s) {s=Local{};}
};
void adjustSetpointForEKFResets(int, trajectory_setpoint_s &s) {s.position[0]+=7.f;}
int failsafes=0;
trajectory_setpoint_s generateFailsafeSetpoint(uint64_t, int, bool) {++failsafes;trajectory_setpoint_s s{};s.timestamp=333;s.position[0]=9;return s;}
struct OutputPub {int calls=0;void publish(const Local&) {++calls;}};
'''
        setup = r'''
struct ObsPub {position_control_handoff_s data{}; int calls=0; void publish(const position_control_handoff_s &s) {data=s;++calls;}};
int main(int argc, char**argv) {
    if (argc!=7) return 4;
    Control _control; _control.bits=std::atoi(argv[1]);
    trajectory_setpoint_s _setpoint{},_last_valid_setpoint{};
    _setpoint.timestamp=111;_setpoint.position[0]=1;_setpoint.yaw=.2f;
    _last_valid_setpoint.timestamp=std::atoi(argv[2]) ? 900000 : 0;
    _last_valid_setpoint.position[0]=4;
    trajectory_setpoint_s _handoff_raw_input{};
    bool _handoff_raw_input_seen=std::atoi(argv[5]);
    if (_handoff_raw_input_seen) _handoff_raw_input=_setpoint;
    if (!std::atoi(argv[4])) _setpoint.position[0]=80;
    bool _handoff_setpoint_is_failsafe=false, _handoff_last_valid_is_failsafe=false;
    (void)_handoff_raw_input_seen; (void)_handoff_setpoint_is_failsafe; (void)_handoff_last_valid_is_failsafe;
    InputSub _trajectory_setpoint_sub; _trajectory_setpoint_sub.fresh=std::atoi(argv[4]);
    Constraints _vehicle_constraints{};
    Param _param_mpc_xy_vel_max,_param_mpc_z_vel_max_up,_param_mpc_z_vel_max_dn;
    OutputPub _local_pos_sp_pub; ObsPub _handoff_observation_pub;
    struct {uint64_t timestamp_sample=456;} vehicle_local_position;
    int states=0; float dt=.01f;
'''
        tail = r'''
    (void)_vehicle_constraints; (void)_handoff_raw_input;
    std::cout << _control.count << " " << failsafes << " " << _last_valid_setpoint.timestamp << " " << _local_pos_sp_pub.calls;
    for (auto call : _control.calls) std::cout << " " << call;
    std::cout << "|" << _handoff_observation_pub.calls;
    if (_handoff_observation_pub.calls) {
        auto &s=_handoff_observation_pub.data;
        std::cout << " " << int(s.update_attempts) << " " << int(s.update_success_mask) << " " << int(s.used_branch)
                  << " " << s.raw_input_timestamp << " " << s.used_input_timestamp << " " << s.state_sample_timestamp
                  << " " << s.raw_position[0] << " " << s.used_position[0] << " " << s.output_position[0]
                  << " " << s.output_timestamp << " " << s.input_updated << " " << s.raw_input_available << " " << s.pre_control_failsafe << " " << s.used_local_failsafe;
    }
    std::cout << "\n";
}
'''
        # Include actual source block's required native output type name.
        prelude += 'using vehicle_local_position_setpoint_s = Local;\n'
        define = '#define DRONE_HANDOFF_OBSERVATION 1\n' if enabled else ''
        # Same adjustment as production, after subscription and before setInput.
        prefailsafe_start = source.index('\t\t\t\t_setpoint = generateFailsafeSetpoint(vehicle_local_position.timestamp_sample, states, false);')
        prefailsafe = source[prefailsafe_start:source.index('\n\t\t\t}', prefailsafe_start)]
        middle = '\nadjustSetpointForEKFResets(0, _setpoint);\nif (std::atoi(argv[3]) && cycle==0) {\n'+prefailsafe+'\n}\n_control.setInputSetpoint(_setpoint);\n'
        # Existing function accepts a complex state; harness overload models that irrelevant type.
        prelude += 'template<class T> void adjustSetpointForEKFResets(T, trajectory_setpoint_s &s) {adjustSetpointForEKFResets(0,s);}\n'
        return define+prelude+'struct position_control_handoff_s {'+'\n'.join(fields)+'};\n'+setup+'for(int cycle=0;cycle<std::atoi(argv[6]);++cycle) {\n_trajectory_setpoint_sub.fresh=std::atoi(argv[4]) && cycle==0;\n'+subscription+middle+block+'\n}\n'+tail

    def result(self, executable, bits, old, prefailsafe=False, fresh=True, seen=False, cycles=1):
        return subprocess.check_output([str(self.executables[executable]), str(bits), str(int(old)), str(int(prefailsafe)), str(int(fresh)), str(int(seen)),str(cycles)], text=True).strip().split('|')

    def test_actual_control_call_order_and_output_preserved_all_branches(self):
        for bits, old in [(1,False),(2,True),(2,False),(4,True),(4,False),(0,True),(0,False)]:
            with self.subTest(bits=bits,old=old):
                original = self.result('original',bits,old)
                disabled = self.result('off',bits,old)
                enabled = self.result('on',bits,old)
                self.assertEqual(original,disabled)
                self.assertEqual(original[0],enabled[0])
                self.assertEqual(disabled[1],'0')
                record=list(map(float,enabled[1].split()))
                count=int(original[0].split()[0])
                self.assertEqual(record[0:3],[1,count,bits & ((1<<count)-1)])
                branch=0 if count==1 or count==2 and not old else 1 if count==2 else 2
                self.assertEqual(record[3],branch)
                self.assertEqual(record[4],111)
                self.assertEqual(record[5],111 if branch==0 else 900000 if branch==1 else 333)
                self.assertEqual(record[6:10],[456,1,8 if branch==0 else 11 if branch==1 else 9,21])
                self.assertEqual(record[10:],[1000000,1,1,0,int(branch==2)])

    def test_no_update_retains_raw_subscription_instead_of_modified_setpoint(self):
        for seen in [False, True]:
            old=self.result('original',1,False,fresh=False,seen=seen)
            new=self.result('on',1,False,fresh=False,seen=seen)
            self.assertEqual(old[0],new[0])
            row=list(map(float,new[1].split()))
            self.assertEqual(row[4],111 if seen else 0)
            self.assertEqual(row[7],1 if seen else 0)
            self.assertEqual(row[8],87) # applied state was modified after the subscription
            self.assertEqual(row[-4:],[0,int(seen),0,0])

    def test_pre_control_failsafe_is_marked_even_if_first_update_succeeds(self):
        old = self.result('original',1,False,True)
        new = self.result('on',1,False,True)
        self.assertEqual(old[0],new[0])
        row=list(map(float,new[1].split()))
        self.assertEqual(row[1:6],[1,1,2,111,333])
        self.assertEqual(row[-2:],[1,1])

    def test_retained_pre_control_failsafe_keeps_provenance_next_cycle(self):
        old=self.result('original',3,False,True,cycles=2)
        new=self.result('on',3,False,True,cycles=2)
        self.assertEqual(old[0],new[0])
        row=list(map(float,new[1].split()))
        self.assertEqual(row[:6],[2,1,1,2,111,333])
        self.assertEqual(row[-4:],[0,1,0,1]) # no new input/generation; retained failsafe

    def test_final_failsafe_failure_is_not_mislabeled_success(self):
        enabled=list(map(int,self.result('on',0,True)[1].split()[:4]))
        self.assertEqual(enabled,[1,3,0,2])

    def test_option_defaults_off_and_logger_has_no_sampling_interval(self):
        cmake=(self.root/BASE/'CMakeLists.txt').read_text()
        self.assertIn('observations" OFF)',cmake)
        self.assertIn('add_optional_topic("position_control_handoff");',
                      (self.root/'src/modules/logger/logged_topics.cpp').read_text())


if __name__ == '__main__': unittest.main()
