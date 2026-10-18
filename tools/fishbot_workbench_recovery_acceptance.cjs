#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { assertMissionBody, inactive, showPanel } = require('./fishbot_map_rules_ui_acceptance.cjs');

async function until(read, predicate, seconds = 30) {
  const end = Date.now() + seconds * 1000; let value;
  while (Date.now() < end) { value = await read(); if (predicate(value)) return value; await new Promise(resolve => setTimeout(resolve, 80)); }
  throw new Error(`Acceptance deadline: ${JSON.stringify(value)}`);
}

async function main() {
  const args = process.argv.slice(2), options = {};
  for (let i = 0; i < args.length; i += 2) { assert.ok(['--plan', '--output', '--chromium'].includes(args[i]) && args[i + 1]); options[args[i].slice(2)] = args[i + 1]; }
  const plan = JSON.parse(fs.readFileSync(options.plan, 'utf8')), output = fs.realpathSync(options.output);
  assert.ok(['return_recovery', 'moving_cancel'].includes(plan.case));
  assert.equal(fs.statSync(output).mode & 0o077, 0); assert.ok(!fs.existsSync(path.join(output, 'browser-result.json')));
  for (const origin of [plan.api, plan.web]) { const url = new URL(origin); assert.ok(url.protocol === 'http:' && url.hostname === '127.0.0.1' && url.port && !url.username && !url.password && url.pathname === '/' && !url.search && !url.hash); }
  const { chromium, request } = require('playwright');
  const report = { passed: false, case: plan.case, posts: [], checks: [], errors: [], events: [], fault_reads: 0, started_epoch: Date.now() / 1000 };
  let marker = { phase: 'prepared', owned_mission_id: null, dispatch_epoch: null, requested_body: null, start_truth: null, cancel_epoch: null };
  function atomic(name, value) { const target = path.join(output, name), temporary = target + '.tmp'; fs.writeFileSync(temporary, JSON.stringify(value, null, 2) + '\n', { mode: 0o600 }); fs.renameSync(temporary, target); }
  function mark(values) { marker = { ...marker, ...values }; atomic('marker.json', marker); }
  function event(name, value) { report.events.push({ name, epoch: Date.now() / 1000, value }); }
  function frame() { const value = JSON.parse(fs.readFileSync(plan.observer_latest, 'utf8')); assert.ok(Date.now() / 1000 - value.epoch < .25 && value.ros_now - value.stamp <= .25 && value.ros_now - value.stamp >= -.05, 'Independent observer snapshot must be fresh'); return value; }
  let browser, api, page, isolated = false, forwarded = null, interceptionError;
  try {
    api = await request.newContext({ baseURL: plan.api, timeout: 5000 });
    async function get(resource) { const response = await api.get('/sim-api/' + resource); assert.equal(response.status(), 200); return response.json(); }
    const before = await get('state'), runtime = await get('runtime'), map = await get('map'), rules = await get('map-rules');
    inactive(before, plan.domain); assert.equal(runtime.instance_id, plan.runtime_instance_id); assert.equal(rules.apply_state, 'applied');
    assert.ok(Math.hypot(plan.target.x - before.pose.x, plan.target.y - before.pose.y) >= .3, 'The declared short target must provide a meaningful outbound leg');
    browser = await chromium.launch({ headless: true, executablePath: options.chromium });
    const context = await browser.newContext({ viewport: { width: 390, height: 950 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
    page = await context.newPage(); page.setDefaultTimeout(20000);
    page.on('pageerror', error => report.errors.push(error.message));
    await context.route('**/*', async route => {
      const req = route.request(), resource = new URL(req.url()).pathname;
      try {
        if (isolated && (resource === '/sim-api/state' || resource.startsWith('/sim-api/tasks/'))) { report.fault_reads++; return route.abort('failed'); }
        if (req.method() !== 'POST') return route.continue();
        const body = req.postDataJSON(); report.posts.push({ resource, body, epoch: Date.now() / 1000 });
        if (resource === '/sim-api/mission') {
          assert.equal(report.posts.filter(p => p.resource === resource).length, 1, 'Never replay the UI mission');
          assert.equal(body.waypoints.length, 1);
          assert.ok(Math.hypot(body.waypoints[0].x - plan.target.x, body.waypoints[0].y - plan.target.y) <= .03, 'Touch target differs from declared input');
          assertMissionBody(body, { waypoints: body.waypoints, return_home: plan.return_home, map_id: map.map_id, rules_revision: rules.revision, timeout_s: 360 });
          const current = await get('state'); inactive(current, plan.domain); assert.equal(current.mission.id, before.mission.id);
          assert.equal((await get('runtime')).instance_id, runtime.instance_id);
          mark({ phase: 'submitted', dispatch_epoch: Date.now() / 1000, owned_mission_id: body.mission_id, requested_body: body, start_truth: frame(), submission_state: 'pending' });
          if (plan.case === 'return_recovery') isolated = true;
          const response = await route.fetch();
          assert.equal(response.status(), 202, await response.text());
          forwarded = await response.json(); assert.equal(forwarded.mission.id, body.mission_id);
          event('actual_server_post_response', forwarded.mission);
          mark({ phase: 'forwarded', actual_server_response_epoch: Date.now() / 1000 });
          if (plan.case === 'return_recovery') return route.abort('failed');
          return route.fulfill({ response });
        }
        if (resource === '/sim-api/cancel') {
          assert.equal(plan.case, 'moving_cancel'); assert.equal(report.posts.filter(p => p.resource === resource).length, 1);
          assert.deepEqual(Object.keys(body).sort(), ['issued_at', 'mission_id']); assert.equal(body.mission_id, marker.owned_mission_id);
          assert.ok(Number.isFinite(body.issued_at) && Math.abs(Date.now() / 1000 - body.issued_at) < 2);
          mark({ cancel_epoch: Date.now() / 1000, cancel_body: body }); return route.continue();
        }
        throw new Error(`Unexpected UI write: ${resource}`);
      } catch (error) { interceptionError = error; report.errors.push(String(error)); await route.abort('failed').catch(() => {}); }
    });
    await page.goto(plan.web + '/simulation', { waitUntil: 'domcontentloaded' });
    const surface = page.locator('[data-workspace="simulation"]');
    await surface.getByRole('status').filter({ hasText: `导航已应用 · 版本 ${rules.revision}` }).waitFor();
    await showPanel(page, 'task');
    const returnHome = surface.getByRole('checkbox', { name: '巡逻结束后返回本次出发点', exact: true });
    if (await returnHome.isChecked() !== plan.return_home) await returnHome.tap();
    await surface.getByRole('button', { name: '巡逻点', exact: true }).tap();
    const svg = surface.getByRole('application'); await svg.scrollIntoViewIfNeeded(); const box = await svg.boundingBox(); assert.ok(box);
    const dx = plan.target.x - map.origin[0], dy = plan.target.y - map.origin[1], c = Math.cos(map.origin[2]), s = Math.sin(map.origin[2]);
    const point = { x: box.x + (c * dx + s * dy) / map.resolution / map.width * box.width,
      y: box.y + (map.height - (-s * dx + c * dy) / map.resolution) / map.height * box.height };
    assert.equal(await svg.evaluate((element, p) => element.contains(document.elementFromPoint(p.x, p.y)), point), true);
    await page.touchscreen.tap(point.x, point.y);
    await showPanel(page, 'objects'); await surface.getByRole('button', { name: '查看巡逻点 1 属性', exact: true }).waitFor();
    await showPanel(page, 'task'); await surface.getByRole('button', { name: '按当前规则复核', exact: true }).tap();
    assert.equal(report.posts.length, 0); await surface.getByRole('button', { name: '开始巡逻', exact: true }).tap();
    await until(() => { if (interceptionError) throw interceptionError; return forwarded; }, Boolean, 15);
    const identity = marker.owned_mission_id;
    await until(() => get('state'), value => { assert.equal(value.mission.id, identity); return value.mission.dispatch_state === 'accepted' && value.mission.native_goal_id; }, 30);
    report.checks.push('one_actual_UI_POST_and_original_native_goal');
    if (plan.case === 'return_recovery') {
      const key = `fishbot.mission-receipt.v1:${plan.domain}`;
      const receipt = await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)), key);
      assert.equal(receipt.missionId, identity); assert.equal(receipt.instanceId, runtime.instance_id);
      await page.reload({ waitUntil: 'domcontentloaded' });
      await surface.getByText('派发回执未知，正在读取原任务状态；暂不能重复派发或编辑。', { exact: true }).waitFor();
      assert.equal((await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)), key)).missionId, identity);
      assert.equal(await surface.getByRole('button', { name: '开始巡逻', exact: true }).isDisabled(), true);
      await new Promise(resolve => setTimeout(resolve, 1200));
      assert.ok(report.fault_reads > 0); event('fault_release', { original_id: identity, reads_blocked: report.fault_reads }); isolated = false;
      await showPanel(page, 'task'); await surface.getByText('已按原任务 ID 核对当前导航状态。', { exact: true }).waitFor();
      report.checks.push('server_received_lost_response_state_blackout_refresh_exact_UUID_recovery_no_replay');
      const during = await get('state'); assert.equal(during.mission.id, identity);
      if (during.mission.status === 'running') {
        await page.setViewportSize({ width: 1440, height: 900 }); await surface.getByRole('application').waitFor();
        await surface.locator('.dv-tab').filter({ hasText: '场景' }).locator('.dv-default-tab-action').click();
        await showPanel(page, 'canvas'); await surface.getByRole('application').waitFor();
        await page.getByRole('button', { name: '雷达与地图', exact: true }).click();
        await page.locator('[data-workspace="radar"]').waitFor();
        await page.getByRole('button', { name: '地图巡逻', exact: true }).first().click();
        await surface.getByRole('application').waitFor();
        assert.equal((await get('state')).mission.id, identity);
        assert.equal(report.posts.length, 1, 'Closing/reopening views and changing routes cannot submit a command');
        event('active_original_task_view_lifecycle', { before: during.mission, after: (await get('state')).mission });
        report.checks.push('active_original_UUID_survives_canvas_close_reopen_and_route_changes_without_POST');
        await page.setViewportSize({ width: 390, height: 950 });
      } else event('view_lifecycle_not_covered', { reason: 'The short task completed before view lifecycle checks', mission: during.mission });
    } else {
      const moving = await until(() => frame(), value => value.epoch >= marker.dispatch_epoch && value.linear_speed > .03
        && Math.hypot(value.x - marker.start_truth.x, value.y - marker.start_truth.y) >= .05, 35);
      event('independent_moving_before_UI_cancel', moving);
      const active = await get('state'); assert.equal(active.mission.id, identity); assert.equal(active.mission.dispatch_state, 'accepted'); assert.equal(active.mission.status, 'running');
      const canceled = page.waitForResponse(response => new URL(response.url()).pathname === '/sim-api/cancel' && response.request().method() === 'POST');
      await surface.getByRole('button', { name: '取消任务', exact: true }).tap();
      assert.equal((await canceled).status(), 202); report.checks.push('accepted_original_UUID_independently_moving_then_explicit_UI_cancel');
    }
    const terminal = await until(() => get('state'), value => { assert.equal(value.mission.id, identity); return ['succeeded', 'failed', 'canceled'].includes(value.mission.status); }, plan.case === 'moving_cancel' ? 15 : 360);
    assert.equal(terminal.mission.status, plan.case === 'moving_cancel' ? 'canceled' : 'succeeded');
    assert.equal(terminal.mission.native_status, plan.case === 'moving_cancel' ? 5 : 4);
    if (plan.case === 'return_recovery') { assert.equal(terminal.mission.native_error_code, 0); assert.deepEqual(terminal.mission.missed_waypoints, []); assert.equal(terminal.mission.return_home, true); }
    await showPanel(page, 'task');
    await until(() => surface.locator('.simulation-mission-state > strong').innerText(), value => value === (plan.case === 'moving_cancel' ? '已取消' : '巡逻完成'), 15);
    assert.equal(report.posts.filter(p => p.resource === '/sim-api/mission').length, 1);
    assert.equal(report.posts.length, plan.case === 'moving_cancel' ? 2 : 1); assert.deepEqual(report.errors, []);
    await page.screenshot({ path: path.join(output, 'terminal.png'), fullPage: true });
    mark({ phase: 'terminal', terminal_mission: terminal.mission }); report.passed = true;
  } catch (error) {
    report.errors.push(String(error.stack || error));
    if (page) await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
  } finally {
    report.finished_epoch = Date.now() / 1000; report.marker = marker; atomic('browser-result.json', report);
    if (browser) await browser.close(); if (api) await api.dispose();
  }
  console.log(JSON.stringify({ passed: report.passed, case: plan.case, mission_id: marker.owned_mission_id, errors: report.errors }));
  return report.passed ? 0 : 1;
}

if (require.main === module) main().then(code => { process.exitCode = code; }).catch(error => { console.error(error); process.exitCode = 1; });
