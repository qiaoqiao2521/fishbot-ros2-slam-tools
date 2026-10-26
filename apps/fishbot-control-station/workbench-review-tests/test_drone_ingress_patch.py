"""Compile real receiver/ground blocks in temporary copies; never start PX4."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_drone_observation_patches import PX4, TOOLS, prepare


def message_struct(path, name):
    types = {'uint64': 'uint64_t', 'uint32': 'uint32_t', 'uint16': 'uint16_t',
             'uint8': 'uint8_t', 'float32': 'float', 'bool': 'bool'}
    fields = []
    for line in path.read_text().splitlines():
        line = line.split('#')[0].strip()
        if not line:
            continue
        kind, declaration = line.split(None, 1)
        array = re.fullmatch(r'(\w+)\[(\d+)\]', kind)
        if array:
            fields.append(f'{types[array[1]]} {declaration}[{array[2]}]{{}};')
        elif '=' in declaration:
            fields.append(f'static constexpr {types[kind]} {declaration};')
        else:
            fields.append(f'{types[kind]} {declaration}{{}};')
    return f'struct {name} {{'+''.join(fields)+'};\n'


PRELUDE = r'''
#include <matrix/math.hpp>
#include <cmath>
#include <cinttypes>
#include <cstdint>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>
uint64_t tick=12345678; int hrt_calls=0;
uint64_t hrt_absolute_time() {++hrt_calls;return tick;}
void scalar(float v) {if (std::isfinite(v)) std::cout<<v;else std::cout<<"null";}
void vector3(const float *v) {std::cout<<'[';for(int i=0;i<3;++i){if(i)std::cout<<',';scalar(v[i]);}std::cout<<']';}
template<class T> struct Pub {
    std::vector<T> rows; bool capture=true; int calls=0;
    bool publish(const T &v) {++calls;if(capture)rows.push_back(v);return capture;}
};
namespace uORB {template<class T> using Publication=Pub<T>;}
struct trajectory_setpoint_s {
    uint64_t timestamp{};float position[3]{},velocity[3]{},acceleration[3]{},yaw{},yawspeed{};
};
void setpoint_json(const trajectory_setpoint_s &s) {
    std::cout<<"{\"timestamp\":"<<s.timestamp<<",\"position\":";vector3(s.position);
    std::cout<<",\"velocity\":";vector3(s.velocity);std::cout<<",\"acceleration\":";vector3(s.acceleration);
    std::cout<<",\"yaw\":";scalar(s.yaw);std::cout<<",\"yawspeed\":";scalar(s.yawspeed);std::cout<<'}';
}
'''


RECEIVER_STUBS = r'''
constexpr uint8_t MAV_FRAME_LOCAL_NED=1,MAV_FRAME_BODY_NED=8;
constexpr uint16_t POSITION_TARGET_TYPEMASK_X_IGNORE=1,POSITION_TARGET_TYPEMASK_Y_IGNORE=2,
 POSITION_TARGET_TYPEMASK_Z_IGNORE=4,POSITION_TARGET_TYPEMASK_VX_IGNORE=8,
 POSITION_TARGET_TYPEMASK_VY_IGNORE=16,POSITION_TARGET_TYPEMASK_VZ_IGNORE=32,
 POSITION_TARGET_TYPEMASK_AX_IGNORE=64,POSITION_TARGET_TYPEMASK_AY_IGNORE=128,
 POSITION_TARGET_TYPEMASK_AZ_IGNORE=256,POSITION_TARGET_TYPEMASK_FORCE_SET=512,
 POSITION_TARGET_TYPEMASK_YAW_IGNORE=1024,POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE=2048;
struct mavlink_set_position_target_local_ned_t {
 uint32_t time_boot_ms=999;float x=1,y=2,z=3,vx=4,vy=5,vz=6,afx=7,afy=8,afz=9,yaw=.3f,yaw_rate=.4f;
 uint16_t type_mask=0;uint8_t coordinate_frame=1,target_system=1,target_component=1;
};
struct mavlink_message_t {uint8_t sysid=42,compid=17,seq=23;mavlink_set_position_target_local_ned_t payload;};
void mavlink_msg_set_position_target_local_ned_decode(const mavlink_message_t *m,mavlink_set_position_target_local_ned_t *v){*v=m->payload;}
struct {uint8_t sysid=1,compid=1;} mavlink_system;
struct offboard_control_mode_s {uint64_t timestamp{};bool position{},velocity{},acceleration{};};
struct vehicle_status_s {static constexpr uint8_t NAVIGATION_STATE_OFFBOARD=14;uint8_t nav_state=14;};
struct StatusSub {uint8_t nav=14;bool copy(vehicle_status_s *s){s->nav_state=nav;return true;}};
struct vehicle_attitude_s {float q[4]{.7071067812f,0,0,.7071067812f};};
struct AttitudeSub {bool copy(vehicle_attitude_s *s){*s=vehicle_attitude_s{};return true;}};
struct Mavlink {bool forward=true;bool get_forward_externalsp(){return forward;}uint8_t get_channel(){return 3;}};
int criticals=0,event_count=0;
template<class... A> void mavlink_log_critical(int*,const char*,A...){++criticals;}
namespace events {
enum class Log {Error};inline int ID(const char*){return 0;}
template<class... A> void send(int,Log,const char*,A...){++event_count;}
}
class MavlinkReceiver {
public:
 Mavlink _mavlink;StatusSub _vehicle_status_sub;AttitudeSub _vehicle_attitude_sub;int _mavlink_log_pub=0;
 Pub<offboard_control_mode_s> _offboard_control_mode_pub;Pub<trajectory_setpoint_s> _trajectory_setpoint_pub;
 Pub<mavlink_setpoint_ingress_s> _handoff_ingress_pub;uint64_t _handoff_ingress_sequence=0;
 void handle_message_set_position_target_local_ned(mavlink_message_t *msg);
};
'''


RECEIVER_MAIN = r'''
int main(int argc,char **argv) {
 if(argc!=2)return 2;std::cout<<std::setprecision(9);std::string test=argv[1];MavlinkReceiver r;mavlink_message_t m;
 if(test=="wrong_system")m.payload.target_system=2;
 if(test=="wrong_component")m.payload.target_component=2;
 if(test=="broadcast"){m.payload.target_system=0;m.payload.target_component=0;}
 if(test=="forward_off")r._mavlink.forward=false;
 if(test=="unsupported")m.payload.coordinate_frame=255;
 if(test=="force")m.payload.type_mask=512;
 if(test=="ignored")m.payload.type_mask=4095;
 if(test=="wire_nan")m.payload.x=m.payload.y=m.payload.z=m.payload.vx=m.payload.vy=m.payload.vz=m.payload.afx=m.payload.afy=m.payload.afz=NAN;
 if(test=="loiter")r._vehicle_status_sub.nav=4;
 if(test=="position_only")m.payload.type_mask=8+16+32+64+128+256+2048;
 if(test=="body" || test=="body_partial")m.payload.coordinate_frame=8;
 if(test=="body_partial")m.payload.type_mask=8;
 if(test=="drop_observation")r._handoff_ingress_pub.capture=false;
 if(test=="wrap")m.seq=255;
 r.handle_message_set_position_target_local_ned(&m);
 if(test=="wrap" || test=="same_tick") {if(test=="wrap")m.seq=0;r.handle_message_set_position_target_local_ned(&m);}
 std::cout<<"{\"ocm\":[";
 for(size_t i=0;i<r._offboard_control_mode_pub.rows.size();++i){if(i)std::cout<<',';const auto &v=r._offboard_control_mode_pub.rows[i];
 std::cout<<'['<<v.timestamp<<','<<v.position<<','<<v.velocity<<','<<v.acceleration<<']';}
 std::cout<<"],\"trajectory\":[";
 for(size_t i=0;i<r._trajectory_setpoint_pub.rows.size();++i){if(i)std::cout<<',';setpoint_json(r._trajectory_setpoint_pub.rows[i]);}
 std::cout<<"],\"criticals\":"<<criticals<<",\"events\":"<<event_count<<",\"hrt_calls\":"<<hrt_calls
 <<",\"ingress_publish_calls\":"<<r._handoff_ingress_pub.calls<<",\"ingress\":[";
 for(size_t i=0;i<r._handoff_ingress_pub.rows.size();++i){if(i)std::cout<<',';const auto &v=r._handoff_ingress_pub.rows[i];
 std::cout<<"{\"timestamp\":"<<v.timestamp<<",\"receive\":"<<v.receive_timestamp<<",\"receiver_sequence\":"<<v.receiver_sequence
 <<",\"message_sequence\":"<<unsigned(v.message_sequence)<<",\"sender_system\":"<<unsigned(v.sender_system)
 <<",\"sender_component\":"<<unsigned(v.sender_component)<<",\"channel\":"<<unsigned(v.receiver_channel)
 <<",\"wire_boot\":"<<v.wire_time_boot_ms<<",\"setpoint_stamp\":"<<v.setpoint_timestamp<<",\"ocm_stamp\":"<<v.offboard_mode_timestamp
 <<",\"decision\":"<<unsigned(v.decision)<<",\"nav\":"<<unsigned(v.nav_state)<<",\"mask\":"<<v.type_mask
 <<",\"frame\":"<<unsigned(v.coordinate_frame)<<",\"wire_position\":";vector3(v.wire_position);
 std::cout<<",\"wire_velocity\":";vector3(v.wire_velocity);std::cout<<",\"wire_acceleration\":";vector3(v.wire_acceleration);
 std::cout<<",\"position\":";vector3(v.decoded_position);std::cout<<",\"velocity\":";vector3(v.decoded_velocity);
 std::cout<<",\"acceleration\":";vector3(v.decoded_acceleration);std::cout<<'}';}
 std::cout<<"]}\n";
}
'''


GROUND_STUBS = r'''
#define PX4_ISFINITE(x) std::isfinite(x)
enum class TakeoffState {ground=0,rampup=1,flight=2};
struct Takeoff {TakeoffState state;TakeoffState getTakeoffState(){return state;}};
struct PositionControl {static const trajectory_setpoint_s empty_trajectory_setpoint;};
const trajectory_setpoint_s PositionControl::empty_trajectory_setpoint=[] {
 trajectory_setpoint_s s;for(int i=0;i<3;++i)s.position[i]=s.velocity[i]=s.acceleration[i]=NAN;s.yaw=s.yawspeed=NAN;return s;}();
struct Control {int hover=0,reset=0;void setHoverThrust(float){++hover;}void resetIntegral(){++reset;}};
struct Param {float get(){return .5f;}};
using matrix::Vector3f;
int main(int argc,char **argv) {
 if(argc!=4)return 2;Takeoff _takeoff{static_cast<TakeoffState>(std::atoi(argv[1]))};
 struct {bool ground_contact;} _vehicle_land_detected{bool(std::atoi(argv[2]))};
 struct {uint64_t timestamp_sample=456;} vehicle_local_position;
 Control _control;Param _param_mpc_thr_hover;trajectory_setpoint_s _setpoint;
 _setpoint.timestamp=123;for(int i=0;i<3;++i){_setpoint.position[i]=float(i+1);_setpoint.velocity[i]=float(i+4);_setpoint.acceleration[i]=float(i+7);}
 if(!std::atoi(argv[3]))_setpoint.velocity[2]=NAN;
 position_control_handoff_s handoff_observation{};
'''


GROUND_TAIL = r'''
 std::cout<<"{\"setpoint\":";setpoint_json(_setpoint);std::cout<<",\"hover\":"<<_control.hover<<",\"reset\":"<<_control.reset
 <<",\"flags\":["<<handoff_observation.ground_state_evaluated<<','<<handoff_observation.not_taken_off<<','
 <<handoff_observation.flying_ground_contact<<','<<handoff_observation.ground_override<<','<<handoff_observation.rampup_acceleration_cleared<<"]}\n";
}
'''


class IngressPatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        base, changed = cls.root/'consumption', cls.root/'ingress'
        prepare(PX4, TOOLS/'patches/px4-handoff-consumption.patch', base)
        ingress = TOOLS/'patches/px4-handoff-ingress.patch'
        # Stage two starts with the applied consumption files, plus only its
        # additional original targets. prepare then applies to a second copy.
        for name in re.findall(r'^--- a/(.+)$', ingress.read_text(), re.M):
            if not (base/name).exists():
                (base/name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(PX4/name, base/name)
        prepare(base, ingress, changed)
        cls.changed = changed
        if not shutil.which('g++'):
            raise RuntimeError('g++ required for real-function ingress checks')
        obs = message_struct(changed/'msg/MavlinkSetpointIngress.msg', 'mavlink_setpoint_ingress_s')
        ground_obs = message_struct(changed/'msg/PositionControlHandoff.msg', 'position_control_handoff_s')
        cls.executables = {}
        for name, tree, enabled in [('original', PX4, False), ('off', changed, False), ('on', changed, True)]:
            source = (tree/'src/modules/mavlink/mavlink_receiver.cpp').read_text()
            begin = source.index('void\nMavlinkReceiver::handle_message_set_position_target_local_ned(')
            end = source.index('\nvoid\nMavlinkReceiver::handle_message_set_position_target_global_int(', begin)
            define = '#define DRONE_HANDOFF_INGRESS_OBSERVATION 1\n' if enabled else ''
            cls.compile(name, define+PRELUDE+obs+RECEIVER_STUBS+source[begin:end]+RECEIVER_MAIN)
            control = (tree/'src/modules/mc_pos_control/MulticopterPositionControl.cpp').read_text()
            begin = control.index('\t\t\tconst bool not_taken_off')
            end = control.index('\n\t\t\t// limit tilt', begin)
            define = '#define DRONE_HANDOFF_OBSERVATION 1\n' if enabled else ''
            cls.compile('ground_'+name, define+PRELUDE+ground_obs+GROUND_STUBS+control[begin:end]+GROUND_TAIL)

    @classmethod
    def compile(cls, name, code):
        target = cls.root/name
        result = subprocess.run(['g++', '-std=gnu++14', '-Wall', '-Wextra', '-Werror',
            '-D__PX4_POSIX', '-D__PX4_LINUX', '-DCONFIG_ARCH_BOARD_PX4_SITL',
            '-I', str(PX4/'src/lib/matrix'), '-I', str(PX4/'platforms/common/include'),
            '-I', str(PX4/'build/px4_sitl_default'), '-x', 'c++', '-', '-o', str(target)],
            input=code, text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(name+' compile failed:\n'+result.stderr)
        cls.executables[name] = target

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_case(self, executable, *arguments):
        result = subprocess.run([str(self.executables[executable]), *map(str, arguments)],
            text=True, capture_output=True, check=True, timeout=5)
        return json.loads(result.stdout)

    def equivalent(self, case):
        original, disabled, enabled = [self.run_case(name, case) for name in ('original', 'off', 'on')]
        self.assertEqual(original, disabled)
        for key in ('ocm', 'trajectory', 'criticals', 'events'):
            self.assertEqual(original[key], enabled[key], (case, key))
        count = 2 if case in ('same_tick', 'wrap') else 1
        self.assertEqual(enabled['hrt_calls'], original['hrt_calls']+2*count)
        self.assertEqual(disabled['ingress'], [])
        return enabled

    def test_rejections_preserve_no_business_publications(self):
        for case, decision in [('wrong_system', 0), ('wrong_component', 0), ('forward_off', 0),
                ('unsupported', 1), ('force', 2), ('ignored', 3), ('wire_nan', 3)]:
            with self.subTest(case=case):
                result = self.equivalent(case)
                self.assertEqual(result['ocm'], [])
                self.assertEqual(result['trajectory'], [])
                row, = result['ingress']
                self.assertEqual(row['decision'], decision)
                self.assertEqual([row['ocm_stamp'], row['setpoint_stamp']], [0, 0])
                self.assertEqual(row['nav'], 255)

    def test_loiter_publishes_mode_but_not_trajectory(self):
        result = self.equivalent('loiter')
        self.assertEqual(result['ocm'], [[12345678, 1, 1, 1]])
        self.assertEqual(result['trajectory'], [])
        row, = result['ingress']
        self.assertEqual([row['decision'], row['nav'], row['ocm_stamp'], row['setpoint_stamp']], [4, 4, 12345678, 0])

    def test_offboard_and_broadcast_preserve_payload_and_local_hrt(self):
        for case in ('offboard', 'broadcast'):
            with self.subTest(case=case):
                result = self.equivalent(case)
                row, = result['ingress']
                payload, = result['trajectory']
                self.assertEqual(row['decision'], 5)
                self.assertEqual([row['receive'], row['timestamp'], row['ocm_stamp'], row['setpoint_stamp']], [12345678]*4)
                self.assertEqual(row['wire_boot'], 999)
                self.assertNotEqual(row['wire_boot']*1000, payload['timestamp'])
                self.assertEqual([row['sender_system'], row['sender_component'], row['channel']], [42, 17, 3])
                for name in ('position', 'velocity', 'acceleration'):
                    self.assertEqual(row[name], payload[name])

    def test_position_only_applies_nan_mask_without_altering_wire_values(self):
        result = self.equivalent('position_only')
        self.assertEqual(result['ocm'], [[12345678, 1, 0, 0]])
        row, = result['ingress']
        self.assertEqual(row['wire_velocity'], [4, 5, 6])
        self.assertEqual(row['wire_acceleration'], [7, 8, 9])
        self.assertEqual(row['velocity'], [None]*3)
        self.assertEqual(row['acceleration'], [None]*3)
        self.assertIsNone(result['trajectory'][0]['yawspeed'])

    def test_body_frame_uses_actual_px4_matrix_rotation(self):
        for case in ('body', 'body_partial'):
            with self.subTest(case=case):
                result = self.equivalent(case)
                row, = result['ingress']
                self.assertEqual(row['position'], [None]*3)
                self.assertEqual(row['wire_position'], [1, 2, 3])
                self.assertEqual(row['wire_velocity'], [4, 5, 6])
                if case == 'body':
                    for actual, expected in zip(row['velocity'], [-5, 4, 6]):
                        self.assertAlmostEqual(actual, expected, places=5)
                else:
                    self.assertEqual(row['velocity'], [None]*3)
                for actual, expected in zip(row['acceleration'], [-8, 7, 9]):
                    self.assertAlmostEqual(actual, expected, places=5)

    def test_eight_bit_wrap_and_same_tick_are_not_unique_identifiers(self):
        for case, wire_sequences in [('wrap', [255, 0]), ('same_tick', [23, 23])]:
            with self.subTest(case=case):
                result = self.equivalent(case)
                rows = result['ingress']
                self.assertEqual([row['message_sequence'] for row in rows], wire_sequences)
                self.assertEqual([row['receiver_sequence'] for row in rows], [1, 2])
                self.assertEqual([row['setpoint_stamp'] for row in rows], [12345678]*2)
                self.assertEqual(len(result['trajectory']), 2)

    def test_lost_observation_does_not_change_publication_decision(self):
        result = self.equivalent('drop_observation')
        self.assertEqual(result['ingress'], [])
        self.assertEqual(result['ingress_publish_calls'], 1)
        self.assertEqual(len(result['ocm']), 1)
        self.assertEqual(len(result['trajectory']), 1)

    def test_ground_flags_match_actual_ground_and_rampup_branches(self):
        for state in range(3):
            for contact in (0, 1):
                for finite_velocity in (0, 1):
                    with self.subTest(state=state, contact=contact, finite_velocity=finite_velocity):
                        old, off, on = [self.run_case('ground_'+name, state, contact, finite_velocity)
                            for name in ('original', 'off', 'on')]
                        self.assertEqual(old, off)
                        for field in ('setpoint', 'hover', 'reset'):
                            self.assertEqual(old[field], on[field])
                        grounded = state == 0 or state == 2 and bool(contact)
                        self.assertEqual(on['flags'], [1, int(state == 0), int(state == 2 and bool(contact)),
                            int(grounded), int(state == 1 and bool(finite_velocity))])
                        self.assertEqual(on['reset'], int(grounded))
                        if grounded:
                            self.assertEqual(on['setpoint']['acceleration'], [0, 0, 100])
                            self.assertEqual(on['setpoint']['timestamp'], 456)

    def test_option_defaults_off_and_decision_is_only_publish_called(self):
        patch = (TOOLS/'patches/px4-handoff-ingress.patch').read_text()
        self.assertIn('observations" OFF)', patch)
        message = (self.changed/'msg/MavlinkSetpointIngress.msg').read_text()
        self.assertIn('PUBLISH_CALLED = 5', message)
        self.assertNotRegex(message.lower(), r'candidate_(id|uuid)|sample_seq|acknowledged')

    def test_ingress_logger_registration_is_not_conditional_on_early_advertisement(self):
        logger = (self.changed/'src/modules/logger/logged_topics.cpp').read_text()
        self.assertRegex(logger, r'add_topic\("mavlink_setpoint_ingress"\);')
        self.assertNotIn('add_optional_topic("mavlink_setpoint_ingress"', logger)
        self.assertIn('add_optional_topic("position_control_handoff");', logger)


if __name__ == '__main__':
    unittest.main()
