"""Offline parity checks for both read-only voice admission boundaries."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from fishbot_voice_ui_acceptance import manual_preflight, wait_fresh_observation
import fishbot_voice_ui_acceptance as acceptance
from fishbot_manual_acceptance import LIMITS, boundary_frames, quiet_result

INSTANCE = '6614308f-3a25-4940-bb97-c338464ee13a'
LEASE = 'a2fc2ba7-fd45-4cac-83d6-9d6977fcdf32'
TASK = '00c00fd8-994c-4639-b581-edc83b112c34'

JS = r"""
const fs=require('node:fs');
const {manualPreflight}=require(process.argv[1]);
const f=JSON.parse(fs.readFileSync(0,'utf8')), reads=[];
manualPreflight(f.runtime,f.state,async path=>{
  reads.push(path);
  if(path==='/sim-api/manual/status')return f.status;
  if(path==='/sim-api/manual/'+f.status.active_lease_id)return {lease:f.lease};
  throw Error('Unexpected read '+path);
}).then(value=>process.stdout.write(JSON.stringify({accepted:true,reads,value})))
.catch(error=>process.stdout.write(JSON.stringify({accepted:false,reads,error:String(error)})));
"""


class VoiceManualPreflightTests(unittest.TestCase):
    def setUp(self):
        self.fixture = {'runtime': {'instance_id': INSTANCE, 'capabilities': [
            {'id': 'teleop', 'protocol': 'manual_lease_v1', 'profile_id': 'passage_manual',
             'available': True, 'limits': copy.deepcopy(LIMITS)}]},
            'state': {'mission': {'id': None, 'status': 'idle'}, 'map_rules': {'map_id': 'map-a'}},
            'status': {'runtime_instance_id': INSTANCE, 'profile_id': 'passage_manual', 'map_id': 'map-a',
                'available': True, 'limits': copy.deepcopy(LIMITS), 'can_acquire': True, 'stop_latched': False,
                'native_owner': {'terminal': True, 'task_id': None, 'native_goal_id': None, 'status': 'idle'},
                'active_lease_id': None, 'quiet': {'confirmed': True, 'duration_s': .7,
                    'receive_age_s': .02, 'source_age_s': .02, 'source_stamp': 10.}}, 'lease': None}

    def both(self, accepted, fixture=None, expected_reads=None):
        fixture = copy.deepcopy(self.fixture if fixture is None else fixture)
        reads = []
        def read(path):
            reads.append('/sim-api/'+path)
            if path == 'manual/status': return fixture['status']
            if path == 'manual/'+str(fixture['status']['active_lease_id']): return {'lease': fixture['lease']}
            raise AssertionError('Unexpected read '+path)
        try:
            value = manual_preflight(fixture['runtime'], fixture['state'], read)
            python_accepted = True
        except (RuntimeError, ValueError, TypeError, KeyError):
            value, python_accepted = None, False
        node = subprocess.run(['node', '-e', JS, str(ROOT/'tools/fishbot_voice_ui_acceptance.cjs')],
            input=json.dumps(fixture), capture_output=True, text=True, timeout=5, check=True)
        js = json.loads(node.stdout)
        self.assertEqual(python_accepted, accepted)
        self.assertEqual(js['accepted'], accepted)
        self.assertEqual(js['reads'], reads)
        if expected_reads is not None: self.assertEqual(reads, expected_reads)
        if accepted: self.assertEqual(js['value'], value)

    def historical_lease(self):
        self.fixture['status']['active_lease_id'] = LEASE
        self.fixture['lease'] = {'lease_id': LEASE, 'runtime_instance_id': INSTANCE,
            'profile_id': 'passage_manual', 'map_id': 'map-a', 'state': 'released',
            'guard_stop_acknowledged': True, 'quiet': {'confirmed': True}}

    def test_fresh_idle_owner_is_read_without_any_mutation(self):
        self.both(True, expected_reads=['/sim-api/manual/status'])

    def test_old_runtime_without_manual_capability_uses_original_contract(self):
        self.fixture['runtime']['capabilities'] = []
        self.both(True, expected_reads=[])

    def test_completed_native_original_id_is_allowed_without_adopting_another_id(self):
        self.fixture['state']['mission'].update(id=TASK, status='canceled')
        self.fixture['status']['native_owner'].update(task_id=TASK, status='canceled')
        self.both(True)
        self.fixture['status']['native_owner']['task_id'] = INSTANCE
        self.both(False)

    def test_retained_terminal_lease_id_requires_its_original_cleanup_receipt(self):
        self.historical_lease()
        for state in ('released', 'expired', 'stopped'):
            with self.subTest(state=state):
                self.fixture['lease']['state'] = state
                self.both(True, expected_reads=['/sim-api/manual/status', '/sim-api/manual/'+LEASE])

    def test_active_unknown_and_unconfirmed_lease_never_admit_voice(self):
        self.historical_lease()
        for field, value in (('state', 'active'), ('state', 'unknown'), ('guard_stop_acknowledged', False),
                ('lease_id', TASK), ('runtime_instance_id', TASK), ('map_id', 'map-b'), ('quiet', {'confirmed': False})):
            with self.subTest(field=field, value=value):
                fixture = copy.deepcopy(self.fixture); fixture['lease'][field] = value
                self.both(False, fixture)

    def test_stop_identity_authority_and_fresh_quiet_boundaries_are_required(self):
        cases = [('stop_latched', True), ('can_acquire', False), ('runtime_instance_id', TASK),
            ('profile_id', 'baseline'), ('map_id', 'map-b'), ('native_owner', {'terminal': False, 'task_id': None})]
        for field, value in cases:
            with self.subTest(field=field):
                fixture = copy.deepcopy(self.fixture); fixture['status'][field] = value
                self.both(False, fixture)
        for field, value in (('confirmed', False), ('duration_s', .699), ('receive_age_s', .251),
                ('receive_age_s', -.001), ('source_age_s', .251), ('source_age_s', -.051), ('source_stamp', None)):
            with self.subTest(quiet=field, value=value):
                fixture = copy.deepcopy(self.fixture); fixture['status']['quiet'][field] = value
                self.both(False, fixture)

    def test_advertised_manual_profile_cannot_silently_downgrade(self):
        for field, value in (('available', False), ('profile_id', 'baseline')):
            with self.subTest(field=field):
                fixture = copy.deepcopy(self.fixture); fixture['runtime']['capabilities'][0][field] = value
                self.both(False, fixture)

    def test_incomplete_owner_or_unresolved_original_cleanup_is_not_idle(self):
        for missing in ('active_lease_id', 'task_id'):
            fixture = copy.deepcopy(self.fixture)
            (fixture['status'] if missing == 'active_lease_id' else fixture['status']['native_owner']).pop(missing)
            self.both(False, fixture)
        self.fixture['state']['mission']['cleanup_state'] = 'unresolved'
        self.both(False)


WAIT_JS = r"""
const fs=require('node:fs');
const {manualPreflight,confirmAfterAdmission}=require(process.argv[1]);
const f=JSON.parse(fs.readFileSync(0,'utf8')), reads=[],waits=[],evidence=[],posts=[];
let now=f.start*1000, index=0, body=null;
const options={deadline:f.deadline*1000,wait:f.wait,now:()=>now,evidence,
  sleep:async ms=>{waits.push({ms,body_created:body!==null});now+=ms;}};
async function read(path){
  reads.push(path);
  now+=f.read_cost_s*1000;
  if(f.read_error)throw Error(f.read_error);
  if(path==='/sim-api/manual/status')return f.statuses[Math.min(index++,f.statuses.length-1)];
  if(path.startsWith('/sim-api/manual/'))return {lease:f.lease};
  throw Error('Unexpected read '+path);
}
async function confirm(){body={command_id:f.command_id,issued_at_ms:now,ttl_ms:5000,text:'前进50厘米'};posts.push({...body});}
(f.confirm?confirmAfterAdmission(f.runtime,f.state,read,confirm,options):manualPreflight(f.runtime,f.state,read,options))
.then(value=>process.stdout.write(JSON.stringify({accepted:true,reads,waits,evidence,now:now/1000,posts,body,value})))
.catch(error=>process.stdout.write(JSON.stringify({accepted:false,reads,waits,evidence,now:now/1000,posts,body,error:String(error)})));
"""


class VoiceAdmissionWaitTests(unittest.TestCase):
    setUp = VoiceManualPreflightTests.setUp
    def run_schedule(self, statuses, *, start=0., deadline=120., wait=True,
                     read_error=None, confirm=False, fixture=None, read_cost_s=0.):
        fixture = copy.deepcopy(self.fixture if fixture is None else fixture)
        clock, waits, reads, evidence = [start], [], [], []
        def read(path):
            reads.append('/sim-api/'+path)
            clock[0] = round(clock[0]+read_cost_s, 12)
            if read_error: raise RuntimeError(read_error)
            if path == 'manual/status': return statuses[min(reads.count('/sim-api/manual/status')-1, len(statuses)-1)]
            if path.startswith('manual/'): return {'lease': fixture['lease']}
            raise AssertionError('Unexpected read '+path)
        def sleep(seconds): waits.append(seconds); clock[0] = round(clock[0]+seconds, 12)
        with patch.object(acceptance.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(acceptance.time, 'sleep', side_effect=sleep):
            try:
                value = manual_preflight(fixture['runtime'], fixture['state'], read,
                    deadline=deadline, evidence=evidence, wait=wait)
                python = {'accepted': True, 'value': value}
            except Exception as error:
                python = {'accepted': False, 'error': str(error)}
        python.update(reads=reads, evidence=evidence, now=clock[0], waits=waits)
        payload = {**fixture, 'statuses': statuses, 'start': start, 'deadline': deadline,
                   'wait': wait, 'read_error': read_error, 'confirm': confirm, 'command_id': TASK,
                   'read_cost_s': read_cost_s}
        node = subprocess.run(['node', '-e', WAIT_JS, str(ROOT/'tools/fishbot_voice_ui_acceptance.cjs')],
            input=json.dumps(payload), capture_output=True, text=True, timeout=5, check=True)
        js = json.loads(node.stdout)
        self.assertEqual(js['accepted'], python['accepted'])
        self.assertEqual(js['reads'], python['reads'])
        self.assertAlmostEqual(js['now'], python['now'])
        self.assertEqual([v['status'] for v in js['evidence']], [v['status'] for v in evidence])
        self.assertEqual(len(js['waits']), len(waits))
        return python, js

    def pending(self, reason='continuous_quiet_unconfirmed'):
        status = copy.deepcopy(self.fixture['status'])
        status.update(can_acquire=False, reason=reason)
        status['quiet'].update(confirmed=False, duration_s=.2)
        return status

    def test_known_delayed_admission_waits_read_only_and_preserves_actual_statuses(self):
        statuses = [self.pending(), self.pending('manual_cleanup_unconfirmed'), self.fixture['status']]
        python, js = self.run_schedule(statuses)
        self.assertTrue(python['accepted']); self.assertAlmostEqual(python['now'], .1)
        self.assertEqual([v['status'].get('reason') for v in python['evidence']],
                         ['continuous_quiet_unconfirmed', 'manual_cleanup_unconfirmed', None])
        self.assertEqual(js['posts'], [])

    def test_pending_admission_obeys_both_fifteen_seconds_and_original_total_deadline(self):
        for start, deadline, expected in ((0., 120., 15.), (119.88, 120., 120.)):
            with self.subTest(start=start):
                python, js = self.run_schedule([self.pending()], start=start, deadline=deadline)
                self.assertFalse(python['accepted']); self.assertIn('deadline', python['error'])
                self.assertAlmostEqual(python['now'], expected)
                self.assertEqual(js['posts'], [])

    def test_fatal_identity_owner_stop_unknown_limits_and_other_rejections_never_wait(self):
        for key, value in (('runtime_instance_id', TASK), ('map_id', 'map-b'), ('profile_id', 'baseline'),
                ('available', False), ('stop_latched', True), ('limits', {**LIMITS, 'command_ttl_ms': 500}),
                ('native_owner', {**self.fixture['status']['native_owner'], 'native_goal_id': TASK}),
                ('native_owner', {**self.fixture['status']['native_owner'], 'status': 'unknown'}),
                ('idle_recovery', {'state': 'unknown'}), ('reason', 'guard_unavailable')):
            with self.subTest(key=key, value=value):
                status = self.pending(); status[key] = value
                python, js = self.run_schedule([status, self.fixture['status']])
                self.assertFalse(python['accepted']); self.assertEqual(python['waits'], [])
                self.assertEqual(len(python['reads']), 1); self.assertEqual(js['posts'], [])

    def test_transport_failure_and_identity_change_after_pending_are_not_retried(self):
        python, js = self.run_schedule([self.pending()], read_error='HTTP outcome unknown')
        self.assertFalse(python['accepted']); self.assertEqual(python['waits'], [])
        self.assertEqual(python['reads'], ['/sim-api/manual/status']); self.assertEqual(js['posts'], [])
        changed = self.pending(); changed['map_id'] = 'map-b'
        python, js = self.run_schedule([self.pending(), changed, self.fixture['status']])
        self.assertFalse(python['accepted']); self.assertEqual(len(python['reads']), 2)
        self.assertAlmostEqual(python['now'], .05); self.assertEqual(js['posts'], [])

    def test_final_route_check_never_waits_for_an_already_created_command(self):
        python, js = self.run_schedule([self.pending(), self.fixture['status']], wait=False)
        self.assertFalse(python['accepted']); self.assertEqual(python['waits'], [])
        self.assertEqual(len(python['reads']), 1); self.assertEqual(js['posts'], [])

    def test_ready_reply_after_original_total_deadline_never_clicks_or_dispatches(self):
        python, js = self.run_schedule([self.fixture['status']], start=119.98, deadline=120.,
                                       read_cost_s=.03, confirm=True)
        self.assertFalse(python['accepted']); self.assertIn('deadline', python['error'])
        self.assertAlmostEqual(python['now'], 120.01)
        self.assertEqual(len(python['reads']), 1); self.assertEqual(len(python['evidence']), 1)
        self.assertEqual(js['posts'], []); self.assertIsNone(js['body'])

    def test_confirm_creates_one_original_envelope_only_after_readiness(self):
        python, js = self.run_schedule([self.pending(), self.pending(), self.fixture['status']], confirm=True)
        self.assertTrue(python['accepted']); self.assertTrue(all(not v['body_created'] for v in js['waits']))
        self.assertEqual(js['posts'], [{'command_id': TASK, 'issued_at_ms': 100, 'ttl_ms': 5000, 'text': '前进50厘米'}])
        self.assertEqual(js['body'], js['posts'][0])
        python, js = self.run_schedule([self.pending()], deadline=.1, confirm=True)
        self.assertFalse(python['accepted']); self.assertIsNone(js['body']); self.assertEqual(js['posts'], [])


RECOVERY_JS = r"""
const fs=require('node:fs'), assert=require('node:assert/strict');
const {stopIdentityAfterSubmission,readStopTerminal,until,captureResponse,checkStopReceipt,forwardTimeout}=require(process.argv[1]);
const f=JSON.parse(fs.readFileSync(0,'utf8')), calls=[],waits=[],posts=[];
let now=f.start??0,index=0;
const opts={deadline:f.deadline??15000,unknown:f.unknown??true,now:()=>now,
  sleep:async ms=>{waits.push(ms);now+=ms;}};
function failure(kind){
  if(kind==='timeout')return Object.assign(Error('GET transport timeout'),{name:'TimeoutError'});
  if(kind==='playwright-timeout')return Error('apiRequestContext.get: Timeout 3000ms exceeded.');
  return Error(kind);
}
(async()=>{
 if(f.mode==='identity'){
  let marker={},submission,markerReads=0,reads=0;
  const options={...opts,sleep:async ms=>{waits.push(ms);now+=ms;
   if(now>=(f.ready_at??80)){marker={stop_command_id:f.identity.stop,task_id:f.identity.task,native_goal_id:f.identity.native};submission='accepted_response';}}};
  try{
   const value=await stopIdentityAfterSubmission(()=>{reads++;return submission;},()=>{markerReads++;return marker;},
    {runtime:f.identity.runtime,domain:f.identity.domain,session:f.identity.session},options);
   return {passed:true,value,reads,markerReads,waits,now,posts,fixture:f};
  }catch(error){return {passed:false,error:String(error),reads,markerReads,waits,now,posts,fixture:f};}
 }
 if(f.mode==='forward'){
  let forwarded=0,error=null,timeout;
  try{timeout=forwardTimeout(opts.deadline,opts.now);forwarded++;}catch(e){error=String(e);}
  return {forwarded,timeout,error};
 }
 if(f.mode==='capture'){
  const post={};let error=null;
  try{
   const result=await captureResponse(async()=>{
    if(f.error)throw failure(f.error);
    return {status:()=>f.status,headers:()=>({'x-fishbot-instance':f.identity.runtime}),text:async()=>f.raw};
   },post);
   if(f.check)checkStopReceipt(result.value,f.identity);
  }catch(e){error=String(e);}
  return {post,error};
 }
 try{
  if(f.mode==='predicate'){
   await until(async()=>{calls.push('GET');return {};},()=>{throw failure('timeout');},15,
    {...opts,retryGetTimeout:true});
  }else{
   await readStopTerminal(async(service,resource,end)=>{
    assert.ok(service==='simulation'?resource==='/sim-api/tasks/'+f.identity.task:resource==='/voice-api/state');
    calls.push({method:'GET',service,resource,end});now+=f.read_cost??0;
    const error=(f.errors||[])[index++];if(error)throw failure(error);
    return service==='simulation'?f.taskView:f.voice;
   },f.identity,opts);
  }
  return {passed:true,calls,waits,now,posts,fixture:f};
 }catch(error){return {passed:false,error:String(error),calls,waits,now,posts,fixture:f};}
})().then(value=>process.stdout.write(JSON.stringify(value)));
"""


class VoiceStopRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.identity = {'runtime': INSTANCE, 'domain': 129, 'session': 'voice-session',
                         'stop': LEASE, 'task': TASK, 'native': '17c93304fd0c4816b7137304519a2aa2'}
        task = {'id': TASK, 'task_id': TASK, 'owner': 'voice:voice-session',
                'native_goal_id': self.identity['native'], 'status': 'canceled', 'native_status': 5}
        self.fixture = {'identity': self.identity, 'taskView': {'runtime_instance_id': INSTANCE,
            'current_runtime_instance_id': INSTANCE, 'mission': copy.deepcopy(task)},
            'voice': {'mode': 'simulation', 'domain': 129, 'session_id': 'voice-session', 'task': task,
                'latest_command': {'command_id': LEASE, 'session_id': 'voice-session', 'accepted': None,
                    'receipt_status': 'task_unknown', 'status': 'canceled', 'task_id': TASK, 'task': copy.deepcopy(task)}}}

    def node(self, **changes):
        payload = {**copy.deepcopy(self.fixture), **changes}
        result = subprocess.run(['node', '-e', RECOVERY_JS, str(ROOT/'tools/fishbot_voice_ui_acceptance.cjs')],
            input=json.dumps(payload), capture_output=True, text=True, timeout=5, check=True)
        value = json.loads(result.stdout)
        if changes.get('mode') not in ('capture', 'forward'):
            self.assertEqual(value['posts'], [])
            self.assertEqual(value['fixture'], payload)  # No identity or receipt is rewritten.
        return value

    def test_unknown_stop_recovers_same_ids_through_only_supported_gets_without_replay(self):
        result = self.node(errors=['timeout'])
        self.assertTrue(result['passed']); self.assertEqual(result['waits'], [80])
        self.assertEqual([(v['method'], v['resource']) for v in result['calls']], [
            ('GET', '/sim-api/tasks/'+TASK), ('GET', '/sim-api/tasks/'+TASK), ('GET', '/voice-api/state')])
        self.assertEqual({v['end'] for v in result['calls']}, {15000})
        self.assertIsNone(result['fixture']['voice']['latest_command']['accepted'])
        self.assertEqual(result['fixture']['voice']['latest_command']['receipt_status'], 'task_unknown')

    def test_only_classified_get_timeout_is_retried_after_explicit_unknown_stop(self):
        for error in ('timeout', 'playwright-timeout'):
            self.assertTrue(self.node(errors=[error])['passed'])
            rejected = self.node(errors=[error], unknown=False)
            self.assertFalse(rejected['passed']); self.assertEqual(len(rejected['calls']), 1)
            self.assertEqual(rejected['waits'], [])
        for error in ('HTTP 404', 'connection reset', 'identity changed'):
            result = self.node(errors=[error])
            self.assertFalse(result['passed']); self.assertEqual(len(result['calls']), 1)
            self.assertEqual(result['waits'], [])

    def test_original_stop_and_total_deadline_never_restart_on_repeated_timeout_or_late_reply(self):
        for start, end in ((0, 150), (119900, 120000)):
            result = self.node(start=start, deadline=end, errors=['timeout']*10)
            self.assertFalse(result['passed']); self.assertEqual(result['now'], end)
            self.assertEqual({v['end'] for v in result['calls']}, {end})
            self.assertLessEqual(max(result['waits']), 80)
        result = self.node(start=119990, deadline=120000, read_cost=6)
        self.assertFalse(result['passed']); self.assertEqual(len(result['calls']), 2)
        self.assertEqual(result['waits'], [])

    def test_stop_identity_is_captured_after_async_submission_and_never_on_timeout(self):
        result = self.node(mode='identity', ready_at=160)
        self.assertTrue(result['passed'])
        self.assertEqual(result['value'], self.identity)
        self.assertEqual(result['markerReads'], 1)
        self.assertGreaterEqual(result['reads'], 3)
        self.assertEqual(result['posts'], [])
        late = self.node(mode='identity', ready_at=160, deadline=100)
        self.assertFalse(late['passed'])
        self.assertEqual(late['markerReads'], 0)
        self.assertEqual(late['posts'], [])

    def test_predicate_timeout_is_fatal_without_transport_retry(self):
        result = self.node(mode='predicate')
        self.assertFalse(result['passed']); self.assertEqual(result['calls'], ['GET'])
        self.assertEqual(result['waits'], [])

    def test_changed_original_identity_or_explicit_failure_is_immediately_fatal(self):
        cases = [('runtime_instance_id', TASK), ('current_runtime_instance_id', TASK)]
        for field, value in cases:
            fixture = copy.deepcopy(self.fixture); fixture['taskView'][field] = value
            result = self.node(**fixture)
            self.assertFalse(result['passed']); self.assertEqual(len(result['calls']), 1)
        for field, value in (('id', LEASE), ('native_goal_id', LEASE), ('status', 'failed'),
                             ('native_status', 4), ('cleanup_state', 'unresolved')):
            fixture = copy.deepcopy(self.fixture); fixture['taskView']['mission'][field] = value
            result = self.node(**fixture)
            self.assertFalse(result['passed']); self.assertEqual(len(result['calls']), 1)
        for field, value in (('session_id', 'other'), ('domain', 128)):
            fixture = copy.deepcopy(self.fixture); fixture['voice'][field] = value
            self.assertFalse(self.node(**fixture)['passed'])
        for field, value in (('command_id', TASK), ('task_id', LEASE), ('accepted', False), ('status', 'failed')):
            fixture = copy.deepcopy(self.fixture); fixture['voice']['latest_command'][field] = value
            result = self.node(**fixture)
            self.assertFalse(result['passed']); self.assertEqual(result['waits'], [])
        for field, value in (('native_goal_id', LEASE), ('owner', 'voice:other'), ('native_status', 6)):
            fixture = copy.deepcopy(self.fixture); fixture['voice']['task'][field] = value
            self.assertFalse(self.node(**fixture)['passed'])

    def test_raw_null_rejected_malformed_and_timeout_response_evidence_precedes_assertions(self):
        receipt = self.fixture['voice']['latest_command']
        for body, status in ((receipt, 200), ({**receipt, 'accepted': False, 'status': 'rejected'}, 409)):
            raw = json.dumps(body, ensure_ascii=False)
            result = self.node(mode='capture', raw=raw, status=status, check=True)
            evidence = result['post']['response']
            self.assertEqual(evidence['http_status'], status)
            self.assertEqual(evidence['headers'], {'x-fishbot-instance': INSTANCE})
            self.assertEqual(evidence['raw_body'], raw); self.assertEqual(evidence['value'], body)
            self.assertIsNone(evidence['error'])
            self.assertEqual(result['error'] is None, status == 200)
        result = self.node(mode='capture', raw='{invalid json', status=502)
        self.assertEqual(result['post']['response']['http_status'], 502)
        self.assertEqual(result['post']['response']['raw_body'], '{invalid json')
        self.assertIsNotNone(result['post']['response']['error'])
        result = self.node(mode='capture', error='timeout')
        self.assertTrue(result['post']['response']['timeout'])
        self.assertIsNone(result['post']['response']['http_status'])

    def test_python_timeout_recovery_retains_fixed_deadline_and_never_retries_http_or_identity_errors(self):
        for error in (TimeoutError('timed out'), URLError(TimeoutError('timed out'))):
            clock, evidence = [0.], []
            reader = Mock(side_effect=[error, {'id': TASK}])
            def sleep(seconds): clock[0] += seconds
            with patch.object(acceptance.time, 'monotonic', side_effect=lambda: clock[0]), \
                    patch.object(acceptance.time, 'sleep', side_effect=sleep):
                value = acceptance.read_with_timeout_recovery(reader, 'tasks/'+TASK, .15, evidence)
            self.assertEqual(value, {'id': TASK}); self.assertEqual(reader.call_count, 2)
            self.assertEqual(clock[0], .08); self.assertTrue(evidence[0]['timeout'])
        for error in (HTTPError('/original', 404, 'not found', {}, None), RuntimeError('identity changed')):
            reader, evidence = Mock(side_effect=error), []
            with patch.object(acceptance.time, 'monotonic', return_value=0.), \
                    patch.object(acceptance.time, 'sleep') as sleep:
                with self.assertRaises(type(error)):
                    acceptance.read_with_timeout_recovery(reader, 'tasks/'+TASK, .15, evidence)
            reader.assert_called_once_with('tasks/'+TASK); sleep.assert_not_called()
        clock, evidence = [119.88], []
        def late_read(resource): clock[0] = 120.01; return {'id': TASK}
        with patch.object(acceptance.time, 'monotonic', side_effect=lambda: clock[0]):
            with self.assertRaises(TimeoutError):
                acceptance.read_with_timeout_recovery(late_read, 'tasks/'+TASK, 120., evidence)
        self.assertTrue(evidence[0]['received']); self.assertEqual(len(evidence), 1)

    def test_post_is_not_forwarded_at_or_after_the_original_deadline(self):
        for start in (15000, 15001):
            result = self.node(mode='forward', start=start, deadline=15000)
            self.assertEqual(result['forwarded'], 0); self.assertIn('not forwarded', result['error'])
        result = self.node(mode='forward', start=14999, deadline=15000)
        self.assertEqual(result['forwarded'], 1); self.assertEqual(result['timeout'], 1)

    def test_fixed_two_second_get_never_starts_in_short_remaining_stop_window(self):
        clock, evidence = [13.01], []
        reader = Mock()
        with patch.object(acceptance.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(acceptance.time, 'sleep') as sleep:
            with self.assertRaises(TimeoutError):
                acceptance.read_with_timeout_recovery(reader, 'tasks/'+TASK, 15., evidence, request_budget_s=2.)
        reader.assert_not_called(); sleep.assert_not_called(); self.assertEqual(evidence, [])
        clock, evidence = [0.], []
        def timeout(resource): clock[0] += 2.; raise TimeoutError('transport timeout')
        def advance(seconds): clock[0] += seconds
        reader = Mock(side_effect=timeout)
        with patch.object(acceptance.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(acceptance.time, 'sleep', side_effect=advance):
            with self.assertRaises(TimeoutError):
                acceptance.read_with_timeout_recovery(reader, 'tasks/'+TASK, 3., evidence, request_budget_s=2.)
        self.assertEqual(reader.call_count, 1); self.assertLess(clock[0], 3.)

    def test_failure_cleanup_rejects_changed_task_native_and_explicit_stop_failure(self):
        marker = {'task_id': TASK, 'native_goal_id': self.identity['native'], 'stop_command_id': LEASE}
        mission = self.fixture['taskView']['mission']
        acceptance.check_cleanup_identity(mission, marker)
        for field, value in (('id', LEASE), ('native_goal_id', LEASE), ('status', 'failed'),
                ('native_status', 4), ('native_status', 6), ('cleanup_state', 'unresolved')):
            with self.subTest(field=field, value=value):
                with self.assertRaises(RuntimeError):
                    acceptance.check_cleanup_identity({**mission, field: value}, marker)


class VoiceObservationBoundaryTests(unittest.TestCase):
    def test_main_waits_for_two_frames_before_the_original_quiet_scorer(self):
        clock = [0.]
        first = {'epoch': 100., 'steady_time': 0., 'stamp': 10., 'ros_now': 10.,
                 'x': 0., 'y': 0., 'yaw': 0., 'linear_speed': 0., 'angular_speed': 0.}
        frames = [first]
        def sleep(seconds):
            clock[0] += seconds
            frames.append({**first, 'epoch': 100.+clock[0], 'steady_time': clock[0],
                           'stamp': 10.+clock[0], 'ros_now': 10.+clock[0]})
        observer = Mock()
        observer.fresh.side_effect = lambda: frames[-1]
        observer.frames_after.side_effect = lambda boundary: boundary_frames(frames, boundary)
        api = Mock(); api.get.side_effect = lambda path: {
            'runtime': {'instance_id': INSTANCE},
            'state': {'domain': 129, 'mode': 'mujoco', 'ready': True, 'mission': {'status': 'idle'}},
        }[path]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'run'
            args = SimpleNamespace(execute=True, api='http://127.0.0.1:9097',
                voice='http://127.0.0.1:9099', web='http://127.0.0.1:5182', domain=129,
                expected_instance=INSTANCE, chromium='/not-launched', output=output)
            with patch('fishbot_voice_ui_acceptance.argparse.ArgumentParser.parse_args', return_value=args), \
                    patch.dict(acceptance.os.environ, {'ROS_DOMAIN_ID': '129', 'FISHBOT_MUJOCO_DOMAIN_ID': '129',
                        'ROS_AUTOMATIC_DISCOVERY_RANGE': 'LOCALHOST', 'ROS_STATIC_PEERS': ''}), \
                    patch.object(acceptance, 'Api', return_value=api), \
                    patch.object(acceptance, 'manual_preflight', return_value={'required': True}), \
                    patch.object(acceptance, 'RuntimeObservation', return_value=observer), \
                    patch.object(acceptance.time, 'monotonic', side_effect=lambda: clock[0]), \
                    patch.object(acceptance.time, 'sleep', side_effect=sleep), \
                    patch.object(acceptance, 'quiet_result', wraps=quiet_result) as score, \
                    patch.object(acceptance.subprocess, 'Popen', side_effect=RuntimeError('Browser boundary reached')) as browser, \
                    patch('sys.stdout', new_callable=io.StringIO):
                self.assertEqual(acceptance.main(), 1)  # Stop before launching any browser.
            report = json.loads((output/'result.json').read_text())
        self.assertEqual(report['errors'], ['Browser boundary reached'])
        self.assertEqual(report['initial_observer_frame'], first)
        self.assertEqual(report['initial_quiet']['boundary_steady'], 0.)
        self.assertGreaterEqual(report['initial_quiet']['quiet_source_s'], .7-1e-9)
        self.assertGreaterEqual(report['initial_quiet']['quiet_wall_s'], .7-1e-9)
        self.assertEqual(len(score.call_args_list[0].args[0]), 2)
        self.assertTrue(all(len(call.args[0]) >= 2 for call in score.call_args_list))
        browser.assert_called_once(); api.call.assert_not_called(); observer.close.assert_called_once()

    def test_delayed_dds_first_frame_precedes_the_fixed_quiet_boundary(self):
        clock = [0.]
        first = {'epoch': 103., 'steady_time': 3., 'stamp': 13., 'ros_now': 13.,
                 'x': 0., 'y': 0., 'yaw': 0., 'linear_speed': 0., 'angular_speed': 0.}
        def fresh():
            if clock[0] < 3.:
                raise RuntimeError('No independent truth')
            return first
        def sleep(seconds): clock[0] += seconds
        with patch('fishbot_voice_ui_acceptance.time.monotonic', side_effect=lambda: clock[0]), \
                patch('fishbot_voice_ui_acceptance.time.sleep', side_effect=sleep):
            self.assertIs(wait_fresh_observation(Mock(fresh=fresh), 120.), first)
        boundary = clock[0]
        self.assertGreaterEqual(boundary, 3.)
        frames = [first]+[{**first, 'epoch': 103.+i*.1, 'steady_time': 3.+i*.1,
                          'stamp': 13.+i*.1, 'ros_now': 13.+i*.1} for i in range(1, 10)]
        self.assertIsNotNone(quiet_result(boundary_frames(frames, boundary)))
        with self.assertRaisesRegex(RuntimeError, 'No fresh independent pre-dispatch boundary'):
            boundary_frames(frames, .5)

    def test_no_fresh_frames_exhausts_the_original_deadline_without_reset(self):
        for message in ('No independent truth', 'Independent truth is stale'):
            with self.subTest(message=message):
                clock, waits = [119.88], []
                observer = Mock(); observer.fresh.side_effect = RuntimeError(message)
                def sleep(seconds): waits.append(seconds); clock[0] += seconds
                with patch('fishbot_voice_ui_acceptance.time.monotonic', side_effect=lambda: clock[0]), \
                        patch('fishbot_voice_ui_acceptance.time.sleep', side_effect=sleep):
                    with self.assertRaisesRegex(RuntimeError, 'before total 120 second deadline'):
                        wait_fresh_observation(observer, 120.)
                self.assertAlmostEqual(clock[0], 120.)
                self.assertAlmostEqual(sum(waits), .12)
                self.assertLessEqual(max(waits), .05)

    def test_other_observer_failures_are_not_silently_retried(self):
        observer = Mock(); observer.fresh.side_effect = RuntimeError('Recorder failed')
        with patch('fishbot_voice_ui_acceptance.time.monotonic', return_value=1.), \
                patch('fishbot_voice_ui_acceptance.time.sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'Recorder failed'):
                wait_fresh_observation(observer, 120.)
        observer.fresh.assert_called_once(); sleep.assert_not_called()


if __name__ == '__main__': unittest.main()
