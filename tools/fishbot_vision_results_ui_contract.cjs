#!/usr/bin/env node
'use strict';
// Real static summary + isolated labelled UI fixtures; never a navigation acceptance.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
async function main() {
  const args = Object.fromEntries(process.argv.slice(2).reduce((rows, v, i, a) => (i % 2 ? rows : [...rows, [v.replace(/^--/, ''), a[i + 1]]]), []));
  const base = new URL(args.base || 'http://127.0.0.1:5194');
  assert.equal(base.hostname, '127.0.0.1'); assert.ok(args.output);
  fs.mkdirSync(args.output, { recursive: true });
  const result = { passed: false, checks: [], writes: [], errors: [], scope: 'Static historical summary and synthetic UI-only playback fixture; no ROS or new physical scoring.' };
  const browser = await chromium.launch({ executablePath: args.chromium || '/opt/google/chrome/chrome', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  let fixture = false, missingReplay = false, unknownReplay = false;
  const summary = await (await page.request.get(new URL('/workbench/j100-vision-result.json', base).href)).json();
  const timing = await (await page.request.get(new URL('/workbench/j100-vision-timing.json', base).href)).json();
  // Explicitly synthetic test trajectory, kept out of public assets and business scores.
  const replay = { schema: 'fishbot.delivery-comparison.v1', read_only: true, rescored: false, view_bounds_xy: [-1, -1, 2, 2], scene: { static_boxes: [], car_footprint_xy: [[-.2,-.15],[.2,-.15],[.2,.15],[-.2,.15]] }, runs: summary.orders.map((o, i) => ({ id: 'ui-fixture-' + i, label: 'UI测试订单' + i, task_id: o.task_id, scope: 'transport', anchors: { recording: 10 }, frames: Array.from({ length: 41 }, (_, n) => ({ source_s: 10 + n / 10, sequence: n, stage: 'UI fixture only', car: [n / 40, i, 0], quaternion: [1,0,0,0], cargo: [n / 40,i,.2] })) })) };
  const recordings = [{ label: '历史K', url: '/workbench/j100-vision-result.json' }, { label: 'UI另一记录', url: '/workbench/ui-only-alternate.json' }];
  const alternateTiming = structuredClone(timing); alternateTiming.source_run_id = 'ui-alternate'; alternateTiming.cases.forEach(c => { c.task_id = 'ui-' + c.task_id; c.route.elapsed_s = 9.87; });
  const fixtureTiming = structuredClone(timing);
  fixtureTiming.cases.forEach(c => {
    c.start_wall_s = 100; c.end_wall_s = 104; c.task_elapsed_s = 4;
    c.spans = [{ id: 'fixture-stage', layer: 'observed_stage', label: 'UI测试阶段', start_wall_s: 101, end_wall_s: 103, duration_s: 2, start_source_s: 11, end_source_s: 13, evidence: 'Synthetic UI-only interval' }];
  });
  try {
    page.on('pageerror', e => result.errors.push(String(e)));
    await page.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url());
      if (!['GET','HEAD','OPTIONS'].includes(req.method())) { result.writes.push(url.pathname); return route.fulfill({ status: 405, json: {} }); }
      if (url.pathname === '/workbench/ui-only-alternate.json') return route.fulfill({ json: { ...summary, run_id: 'ui-alternate', recordings, orders: summary.orders.map(o => ({ ...o, task_id: 'ui-' + o.task_id, route_seconds: 9.87 })), assets: { timing: '/workbench/ui-only-alternate-timing.json' } } });
      if (url.pathname === '/workbench/ui-only-alternate-timing.json') return route.fulfill({ json: alternateTiming });
      if (fixture && url.pathname === '/workbench/j100-vision-result.json') return route.fulfill({ json: { ...summary, recordings, assets: { ...summary.assets, replay: '/workbench/ui-only-replay.json', video: missingReplay ? '/workbench/ui-only-missing.mp4' : null } } });
      if (fixture && url.pathname === '/workbench/j100-vision-timing.json') return route.fulfill({ json: fixtureTiming });
      if (url.pathname === '/workbench/ui-only-missing.mp4') return route.fulfill({ status: 404, body: '' });
      if (url.pathname === '/workbench/ui-only-replay.json') return route.fulfill(missingReplay ? { status: 404, json: {} } : { json: unknownReplay ? { ...replay, schema: 'editable', read_only: false, rescored: true } : replay });
      if (/^\/(?:api|coop-api|mission-api|voice-api|control|scene-validation|hardware-lab)\b/.test(url.pathname)) return route.fulfill({ status: 503, json: {} });
      return route.continue();
    });
    await page.goto(new URL('/results', base).href);
    const card = page.locator('#j100-vision-delivery'), panel = page.locator('#workbench-delivery-timing');
    await card.getByText('49.90 s', { exact: true }).waitFor();
    await card.getByRole('button', { name: '订单 A', exact: true }).click();
    await card.getByText('20.97 s', { exact: true }).waitFor();
    assert.ok(await card.getByText('位置回放尚未载入', { exact: true }).isVisible());
    await panel.getByText('20.968 s', { exact: true }).waitFor();
    result.checks.push('Actual historical A/B summary and timing selection stay aligned; deleted media explicitly unavailable');
    await card.screenshot({ path: path.join(args.output, 'vision-desktop.png') });
    await page.setViewportSize({ width: 390, height: 844 });
    await card.screenshot({ path: path.join(args.output, 'vision-mobile.png') });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    result.checks.push('390px viewport has no horizontal overflow');
    fixture = true; await page.reload();
    await card.getByRole('slider', { name: '视觉配送源时间' }).waitFor();
    await card.getByRole('button', { name: '播放视觉配送回放' }).click();
    await page.waitForFunction(() => Number(document.querySelector('#j100-vision-replay input[type=range]').value) > .3);
    await card.getByRole('button', { name: '暂停视觉配送回放' }).click();
    await panel.getByRole('button', { name: '完整任务', exact: true }).click();
    await panel.locator('.delivery-timing-row').filter({ hasText: 'UI测试阶段' }).click();
    await panel.getByRole('button', { name: '在回放中定位此阶段' }).click();
    assert.equal(await card.getByRole('slider', { name: '视觉配送源时间' }).inputValue(), '1');
    result.checks.push('Synthetic UI-only replay plays, pauses and seeks stage source time without interpolating physical data');
    await card.getByLabel('选择视觉配送成果').selectOption('/workbench/ui-only-alternate.json');
    await card.getByText('9.87 s', { exact: true }).waitFor(); await panel.getByText('9.870 s', { exact: true }).waitFor();
    assert.equal(await card.getByRole('link', { name: '下载成果摘要' }).getAttribute('href'), '/workbench/ui-only-alternate.json');
    await card.getByLabel('选择视觉配送成果').selectOption('/workbench/j100-vision-result.json');
    await card.getByRole('slider', { name: '视觉配送源时间' }).waitFor();
    result.checks.push('Separate record selection switches summary, task identities, timing source and download together');
    unknownReplay = true; await card.getByRole('button', { name: '刷新成果' }).click();
    await card.getByText('来源边界未确认；播放不代表执行或重新评分。', { exact: true }).waitFor();
    assert.ok((await card.locator('.vision-result-caption').innerText()).includes('已导入的展示采样'));
    result.checks.push('Unconfirmed replay provenance stays visible and is not certified as observed physical evidence');
    missingReplay = true; await card.getByRole('button', { name: '刷新成果' }).click();
    await card.getByText('位置回放尚未载入', { exact: true }).waitFor();
    await card.getByText('49.90 s', { exact: true }).waitFor();
    assert.ok((await card.innerText()).includes('HTTP 404'));
    await card.getByText('录像加载失败；成果摘要与可用的数据回放继续保留。', { exact: true }).waitFor();
    result.checks.push('Optional replay/video HTTP404 retain summary and explicit item errors');
    assert.deepEqual(result.writes, []); assert.deepEqual(result.errors, []); result.passed = true;
  } finally {
    fs.writeFileSync(path.join(args.output, 'ui-result.json'), JSON.stringify(result, null, 2)); await browser.close();
  }
  process.stdout.write(JSON.stringify(result) + '\n');
}
main().catch(e => { console.error(e); process.exitCode = 1; });
