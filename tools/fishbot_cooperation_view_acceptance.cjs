#!/usr/bin/env node
'use strict';
// Read-only view acceptance. --fixture intercepts every API read and all writes.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { argumentsFrom } = require('./fishbot_workbench_edit_ui_contract.cjs');
async function wait(read, predicate, name, seconds = 15) {
  const end = Date.now() + seconds * 1000;
  while (Date.now() < end) { const v = await read(); if (predicate(v)) return v; await new Promise(r => setTimeout(r, 100)); }
  throw new Error('View acceptance timeout: ' + name);
}
function sourceManifest() {
  return { ...Object.fromEntries(['App.tsx', 'components/cooperation/cooperation-page.tsx', 'components/cooperation/cooperation-canvas.tsx',
    'components/cooperation/cooperation-camera-session.ts', 'components/workspace/workspace-desktop.tsx', 'components/workspace/workspace-surface.tsx',
    'lib/cooperation.ts', 'lib/cooperation-frame.ts'].map(p => [p, crypto.createHash('sha256').update(fs.readFileSync(path.join(__dirname, '../apps/fishbot-control-station/frontend/src', p))).digest('hex')])),
    'tools/fishbot_cooperation_view_acceptance.cjs': crypto.createHash('sha256').update(fs.readFileSync(__filename)).digest('hex') };
}
async function main(options) {
  const report = { scope: options.fixture ? 'Browser object-property fixture; all API traffic intercepted; no ROS or physical acceptance' : 'Real ROS cooperation state through UI; only camera reads faulted; no commands', passed: false, checks: [], errors: [], posts: [], source_start: sourceManifest() };
  let browser, fault = false;
  const read = async () => { const r = await fetch(options.base + '/coop-api/state', { signal: AbortSignal.timeout(3000) }); assert.ok(r.ok); return r.json(); };
  try {
    if (options.fixture) {
      browser = await chromium.launch({ headless: true, ...(options.chromium ? { executablePath: options.chromium } : {}) });
      const state = { mode: 'mujoco', domain: options.domain, ready: true, reason: 'Object-property fixture only',
        episode_id: 'property-fixture-episode', task: { id: 'property-fixture-task', status: 'running', stage: 'arm_lift', message: 'Property fixture only' },
        events: [], physics: { stamp: 12.5, car: { x: 1.1, y: .3, yaw: .5, linear_speed: .02, angular_speed: .01 },
          arm: { q: [.1, .2], velocity: [.3, .4] }, cargo: { x: 1.2, y: .3, z: .24, speed: .06, tip_forces: [2.1, 1.9], tray_contact: false } },
        frame: { available: false, stamp: null }, source: { scene_sha: 'property-fixture-scene' },
        nav: { ready: true, pose: { x: 1.09, y: .29, yaw: .5 } }, stations: { dock: { x: 1, y: 2, yaw: 0 }, delivery: { x: 3, y: 4, yaw: 0 } } };
      const runtime = { schema_version: 1, service: 'cooperation', instance_id: 'property-fixture-runtime', mode: 'simulation', domain: options.domain,
        scene_id: 'property-fixture-scene', episode_id: state.episode_id, capabilities: [] };
      const labels = { car: ['物理朝向', '线速度'], arm: ['关节数量', '实际关节角度'], cargo: ['高度', '夹指接触力'], station: ['固定工位', '交付点'] };
      const values = { car: ['28.6°', '0.020 m/s'], arm: ['0.400 rad/s', '5.7° / 11.5°'], cargo: ['0.240 m', '2.10 / 1.90 N'], station: ['1.00, 2.00 m', '3.00, 4.00 m'] };
      const responseChecks = []; report.fixture_api_requests = []; report.real_api_requests = []; report.external_requests = [];
      const intercept = route => {
        const request = route.request(), url = new URL(request.url());
        if (request.method() !== 'GET') { report.posts.push(request.url()); return route.abort(); }
        if (url.origin !== options.base) { report.external_requests.push(request.url()); return route.abort(); }
        if (/^\/(sim-api|coop-api|voice-api|api)\//.test(url.pathname)) {
          report.fixture_api_requests.push(url.pathname);
          const value = url.pathname === '/coop-api/state' ? state : url.pathname === '/coop-api/runtime' ? runtime : null;
          return route.fulfill({ status: value ? 200 : 503, json: value ?? { error: 'Unsupported isolated fixture API' }, headers: { 'X-Fishbot-Instance': runtime.instance_id } });
        }
        return route.continue();
      };
      for (const touch of [false, true]) {
        const size = touch ? 'mobile' : 'desktop';
        const context = await browser.newContext({ viewport: touch ? { width: 390, height: 844 } : { width: 1440, height: 900 }, isMobile: touch, hasTouch: touch, serviceWorkers: 'block' });
        await context.route('**/*', intercept);
        const page = await context.newPage(); page.setDefaultTimeout(15000); page.on('pageerror', error => report.errors.push(error.message));
        page.on('response', response => {
          if (/^\/(sim-api|coop-api|voice-api|api)\//.test(new URL(response.url()).pathname)) responseChecks.push(response.serverAddr().then(address => { if (address) report.real_api_requests.push(response.url()); }));
        });
        await page.goto(options.base + '/cooperation', { waitUntil: 'domcontentloaded' });
        await page.getByText('共享场景已就绪', { exact: true }).waitFor();
        const workspace = page.locator('[data-workspace="cooperation"]');
        for (const [selected, measurements] of Object.entries(labels)) {
          if (touch) await workspace.getByRole('tab', { name: '对象', exact: true }).tap();
          const button = workspace.locator(`[data-coop-object="${selected}"]`);
          if (touch) await button.tap(); else await button.click();
          if (touch) await workspace.getByRole('tab', { name: '属性', exact: true }).tap();
          for (const object of Object.keys(labels)) assert.equal(await workspace.locator(`[data-object-properties="${object}"]`).isVisible(), object === selected, `${selected}: ${object} property visibility`);
          const group = workspace.locator(`[data-object-properties="${selected}"]`);
          for (const label of measurements) assert.equal(await group.getByText(label, { exact: true }).isVisible(), true, `${selected}: ${label}`);
          for (const value of values[selected]) assert.equal(await group.getByText(value, { exact: true }).isVisible(), true, `${selected}: ${value}`);
          report.checks.push(`${size}_${selected}_selected_properties_visible`);
        }
        await page.screenshot({ path: path.join(options.output, `${size}-properties.png`), fullPage: true });
        await Promise.all(responseChecks); await context.close();
      }
      assert.equal(report.posts.length, 0); assert.equal(report.real_api_requests.length, 0); assert.equal(report.external_requests.length, 0); assert.equal(report.errors.length, 0);
      report.checks.push('all_api_reads_intercepted_zero_writes'); report.passed = true; return;
    }
    const runtimeResponse = await fetch(options.base + '/coop-api/runtime'); const runtime = await runtimeResponse.json();
    assert.equal(runtime.domain, options.domain); assert.equal(runtime.service, 'cooperation'); assert.equal(runtimeResponse.headers.get('X-Fishbot-Instance'), runtime.instance_id);
    report.runtime = runtime; report.before = await read(); assert.equal(report.before.task.status, 'running');
    const originalId = report.before.task.id;
    browser = await chromium.launch({ headless: true, ...(options.chromium ? { executablePath: options.chromium } : {}) });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
    await context.route('**/*', route => {
      const req = route.request();
      if (req.method() !== 'GET') { report.posts.push(req.url()); return route.abort(); }
      if (fault && new URL(req.url()).pathname === '/coop-api/frame.jpg') return route.fulfill({ status: 503, json: { error: 'acceptance_camera_read_failure' } });
      return route.continue();
    });
    const page = await context.newPage(); page.on('pageerror', e => report.errors.push(e.message)); page.setDefaultTimeout(15000);
    await page.goto(options.base + '/cooperation', { waitUntil: 'domcontentloaded' });
    const camera = page.locator('.cooperation-camera');
    await wait(() => camera.getAttribute('data-frame-live'), v => v === 'true', 'initial actual decoded frame');
    report.checks.push('real_episode_camera_live'); fault = true;
    await wait(() => camera.getAttribute('data-frame-live'), v => v === 'false', 'camera fault visible');
    report.during_fault = await read(); assert.equal(report.during_fault.task.id, originalId); assert.equal(report.during_fault.task.status, 'running');
    report.checks.push('camera_failure_does_not_cancel_or_replace_task'); fault = false;
    await wait(() => camera.getAttribute('data-frame-live'), v => v === 'true', 'camera recovered');
    report.checks.push('camera_recovers_in_same_episode');
    await page.getByRole('button', { name: '控制总览', exact: true }).click();
    report.during_hidden = await read(); assert.equal(report.during_hidden.task.id, originalId); assert.equal(report.during_hidden.task.status, 'running');
    await page.getByRole('button', { name: '车臂协同', exact: true }).click();
    await wait(() => camera.getAttribute('data-frame-live'), v => v === 'true', 'reopened actual frame');
    report.after = await read(); assert.equal(report.after.task.id, originalId); assert.equal(report.after.episode_id, report.before.episode_id);
    assert.equal(report.posts.length, 0); assert.equal(report.errors.length, 0);
    report.checks.push('route_exit_reopen_preserves_original_task_zero_writes');
    await page.screenshot({ path: path.join(options.output, 'actual-cooperation.png'), fullPage: true }); report.passed = true;
  } catch (e) { report.errors.push(e.stack || String(e)); }
  finally {
    if (browser) await browser.close(); report.source_end = sourceManifest(); report.source_unchanged = JSON.stringify(report.source_start) === JSON.stringify(report.source_end);
    report.passed = report.passed && report.source_unchanged; if (!report.passed) process.exitCode = 1;
    fs.writeFileSync(path.join(options.output, 'result.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
    console.log(JSON.stringify({ passed: report.passed, checks: report.checks, errors: report.errors, output: options.output }));
  }
}
if (require.main === module) {
  const argv = process.argv.slice(2), fixture = argv.includes('--fixture');
  main({ ...argumentsFrom(argv.filter(value => value !== '--fixture')), fixture }).catch(e => { console.error(e); process.exitCode = 1 });
}
