// Native 3D editing and real EGO preview. Flight task writes are always blocked.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const upstream = createRequire(path.join(__dirname, '../workbench/package.json'));
const { chromium, expect } = upstream('@playwright/test');
const { PNG } = upstream('pngjs');
const base = process.env.STATION_TEST_URL ?? 'http://127.0.0.1:5187';
const output = process.env.DRONE_QA_OUTPUT ?? path.join(__dirname, 'output/drone-3d-plan');
fs.mkdirSync(output, { recursive: true });
const result = { passed: false, checks: [], writes: [], errors: [], plans: [] };
const save = () => fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(result, null, 2));
const checked = name => { result.checks.push(name); save(); console.log(name); };

// Locate an actually rendered solid-color object or native gizmo handle.
function component(bytes, color) {
  const png = PNG.sync.read(bytes);
  const visited = new Uint8Array(png.width * png.height);
  let largest = [];
  for (let index = 0; index < visited.length; index++) {
    if (visited[index]) continue;
    visited[index] = 1;
    if (!color(...png.data.subarray(index * 4, index * 4 + 4))) continue;
    const queue = [index];
    for (let cursor = 0; cursor < queue.length; cursor++) {
      const current = queue[cursor], x = current % png.width, y = Math.floor(current / png.width);
      for (const [dx, dy] of [[-1,-1],[0,-1],[1,-1],[-1,0],[1,0],[-1,1],[0,1],[1,1]]) {
        const nx = x + dx, ny = y + dy, next = ny * png.width + nx;
        if (nx < 0 || ny < 0 || nx >= png.width || ny >= png.height || visited[next]) continue;
        visited[next] = 1;
        if (color(...png.data.subarray(next * 4, next * 4 + 4))) queue.push(next);
      }
    }
    if (queue.length > largest.length) largest = queue;
  }
  assert(largest.length > 8, 'The rendered object/handle must be visibly present');
  return {
    count: largest.length,
    x: largest.reduce((sum, index) => sum + index % png.width, 0) / largest.length,
    y: largest.reduce((sum, index) => sum + Math.floor(index / png.width), 0) / largest.length,
  };
}
function yellowPixels(bytes) {
  const png = PNG.sync.read(bytes);
  let count = 0;
  for (let i = 0; i < png.data.length; i += 4) {
    if (png.data[i] > 190 && png.data[i + 1] > 150 && png.data[i + 2] < 100) count++;
  }
  return count;
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/usr/bin/google-chrome', headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1100 }, acceptDownloads: true });
  const page = await context.newPage();
  page.on('pageerror', error => { result.errors.push(error.message); save(); });
  await context.route(/\/api\/(?:drone|so101)\/tasks(?:[/?]|$)/, async route => {
    if (!['GET', 'HEAD'].includes(route.request().method())) {
      result.writes.push(route.request().url());
      save();
      return route.abort('blockedbyclient');
    }
    return route.continue();
  });
  const panel = page.getByTestId('panel-mouseenter-container RobotStation!dronestation');
  const scene = page.getByTestId('panel-mouseenter-container 3D!dronelive');
  const canvas = scene.locator('canvas').first();
  const exportDraft = async name => {
    const pending = page.waitForEvent('download');
    await panel.getByRole('button', { name: '导出 JSON', exact: true }).click();
    const file = path.join(output, name);
    await (await pending).saveAs(file);
    return JSON.parse(fs.readFileSync(file, 'utf8')).station;
  };
  const preview = async () => {
    const pending = page.waitForResponse(response => response.url() === `${base}/api/drone/plans` && response.request().method() === 'POST');
    await panel.getByRole('button', { name: 'EGO 起飞前预演', exact: true }).click();
    const submitted = await pending;
    assert(submitted.ok());
    let task = await submitted.json();
    await expect.poll(async () => {
      const response = await page.request.get(`${base}/api/drone/plans/${task.id}`);
      assert(response.ok());
      task = await response.json();
      return ['succeeded', 'failed', 'cancelled'].includes(task.status);
    }, { timeout: 240000, intervals: [1000] }).toBe(true);
    result.plans.push(task);
    save();
    assert.equal(task.status, 'succeeded', task.message);
    assert.equal(task.report.flight_control, false);
    assert.equal(task.report.valid, true, task.report.reason);
    assert(task.report.points.length > 3);
    await expect(panel.getByRole('region', { name: 'EGO 起飞前预演' })).toContainText('当前草稿预演有效');
    return task;
  };
  const readPosition = async () => Promise.all(['X', 'Y', 'Z'].map(async axis => Number(await panel.getByLabel(`${axis}（m）`, { exact: true }).inputValue())));
  const checkScenePose = async (station, id, label) => {
    const world = nodeId => {
      const node = station.nodes.find(item => item.id === nodeId);
      const parent = node.parent === 'world' ? [0, 0, 0] : world(node.parent);
      return node.position.map((value, index) => value + parent[index]);
    };
    const expected = world(id);
    let state, entity;
    await expect.poll(async () => {
      const response = await page.request.get(`${base}/api/drone/scene-state`);
      assert(response.ok());
      state = await response.json();
      entity = state.scene.entities.find(item => item.metadata?.some(meta => meta.key === 'station_node_id' && meta.value === id));
      const pose = entity?.cubes[0]?.pose.position;
      return pose ? [pose.x, pose.y, pose.z] : undefined;
    }, { timeout: 15000 }).toEqual(expected);
    result[label] = { local: station.nodes.find(item => item.id === id).position, expectedWorld: expected, sceneWorld: entity.cubes[0].pose.position };
    save();
  };
  const dragRedHandle = async name => {
    const box = await canvas.boundingBox();
    const bytes = await canvas.screenshot({ path: path.join(output, `${name}-before.png`) });
    const handle = component(bytes, (r, g, b, a) => a > 200 && r > 220 && g < 45 && b < 45);
    result[`${name}Handle`] = handle;
    await page.mouse.move(box.x + handle.x, box.y + handle.y);
    await page.mouse.down();
    await page.mouse.move(box.x + handle.x + 45, box.y + handle.y, { steps: 12 });
    await page.mouse.up();
    await expect(panel).toContainText('三维变换已写入草稿');
  };
  try {
    await page.goto(`${base}/drone-station`);
    await expect(panel.getByRole('button', { name: '复制为新任务', exact: true })).toBeEnabled({ timeout: 90000 });
    await panel.getByRole('button', { name: '编辑预览', exact: true }).click();
    await expect(panel.getByRole('button', { name: '起飞并执行仿真', exact: true })).toBeDisabled();
    await panel.getByRole('button', { name: '添加障碍', exact: true }).click();
    await panel.getByLabel('Y（m）', { exact: true }).fill('-1.5');
    if (process.env.DRONE_QA_GESTURE_CHECK === '1') {
      await panel.getByRole('combobox', { name: /^障碍运动/ }).click();
      await page.getByRole('option', { name: '往返移动立柱', exact: true }).click();
      await panel.getByRole('combobox', { name: /^障碍启用状态/ }).click();
      await page.getByRole('option', { name: '停用，保留草稿配置', exact: true }).click();
      await expect.poll(async () => {
        const state = await (await page.request.get(`${base}/api/drone/scene-state`)).json();
        return state.scene.entities.filter(item => item.id.startsWith('obstacle-')).length;
      }, { timeout: 15000 }).toBe(0);
      const disabledCanvas = await canvas.screenshot({ path: path.join(output, 'disabled-box.png') });
      assert.throws(() => component(disabledCanvas, (r, g, b, a) => a > 200 && r > 220 && g < 45 && b < 45));
      await panel.getByRole('combobox', { name: /^障碍启用状态/ }).click();
      await page.getByRole('option', { name: '启用，参与预演和碰撞检查', exact: true }).click();
      checked('disabled-moving-box-keeps-settings-but-leaves-the-scene');
    }
    const initial = await exportDraft('initial.json');
    const boxNode = initial.nodes.find(node => node.kind === 'obstacle');
    assert(boxNode);
    await panel.locator('[aria-label="工作站对象树"]').getByRole('button', { name: /航点 1/ }).click();
    await expect.poll(async () => {
      try { return component(await canvas.screenshot(), (r, g, b, a) => a > 200 && r > 150 && g > 65 && g < 165 && b < 70).count; }
      catch { return 0; }
    }, { timeout: 30000 }).toBeGreaterThan(100);
    const orange = component(await canvas.screenshot(), (r, g, b, a) => a > 200 && r > 150 && g > 65 && g < 165 && b < 70);
    const bounds = await canvas.boundingBox();
    await page.mouse.click(bounds.x + orange.x, bounds.y + orange.y);
    await expect(panel.getByLabel('对象名称', { exact: true })).toHaveValue(boxNode.name);
    checked('native-3d-picking-selects-the-editable-box');
    if (process.env.DRONE_QA_GESTURE_CHECK === '1') {
      for (const event of ['pointercancel', 'blur']) {
        const before = await readPosition();
        const bounds = await canvas.boundingBox();
        const handle = component(await canvas.screenshot(), (r, g, b, a) => a > 200 && r > 220 && g < 45 && b < 45);
        await page.mouse.move(bounds.x + handle.x, bounds.y + handle.y);
        await page.mouse.down();
        await page.mouse.move(bounds.x + handle.x + 25, bounds.y + handle.y, { steps: 6 });
        if (event === 'pointercancel') await canvas.dispatchEvent('pointercancel', { pointerId: 1, pointerType: 'mouse', button: 0 });
        else await page.evaluate(() => window.dispatchEvent(new Event('blur')));
        await page.mouse.up();
        await expect.poll(readPosition).toEqual(before);
        await checkScenePose(initial, boxNode.id, `after-${event}-pose`);
      }
      // Blank-space orbit after a cancelled handle must work. Compare scene
      // pixels with the mouse outside so hover colors cannot satisfy this.
      const bounds = await canvas.boundingBox();
      await page.mouse.move(20, 20);
      const beforeCamera = PNG.sync.read(await canvas.screenshot());
      await page.mouse.move(bounds.x + 70, bounds.y + 150);
      await page.mouse.down({ button: 'right' });
      await page.mouse.move(bounds.x + 110, bounds.y + 160, { steps: 8 });
      await page.mouse.up({ button: 'right' });
      await page.mouse.move(20, 20);
      await expect.poll(async () => {
        const afterCamera = PNG.sync.read(await canvas.screenshot());
        let changed = 0;
        for (let i = 0; i < beforeCamera.data.length; i += 4) {
          if (Math.abs(beforeCamera.data[i] - afterCamera.data[i]) + Math.abs(beforeCamera.data[i + 1] - afterCamera.data[i + 1]) + Math.abs(beforeCamera.data[i + 2] - afterCamera.data[i + 2]) > 60) changed++;
        }
        return changed;
      }).toBeGreaterThan(2000);
      checked('pointercancel-and-blur-discard-uncommitted-drag-and-release-orbit');
    }
    await checkScenePose(initial, boxNode.id, 'beforeDragPose');
    const beforePosition = await readPosition();
    await dragRedHandle('translate');
    await expect.poll(readPosition).not.toEqual(beforePosition);
    const translatedPosition = await readPosition();
    await checkScenePose(await exportDraft('translated.json'), boxNode.id, 'afterDragPose');
    await panel.getByRole('button', { name: '撤销', exact: true }).click();
    await expect.poll(readPosition).toEqual(beforePosition);
    await panel.getByRole('button', { name: '重做', exact: true }).click();
    await expect.poll(readPosition).toEqual(translatedPosition);
    checked('one-native-drag-is-one-undoable-draft-edit');
    await scene.getByRole('button', { name: '拖动障碍尺寸', exact: true }).click();
    const beforeWidth = Number(await panel.getByLabel('宽（m）', { exact: true }).inputValue());
    await dragRedHandle('scale');
    await expect.poll(async () => Number(await panel.getByLabel('宽（m）', { exact: true }).inputValue())).not.toBe(beforeWidth);
    const edited = await exportDraft('edited.json');
    assert(edited.nodes.find(node => node.id === boxNode.id).size.every(value => value > 0));
    assert.deepEqual(edited.nodes.find(node => node.id === boxNode.id).motion, boxNode.motion);
    await page.screenshot({ path: path.join(output, 'edited-desktop.png'), fullPage: true });
    checked('native-transform-controls-translate-and-scale-write-the-draft');
    await panel.getByRole('button', { name: '保存草稿', exact: true }).click();
    await expect(panel).toContainText('草稿与当前布局已保存');
    await page.reload();
    await expect(panel.getByRole('button', { name: '复制为新任务', exact: true })).toBeEnabled({ timeout: 60000 });
    assert.deepEqual(await exportDraft('reloaded.json'), edited);
    checked('3d-edits-persist-exactly-after-save-and-refresh');
    if (process.env.DRONE_QA_EDIT_ONLY === '1') {
      if (process.env.DRONE_QA_GESTURE_CHECK === '1') {
        const mobile = await context.newPage();
        mobile.on('pageerror', error => { result.errors.push(error.message); save(); });
        await mobile.setViewportSize({ width: 390, height: 844 });
        await mobile.goto(`${base}/drone-station-mobile`);
        const narrow = mobile.getByTestId('panel-mouseenter-container RobotStation!dronestation');
        await expect(narrow.getByRole('button', { name: '复制为新任务', exact: true })).toBeVisible({ timeout: 90000 });
        await mobile.screenshot({ path: path.join(output, 'mobile-editor.png'), fullPage: true });
        for (const label of ['高度上限（m）', '到点误差上限（m）', '最小机体净空（m）', '最低巡航速度（m/s）', '深度丢帧比例（0–1）', '深度延迟（ms）', '随机种子']) {
          const field = narrow.getByLabel(label, { exact: true });
          await field.scrollIntoViewIfNeeded();
          const bounds = await field.boundingBox();
          assert(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 391, `${label} must fit the mobile width`);
        }
        await mobile.screenshot({ path: path.join(output, 'mobile-acceptance-sensors.png'), fullPage: true });
        for (const name of ['EGO 起飞前预演', '起飞并执行仿真', '停止并安全返回降落']) {
          const button = narrow.getByRole('button', { name, exact: true });
          await button.scrollIntoViewIfNeeded();
          const bounds = await button.boundingBox();
          assert(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 391, `${name} must fit the mobile width`);
        }
        assert(await mobile.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
        assert(await narrow.evaluate(element => element.scrollWidth <= element.clientWidth));
        await mobile.screenshot({ path: path.join(output, 'mobile-preview-actions.png'), fullPage: true });
        checked('390px-acceptance-sensors-and-preview-actions-without-horizontal-overflow');
        await mobile.close();
      }
      assert.deepEqual(result.writes, []);
      assert.deepEqual(result.errors, []);
      result.scope = '3d-edit-only';
      result.passed = true;
      save();
      return;
    }
    await panel.locator('[aria-label="工作站对象树"]').getByRole('button', { name: /航点 1/ }).click();
    const beforePlanYellow = yellowPixels(await canvas.screenshot());
    const first = await preview();
    await expect.poll(async () => yellowPixels(await canvas.screenshot()), { timeout: 30000 }).toBeGreaterThan(beforePlanYellow + 20);
    result.yellowPixels = { before: beforePlanYellow, planned: yellowPixels(await canvas.screenshot()) };
    await page.screenshot({ path: path.join(output, 'valid-plan.png'), fullPage: true });
    checked('native-3d-displays-the-real-planner-yellow-curve');
    await page.reload();
    await expect(panel).toContainText(`预演 ID：${first.id}`, { timeout: 60000 });
    await expect(panel.getByRole('button', { name: '起飞并执行仿真', exact: true })).toBeEnabled();
    await panel.locator('[aria-label="工作站对象树"]').getByRole('button', { name: new RegExp(boxNode.name) }).click();
    await panel.getByLabel('Y（m）', { exact: true }).fill('-2');
    await expect(panel).toContainText('草稿已修改，旧预演已过期');
    await expect(panel.getByRole('button', { name: '起飞并执行仿真', exact: true })).toBeDisabled();
    const second = await preview();
    assert.notEqual(second.id, first.id);
    checked('real-ego-preview-refresh-invalidation-and-replan-without-flight');
    assert.deepEqual(result.writes, []);
    assert.deepEqual(result.errors, []);
    result.passed = true;
    save();
    console.log(JSON.stringify({ passed: true, checks: result.checks, output }));
  } catch (error) {
    result.failure = error.stack ?? error.message;
    await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
    save();
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
