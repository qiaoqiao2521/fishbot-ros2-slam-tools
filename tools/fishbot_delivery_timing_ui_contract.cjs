#!/usr/bin/env node
'use strict';
// Isolated UI checks; the served document and timing snapshot remain real HTTP assets.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

async function main() {
  const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, values) => {
    if (index % 2 === 0) pairs.push([value.replace(/^--/, ''), values[index + 1]]);
    return pairs;
  }, []));
  const base = new URL(args.base || 'http://127.0.0.1:5191');
  assert.equal(base.hostname, '127.0.0.1');
  assert.ok(args.output, 'Provide a private evidence output directory');
  fs.mkdirSync(args.output, { recursive: true, mode: 0o700 });
  const output = name => path.join(args.output, name);
  const result = { passed: false, checks: [], writes: [], page_errors: [], screenshots: [],
    scope: 'Historical timing UI only; no ROS execution or scoring; unrelated API GETs return explicitly offline.' };
  const browser = await chromium.launch({ headless: true,
    executablePath: args.chromium || process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || '/opt/google/chrome/chrome',
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, acceptDownloads: true });
  let failSnapshot = false;
  try {
    page.on('pageerror', error => result.page_errors.push(String(error)));
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        result.writes.push({ method: request.method(), path: url.pathname });
        return route.fulfill({ status: 405, json: { message: 'Isolated read-only UI test' } });
      }
      if (url.pathname === '/workbench/delivery-timing.json' && failSnapshot) return route.fulfill({ status: 404, json: {} });
      if (/^\/(?:api|coop-api|mission-api|voice-api|control|scene-validation|hardware-lab)\b/.test(url.pathname)) {
        return route.fulfill({ status: 503, json: { message: 'Isolated UI test: service offline' } });
      }
      return route.continue();
    });
    const response = await page.goto(new URL('/results', base).href);
    assert.equal(response.status(), 200);
    const panel = page.locator('#workbench-delivery-timing');
    await panel.getByText('119.794 s', { exact: true }).waitFor();
    assert.ok(await panel.getByText('0.206 s', { exact: true }).isVisible());
    assert.equal(await panel.locator('.delivery-timing-row').count(), 5);
    result.checks.push('served B route has original elapsed, margin and five disjoint child intervals');
    await panel.locator('.delivery-timing-row').filter({ hasText: '进场目标' }).click();
    assert.ok(await panel.getByText('fd31b33a409e47e7b9636c5634a98b82', { exact: true }).isVisible());
    assert.ok((await panel.locator('.delivery-timing-detail').innerText()).includes('89.251 s'));
    result.checks.push('native Goal UUID and interval details visible');
    await panel.screenshot({ path: output('desktop-b-route.png') }); result.screenshots.push('desktop-b-route.png');
    await panel.getByRole('button', { name: '完整任务', exact: true }).click();
    assert.ok(await panel.getByText('268.405 s', { exact: true }).isVisible());
    await panel.locator('.delivery-timing-row').filter({ hasText: '驶向工位' }).click();
    assert.ok((await panel.locator('.delivery-timing-detail').innerText()).includes('不能将采样边界当作精确事件'));
    result.checks.push('task axis includes egress and sampled-stage boundary uncertainty');
    await panel.getByRole('button', { name: '订单 A', exact: true }).click();
    await panel.getByRole('button', { name: '配送路线', exact: true }).click();
    assert.ok(await panel.getByText('34.883 s', { exact: true }).isVisible());
    await panel.locator('.delivery-timing-evidence summary').click();
    assert.ok((await panel.locator('.delivery-timing-evidence').innerText()).includes('缺 33 帧'));
    result.checks.push('A route and its three original sampling gaps retained');
    const chassis = page.locator('#workbench-chassis');
    assert.equal(await chassis.locator('[data-chassis]').count(), 3);
    assert.ok(await chassis.getByText('ROS 底盘已合并 · 仿真模型待接入', { exact: true }).isVisible());
    await chassis.screenshot({ path: output('desktop-chassis.png') }); result.screenshots.push('desktop-chassis.png');
    result.checks.push('one workbench exposes three chassis without promoting mecanum to accepted MuJoCo transport');
    await page.setViewportSize({ width: 390, height: 844 });
    await panel.scrollIntoViewIfNeeded();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    assert.ok(await panel.locator('.delivery-timing-scroll').evaluate(element => element.scrollWidth > element.clientWidth));
    await panel.screenshot({ path: output('mobile-a-route.png') }); result.screenshots.push('mobile-a-route.png');
    result.checks.push('390px layout has internal chart scroll and no page overflow');
    await chassis.screenshot({ path: output('mobile-chassis.png') }); result.screenshots.push('mobile-chassis.png');
    await panel.getByLabel('导入配送耗时 JSON').setInputFiles({ name: 'broken.json', mimeType: 'application/json', buffer: Buffer.from('{bad') });
    await panel.getByRole('alert').waitFor();
    assert.ok(await panel.getByText('34.883 s', { exact: true }).isVisible());
    result.checks.push('malformed local JSON leaves the last report intact');
    const original = await (await page.request.get(new URL('/workbench/delivery-timing.json', base).href)).json();
    const edited = { ...original, label: '人工补注 · UI验收' };
    await panel.getByLabel('导入配送耗时 JSON').setInputFiles({ name: 'edited.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(edited)) });
    await panel.getByText('人工补注 · UI验收', { exact: true }).waitFor();
    const downloadEvent = page.waitForEvent('download');
    await panel.getByRole('button', { name: '下载原始摘要 JSON' }).click();
    const download = await downloadEvent;
    await download.saveAs(output('downloaded-summary.json'));
    assert.equal(JSON.parse(fs.readFileSync(output('downloaded-summary.json'), 'utf8')).label, edited.label);
    result.checks.push('editable JSON import and download preserve the loaded summary');
    failSnapshot = true;
    await panel.getByRole('button', { name: '刷新报告', exact: true }).click();
    await panel.getByRole('alert').filter({ hasText: 'HTTP 404' }).waitFor();
    assert.ok(await panel.getByText(edited.label, { exact: true }).isVisible());
    result.checks.push('missing served snapshot is explicit and keeps existing report');
    assert.equal(result.writes.length, 0);
    assert.equal(result.page_errors.length, 0);
    result.checks.push('zero write requests and zero uncaught page errors');
    result.passed = true;
  } catch (error) {
    result.failure = String(error);
    await page.screenshot({ path: output('failure.png'), fullPage: true });
    throw error;
  } finally {
    await browser.close();
    result.browser_closed = true;
    fs.writeFileSync(output('browser-result.json'), JSON.stringify(result, null, 2) + '\n');
    console.log(JSON.stringify(result));
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
