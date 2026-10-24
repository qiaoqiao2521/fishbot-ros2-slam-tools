// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// Project-local acceptance of real historical data. Never starts a flight.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const upstream = createRequire(path.join(__dirname, '../workbench/package.json'));
const { chromium, expect } = upstream('@playwright/test');
const base = process.env.STATION_TEST_URL ?? 'http://127.0.0.1:5187';
const output = process.env.DRONE_QA_OUTPUT ?? path.join(__dirname, 'output/drone-diagnostics');
fs.mkdirSync(output, { recursive: true });
const result = { passed: false, checks: [], errors: [], writes: [], websockets: [], screenshots: [] };
const save = () => fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
const checked = name => { result.checks.push(name); save(); console.log(name); };
(async () => {
  let browser;
  try {
    const taskId = process.env.DRONE_DIAGNOSTIC_ID;
    assert(taskId, 'Set DRONE_DIAGNOSTIC_ID to an existing historical flight ID');
    const response = await fetch(`${base}/api/drone/diagnostics/${taskId}`);
    assert(response.ok, `Original diagnostics HTTP ${response.status}`);
    const evidence = await response.json();
    result.original = evidence;
    assert.equal(evidence.passed, false, 'This acceptance exercises a recorded failed flight');
    assert(evidence.primary_failure?.simulation_s > evidence.recording.start_s);
    browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', headless: true,
      args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
    for (const mobile of [false, true]) {
      const context = await browser.newContext({ viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
      const page = await context.newPage();
      page.on('pageerror', error => { result.errors.push(error.message); save(); });
      page.on('websocket', socket => { result.websockets.push(socket.url()); save(); });
      await page.route('**/api/**', async route => {
        if (!['GET', 'HEAD'].includes(route.request().method())) {
          result.writes.push({ method: route.request().method(), url: route.request().url() });
          save(); await route.abort(); return;
        }
        await route.continue();
      });
      await page.goto(`${base}/drone-diagnostics?taskId=${taskId}${mobile ? '&mobile=1' : ''}`);
      const panel = page.getByTestId('panel-mouseenter-container DroneDiagnostics!diagnostics');
      const timestamp = page.getByTestId('PlaybackTime-text').locator('input');
      await expect(panel).toContainText(taskId, { timeout: 90000 });
      await expect(panel).toContainText(`高度最高 ${evidence.maximum_altitude_m.toFixed(6)}`);
      await expect(panel).toContainText('原任务：未通过');
      await expect(panel).toContainText('青：备份未记录');
      await expect(page.getByTestId('panel-mouseenter-container RobotStation!dronestation')).toHaveCount(0);
      checked(`${mobile ? 'mobile' : 'desktop'}-original-id-final-failure-and-missing-backup`);
      const jump = panel.getByRole('button', { name: /^定位首发故障/ });
      await jump.click();
      await expect.poll(async () => Number(await timestamp.inputValue()), { timeout: 15000 }).toBeCloseTo(evidence.primary_failure.simulation_s, 3);
      await expect(panel).toContainText(`仿真时间 ${evidence.primary_failure.simulation_s.toFixed(3)}`);
      const scene = page.getByTestId('panel-mouseenter-container 3D!dronelive');
      await expect(scene.locator('canvas').first()).toBeVisible();
      await page.waitForLoadState('networkidle');
      // Native Plot prefetch runs in a worker after range reads; allow the 26 MiB fixture to fill.
      await page.waitForTimeout(7000);
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      const shot = path.join(output, mobile ? 'mobile-failure.png' : 'desktop-failure.png');
      await page.screenshot({ path: shot, fullPage: true }); result.screenshots.push(shot); save();
      checked(`${mobile ? 'mobile' : 'desktop'}-failure-button-seeks-native-clock-and-3d`);
      const back = Math.max(evidence.recording.start_s, evidence.primary_failure.simulation_s - 5);
      await timestamp.fill(back.toFixed(9)); await timestamp.press('Enter'); await timestamp.blur();
      await expect(panel).toContainText(`仿真时间 ${back.toFixed(3)}`);
      await page.getByTestId('play-button').click();
      await expect.poll(async () => Number(await timestamp.inputValue()), { timeout: 15000 }).toBeGreaterThan(back + .1);
      await page.getByTestId('play-button').click();
      await jump.click();
      await expect(panel).toContainText(`仿真时间 ${evidence.primary_failure.simulation_s.toFixed(3)}`);
      checked(`${mobile ? 'mobile' : 'desktop'}-rewind-play-pause-and-seek-retain-source-id`);
      await panel.getByRole('combobox', { name: '筛选事件' }).click();
      await page.getByRole('option', { name: '候选碰撞', exact: true }).click();
      const unknown = panel.getByRole('button', { name: /^无绝对时刻/ });
      await expect(unknown).toHaveCount(evidence.unaligned_events);
      if (evidence.unaligned_events) await expect(unknown.first()).toBeDisabled();
      await panel.getByText('通道与证据边界', { exact: true }).click();
      await expect(panel).toContainText('非全帧延迟统计');
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'No page horizontal overflow');
      checked(`${mobile ? 'mobile' : 'desktop'}-unaligned-events-disabled-and-source-limits-visible`);
      await context.close();
    }
    assert.deepEqual(result.errors, []);
    assert.deepEqual(result.writes, []);
    assert.deepEqual(result.websockets, []);
    checked('zero-control-requests-and-zero-live-connections');
    result.passed = true; save();
  } catch (error) {
    result.error = error.stack; save(); throw error;
  } finally { await browser?.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
