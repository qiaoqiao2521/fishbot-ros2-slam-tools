#!/usr/bin/env node
'use strict';
// Real browser events against fully intercepted API fixtures. Never reaches ROS.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');
const { argumentsFrom } = require('./fishbot_workbench_edit_ui_contract.cjs');
const root = path.join(__dirname, '..');
function sources() {
  return Object.fromEntries(['tools/fishbot_manual_ui_contract.cjs', ...['App.tsx', 'lib/manual-control.ts', 'hooks/use-manual-owner.ts',
    'components/control/leased-motion-panel.tsx', 'components/control/leased-motion.css', 'lib/runtime-context.ts', 'lib/simulation.ts'].map(s => 'apps/fishbot-control-station/frontend/src/' + s)]
    .map(s => [s, crypto.createHash('sha256').update(fs.readFileSync(path.join(root, s))).digest('hex')]));
}
async function until(read, predicate, label, ms = 15000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) { const v = await read(); if (predicate(v)) return v; await new Promise(resolve => setTimeout(resolve, 50)); }
  throw new Error('Deadline: ' + label);
}
async function main(options) {
  const report = { passed: false, scope: 'Browser event contract fixture; no physical or native action evidence', checks: [], posts: [], errors: [], source_start: sources(), started_epoch: Date.now() / 1000 };
  const instance = '00000000-0000-4000-8000-000000000001';
  const quiet = { confirmed: false, duration_s: 0, source: '/ground_truth/free_joint_states', source_stamp: null, receive_age_s: null, source_age_s: null };
  const stopped = { ...quiet, confirmed: true, duration_s: .8, source_stamp: 1, receive_age_s: .02, source_age_s: .01 };
  const limits = { forward_mps: .08, reverse_mps: .03, angular_rps: .25, command_ttl_ms: 250, acquire_ttl_ms: 1000, heartbeat_ms: 140 };
  let lease = null, stop = null, reset = null, browser, page, loseCommand = false, loseStop = false;
  let native = { task_id: null, status: 'idle', native_goal_id: null, terminal: true };
  const leases = new Map(), stops = new Map(), resets = new Map();
  function expire() { if (lease && ['ready', 'active', 'arming'].includes(lease.state)) Object.assign(lease, { state: 'expired', remaining_ms: 0, quiet: stopped, guard_stop_acknowledged: true }); }
  function status() {
    return { runtime_instance_id: instance, map_id: 'manual-contract-map', profile_id: 'passage_manual', available: true,
      can_acquire: (!lease || ['expired', 'released', 'stopped'].includes(lease.state)) && !stop && native.terminal,
      can_stop: true, can_reset: stop?.state === 'stopped', reason: null, active_lease_id: lease?.lease_id ?? null, active_stop_request_id: stop?.request_id ?? null,
      stop_latched: !!stop, native_owner: native, quiet: stopped, limits };
  }
  function check(name) { report.checks.push(name); console.log('PASS ' + name); }
  async function intercept(route) {
    const req = route.request(), url = new URL(req.url()), p = url.pathname;
    if (url.origin !== options.base) return route.abort();
    const headers = { 'X-Fishbot-Instance': instance };
    if (req.method() !== 'GET') {
      const b = req.postDataJSON(); report.posts.push({ path: p, body: b, at: Date.now() });
      assert.equal(b.runtime_instance_id, instance); assert.equal(b.map_id, 'manual-contract-map'); assert.equal(b.profile_id, 'passage_manual');
      assert.ok(Date.now() - b.issued_at_ms < b.ttl_ms && b.ttl_ms <= 1000);
      if (p === '/sim-api/manual/acquire') {
        assert.equal(status().can_acquire, true); assert.equal(b.sequence, 0); assert.ok(!leases.has(b.lease_id));
        lease = { ...b, last_sequence: 0, state: 'ready', reason: null, remaining_ms: 1000, expires_at_ms: Date.now() + 1000, guard_reset_acknowledged: true, guard_stop_acknowledged: false, quiet };
        leases.set(lease.lease_id, lease);
      } else if (p === '/sim-api/manual/command' || p === '/sim-api/manual/release') {
        assert.equal(b.lease_id, lease.lease_id); assert.ok(b.sequence > lease.last_sequence); assert.equal(b.session_id, lease.session_id);
        lease.last_sequence = b.sequence;
        if (p.endsWith('/command')) {
          assert.equal(b.ttl_ms, 250); assert.ok(b.linear_x <= .08 && b.linear_x >= -.03 && Math.abs(b.angular_z) <= .25);
          Object.assign(lease, { state: 'active', remaining_ms: 250, expires_at_ms: Date.now() + 250 });
          if (loseCommand) { loseCommand = false; return route.abort(); }
        } else Object.assign(lease, { state: 'released', remaining_ms: 0, quiet: stopped, guard_stop_acknowledged: true });
      } else if (p === '/sim-api/manual/stop') {
        assert.equal(b.target_id, native.task_id ?? lease?.lease_id ?? null);
        stop = { request_id: b.request_id, target_id: b.target_id, target_kind: native.task_id ? 'mission' : lease ? 'manual' : 'idle', state: 'stopped', runtime_instance_id: instance,
          guard_stop_acknowledged: true, native_cancel_acknowledged: true, native_terminal: true, native_status: 5, quiet: stopped, reason: null };
        stops.set(stop.request_id, stop); native = { ...native, terminal: true, status: 'canceled' }; expire();
        if (loseStop) { loseStop = false; return route.abort(); }
        return route.fulfill({ json: { accepted: true, outcome: 'accepted', stop }, headers });
      } else if (p === '/sim-api/manual/reset') {
        assert.equal(b.stop_request_id, stop.request_id); assert.equal(b.gesture, 'reset');
        reset = { request_id: b.request_id, stop_request_id: b.stop_request_id, state: 'ready', runtime_instance_id: instance, guard_reset_acknowledged: true, reason: null };
        resets.set(reset.request_id, reset); stop = null;
        return route.fulfill({ json: { accepted: true, outcome: 'accepted', reset }, headers });
      } else throw new Error('Forbidden API write: ' + p);
      return route.fulfill({ json: { accepted: true, outcome: 'accepted', lease }, headers });
    }
    if (p === '/sim-api/runtime') return route.fulfill({ headers, json: { schema_version: 1, service: 'mission', instance_id: instance, mode: 'simulation', domain: options.domain,
      scene_id: null, episode_id: null, capabilities: [{ id: 'teleop', submission: 'topic_publish', task_lookup: true, cancel: true, event_history: 'snapshot', available: true, protocol: 'manual_lease_v1', profile_id: 'passage_manual', limits }] } });
    if (p === '/sim-api/manual/status') return route.fulfill({ headers, json: status() });
    if (p.startsWith('/sim-api/manual/stops/')) return route.fulfill({ headers, json: { stop: stops.get(p.split('/').at(-1)) } });
    if (p.startsWith('/sim-api/manual/resets/')) return route.fulfill({ headers, json: { reset: resets.get(p.split('/').at(-1)) } });
    if (p.startsWith('/sim-api/manual/')) return route.fulfill({ headers, json: { lease: leases.get(p.split('/').at(-1)) } });
    if (/^\/(api|sim-api|voice-api|coop-api|workbench-service)\//.test(p)) return route.fulfill({ status: 503, headers, json: { error: 'Isolated manual fixture' } });
    return route.continue();
  }
  function posts(op) { return report.posts.filter(p => p.path.endsWith('/' + op)); }
  const direction = label => page.getByRole('button', { name: '按住' + label, exact: true });
  async function press(label) { const b = direction(label); await b.scrollIntoViewIfNeeded(); await until(() => b.isEnabled(), Boolean, 'manual ready'); const box = await b.boundingBox(); await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2); await page.mouse.down(); }
  async function ready() { await until(() => direction('前进').isEnabled(), Boolean, 'new gesture permitted'); }
  try {
    browser = await chromium.launch({ headless: true, ...(options.chromium ? { executablePath: options.chromium } : {}) });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
    await context.route('**/*', async route => { try { await intercept(route) } catch (e) { report.errors.push(e.stack); await route.abort().catch(() => {}) } });
    page = await context.newPage(); page.setDefaultTimeout(20000); page.on('pageerror', e => report.errors.push(e.message));
    await page.goto(options.base + '/', { waitUntil: 'domcontentloaded' }); await ready(); assert.equal(report.posts.length, 0); check('entry_has_no_write');
    await press('前进'); await until(() => posts('command').length, n => n >= 2, 'held commands'); const count = posts('command').length;
    await page.mouse.up(); await ready(); await page.waitForTimeout(350); assert.equal(posts('command').length, count); assert.equal(posts('release').length, 1); check('pointer_hold_release_exact_lease');
    await press('左转'); await until(() => posts('acquire').length, n => n === 2, 'second gesture'); await page.evaluate(() => window.dispatchEvent(new Event('blur'))); await page.mouse.up(); await ready(); check('window_blur_releases_without_resuming');
    loseCommand = true; await press('右转'); await until(() => page.getByRole('alert').count(), n => n > 0, 'lost command surfaced'); await page.mouse.up();
    const lostCount = report.posts.length, originalLease = lease.lease_id; await page.reload({ waitUntil: 'domcontentloaded' }); await page.waitForTimeout(1000);
    assert.equal(report.posts.length, lostCount); assert.equal(lease.lease_id, originalLease); assert.equal(await direction('前进').isEnabled(), false); expire(); await ready(); check('lost_command_reload_queries_original_never_replays');
    await press('后退'); await until(() => posts('acquire').length, n => n === 4, 'backward gesture');
    await page.getByRole('button', { name: '成果验收', exact: true }).click(); await page.mouse.up(); await until(() => lease.state, s => s === 'released', 'route exit release');
    await page.getByRole('button', { name: '控制总览', exact: true }).click(); await ready(); check('route_exit_releases_application_owned_lease');
    const keyboardToggle = page.getByRole('checkbox', { name: '启用键盘（焦点留在本面板）', exact: true });
    await keyboardToggle.check();
    const keyboardPanel = page.getByRole('region', { name: '低速人工控制', exact: true });
    assert.equal(await keyboardToggle.evaluate(element => element === document.activeElement), true);
    const beforeToggleSpace = report.posts.length;
    await page.keyboard.press('Space'); assert.equal(await keyboardToggle.isChecked(), false);
    await page.waitForTimeout(180); assert.equal(report.posts.length, beforeToggleSpace);
    await page.keyboard.press('Space'); assert.equal(await keyboardToggle.isChecked(), true);
    await page.waitForTimeout(180); assert.equal(report.posts.length, beforeToggleSpace); check('checkbox_space_preserves_native_toggle_without_stop_or_acquire');
    for (const modifier of ['Control', 'Meta', 'Alt']) {
      const beforeShortcut = report.posts.length, beforeUrl = page.url();
      await page.keyboard.press(modifier + '+ArrowUp'); await page.waitForTimeout(180);
      assert.equal(report.posts.length, beforeShortcut); assert.equal(page.url(), beforeUrl);
    }
    check('modified_arrow_shortcuts_never_acquire_control');
    const beforeKeyboard = posts('command').length;
    await page.keyboard.down('w'); await until(() => posts('command').length, n => n > beforeKeyboard, 'focused keyboard command');
    assert.ok(posts('command').at(-1).body.linear_x > 0); await page.keyboard.up('w'); await ready();
    const afterKeyup = report.posts.length; await page.waitForTimeout(350); assert.equal(report.posts.length, afterKeyup); check('focused_keyboard_hold_keyup_releases_exact_lease');
    await keyboardToggle.focus(); const beforeArrow = posts('command').length;
    await page.keyboard.down('ArrowLeft'); await until(() => posts('command').length, n => n > beforeArrow, 'checkbox arrow command');
    assert.ok(posts('command').at(-1).body.angular_z > 0); await page.keyboard.up('ArrowLeft'); await ready(); check('checkbox_focus_accepts_w_and_arrow_keys');
    await keyboardToggle.focus(); const beforeFocusHold = posts('command').length, beforeFocusAcquire = posts('acquire').length, beforeFocusRelease = posts('release').length;
    await page.keyboard.down('w'); await until(() => posts('command').length, n => n > beforeFocusHold, 'keyboard hold before focus transition');
    const focusLease = lease.lease_id;
    await page.keyboard.press('Tab');
    assert.equal(await keyboardPanel.evaluate(element => element.contains(document.activeElement)), true);
    await page.waitForTimeout(180); assert.equal(posts('release').length, beforeFocusRelease); assert.equal(lease.lease_id, focusLease); assert.equal(lease.state, 'active');
    check('keyboard_focus_inside_panel_keeps_original_hold');
    for (let tabs = 0; tabs < 12 && await keyboardPanel.evaluate(element => element.contains(document.activeElement)); tabs++) await page.keyboard.press('Tab');
    assert.equal(await keyboardPanel.evaluate(element => element.contains(document.activeElement)), false);
    await until(() => posts('release').length, n => n === beforeFocusRelease + 1, 'focus exit original release');
    assert.equal(posts('release').at(-1).body.lease_id, focusLease); assert.equal(posts('acquire').length, beforeFocusAcquire + 1);
    const afterFocusRelease = posts('command').length; await page.waitForTimeout(350); assert.equal(posts('command').length, afterFocusRelease);
    await page.keyboard.up('w'); await ready(); assert.equal(posts('release').length, beforeFocusRelease + 1); check('keyboard_tab_exit_releases_original_lease_without_reacquire');
    await keyboardToggle.focus(); const beforeShift = posts('command').length, beforeShiftRelease = posts('release').length, beforeShiftAcquire = posts('acquire').length;
    await page.keyboard.down('Shift'); await page.keyboard.down('w');
    await until(() => posts('command').length, n => n > beforeShift, 'shift W command'); assert.ok(posts('command').at(-1).body.linear_x > 0);
    const shiftLease = lease.lease_id;
    for (let tabs = 0; tabs < 12 && await keyboardPanel.evaluate(element => element.contains(document.activeElement)); tabs++) await page.keyboard.press('Tab');
    assert.equal(await keyboardPanel.evaluate(element => element.contains(document.activeElement)), false);
    await until(() => posts('release').length, n => n === beforeShiftRelease + 1, 'shift tab exit original release');
    assert.equal(posts('release').at(-1).body.lease_id, shiftLease); assert.equal(posts('acquire').length, beforeShiftAcquire + 1);
    await page.keyboard.up('w'); await page.keyboard.up('Shift'); await ready(); check('shift_w_and_shift_tab_exit_keep_original_release');
    await page.getByRole('button', { name: '控制总览', exact: true }).focus();
    const beforeOutside = report.posts.length; await page.keyboard.press('w'); await page.waitForTimeout(350);
    assert.equal(report.posts.length, beforeOutside); check('keyboard_outside_panel_has_no_control_intent');
    // The product has no text field inside this panel. Add one isolated fixture
    // field to exercise the real handler's input guard with actual key events.
    await keyboardPanel.evaluate(element => { const input = document.createElement('input'); input.type = 'text'; input.id = 'manual-contract-text'; input.setAttribute('aria-label', '合同夹具文本输入'); element.appendChild(input); });
    const fixtureText = page.getByRole('textbox', { name: '合同夹具文本输入', exact: true }); await fixtureText.focus();
    const beforeTyping = report.posts.length; await page.keyboard.type('wasd'); await page.waitForTimeout(350);
    assert.equal(await fixtureText.inputValue(), 'wasd'); assert.equal(report.posts.length, beforeTyping);
    await fixtureText.evaluate(element => element.remove()); check('fixture_text_input_inside_keyboard_panel_never_dispatches');
    await page.getByRole('slider', { name: '人工线速度', exact: true }).focus();
    const beforeRange = report.posts.length; await page.keyboard.press('ArrowLeft'); await page.waitForTimeout(180); assert.equal(report.posts.length, beforeRange);
    await keyboardPanel.evaluate(element => {
      const select = document.createElement('select'); select.id = 'manual-contract-select'; select.setAttribute('aria-label', '合同夹具选择');
      for (const label of ['一', '二']) { const option = document.createElement('option'); option.textContent = label; select.appendChild(option); }
      const editor = document.createElement('div'); editor.id = 'manual-contract-editor'; editor.contentEditable = 'true'; editor.setAttribute('role', 'textbox'); editor.setAttribute('aria-label', '合同夹具编辑');
      element.append(select, editor);
    });
    const fixtureSelect = page.getByRole('combobox', { name: '合同夹具选择', exact: true }); await fixtureSelect.focus();
    const beforeSelect = report.posts.length; await page.keyboard.press('ArrowDown'); await page.waitForTimeout(180); assert.equal(report.posts.length, beforeSelect);
    const fixtureEditor = page.getByRole('textbox', { name: '合同夹具编辑', exact: true }); await fixtureEditor.focus();
    const beforeEditor = report.posts.length; await page.keyboard.type('wasd'); await page.waitForTimeout(180); assert.equal(await fixtureEditor.textContent(), 'wasd'); assert.equal(report.posts.length, beforeEditor);
    await fixtureSelect.evaluate(element => element.remove()); await fixtureEditor.evaluate(element => element.remove()); check('range_select_and_contenteditable_do_not_dispatch_keyboard_motion');
    // Completed manual receipt is gone. Stop now binds the current native task.
    lease = null; native = { task_id: crypto.randomUUID(), native_goal_id: 'fixture-native', terminal: false, status: 'running' }; loseStop = true;
    await until(() => direction('前进').isEnabled(), v => !v, 'native task excludes manual');
    await page.getByRole('button', { name: '停止当前执行器', exact: true }).first().click();
    await until(() => posts('stop').length, n => n === 1, 'single original stop'); const originalStop = stop.request_id;
    const foreignTab = await context.newPage(); foreignTab.setDefaultTimeout(20000); foreignTab.on('pageerror', error => report.errors.push(error.message));
    const beforeForeign = report.posts.length; await foreignTab.goto(options.base + '/', { waitUntil: 'domcontentloaded' });
    const foreignReset = foreignTab.getByRole('button', { name: '解除本次停车锁', exact: true });
    await foreignReset.waitFor({ state: 'visible' }); assert.equal(await foreignReset.isEnabled(), false);
    await foreignTab.getByText('本页没有当前停车锁的原回执。请在原会话解除，或先点“停止”建立本页停车回执。', { exact: true }).waitFor();
    await foreignTab.waitForTimeout(350); assert.equal(report.posts.length, beforeForeign);
    await foreignTab.close(); check('fresh_tab_lock_has_original_receipt_guidance_no_write');
    await page.reload({ waitUntil: 'domcontentloaded' }); const resetButton = page.getByRole('button', { name: '解除本次停车锁', exact: true });
    await until(() => resetButton.isEnabled(), Boolean, 'original stop recovered'); assert.equal(posts('stop').length, 1); assert.equal(stop.request_id, originalStop);
    await resetButton.click(); await ready(); const afterReset = report.posts.length; await page.waitForTimeout(500); assert.equal(report.posts.length, afterReset); check('stop_receipt_loss_and_reset_do_not_resume');
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await press('前进'); await until(() => lease?.state, s => s === 'active', 'mobile hold'); await page.mouse.up(); await ready(); check('mobile_control_and_release_no_horizontal_overflow');
    await page.screenshot({ path: path.join(options.output, 'manual-mobile.png'), fullPage: true });
    lease = null; native = { task_id: crypto.randomUUID(), native_goal_id: 'fixture-space-native', terminal: false, status: 'running' };
    const spaceTarget = native.task_id, beforePanelSpace = posts('stop').length;
    await until(() => direction('前进').isEnabled(), v => !v, 'space native owner excludes manual');
    await keyboardToggle.check(); await keyboardPanel.focus(); await page.keyboard.press('Space');
    await until(() => posts('stop').length, n => n === beforePanelSpace + 1, 'panel space original stop');
    assert.equal(posts('stop').at(-1).body.target_id, spaceTarget); check('panel_space_stops_original_native_owner');
    assert.equal(report.errors.length, 0); report.passed = true;
  } catch (e) { report.errors.push(e.stack || String(e)); process.exitCode = 1; }
  finally {
    report.source_end = sources(); report.source_unchanged = JSON.stringify(report.source_start) === JSON.stringify(report.source_end);
    report.passed = report.passed && report.source_unchanged && !report.errors.length;
    if (!report.passed) process.exitCode = 1;
    if (browser) await browser.close();
    report.browser_closed = !browser || !browser.isConnected(); report.elapsed_s = Date.now() / 1000 - report.started_epoch;
    fs.writeFileSync(path.join(options.output, 'browser-result.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
    console.log(JSON.stringify({ passed: report.passed, checks: report.checks, errors: report.errors, output: options.output }));
  }
}
if (require.main === module) main(argumentsFrom(process.argv.slice(2))).catch(e => { console.error(e); process.exitCode = 1 });
