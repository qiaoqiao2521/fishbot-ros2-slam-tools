#!/usr/bin/env node
'use strict';

// Browser contract fixtures only. Every API request is intercepted before it reaches ROS.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

function argumentsFrom(argv) {
  const options = { base: 'http://127.0.0.1:5182', domain: 127, chromium: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH };
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    assert.ok(['--base', '--domain', '--output', '--chromium'].includes(key), `Unknown option: ${key}`);
    assert.ok(argv[index + 1], `Missing value for ${key}`);
    options[key.slice(2)] = argv[index + 1];
  }
  const address = new URL(options.base);
  assert.ok(address.protocol === 'http:' && address.hostname === '127.0.0.1' && address.port
    && !address.username && !address.password && address.pathname === '/' && !address.search && !address.hash,
  'Select an explicit loopback HTTP origin');
  options.base = address.origin; options.domain = Number(options.domain);
  assert.ok(Number.isInteger(options.domain) && options.domain > 0 && options.domain <= 232, 'Select a nonzero simulation domain');
  assert.ok(options.output, 'Provide --output outside the repository');
  const repository = fs.realpathSync(path.join(__dirname, '..'));
  const requested = path.resolve(options.output);
  assert.ok(requested !== repository && !requested.startsWith(repository + path.sep), 'Output must be outside the repository');
  fs.mkdirSync(requested, { recursive: true, mode: 0o700 }); options.output = fs.realpathSync(requested);
  assert.ok(options.output !== repository && !options.output.startsWith(repository + path.sep), 'Output cannot resolve inside the repository');
  assert.equal(fs.statSync(options.output).mode & 0o077, 0, 'Output must be private (0700)');
  assert.equal(fs.readdirSync(options.output).length, 0, 'Use a fresh output directory; prior evidence is preserved');
  return options;
}

async function until(read, predicate, label, seconds = 20) {
  const deadline = Date.now() + seconds * 1000; let value;
  while (Date.now() < deadline) { value = await read(); if (predicate(value)) return value; await new Promise(resolve => setTimeout(resolve, 80)); }
  throw new Error(`Contract deadline (${label}): ${JSON.stringify(value)}`);
}

function sourceManifest() {
  const root = path.join(__dirname, '..');
  return Object.fromEntries(['tools/fishbot_workbench_edit_ui_contract.cjs',
    ...['components/simulation/simulation-page.tsx', 'components/simulation/simulation-map.tsx',
      'components/simulation/simulation-properties.tsx', 'components/simulation/simulation.css', 'lib/simulation-workspace.ts',
      'components/workspace/workspace-surface.tsx', 'components/workspace/workspace-desktop.tsx',
      'components/workspace/workspace-visibility.ts', 'components/workspace/workspace-slots.ts',
      'components/workspace/workspace-layout.ts', 'components/workspace/workspace.css',
      'hooks/use-simulation-workspace.ts', 'hooks/use-simulation.ts', 'hooks/use-patrol-draft-cache.ts',
      'lib/rule-draft-cache.ts', 'lib/patrol-draft-cache.ts', 'lib/route-safety.ts', 'lib/map-zones.ts', 'lib/simulation.ts', 'App.tsx']
      .map(name => `apps/fishbot-control-station/frontend/src/${name}`)]
    .map(name => [name, crypto.createHash('sha256').update(fs.readFileSync(path.join(root, name))).digest('hex')]));
}

async function main(options) {
  const report = { passed: false, scope: 'Real browser against intercepted API fixtures; no ROS, physics or native action acceptance',
    base: options.base, domain: options.domain, started_epoch: Date.now() / 1000, checks: [], posts: [], errors: [], screenshots: [], source_start: sourceManifest() };
  const map = { map_id: 'workbench-edit-contract-map', width: 120, height: 90, resolution: .05, origin: [-3, -2.25, 0],
    data: Array.from({ length: 10800 }, (_, index) => { const x = index % 120, y = Math.floor(index / 120); return x < 3 || x > 116 || y < 3 || y > 86 ? 100 : 0; }) };
  const originalWall = { id: 'fixture-wall', kind: 'wall', points: [{ x: 1.6, y: .4 }, { x: 1.6, y: 1.1 }], width: .02 };
  const rules = { map_id: map.map_id, revision: 1, zones: [structuredClone(originalWall)], apply_state: 'applied', message: 'Browser contract fixture' };
  const routes = [];
  const state = { mode: 'mujoco', domain: options.domain, ready: true, reason: '浏览器合同样本；不作为 ROS 运动验收',
    pose: { x: -1, y: 0, yaw: 0 }, truth: null, path: [], mission: { id: null, status: 'idle', current_index: 0, waypoints: [], return_home: false, message: '未派发' },
    obstacle: { state: 'parked', x: null, y: null, size: .36 }, home: { x: -1, y: 0, yaw: 0 } };
  let browser, page, disconnected = false, touch = false;
  function writeResult() { fs.writeFileSync(path.join(options.output, 'browser-result.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 }); }
  function check(name) { report.checks.push(name); console.log(`PASS ${name}`); }
  async function screenshot(name) { await page.screenshot({ path: path.join(options.output, name + '.png'), fullPage: true }); report.screenshots.push(name + '.png'); }
  async function intercept(route) {
    const request = route.request(), url = new URL(request.url()), resource = url.pathname;
    const headers = { 'X-Fishbot-Instance': 'edit-contract-fixture' };
    if (url.origin !== options.base) return route.abort();
    if (request.method() !== 'GET') {
      const body = request.postDataJSON(); report.posts.push({ resource, body });
      if (resource === '/sim-api/map-rules') {
        assert.equal(body.map_id, map.map_id); assert.equal(body.base_revision, rules.revision);
        rules.zones = structuredClone(body.zones); rules.revision++; rules.apply_state = 'published';
        return route.fulfill({ json: rules, headers });
      }
      if (resource === '/sim-api/routes') {
        assert.equal(body.map_id, map.map_id);
        routes.push({ ...body, revision: rules.revision });
        return route.fulfill({ json: { map_id: map.map_id, routes }, headers });
      }
      report.errors.push(`Forbidden write intercepted: ${resource}`);
      return route.abort();
    }
    if (resource === '/sim-api/runtime') return route.fulfill({ json: { schema_version: 1, service: 'mission', instance_id: 'edit-contract-fixture', mode: 'simulation', domain: options.domain, scene_id: null, episode_id: null, capabilities: [] }, headers });
    if (resource === '/sim-api/state' && disconnected) return route.abort();
    const values = { '/sim-api/map': map, '/sim-api/state': state, '/sim-api/map-rules': rules,
      '/sim-api/routes': { map_id: map.map_id, routes }, '/sim-api/runs': { runs: [] },
      '/sim-api/rviz': { available: false, running: false, domain: options.domain, message: 'Contract fixture does not open native windows' } };
    if (values[resource]) return route.fulfill({ json: values[resource], headers });
    if (/^\/(sim-api|coop-api|voice-api|api)\//.test(resource)) return route.fulfill({ status: 503, json: { error: 'Isolated contract fixture: unsupported endpoint' }, headers });
    return route.continue();
  }
  async function isolatedRoute(route) {
    try { await intercept(route); }
    catch (error) { report.errors.push(`Fixture contract error: ${error.message}`); await route.abort().catch(() => {}); }
  }
  function surface() { return page.locator('[data-workspace="simulation"]'); }
  function form() { return surface().locator('.simulation-object-form'); }
  async function clickWorld(x, y) {
    const svg = surface().getByRole('application'); await svg.scrollIntoViewIfNeeded();
    const box = await svg.boundingBox(); assert.ok(box?.width > 0 && box.height > 0, 'Visible map is required');
    const dx = x - map.origin[0], dy = y - map.origin[1], c = Math.cos(map.origin[2]), s = Math.sin(map.origin[2]);
    const px = (c * dx + s * dy) / map.resolution, py = map.height - (-s * dx + c * dy) / map.resolution;
    const position = { x: px / map.width * box.width, y: py / map.height * box.height };
    if (touch) await page.touchscreen.tap(box.x + position.x, box.y + position.y);
    else await svg.click({ position });
  }
  async function select(name, mobile = false) {
    if (mobile) await surface().getByRole('tab', { name: '对象', exact: true }).tap();
    const object = surface().getByRole('button', { name, exact: true });
    if (mobile) await object.tap(); else await object.click();
    if (mobile) await surface().getByRole('tab', { name: '属性', exact: true }).tap();
    await form().waitFor();
  }
  async function pose(x, y, degrees, zone = false) {
    await form().getByRole('spinbutton', { name: zone ? '中心 X（米）' : 'X（米）', exact: true }).fill(String(x));
    await form().getByRole('spinbutton', { name: zone ? '中心 Y（米）' : 'Y（米）', exact: true }).fill(String(y));
    if (degrees !== null) await form().getByRole('spinbutton', { name: '朝向（度）', exact: true }).fill(String(degrees));
    const apply = form().getByRole('button', { name: '应用到草稿', exact: true });
    if (touch) await apply.tap(); else await apply.click();
  }
  async function ready() {
    await surface().getByRole('application').waitFor();
    await until(() => surface().getByRole('button', { name: '虚拟墙', exact: true }).isEnabled(), Boolean, 'editor ready');
  }
  try {
    browser = await chromium.launch({ headless: true, ...(options.chromium ? { executablePath: options.chromium } : {}) });
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' });
    page = await context.newPage(); page.setDefaultTimeout(20000);
    page.on('pageerror', error => report.errors.push(error.message)); await context.route('**/*', isolatedRoute);
    await page.goto(options.base + '/simulation', { waitUntil: 'domcontentloaded' }); await ready();
    assert.equal(report.posts.length, 0); check('enter_without_writes');
    await clickWorld(-.5, -.5); await select('查看巡逻点 1 属性');
    await pose(-.4, .1, 90);
    await surface().getByRole('button', { name: '查看巡逻点 1 属性', exact: true }).filter({ hasText: '(-0.40, 0.10)' }).waitFor();
    await surface().locator('[data-selected-waypoint="1"]').waitFor();
    assert.ok(Math.abs(Number(await form().getByRole('spinbutton', { name: '朝向（度）', exact: true }).inputValue()) - 90) < 1e-6);
    await surface().getByRole('button', { name: '撤销航点', exact: true }).click();
    await surface().getByRole('button', { name: '查看巡逻点 1 属性', exact: true }).filter({ hasText: '(-0.50, -0.50)' }).waitFor();
    await surface().getByRole('button', { name: '重做航点', exact: true }).click(); await form().waitFor();
    check('waypoint_pose_explicit_draft_transaction_undo_redo');
    await form().getByRole('spinbutton', { name: 'X（米）', exact: true }).fill('');
    await form().getByRole('button', { name: '应用到草稿', exact: true }).click();
    assert.equal(await form().getByRole('spinbutton', { name: 'X（米）', exact: true }).evaluate(input => input.validity.valueMissing), true);
    await pose(99, .1, 90); await form().getByRole('alert').filter({ hasText: '车体范围' }).waitFor();
    assert.equal(report.posts.length, 0); check('blank_and_outside_input_preserve_draft');
    await select('查看虚拟墙 1 属性'); await pose(.8, .8, 0, true);
    const wallPoints = await surface().locator('[data-selected-zone="fixture-wall"] polyline').getAttribute('points');
    const wallPixels = wallPoints.split(/[ ,]/).map(Number);
    assert.ok(wallPixels.length === 4 && wallPixels.every((value, index) => Math.abs(value - [69, 29, 83, 29][index]) < 1e-6), `Unexpected rigid wall geometry: ${wallPoints}`);
    await surface().getByRole('button', { name: '撤销', exact: true }).click();
    await until(() => surface().locator('[data-selected-zone="fixture-wall"] polyline').getAttribute('points'), value => value !== wallPoints, 'rule undo');
    await surface().getByRole('button', { name: '重做', exact: true }).click();
    assert.equal(await surface().locator('[data-selected-zone="fixture-wall"] polyline').getAttribute('points'), wallPoints);
    check('wall_rigid_pose_and_exact_highlight_undo_redo');
    await surface().getByRole('button', { name: '禁区', exact: true }).click();
    await clickWorld(-1.5, -1.2); await clickWorld(-1, -.7); await select('查看禁区 2 属性');
    assert.equal(await form().getByRole('spinbutton', { name: '朝向（度）', exact: true }).count(), 0);
    await pose(-.8, -1, null, true); await surface().locator('[data-selected-zone] polygon').waitFor();
    assert.deepEqual(rules.zones, [originalWall]); assert.equal(report.posts.length, 0);
    await screenshot('desktop-unsaved-objects'); check('area_translation_without_invented_rotation_or_publish');
    await page.reload({ waitUntil: 'domcontentloaded' }); await ready();
    await surface().getByText('已恢复本标签页未发布规则草稿；未自动保存或派发。', { exact: true }).waitFor();
    assert.equal(await surface().locator('.simulation-rule-list > li').count(), 2);
    assert.equal(report.posts.length, 0); check('unpublished_rules_restore_on_refresh');
    rules.revision = 2;
    await page.reload({ waitUntil: 'domcontentloaded' }); await ready();
    await surface().getByText('已恢复旧版本规则草稿；服务端版本已变化，请核对后恢复已保存规则。', { exact: true }).waitFor();
    assert.equal(await surface().locator('.simulation-rule-list > li').count(), 2);
    assert.equal(await surface().getByRole('button', { name: '保存规则', exact: true }).isDisabled(), true);
    await surface().getByRole('button', { name: '恢复已保存', exact: true }).click();
    await until(() => surface().locator('.simulation-rule-list > li').count(), count => count === 1, 'explicit server restore');
    check('new_server_revision_retains_old_draft_and_blocks_publish');
    await select('查看虚拟墙 1 属性'); await pose(.8, .8, 0, true);
    await surface().getByRole('button', { name: '保存规则', exact: true }).click();
    await surface().getByText('规则已发布，等待导航确认。', { exact: true }).waitFor();
    assert.equal(report.posts.length, 1); assert.equal(report.posts[0].resource, '/sim-api/map-rules');
    assert.equal(rules.apply_state, 'published'); rules.apply_state = 'applied';
    await surface().getByRole('status').filter({ hasText: '导航已应用 · 版本 3' }).waitFor();
    check('explicit_save_only_then_separate_navigation_application');
    await surface().getByRole('textbox', { name: '路线名称', exact: true }).fill('属性编辑合同路线');
    await surface().getByRole('button', { name: '保存当前路线', exact: true }).click();
    await surface().getByRole('button', { name: '查看路线 属性编辑合同路线 属性', exact: true }).waitFor();
    assert.equal(report.posts.length, 2); assert.equal(report.posts[1].resource, '/sim-api/routes');
    check('explicit_route_save_without_movement');
    disconnected = true;
    await surface().getByText('连接中断，正在重连', { exact: true }).waitFor();
    await select('查看巡逻点 1 属性'); await pose(-.4, .2, 90);
    assert.equal(report.posts.length, 2); disconnected = false;
    await surface().getByText('已就绪，可以派发', { exact: true }).waitFor();
    check('offline_local_waypoint_edit_without_motion_or_replay');
    await screenshot('desktop-edited-final');
    const phoneContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
    await phoneContext.route('**/*', isolatedRoute); page = await phoneContext.newPage();
    touch = true;
    page.setDefaultTimeout(20000); page.on('pageerror', error => report.errors.push(error.message));
    await page.goto(options.base + '/simulation', { waitUntil: 'domcontentloaded' }); await ready();
    await clickWorld(-.5, -.5); await select('查看巡逻点 1 属性', true); await pose(-.6, -.3, -45);
    await surface().getByRole('tab', { name: '对象', exact: true }).tap();
    await surface().getByRole('button', { name: '查看巡逻点 1 属性', exact: true }).filter({ hasText: '(-0.60, -0.30)' }).waitFor();
    await select('查看虚拟墙 1 属性', true); await pose(.7, .8, 30, true);
    await surface().getByRole('button', { name: '保存规则', exact: true }).tap();
    await until(() => report.posts.length, count => count === 3, 'phone explicit rule save'); rules.apply_state = 'applied';
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
    await screenshot('mobile-property-edit'); check('phone_waypoint_wall_edit_and_explicit_save_no_overflow');
    assert.deepEqual(report.errors, []);
    assert.equal(report.posts.filter(post => !['/sim-api/map-rules', '/sim-api/routes'].includes(post.resource)).length, 0);
    report.source_end = sourceManifest(); assert.deepEqual(report.source_end, report.source_start, 'Execution source changed during browser contract');
    report.passed = true;
  } catch (error) {
    report.errors.push(String(error.stack || error));
    if (page && !page.isClosed()) await screenshot('failure').catch(() => {});
    throw error;
  } finally {
    report.finished_epoch = Date.now() / 1000; report.source_end = sourceManifest(); writeResult();
    if (browser) await browser.close();
  }
  console.log(JSON.stringify({ passed: report.passed, checks: report.checks.length, posts: report.posts.map(post => post.resource), output: options.output }));
}

if (require.main === module) {
  let options;
  try { options = argumentsFrom(process.argv.slice(2)); } catch (error) { console.error(error.message); process.exitCode = 1; }
  if (options) main(options).catch(error => { console.error(error.stack || error); process.exitCode = 1; });
}
module.exports = { argumentsFrom };
