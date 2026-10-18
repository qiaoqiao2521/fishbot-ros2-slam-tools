#!/usr/bin/env node
'use strict';

// Real touch UI -> persisted template -> one native navigation request.
// An independent Python observer owns physical scoring and failure cleanup.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { performance } = require('node:perf_hooks');

function argumentsFrom(argv) {
  const options = { base: 'http://127.0.0.1:5179', domain: 107,
    chromium: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH };
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    assert.ok(['--base', '--domain', '--output', '--chromium'].includes(key), `Unknown option: ${key}`);
    assert.ok(argv[index + 1], `Missing value for ${key}`);
    options[key.slice(2)] = argv[index + 1];
  }
  options.domain = Number(options.domain);
  assert.ok(Number.isInteger(options.domain) && options.domain >= 1 && options.domain <= 232,
    'Select one explicit nonzero simulation domain');
  const address = new URL(options.base);
  assert.ok(address.protocol === 'http:' && address.hostname === '127.0.0.1' && address.port
    && !address.username && !address.password && address.pathname === '/' && !address.search && !address.hash,
  'Only an explicit loopback HTTP origin is supported');
  options.base = address.origin;
  assert.ok(options.output, 'Provide --output outside the repository');
  const repository = fs.realpathSync(path.join(__dirname, '..'));
  const requested = path.resolve(options.output);
  assert.ok(requested !== repository && !requested.startsWith(repository + path.sep),
    'Acceptance artifacts must stay outside the repository');
  if (!fs.existsSync(requested)) fs.mkdirSync(requested, { recursive: true, mode: 0o700 });
  options.output = fs.realpathSync(requested);
  assert.ok(options.output !== repository && !options.output.startsWith(repository + path.sep),
    'Acceptance artifacts must stay outside the repository');
  assert.equal(fs.statSync(options.output).mode & 0o077, 0, 'Output directory must be private (0700)');
  for (const name of ['marker.json', 'browser-result.json']) {
    assert.ok(!fs.existsSync(path.join(options.output, name)), `Refusing to overwrite ${name}`);
  }
  return options;
}

async function until(get, predicate, seconds = 30) {
  const deadline = performance.now() + seconds * 1000;
  let value;
  while (performance.now() < deadline) {
    value = await get();
    if (predicate(value)) return value;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Acceptance deadline: ${JSON.stringify(value)}`);
}

function exactKeys(value, names) {
  assert.deepEqual(Object.keys(value).sort(), [...names].sort());
}

function inactive(state, domain) {
  assert.equal(state.mode, 'mujoco');
  assert.equal(state.domain, domain);
  assert.equal(state.ready, true, `Simulation unavailable: ${state.reason}`);
  assert.ok(!['running', 'canceling', 'unknown'].includes(state.mission.status),
    'An existing mission must remain untouched');
  assert.notEqual(state.mission.cleanup_state, 'unresolved');
  assert.notEqual(state.mission.dispatch_state, 'unavailable');
}

function sameMissionPayload(actual, expected) {
  assert.deepEqual(actual.waypoints, expected.waypoints);
  assert.equal(actual.return_home, expected.return_home);
  assert.equal(actual.map_id, expected.map_id);
  assert.equal(actual.rules_revision, expected.rules_revision);
}

function assertMissionBody(body, expected, now = Date.now() / 1000) {
  exactKeys(body, ['mission_id', 'waypoints', 'return_home', 'map_id', 'rules_revision', 'issued_at', 'timeout_s']);
  assert.match(body.mission_id, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/, 'The UI must assign one canonical client UUID');
  sameMissionPayload(body, expected);
  assert.equal(body.timeout_s, expected.timeout_s, 'Preserve the existing owner deadline');
  assert.ok(Number.isFinite(body.issued_at) && Math.abs(now - body.issued_at) < 2, 'Require a fresh UI dispatch');
}

async function showPanel(page, slot) {
  const root = page.locator('[data-workspace="simulation"]');
  const labels = { objects: '对象', properties: '属性', task: '任务与反馈' };
  assert.ok(slot === 'canvas' || labels[slot], `Unsupported workspace slot: ${slot}`);
  if (await root.locator('.workspace-mobile').isVisible()) {
    if (slot !== 'canvas') await root.getByRole('tab', { name: labels[slot], exact: true }).tap();
  } else {
    await root.getByRole('navigation', { name: '显示面板' }).getByRole('button', {
      name: slot === 'canvas' ? '场景' : labels[slot], exact: true,
    }).click();
  }
}

async function terminalVisible(phone, identity, revision) {
  await showPanel(phone, 'task');
  const panel = phone.locator('.simulation-runs');
  if (await panel.getAttribute('open') !== '') await panel.locator('summary').tap();
  const row = panel.locator('li').filter({ hasText: identity });
  await row.waitFor();
  await until(() => row.locator('strong').innerText(), (text) => text === '巡逻完成');
  await phone.getByRole('status').filter({ hasText: `导航已应用 · 版本 ${revision}` }).waitFor();
}

async function main(options) {
  const { chromium, request: playwrightRequest } = require('playwright');
  const report = { passed: false, domain: options.domain, base: options.base,
    started_epoch: Date.now() / 1000, checks: [], events: [], errors: [], posts: [], screenshots: [],
    source_sha256: crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex'),
    scope: 'Touch UI and native task lifecycle; physical scoring belongs to the independent observer' };
  let browser, api, phone;
  let marker = { phase: 'initializing', domain: options.domain, base: options.base,
    dispatch_epoch: null, before_id: null, requested_body: null, requested_mission_id: null,
    owned_mission_id: null, submission_state: 'not_submitted', accepted_epoch: null };
  function atomicJson(filename, value) {
    const temporary = path.join(options.output, `.${filename}.${process.pid}.${crypto.randomUUID()}`);
    fs.writeFileSync(temporary, JSON.stringify(value, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
    fs.renameSync(temporary, path.join(options.output, filename));
  }
  function mark(change) { marker = { ...marker, ...change }; atomicJson('marker.json', marker); }
  function event(kind, value) { report.events.push({ kind, epoch: Date.now() / 1000, value }); }
  async function screenshot(name) {
    const filename = `${name}.png`;
    await phone.screenshot({ path: path.join(options.output, filename), fullPage: true });
    report.screenshots.push(filename);
  }
  try {
    // APIRequestContext reads bypass the page's intentionally lost save receipt.
    api = await playwrightRequest.newContext({ baseURL: options.base, timeout: 5000 });
    async function get(resource) {
      const response = await api.get(`/sim-api/${resource}`);
      assert.equal(response.status(), 200, `GET ${resource}: ${await response.text()}`);
      return response.json();
    }
    const initial = await get('state');
    inactive(initial, options.domain);
    assert.ok(initial.truth && Math.abs(initial.truth.linear_speed) < 0.005
      && Math.abs(initial.truth.angular_speed) < 0.02, 'Require a stationary simulation');
    const original = await until(() => get('map-rules'), (rules) => rules.apply_state === 'applied');
    const map = await get('map');
    const originalRoutes = await get('routes');
    const runtime = await get('runtime');
    assert.equal(runtime.service, 'mission');
    assert.equal(runtime.domain, options.domain);
    assert.ok(typeof runtime.instance_id === 'string' && runtime.instance_id, 'Require the actual runtime identity');
    report.runtime = runtime;
    assert.equal(map.map_id, original.map_id);
    assert.equal(originalRoutes.map_id, original.map_id);
    assert.ok(original.zones.length < 64, 'No space for an additional owned test rule');
    mark({ before_id: initial.mission.id, map_id: map.map_id, original_rules: original,
      requested_points: [{ x: 0.60, y: 0.0, yaw: 0 }, { x: 0.15, y: 0.40, yaw: 0 }] });
    browser = await chromium.launch({ headless: true,
      ...(options.chromium ? { executablePath: options.chromium } : {}) });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 },
      hasTouch: true, deviceScaleFactor: 1 });
    phone = await context.newPage();
    phone.setDefaultTimeout(30000);
    phone.on('pageerror', (error) => report.errors.push(`Page error: ${error}`));
    phone.on('request', (request) => {
      if (request.method() === 'POST') report.posts.push({ url: request.url(),
        body: request.postDataJSON(), epoch: Date.now() / 1000 });
    });
    await phone.goto(options.base + '/simulation');
    await phone.getByRole('status').filter({ hasText: `导航已应用 · 版本 ${original.revision}` }).waitFor();
    for (const slot of ['objects', 'properties', 'task', 'canvas']) await showPanel(phone, slot);
    assert.equal(report.posts.length, 0, 'Desktop panel changes must not write');
    await screenshot('00-desktop-readonly-workspace');
    await phone.setViewportSize({ width: 390, height: 950 });
    await phone.locator('[data-workspace="simulation"] .workspace-mobile').waitFor();
    await showPanel(phone, 'objects');
    report.checks.push('desktop_and_phone_panel_changes_without_write');
    assert.equal(await phone.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1), false);
    async function beforeEdit() {
      const state = await get('state');
      inactive(state, options.domain);
      assert.equal(state.mission.id, initial.mission.id, 'Mission changed during editing; stop without dispatch');
      return state;
    }
    async function tapPoint(x, y) {
      await showPanel(phone, 'canvas');
      const svg = phone.getByRole('application');
      await svg.scrollIntoViewIfNeeded();
      const box = await svg.boundingBox();
      assert.ok(box && box.width > 0 && box.height > 0, 'Map has no visible touch surface');
      const dx = x - map.origin[0], dy = y - map.origin[1];
      const cosine = Math.cos(map.origin[2]), sine = Math.sin(map.origin[2]);
      const px = (cosine * dx + sine * dy) / map.resolution;
      const py = map.height - (-sine * dx + cosine * dy) / map.resolution;
      assert.ok(px > 0 && px < map.width && py > 0 && py < map.height, 'Test point is outside the map');
      const point = { x: box.x + px / map.width * box.width, y: box.y + py / map.height * box.height };
      assert.ok(point.x >= 0 && point.x < 390 && point.y >= 0 && point.y < 950,
        'The touch target is outside the phone viewport');
      assert.equal(await svg.evaluate((element, target) => element.contains(document.elementFromPoint(target.x, target.y)), point), true,
        'The exact map target is obscured by a panel or canvas tool; do not tap an unrelated control');
      await phone.touchscreen.tap(point.x, point.y);
    }
    const missionPosts = () => report.posts.filter((post) => post.url.endsWith('/sim-api/mission'));
    await phone.getByRole('button', { name: '观察', exact: true }).tap();
    await tapPoint(2.0, 2.0);
    assert.equal(report.posts.length, 0);
    report.checks.push('phone_observe_without_write');

    await phone.getByRole('button', { name: '禁区', exact: true }).tap();
    await tapPoint(2.0, 2.0);
    await tapPoint(2.3, 2.3);
    const saveRules = phone.getByRole('button', { name: '保存规则', exact: true });
    await until(() => saveRules.isEnabled(), Boolean);
    await phone.getByRole('button', { name: '撤销', exact: true }).tap();
    assert.equal(await saveRules.isDisabled(), true);
    assert.equal(report.posts.length, 0);
    report.checks.push('phone_rectangle_draft_undo_without_publish');
    await tapPoint(2.0, 2.0);
    await tapPoint(2.3, 2.3);
    await beforeEdit();
    assert.deepEqual((await get('map-rules')).zones, original.zones);
    const saveReceipt = phone.waitForResponse((response) => response.url().endsWith('/sim-api/map-rules')
      && response.request().method() === 'POST');
    await saveRules.tap();
    assert.equal((await saveReceipt).status(), 200);
    const savedRules = await until(() => get('map-rules'), (rules) =>
      rules.revision === original.revision + 1 && rules.apply_state === 'applied');
    const oldIds = new Set(original.zones.map((zone) => zone.id));
    const added = savedRules.zones.filter((zone) => !oldIds.has(zone.id));
    assert.equal(added.length, 1);
    assert.equal(added[0].kind, 'no_go');
    assert.equal(added[0].points.length, 4);
    const corners = [[2.0, 2.0], [2.3, 2.0], [2.3, 2.3], [2.0, 2.3]];
    for (const [x, y] of corners) assert.ok(added[0].points.some((point) =>
      Math.hypot(point.x - x, point.y - y) <= 0.03), 'The saved rectangle differs from the touch selection');
    assert.deepEqual(savedRules.zones.filter((zone) => oldIds.has(zone.id)), original.zones);
    mark({ owned_rule_id: added[0].id, saved_rules_revision: savedRules.revision });
    await phone.getByRole('status').filter({ hasText: `导航已应用 · 版本 ${savedRules.revision}` }).waitFor();
    await screenshot('01-phone-saved-rule');
    report.checks.push('phone_rule_save_reaches_native_applied_revision');

    // Only remove the new owned row; all preexisting rules remain byte-equivalent.
    const row = savedRules.zones.findIndex((zone) => zone.id === added[0].id);
    await showPanel(phone, 'objects');
    await beforeEdit();
    const currentRules = await get('map-rules');
    assert.equal(currentRules.revision, savedRules.revision);
    assert.deepEqual(currentRules.zones, savedRules.zones);
    await phone.getByRole('button', { name: `移除禁区 ${row + 1}`, exact: true }).tap();
    const removeReceipt = phone.waitForResponse((response) => response.url().endsWith('/sim-api/map-rules')
      && response.request().method() === 'POST');
    await saveRules.tap();
    assert.equal((await removeReceipt).status(), 200);
    const restored = await until(() => get('map-rules'), (rules) =>
      rules.revision === savedRules.revision + 1 && rules.apply_state === 'applied');
    assert.deepEqual(restored.zones, original.zones);
    await phone.getByRole('status').filter({ hasText: `导航已应用 · 版本 ${restored.revision}` }).waitFor();
    event('owned_rule_removed_original_preserved', restored);
    mark({ owned_rule_removed: true, rules_revision: restored.revision });
    report.checks.push('phone_owned_rule_removal_preserves_existing_rules');

    await phone.getByRole('button', { name: '巡逻点', exact: true }).tap();
    await tapPoint(0.60, 0.0);
    await tapPoint(0.15, 0.40);
    assert.equal(await phone.locator('.simulation-waypoints li').count(), 2);
    await showPanel(phone, 'task');
    const returnHome = phone.getByRole('checkbox', { name: '巡逻结束后返回本次出发点', exact: true });
    if (await returnHome.isChecked()) await returnHome.tap();
    assert.equal(await returnHome.isChecked(), false);
    const name = `触屏闭环-${crypto.randomUUID()}`;
    await showPanel(phone, 'objects');
    await phone.getByLabel('路线名称', { exact: true }).fill(name);
    let holdReads = true, forwarded = 0, forwardedTemplate;
    let interceptionError;
    await phone.route('**/sim-api/routes', async (route) => {
      try {
        if (route.request().method() === 'POST') {
          forwarded += 1;
          assert.equal(forwarded, 1, 'A lost route save must never repost');
          const body = route.request().postDataJSON();
          assert.ok(body.id && !originalRoutes.routes.some((template) => template.id === body.id));
          assert.equal(body.name, name);
          assert.equal(body.map_id, map.map_id);
          assert.equal(body.return_home, false);
          assert.equal(body.waypoints.length, 2);
          for (let index = 0; index < body.waypoints.length; index += 1) {
            const point = body.waypoints[index], desired = marker.requested_points[index];
            assert.ok(Math.hypot(point.x - desired.x, point.y - desired.y) <= 0.03,
              'Touch-selected point differs by more than the 3 cm event-pixel allowance');
            assert.equal(point.yaw, 0);
          }
          // Forward once to the actual backend, then intentionally lose the browser receipt.
          const response = await route.fetch();
          assert.equal(response.status(), 200);
          const collection = await response.json();
          forwardedTemplate = collection.routes.find((template) => template.id === body.id);
          assert.ok(forwardedTemplate, 'The real route write did not persist its client ID');
          assert.deepEqual(forwardedTemplate.waypoints, body.waypoints);
          mark({ template_id: body.id, saved_route: forwardedTemplate });
          await route.abort('failed');
        } else if (holdReads) await route.fulfill({ status: 200, contentType: 'application/json',
          body: JSON.stringify(originalRoutes), headers: { 'X-Fishbot-Instance': runtime.instance_id } });
        else await route.continue();
      } catch (error) {
        interceptionError = error;
        event('route_interception_error', String(error));
        await route.abort('failed');
      }
    });
    await beforeEdit();
    const saveRoute = phone.getByRole('button', { name: '保存当前路线', exact: true });
    await saveRoute.tap();
    await phone.getByRole('status').filter({ hasText: '路线保存结果未知' }).waitFor();
    if (interceptionError) throw interceptionError;
    assert.equal(await saveRoute.isDisabled(), true);
    // Waiting while reads remain stale proves that reconciliation never resends.
    await new Promise((resolve) => setTimeout(resolve, 650));
    assert.equal(forwarded, 1);
    assert.ok(forwardedTemplate);
    await screenshot('02-phone-route-save-unknown');
    holdReads = false;
    const routes = await until(() => get('routes'), (collection) =>
      collection.routes.some((template) => template.id === marker.template_id));
    const savedRoute = routes.routes.find((template) => template.id === marker.template_id);
    assert.deepEqual(savedRoute, forwardedTemplate);
    assert.deepEqual(routes.routes.filter((template) => template.id !== savedRoute.id), originalRoutes.routes);
    await phone.getByRole('status').filter({ hasText: '已读取到保存的路线' }).waitFor();
    assert.equal(forwarded, 1);
    await phone.unroute('**/sim-api/routes');
    report.checks.push('phone_lost_actual_template_receipt_reconciles_without_repost');

    await phone.getByRole('button', { name: '清空待派发点', exact: true }).tap();
    assert.equal(await phone.locator('.simulation-waypoints li').count(), 0);
    // Invert the draft option first, then prove loading restores the saved option.
    await showPanel(phone, 'task');
    await returnHome.tap();
    assert.equal(await returnHome.isChecked(), true);
    await showPanel(phone, 'objects');
    const templateRow = phone.locator('.simulation-template-list li').filter({
      has: phone.getByText(name, { exact: true }) });
    assert.equal(await templateRow.count(), 1);
    await templateRow.getByRole('button', { name: '载入草稿', exact: true }).tap();
    const waypointRows = phone.locator('.simulation-waypoints li');
    assert.equal(await waypointRows.count(), savedRoute.waypoints.length);
    for (let index = 0; index < savedRoute.waypoints.length; index += 1) {
      const point = savedRoute.waypoints[index];
      assert.ok((await waypointRows.nth(index).innerText()).includes(
        `(${point.x.toFixed(2)}, ${point.y.toFixed(2)}) 米`));
    }
    await showPanel(phone, 'task');
    assert.equal(await returnHome.isChecked(), savedRoute.return_home);
    await showPanel(phone, 'objects');
    assert.equal(await phone.getByLabel('路线名称', { exact: true }).inputValue(), savedRoute.name);
    assert.equal(missionPosts().length, 0);
    const editedState = await beforeEdit();
    assert.ok(Math.hypot(editedState.truth.x - initial.truth.x, editedState.truth.y - initial.truth.y) < 0.01,
      'Rule/template edits moved the robot');
    assert.deepEqual((await get('map-rules')).zones, original.zones);
    report.checks.push('phone_template_load_restores_points_and_return_option_without_motion');
    await screenshot('03-phone-loaded-template');

    const dispatchRules = await get('map-rules');
    assert.equal(dispatchRules.apply_state, 'applied');
    assert.equal(dispatchRules.revision, restored.revision);
    assert.deepEqual(dispatchRules.zones, original.zones);
    await showPanel(phone, 'task');
    const reviewDraft = phone.getByRole('button', { name: '按当前规则复核', exact: true });
    assert.equal(await reviewDraft.isEnabled(), true);
    await reviewDraft.tap();
    assert.equal(missionPosts().length, 0, 'Reviewing the restored draft must not dispatch');
    report.checks.push('explicit_current_revision_draft_review_without_dispatch');
    const expected = { waypoints: savedRoute.waypoints, return_home: savedRoute.return_home,
      map_id: savedRoute.map_id, rules_revision: dispatchRules.revision, timeout_s: 360 };
    mark({ phase: 'prepared', prepared_epoch: Date.now() / 1000,
      dispatch_epoch: Date.now() / 1000, expected_body: expected });
    let dispatched = 0, dispatchError;
    await phone.route('**/sim-api/mission', async (route) => {
      try {
        assert.equal(route.request().method(), 'POST');
        dispatched += 1;
        assert.equal(dispatched, 1, 'Only one UI mission POST is permitted');
        const body = route.request().postDataJSON();
        assertMissionBody(body, expected);
        assert.notEqual(body.mission_id, initial.mission.id, 'A new dispatch cannot reuse the previous task UUID');
        await beforeEdit();
        const rules = await get('map-rules');
        assert.equal(rules.apply_state, 'applied');
        assert.equal(rules.revision, dispatchRules.revision);
        assert.deepEqual(rules.zones, original.zones);
        // The client owns this UUID before the response. Pending is not native acceptance.
        // The independent observer may clean up only if the current backend task has this exact UUID.
        mark({ phase: 'submitted', dispatch_epoch: Date.now() / 1000, requested_body: body,
          requested_mission_id: body.mission_id, owned_mission_id: body.mission_id, submission_state: 'pending' });
        await route.continue();
      } catch (error) {
        dispatchError = error;
        event('dispatch_guard_error', String(error));
        await route.abort('failed');
      }
    });
    const start = phone.getByRole('button', { name: '开始巡逻', exact: true });
    assert.equal(await start.isEnabled(), true);
    const missionReceipt = phone.waitForResponse((response) => response.url().endsWith('/sim-api/mission')
      && response.request().method() === 'POST', { timeout: 10000 });
    await start.tap();
    const accepted = await missionReceipt;
    if (dispatchError) throw dispatchError;
    assert.equal(accepted.status(), 202, `UI mission rejected: ${await accepted.text()}`);
    const receipt = await accepted.json();
    assert.ok(receipt.mission.id && receipt.mission.id !== initial.mission.id);
    assert.equal(receipt.mission.id, marker.requested_mission_id, 'The backend task owner must retain the exact client UUID');
    sameMissionPayload(receipt.mission, expected);
    mark({ owned_mission_id: receipt.mission.id, accepted_epoch: Date.now() / 1000, submission_state: 'receipt_received' });
    event('ui_mission_receipt', receipt.mission);
    assert.equal(dispatched, 1);
    assert.equal(missionPosts().length, 1);
    report.checks.push('single_ui_mission_dispatch_matches_saved_template_and_rules');
    await showPanel(phone, 'task');
    await screenshot('04-phone-native-mission');
    const terminal = await until(() => get('state'), (state) => {
      assert.equal(state.domain, options.domain);
      assert.equal(state.mission.id, marker.owned_mission_id, 'A different mission replaced the owned task');
      return ['succeeded', 'failed', 'canceled'].includes(state.mission.status);
    }, 150);
    event('owned_mission_terminal', terminal.mission);
    mark({ phase: 'terminal', terminal_epoch: Date.now() / 1000, terminal_mission: terminal.mission });
    assert.equal(terminal.mission.status, 'succeeded', 'The UI-loaded route did not complete');
    const runs = await until(() => get('runs'), (collection) => collection.runs.some((run) =>
      run.id === marker.owned_mission_id && run.status === 'succeeded'));
    const run = runs.runs.find((record) => record.id === marker.owned_mission_id);
    sameMissionPayload(run, expected);
    event('owned_run_saved', run);
    await terminalVisible(phone, marker.owned_mission_id, dispatchRules.revision);
    assert.equal(missionPosts().length, 1);
    assert.equal(report.posts.filter((post) => post.url.endsWith('/sim-api/map-rules')).length, 2);
    assert.equal(report.posts.filter((post) => post.url.endsWith('/sim-api/routes')).length, 1);
    assert.equal(report.posts.length, 4, 'An unexpected write occurred during UI acceptance');
    assert.equal(await phone.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1), false);
    assert.equal(report.errors.length, 0, 'Page errors occurred during acceptance');
    await screenshot('05-phone-completed-task-record');
    report.checks.push('owned_template_task_succeeds_and_same_id_record_is_visible');
    report.checks.push('phone_no_horizontal_overflow_or_page_error');
    report.passed = true;
  } catch (error) {
    report.errors.push(String(error && error.stack || error));
    event('failed_without_motion_retry_or_cancel', { phase: marker.phase,
      owned_mission_id: marker.owned_mission_id });
    if (phone) {
      try { await screenshot('failure'); } catch (captureError) {
        report.errors.push(`Failure screenshot unavailable: ${captureError}`);
      }
    }
  } finally {
    report.finished_epoch = Date.now() / 1000;
    report.marker = marker;
    try { if (browser) await browser.close(); } catch (error) {
      report.errors.push(`Browser cleanup failed: ${error}`); report.passed = false;
    }
    try { if (api) await api.dispose(); } catch (error) {
      report.errors.push(`Read-only request client cleanup failed: ${error}`); report.passed = false;
    }
    atomicJson('browser-result.json', report);
    process.stdout.write(JSON.stringify({ passed: report.passed, checks: report.checks,
      errors: report.errors, owned_mission_id: marker.owned_mission_id }) + '\n');
  }
  return report.passed ? 0 : 1;
}

if (require.main === module) {
  main(argumentsFrom(process.argv.slice(2))).then((code) => { process.exitCode = code; })
    .catch((error) => { process.stderr.write(String(error.stack || error) + '\n'); process.exitCode = 1; });
}

module.exports = { argumentsFrom, assertMissionBody, inactive, sameMissionPayload, showPanel, terminalVisible };
