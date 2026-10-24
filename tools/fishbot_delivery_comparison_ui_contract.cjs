#!/usr/bin/env node
'use strict';
// Isolated browser QA. Actual report HTTP is retained; motion services are offline.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

async function main() {
  const argv = process.argv.slice(2), args = {};
  for (let i = 0; i < argv.length; i += 2) args[argv[i].replace(/^--/, '')] = argv[i + 1];
  const base = new URL(args.base || 'http://127.0.0.1:5191');
  assert.equal(base.hostname, '127.0.0.1');
  assert.ok(args.output, 'Choose a private output directory');
  fs.mkdirSync(args.output, { recursive: true, mode: 0o700 });
  const result = { passed: false, checks: [], writes: [], page_errors: [],
    scope: 'Recorded comparison UI, not a new ROS run or score. Other APIs explicitly offline.' };
  const browser = await chromium.launch({ headless: true, executablePath: args.chromium || '/opt/google/chrome/chrome',
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, acceptDownloads: true });
  let failReport = false;
  try {
    page.on('pageerror', e => result.page_errors.push(String(e)));
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        result.writes.push({ method: request.method(), path: url.pathname });
        return route.fulfill({ status: 405, json: { message: 'Read-only QA' } });
      }
      if (url.pathname === '/workbench/continuous-comparison.json' && failReport)
        return route.fulfill({ status: 404, json: {} });
      if (/^\/(?:api|coop-api|mission-api|voice-api|control|scene-validation|hardware-lab)\b/.test(url.pathname))
        return route.fulfill({ status: 503, json: { message: 'Isolated QA: service offline' } });
      return route.continue();
    });
    const response = await page.goto(new URL('/regression', base).href);
    assert.equal(response.status(), 200);
    await page.getByRole('heading', { name: '配送回归', exact: true }).waitFor();
    await page.locator('.regression-viewport').nth(1).waitFor();
    const real = await (await page.request.get(new URL('/workbench/continuous-comparison.json', base).href)).json();
    assert.ok(real.runs.length >= 2 && real.read_only && real.rescored === false);
    const expected = real.view_bounds_xy;
    const bounds = `${expected[0]} ${-expected[3]} ${expected[2] - expected[0]} ${expected[3] - expected[1]}`;
    for (const svg of await page.locator('.regression-viewport svg[role=img]').all())
      assert.equal(await svg.getAttribute('viewBox'), bounds);
    result.checks.push('actual two-run report, same absolute world bounds in both viewports');
    assert.equal(await page.getByText('原独立评分未通过', { exact: true }).count(), 2);
    result.checks.push('both original R2 route failures remain failures');
    const viewport = page.locator('.regression-viewport').first();
    await viewport.locator('summary').click();
    assert.ok((await viewport.innerText()).includes(real.runs[0].task_id));
    assert.ok((await viewport.innerText()).includes(real.runs[0].episode_id));
    for (const action of real.runs[0].spans.filter(s => s.layer === 'native' && s.goal_id))
      assert.ok((await viewport.innerText()).includes(action.goal_id));
    result.checks.push('original task and episode identities visible');
    await page.getByRole('button', { name: '播放回放', exact: true }).click();
    await page.waitForFunction(() => Number.parseFloat(document.querySelector('.regression-timeline output').textContent) > .2);
    await page.getByRole('button', { name: '暂停回放', exact: true }).click();
    const before = await page.locator('.regression-timeline output').innerText();
    const slider = page.getByRole('slider', { name: '共享源时间轴' });
    await slider.focus(); await page.keyboard.press('ArrowRight');
    assert.notEqual(await page.locator('.regression-timeline output').innerText(), before);
    result.checks.push('shared source cursor plays, pauses and seeks without executing');
    await page.getByLabel('叠加另一回合').uncheck();
    assert.equal(await page.locator('[data-replay-ghost]').count(), 0);
    await page.getByLabel('叠加另一回合').check();
    assert.ok(await page.locator('[data-replay-ghost]').count() > 0);
    result.checks.push('ghost can be disabled without altering source coordinates');
    await page.getByLabel('时间锚点').selectOption('recording');
    assert.ok((await page.locator('.regression-timeline output').innerText()).startsWith('0.00'));
    await page.screenshot({ path: path.join(args.output, 'desktop.png'), fullPage: true });
    failReport = true;
    await page.getByRole('button', { name: '刷新报告', exact: true }).click();
    await page.getByRole('alert').waitFor();
    assert.ok((await page.getByRole('alert').innerText()).includes('404'));
    assert.equal(await page.locator('.regression-viewport').count(), 2);
    result.checks.push('404 keeps the previous report and its failures');
    const upload = page.getByLabel('导入配送对照 JSON');
    await upload.setInputFiles({ name: 'broken.json', mimeType: 'application/json', buffer: Buffer.from('{broken') });
    await page.getByRole('alert').waitFor();
    assert.equal(await page.locator('.regression-viewport').count(), 2);
    result.checks.push('malformed editable JSON preserves previous data');
    const edited = structuredClone(real); edited.same_checkpoint_id = false;
    await upload.setInputFiles({ name: 'edited.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(edited)) });
    await page.getByText('来源未满足同起点 A/B 对照', { exact: true }).waitFor();
    assert.ok(await page.getByLabel('叠加另一回合').isDisabled());
    assert.equal(await page.locator('.regression-viewport').count(), 2);
    result.checks.push('human metadata edits accepted; incompatible ghost is explicitly disabled');
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: '下载摘要', exact: true }).click();
    const download = await downloadPromise;
    const target = path.join(args.output, 'download.json'); await download.saveAs(target);
    assert.equal(JSON.parse(fs.readFileSync(target)).runs[0].frames[0].car[0], real.runs[0].frames[0].car[0]);
    result.checks.push('download retains original world coordinates');
    await page.setViewportSize({ width: 390, height: 980 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    await page.screenshot({ path: path.join(args.output, 'mobile.png'), fullPage: true });
    result.checks.push('390px stacked viewports without page overflow');
    failReport = false;
    await page.getByRole('button', { name: '成果验收', exact: true }).click();
    await page.getByRole('button', { name: '配送回归', exact: true }).click();
    await page.locator('.regression-viewport').nth(1).waitFor();
    assert.deepEqual(result.writes, []); assert.deepEqual(result.page_errors, []);
    result.checks.push('refresh, playback, import and page navigation issue zero motion writes');
    result.passed = true;
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(args.output, 'result.json'), JSON.stringify(result, null, 2));
  }
  console.log(JSON.stringify(result));
  if (!result.passed) process.exitCode = 1;
}
main().catch(e => { console.error(e); process.exitCode = 1; });
