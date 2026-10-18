#!/usr/bin/env node
'use strict';

// Two explicit voice commands through the real UI. Truth comes from a separate
// read-only ROS observer; page timers and task labels are never physical proof.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const MANUAL_LIMITS = { forward_mps: .08, reverse_mps: .03, angular_rps: .25,
  command_ttl_ms: 250, acquire_ttl_ms: 1000, heartbeat_ms: 140 };

async function manualPreflight(runtime, state, read, options = {}) {
  const capability = (runtime.capabilities || []).find(v => v.id === 'teleop' && v.protocol === 'manual_lease_v1');
  if (!capability) return { required: false, reason: 'manual_capability_absent' };
  const mapId = state.map_rules?.map_id;
  assert.equal(capability.profile_id, 'passage_manual'); assert.equal(capability.available, true);
  assert.deepEqual(capability.limits, MANUAL_LIMITS); assert.ok(mapId);
  assert.ok(['idle', 'completed', 'succeeded', 'failed', 'canceled'].includes(state.mission.status));
  assert.notEqual(state.mission.cleanup_state, 'unresolved');
  const now = options.now || (() => performance.now());
  const sleep = options.sleep || (ms => new Promise(resolve => setTimeout(resolve, ms)));
  const end = Math.min(now() + 15000, options.deadline ?? Infinity);
  let originalLeaseId;
  while (now() < end) {
    const status = await read('/sim-api/manual/status');
    options.evidence?.push({ epoch: Date.now() / 1000, steady_ms: now(), status });
    assert.equal(status.runtime_instance_id, runtime.instance_id); assert.equal(status.profile_id, 'passage_manual');
    assert.equal(status.map_id, mapId); assert.deepEqual(status.limits, MANUAL_LIMITS);
    assert.equal(status.available, true); assert.equal(status.stop_latched, false);
    assert.ok(Object.hasOwn(status, 'active_lease_id'));
    const owner = status.native_owner;
    assert.ok(owner && ['task_id', 'native_goal_id', 'status', 'terminal'].every(key => Object.hasOwn(owner, key)));
    assert.equal(owner.terminal, true); assert.equal(owner.task_id, state.mission.id ?? null);
    assert.equal(owner.native_goal_id, state.mission.native_goal_id ?? null);
    assert.equal(owner.status, state.mission.status === 'completed' ? 'succeeded' : state.mission.status);
    assert.notEqual(status.idle_recovery?.state, 'unknown');
    if (originalLeaseId === undefined) originalLeaseId = status.active_lease_id;
    assert.equal(status.active_lease_id, originalLeaseId, 'Original manual lease changed during admission');
    let lease = null;
    if (status.active_lease_id !== null) {
      const id = status.active_lease_id;
      assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
      ({ lease } = await read('/sim-api/manual/' + id));
      assert.equal(lease.lease_id, id); assert.equal(lease.runtime_instance_id, runtime.instance_id);
      assert.equal(lease.map_id, mapId); assert.equal(lease.profile_id, 'passage_manual');
      assert.ok(['released', 'expired', 'stopped'].includes(lease.state));
      assert.equal(lease.guard_stop_acknowledged, true); assert.equal(lease.quiet?.confirmed, true);
    }
    if (status.can_acquire === true && status.reason == null) {
      const quiet = status.quiet;
      assert.equal(quiet?.confirmed, true);
      assert.ok(['duration_s', 'receive_age_s', 'source_age_s', 'source_stamp'].every(k => Number.isFinite(quiet[k])));
      assert.ok(quiet.duration_s >= .7 && quiet.receive_age_s >= 0 && quiet.receive_age_s <= .25 && quiet.source_age_s >= -.05 && quiet.source_age_s <= .25);
      if (now() >= end) break;
      return { required: true, status, lease };
    }
    assert.ok(options.wait !== false && status.can_acquire === false
      && ['continuous_quiet_unconfirmed', 'manual_cleanup_unconfirmed'].includes(status.reason),
    'Manual owner rejected admission: ' + status.reason);
    const remaining = end - now();
    if (remaining > 0) await sleep(Math.min(50, remaining));
  }
  throw Error('Manual owner admission deadline before total 120 second deadline');
}

async function confirmAfterAdmission(runtime, state, read, confirm, options) {
  const preflight = await manualPreflight(runtime, state, read, options);
  await confirm();
  return preflight;
}

function isTimeout(error) {
  // APIRequestContext also reports deadline expiry as Error with this prefix.
  return error?.name === 'TimeoutError'
    || /^(?:apiRequestContext\.(?:get|fetch)|route\.fetch): Timeout \d+ms exceeded\.?/.test(error?.message || '');
}

async function until(read, predicate, seconds = 15, options = {}) {
  const now = options.now || (() => performance.now());
  const sleep = options.sleep || (ms => new Promise(resolve => setTimeout(resolve, ms)));
  const end = Math.min(now() + seconds * 1000, options.deadline ?? Infinity); let value;
  while (now() < end) {
    let received = false;
    try { value = await read(end); received = true; }
    catch (error) { if (!options.retryGetTimeout || !isTimeout(error)) throw error; }
    // Assertion and identity failures are never transport retries.
    if (received && predicate(value) && now() < end) return value;
    const remaining = end - now();
    if (remaining > 0) await sleep(Math.min(80, remaining));
  }
  throw new Error(`Voice acceptance deadline: ${JSON.stringify(value)}`);
}

async function captureResponse(fetch, post) {
  const receipt = { before_epoch: Date.now() / 1000, before_steady_ms: performance.now(),
    http_status: null, headers: null, raw_body: null, value: null, error: null, timeout: false };
  post.response = receipt;
  try {
    const response = await fetch(); receipt.http_status = response.status(); receipt.headers = response.headers();
    receipt.raw_body = await response.text(); receipt.value = JSON.parse(receipt.raw_body);
    return { response, value: receipt.value };
  } catch (error) { receipt.error = String(error); receipt.timeout = isTimeout(error); throw error; }
  finally { receipt.after_epoch = Date.now() / 1000; receipt.after_steady_ms = performance.now(); }
}

function forwardTimeout(deadline, now = () => performance.now()) {
  const remaining = deadline - now();
  assert.ok(remaining > 0, 'Original POST deadline exhausted; request not forwarded');
  return Math.min(3000, remaining);
}

function checkStopReceipt(value, identity) {
  assert.equal(value.command_id, identity.stop); assert.equal(value.session_id, identity.session);
  assert.equal(value.task_id, identity.task); assert.notEqual(value.accepted, false);
  assert.ok(value.accepted === true || value.accepted === null);
  assert.ok(['accepted', 'canceling', 'canceled', 'unknown', 'task_unknown'].includes(value.status));
  return value.accepted === null || ['unknown', 'task_unknown'].includes(value.status);
}

function checkMissionReadback(taskView, identity) {
  assert.equal(taskView.runtime_instance_id, identity.runtime);
  assert.equal(taskView.current_runtime_instance_id, identity.runtime);
  const mission = taskView.mission;
  assert.equal(mission.id, identity.task); assert.equal(mission.native_goal_id, identity.native);
  assert.ok(['running', 'canceling', 'canceled'].includes(mission.status));
  assert.ok(![4, 6].includes(mission.native_status), 'Original native action failed or completed instead of cancellation');
  assert.notEqual(mission.cleanup_state, 'unresolved');
  if (mission.status === 'canceled') assert.equal(mission.native_status, 5);
  return mission;
}

function stopReadback(taskView, voice, identity) {
  const mission = checkMissionReadback(taskView, identity);
  assert.equal(voice.mode, 'simulation'); assert.equal(voice.domain, identity.domain); assert.equal(voice.session_id, identity.session);
  const command = voice.latest_command, task = voice.task;
  checkStopReceipt(command, identity);
  assert.equal(task.id, identity.task); assert.equal(task.task_id, identity.task);
  assert.equal(task.owner, 'voice:' + identity.session); assert.equal(task.native_goal_id, identity.native);
  assert.equal(command.task.id, identity.task); assert.equal(command.task.native_goal_id, identity.native);
  assert.equal(command.task.task_id, identity.task); assert.equal(command.task.owner, 'voice:' + identity.session);
  assert.equal(command.task.status, task.status); assert.equal(command.task.native_status, task.native_status);
  assert.ok(['running', 'canceling', 'canceled', 'unknown', 'task_unknown'].includes(task.status));
  assert.ok(![4, 6].includes(task.native_status));
  if (task.status === 'canceled') assert.equal(task.native_status, 5);
  return mission.status === 'canceled' && mission.native_status === 5 && task.status === 'canceled'
    && task.native_status === 5 && command.status === 'canceled';
}

async function stopIdentityAfterSubmission(readSubmission, readMarker, metadata, options) {
  await until(readSubmission, Boolean, 15, options);
  // The intercepted POST may still be awaiting its pre-send GET. Snapshot its
  // identity only after that same submission has finished, never before it.
  const marker = readMarker();
  for (const key of ['stop_command_id', 'task_id', 'native_goal_id']) assert.ok(typeof marker[key] === 'string' && marker[key].length > 0, 'Original STOP identity is incomplete');
  return { ...metadata, stop: marker.stop_command_id, task: marker.task_id, native: marker.native_goal_id };
}

async function readStopTerminal(get, identity, options) {
  return until(async end => {
    const taskView = await get('simulation', '/sim-api/tasks/' + identity.task, end);
    checkMissionReadback(taskView, identity);
    const voiceState = await get('voice', '/voice-api/state', end);
    return { taskView, voiceState };
  }, value => stopReadback(value.taskView, value.voiceState, identity), 15,
  { ...options, retryGetTimeout: options.unknown === true });
}

async function main() {
  const options = {}, argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i += 2) { assert.ok(['--plan', '--output', '--chromium'].includes(argv[i]) && argv[i + 1]); options[argv[i].slice(2)] = argv[i + 1]; }
  const plan = JSON.parse(fs.readFileSync(options.plan, 'utf8')), output = fs.realpathSync(options.output);
  assert.equal(fs.statSync(output).mode & 0o077, 0);
  assert.ok(!fs.existsSync(path.join(output, 'browser-result.json')));
  for (const address of [plan.api, plan.voice, plan.web]) { const u = new URL(address); assert.ok(u.protocol === 'http:' && u.hostname === '127.0.0.1' && u.port && u.pathname === '/' && !u.username && !u.password && !u.search && !u.hash); }
  const { chromium, request } = require('playwright');
  const report = { passed: false, posts: [], checks: [], errors: [], marker: {}, admission_observations: [], http_observations: [] };
  const now = () => Number(process.hrtime.bigint()) / 1e6;
  assert.ok(Number.isFinite(plan.deadline_monotonic_s));
  const deadline = Math.min(plan.deadline_monotonic_s * 1000,
    now() + Math.max(0, Math.min(120, plan.remaining_budget_s)) * 1000);
  function admission(stage, wait = true) {
    const evidence = []; report.admission_observations.push({ stage, wait, evidence });
    return { deadline, wait, evidence, now };
  }
  function mark(value) { Object.assign(report.marker, value); const p = path.join(output, 'marker.json'); fs.writeFileSync(p + '.tmp', JSON.stringify(report.marker)); fs.renameSync(p + '.tmp', p); }
  function truth() {
    const f = JSON.parse(fs.readFileSync(plan.observer_latest, 'utf8'));
    assert.ok(Date.now() / 1000 - f.epoch <= .25 && Date.now() / 1000 >= f.epoch && f.ros_now - f.stamp >= -.05 && f.ros_now - f.stamp <= .25, 'Independent truth must be fresh'); return f;
  }
  let browser, http, page, interceptionError, stopDeadline, voiceInstance;
  try {
    http = await request.newContext({ timeout: 3000 });
    async function get(origin, resource, end = deadline) {
      const entry = { origin, resource, epoch: Date.now() / 1000, steady_ms: now() };
      assert.ok(report.http_observations.length < 2048, 'Bounded HTTP evidence exhausted');
      report.http_observations.push(entry);
      try {
        const remaining = Math.min(end, deadline) - now(); assert.ok(remaining > 0, 'Original read deadline exhausted');
        const r = await http.get(origin + resource, { timeout: Math.min(3000, remaining), maxRetries: 0, maxRedirects: 0 });
        entry.http_status = r.status(); entry.headers = r.headers(); entry.raw_body = await r.text();
        entry.value = JSON.parse(entry.raw_body); assert.equal(r.status(), 200);
        assert.ok(now() < Math.min(end, deadline), 'Original read deadline exhausted after response');
        if (origin === plan.api) assert.equal(entry.headers['x-fishbot-instance'], plan.runtime_instance_id);
        if (origin === plan.voice) {
          assert.match(entry.headers['x-fishbot-instance'], /^[0-9a-f-]{36}$/);
          if (voiceInstance === undefined) voiceInstance = entry.headers['x-fishbot-instance'];
          assert.equal(entry.headers['x-fishbot-instance'], voiceInstance);
        }
        return entry.value;
      } catch (error) { entry.error = String(error); entry.timeout = isTimeout(error); throw error; }
      finally { entry.after_epoch = Date.now() / 1000; entry.after_steady_ms = now(); }
    }
    const before = await get(plan.api, '/sim-api/state'), runtime = await get(plan.api, '/sim-api/runtime');
    assert.equal(runtime.instance_id, plan.runtime_instance_id); assert.equal(before.domain, plan.domain); assert.equal(before.mode, 'mujoco'); assert.equal(before.ready, true);
    assert.ok(!['running', 'canceling', 'unknown'].includes(before.mission.status));
    report.manual_preflight = await manualPreflight(runtime, before, resource => get(plan.api, resource), admission('initial'));
    const voice = await get(plan.voice, '/voice-api/state'); assert.equal(voice.domain, plan.domain); assert.equal(voice.mode, 'simulation'); assert.equal(voice.ready, true);
    browser = await chromium.launch({ headless: true, executablePath: options.chromium });
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, serviceWorkers: 'block' });
    page = await context.newPage(); page.setDefaultTimeout(15000); page.on('pageerror', e => report.errors.push(e.message));
    await context.route('**/*', async route => {
      const req = route.request(); if (['GET', 'HEAD', 'OPTIONS'].includes(req.method())) return route.continue();
      try {
        assert.equal(req.method(), 'POST'); assert.equal(new URL(req.url()).origin, new URL(plan.web).origin);
        const resource = new URL(req.url()).pathname, body = req.postDataJSON();
        const post = { resource, body, epoch: Date.now() / 1000 }; report.posts.push(post);
        mark({ post_count: report.posts.length });
        assert.ok(['/voice-api/preview', '/voice-api/execute'].includes(resource), 'No direct motion or unrelated UI write');
        assert.ok(report.posts.length <= 4);
        if (resource === '/voice-api/execute') {
          const number = report.posts.filter(p => p.resource === resource).length;
          assert.equal(body.session_id, voice.session_id); assert.ok(number <= 2);
          assert.equal(body.text, number === 1 ? '前进50厘米' : '停止');
          if (number === 1) {
            const current = await get(plan.api, '/sim-api/state'); assert.equal(current.mission.id, before.mission.id);
            // The UI already created this envelope. Never wait or retime it.
            report.dispatch_manual_preflight = await manualPreflight(runtime, current, resource => get(plan.api, resource), admission('route_final', false));
            mark({ task_id: body.command_id, dispatch_epoch: Date.now() / 1000, start_truth: truth() });
          }
          else {
            const boundary = now(), cancelEpoch = Date.now() / 1000;
            assert.equal(stopDeadline, undefined, 'STOP is never submitted again');
            stopDeadline = Math.min(deadline, boundary + 15000);
            assert.equal((await get(plan.api, '/sim-api/state')).mission.id, report.marker.task_id);
            mark({ cancel_epoch: cancelEpoch, cancel_steady_ms: boundary,
              stop_terminal_deadline_ms: stopDeadline, stop_command_id: body.command_id });
          }
        }
        let captured;
        try {
          const timeout = forwardTimeout(stopDeadline ?? deadline, now);
          captured = await captureResponse(() => route.fetch({ maxRetries: 0, maxRedirects: 0,
            timeout }), post);
        } catch (error) {
          if (resource === '/voice-api/execute' && body.command_id === report.marker.stop_command_id && isTimeout(error)) {
            report.stop_submission = 'unknown_transport_timeout';
            mark({ stop_outcome_unknown: true });
            // No response exists to fulfill. Keep the original sent ID unknown.
            return route.abort('timedout');
          }
          throw error;
        }
        const { response, value } = captured;
        try {
          assert.ok(response.status() >= 200 && response.status() < 300, post.response.raw_body);
          assert.equal(post.response.headers['x-fishbot-instance'], voiceInstance);
          if (resource === '/voice-api/execute' && body.command_id === report.marker.stop_command_id) {
            const unknown = checkStopReceipt(value, { stop: body.command_id, session: voice.session_id, task: report.marker.task_id });
            report.stop_submission = unknown ? 'unknown_response' : 'accepted_response';
            mark({ stop_outcome_unknown: unknown });
          } else assert.equal(value.accepted, true);
          if (resource === '/voice-api/execute') {
            assert.equal(value.command_id, body.command_id); assert.equal(value.session_id, voice.session_id);
            assert.equal(value.task_id, report.marker.task_id);
          }
        } catch (error) {
          interceptionError = error; report.errors.push(String(error));
        }
        // Preserve the actual response, including accepted=null or rejection.
        return route.fulfill({ response });
      } catch (e) { interceptionError = e; report.errors.push(String(e)); return route.abort('failed'); }
    });
    await page.goto(plan.web + '/results', { waitUntil: 'domcontentloaded' });
    const panel = page.locator('#workbench-voice');
    await panel.getByRole('button', { name: '连接语音服务', exact: true }).click();
    await panel.getByText(`仿真语音服务 · ROS 域 ${plan.domain}`, { exact: true }).waitFor();
    assert.equal(report.posts.length, 0);
    await panel.getByLabel('输入想让小车做的事').fill('前进50厘米');
    await panel.getByRole('button', { name: '预览任务', exact: true }).click();
    await panel.getByRole('button', { name: '确认执行此任务', exact: true }).waitFor();
    assert.equal((await get(plan.api, '/sim-api/state')).mission.id, before.mission.id);
    assert.equal(report.posts.filter(p => p.resource === '/voice-api/execute').length, 0);
    report.checks.push('actual_preview_has_no_native_dispatch');
    report.confirm_manual_preflight = await confirmAfterAdmission(runtime, before, resource => get(plan.api, resource),
      () => panel.getByRole('button', { name: '确认执行此任务', exact: true }).click(), admission('before_confirm'));
    const active = await until(() => { if (interceptionError) throw interceptionError; return get(plan.api, '/sim-api/state'); }, s => s.mission.id === report.marker.task_id && s.mission.dispatch_state === 'accepted' && s.mission.native_goal_id,
      15, { deadline, now });
    mark({ native_goal_id: active.mission.native_goal_id });
    await page.getByRole('navigation', { name: '工作区' }).getByRole('button', { name: '控制总览', exact: true }).click();
    await page.getByRole('navigation', { name: '工作区' }).getByRole('button', { name: '成果验收', exact: true }).click();
    await panel.getByText(report.marker.task_id, { exact: true }).first().waitFor();
    assert.equal(report.posts.filter(p => p.resource === '/voice-api/execute').length, 1);
    const moving = await until(() => truth(), f => f.linear_speed > .03 && Math.hypot(f.x - report.marker.start_truth.x, f.y - report.marker.start_truth.y) > .05,
      20, { deadline, now });
    mark({ moving_truth: moving }); report.checks.push('explicit_confirm_original_UUID_moves_and_survives_route_change');
    await panel.getByLabel('输入想让小车做的事').fill('停止');
    await panel.getByRole('button', { name: '预览任务', exact: true }).click();
    await panel.getByRole('button', { name: '确认停止当前语音任务', exact: true }).click();
    assert.ok(Number.isFinite(stopDeadline), 'Original STOP boundary missing');
    const identity = await stopIdentityAfterSubmission(() => {
      if (interceptionError) throw interceptionError;
      return report.stop_submission;
    }, () => report.marker, { runtime: plan.runtime_instance_id, domain: plan.domain, session: voice.session_id },
    { deadline: stopDeadline, now });
    const terminal = await readStopTerminal((service, resource, end) => {
      if (interceptionError) throw interceptionError;
      return get(service === 'simulation' ? plan.api : plan.voice, resource, end);
    }, identity, { deadline: stopDeadline, now, unknown: report.marker.stop_outcome_unknown });
    report.stop_readback = terminal;
    await panel.getByRole('button', { name: '刷新任务状态', exact: true }).click({ timeout: Math.max(1, stopDeadline - now()) });
    await until(async () => ({ text: await panel.locator('.voice-task-result').innerText(),
      unknown: await panel.locator('.voice-receipt').getAttribute('data-receipt-unknown'),
      receipt: await panel.locator('.voice-receipt').innerText() }),
    value => value.text.includes('已取消') && value.text.includes(identity.task) && value.unknown === 'false' && value.receipt.includes(identity.stop),
    15, { deadline: stopDeadline, now });
    mark({ terminal: terminal.taskView.mission }); report.checks.push('explicit_voice_STOP_cancels_same_native_UUID');
    report.checks.push('explicit_UI_refresh_resolves_original_STOP_without_replay');
    assert.equal(report.posts.filter(p => p.resource === '/voice-api/execute').length, 2); assert.deepEqual(report.errors, []);
    await page.screenshot({ path: path.join(output, 'voice-terminal.png'), fullPage: true }); report.passed = true;
  } catch (e) { report.errors.push(String(e.stack || e)); }
  finally { if (browser) await browser.close(); if (http) await http.dispose(); fs.writeFileSync(path.join(output, 'browser-result.json'), JSON.stringify(report, null, 2)); }
  console.log(JSON.stringify({ passed: report.passed, checks: report.checks, errors: report.errors })); process.exitCode = report.passed ? 0 : 1;
}
if (require.main === module) main().catch(e => { console.error(e); process.exitCode = 1; });
module.exports = { stopIdentityAfterSubmission, manualPreflight, confirmAfterAdmission, isTimeout, until, captureResponse, forwardTimeout, checkStopReceipt, stopReadback, readStopTerminal };
