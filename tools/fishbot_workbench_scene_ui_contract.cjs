#!/usr/bin/env node
'use strict';

// Isolated Playwright fixtures. No API request or action reaches a ROS service.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function argumentsFrom(argv) {
  const options = { base: 'http://127.0.0.1:5182', domain: 127, duration: 1800, diagnose: 0, mode: 'development', graphics: 'software',
    chromium: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || '/opt/google/chrome/chrome' };
  for (let i = 0; i < argv.length; i += 2) {
    assert.ok(['--base', '--domain', '--output', '--chromium', '--duration', '--diagnose', '--mode', '--graphics', '--dist', '--build-receipt'].includes(argv[i]), `Unknown option: ${argv[i]}`);
    assert.ok(argv[i + 1], `Missing ${argv[i]}`); options[argv[i].slice(2)] = argv[i + 1];
  }
  const url = new URL(options.base);
  assert.ok(url.protocol === 'http:' && url.hostname === '127.0.0.1' && url.port && url.pathname === '/' && !url.search && !url.hash && !url.username, 'Use an explicit loopback origin');
  options.base = url.origin; options.domain = Number(options.domain); options.duration = Number(options.duration); options.diagnose = Number(options.diagnose);
  assert.ok(Number.isInteger(options.domain) && options.domain > 0 && options.domain <= 232);
  assert.ok(options.duration === 0 || options.duration === 1800, 'Duration is 0 (preflight) or 1800 seconds');
  assert.ok(options.diagnose === 0 || options.diagnose === 20, 'Diagnostic window is 0 or 20 seconds');
  assert.ok(options.mode === 'development' || options.mode === 'production', 'Explicit mode is development or production');
  graphicsLaunchOptions(options.graphics);
  assert.ok(options.mode === 'production' ? options.dist && options['build-receipt'] : !options.dist && !options['build-receipt'], 'Production requires a sealed dist and build receipt; development cannot carry them');
  if (options.mode === 'production') {
    options.dist = fs.realpathSync(options.dist); options.buildReceipt = fs.realpathSync(options['build-receipt']);
    validateProductionBuild(options.dist, options.buildReceipt);
  }
  assert.ok(options.output, 'Provide a fresh private output directory');
  const repository = fs.realpathSync(path.join(__dirname, '..')), requested = path.resolve(options.output);
  assert.ok(requested !== repository && !requested.startsWith(repository + path.sep), 'Evidence stays outside Git');
  fs.mkdirSync(requested, { recursive: true, mode: 0o700 }); options.output = fs.realpathSync(requested);
  assert.ok(!options.output.startsWith(repository + path.sep));
  assert.equal(fs.statSync(options.output).mode & 0o077, 0); assert.equal(fs.readdirSync(options.output).length, 0, 'Preserve previous evidence');
  return options;
}
async function until(read, predicate, name, milliseconds = 20000) {
  const deadline = Date.now() + milliseconds; let value;
  while (Date.now() < deadline) { value = await read(); if (predicate(value)) return value; await sleep(80); }
  throw new Error(`Deadline ${name}: ${JSON.stringify(value)}`);
}
function sourceManifest() {
  const root = path.resolve(__dirname, '..'), front = 'apps/fishbot-control-station/frontend';
  const files = ['tools/fishbot_workbench_scene_ui_contract.cjs', `${front}/package.json`, `${front}/package-lock.json`,
    ...['App.tsx', 'components/radar/radar-workbench-page.tsx', 'components/workspace/workspace-surface.tsx',
      'components/radar/radar-viewport.tsx', 'components/radar/radar-visual.ts', 'components/radar/radar-visual.test.ts',
      'components/workspace/workspace-desktop.tsx', 'components/workspace/workspace-visibility.ts', 'components/workspace/workspace.css',
      'hooks/use-station-bootstrap.ts', 'store/station-store.ts', 'lib/runtime-context.ts', 'lib/api.ts', 'lib/station-validation.ts'].map(s => `${front}/src/${s}`)];
  for (const name of fs.readdirSync(path.join(root, front, 'src/lib'))) if (/^scene.*\.ts$/.test(name)) files.push(`${front}/src/lib/${name}`);
  for (const name of fs.readdirSync(path.join(root, front, 'src/components/scene'))) files.push(`${front}/src/components/scene/${name}`);
  function collect(folder) {
    for (const entry of fs.readdirSync(path.join(root, folder), { withFileTypes: true })) {
      const name = `${folder}/${entry.name}`
      if (entry.isDirectory()) collect(name)
      else if (entry.isFile()) files.push(name)
      else assert.fail(`Source entry is not a regular file/directory: ${name}`)
    }
  }
  collect(`${front}/src`); collect(`${front}/public`)
  for (const name of fs.readdirSync(path.join(root, front))) if (/^(?:.*config.*\.(?:[cm]?js|ts|json)|index\.html)$/.test(name)) files.push(`${front}/${name}`)
  return Object.fromEntries([...new Set(files)].sort().map(name => [name, crypto.createHash('sha256').update(fs.readFileSync(path.join(root, name))).digest('hex')]));
}
/** A production receipt binds a fresh build's before/after source to every
 * output byte. These helpers never invoke a builder, server, browser or API.
 */
function sha256(bytes) { return crypto.createHash('sha256').update(bytes).digest('hex'); }
function privateReceiptPath(requested) {
  const target = path.resolve(requested), parent = fs.realpathSync(path.dirname(target));
  const repository = fs.realpathSync(path.join(__dirname, '..'));
  assert.ok(parent !== repository && !parent.startsWith(repository + path.sep), 'Build receipts stay outside Git');
  assert.equal(fs.statSync(parent).mode & 0o077, 0, 'Build receipt parent must be private');
  assert.ok(!fs.existsSync(target), 'Preserve the existing build receipt');
  return path.join(parent, path.basename(target));
}
function distManifest(directory) {
  const root = fs.realpathSync(directory), files = {}, stack = ['']; let bytes = 0;
  assert.ok(fs.statSync(root).isDirectory(), 'Production dist must be a directory');
  while (stack.length) {
    const folder = stack.pop();
    for (const item of fs.readdirSync(path.join(root, folder), { withFileTypes: true })) {
      const name = folder ? `${folder}/${item.name}` : item.name, full = path.join(root, name);
      assert.ok(!item.isSymbolicLink(), 'Production assets cannot escape through symlinks');
      if (item.isDirectory()) { stack.push(name); continue; }
      assert.ok(item.isFile(), 'Production assets must be regular files');
      const info = fs.statSync(full); bytes += info.size;
      assert.ok(Object.keys(files).length < 2048 && bytes <= 64 * 1024 * 1024, 'Bound the complete production artifact inventory');
      files[name] = sha256(fs.readFileSync(full));
    }
  }
  assert.ok(Object.hasOwn(files, 'index.html'), 'Production dist lacks index.html');
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8').replace(/<!--[\s\S]*?-->/g, '');
  const indexReferences = [];
  for (const tag of html.matchAll(/<(?:script|link)\b[^>]*>/gi)) {
    const attribute = /\b(?:src|href)\s*=\s*(["'])([^"']+)\1/i.exec(tag[0]);
    if (!attribute) continue;
    assert.ok(!attribute[2].includes('\\') && !/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(attribute[2].trim()), 'Index references must be local relative/root paths');
    const url = new URL(attribute[2], 'http://production.invalid/');
    assert.equal(url.origin, 'http://production.invalid', 'Index must reference same-origin production assets');
    assert.ok(!url.search && !url.hash && !url.username && !url.password, 'Index asset references must be immutable plain paths');
    const name = decodeURIComponent(url.pathname.slice(1));
    assert.ok(name && Object.hasOwn(files, name), `Index references absent production asset: ${name}`);
    indexReferences.push({ path: name, sha256: files[name] });
  }
  assert.ok(indexReferences.some(value => /\.js$/.test(value.path)), 'Production index must reference a built JS entry');
  return { directory: root, files: Object.fromEntries(Object.entries(files).sort(([a], [b]) => a.localeCompare(b))),
    index_references: indexReferences.sort((a, b) => a.path.localeCompare(b.path)), total_bytes: bytes };
}
function freezeBuildSource(output, directory) {
  assert.ok(typeof directory === 'string' && directory.length, 'Declare a fresh private dist before building');
  const plannedDist = privateReceiptPath(directory);
  const file = privateReceiptPath(output), value = { schema_version: 1, source_files: sourceManifest(), planned_dist: plannedDist, captured_epoch: Date.now() / 1000 };
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n', { flag: 'wx', mode: 0o600 }); return value;
}
function sealProductionBuild(sourceFile, directory, output) {
  const file = privateReceiptPath(output), before = JSON.parse(fs.readFileSync(sourceFile, 'utf8'));
  assert.equal(before.schema_version, 1); assert.deepEqual(sourceManifest(), before.source_files, 'Build source changed after its capture');
  assert.equal(fs.realpathSync(directory), before.planned_dist, 'Build output differs from the declared fresh dist');
  const dist = distManifest(directory), after = sourceManifest();
  assert.deepEqual(after, before.source_files, 'Source changed while sealing the production artifact');
  const value = { schema_version: 1, mode: 'production', source_start: before.source_files, source_end: after,
    dist, source_capture_epoch: before.captured_epoch, sealed_epoch: Date.now() / 1000 };
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n', { flag: 'wx', mode: 0o600 }); return value;
}
function validateProductionBuild(directory, receiptFile) {
  assert.equal(fs.statSync(receiptFile).mode & 0o077, 0, 'Build receipt must be private');
  assert.ok(fs.statSync(receiptFile).size <= 1024 * 1024, 'Bound the production build receipt');
  const receipt = JSON.parse(fs.readFileSync(receiptFile, 'utf8'));
  assert.equal(receipt.schema_version, 1); assert.equal(receipt.mode, 'production');
  assert.deepEqual(receipt.source_start, receipt.source_end, 'Build source changed during compilation');
  assert.deepEqual(sourceManifest(), receipt.source_end, 'Current source differs from the sealed production build');
  const dist = distManifest(directory); assert.deepEqual(dist, receipt.dist, 'Production artifact differs from its sealed build');
  return { receipt_file: fs.realpathSync(receiptFile), receipt_sha256: sha256(fs.readFileSync(receiptFile)), ...receipt };
}
function executedSourceManifest(options) {
  const files = sourceManifest();
  if (options.mode === 'production') {
    for (const [name, hash] of Object.entries(distManifest(options.dist).files)) files[`@production-dist/${name}`] = hash;
    files['@production-build-receipt'] = sha256(fs.readFileSync(options.buildReceipt));
  }
  return files;
}
function productionAssetPath(pathname, inventory) {
  const spa = new Set(['/', '/radar', '/results', '/workbench', '/simulation', '/cooperation']);
  const name = spa.has(pathname) ? 'index.html' : decodeURIComponent(pathname.slice(1));
  assert.ok(Object.hasOwn(inventory.files, name), `Request is absent from the frozen production artifact: ${pathname}`);
  return name;
}
function verifyProductionAsset(name, inventory, body, status) {
  assert.ok(Object.hasOwn(inventory.files, name), `Production asset absent from frozen inventory: ${name}`);
  assert.equal(status, 200, `Production asset HTTP status: ${name}`);
  const actual = sha256(body), expected = inventory.files[name];
  assert.equal(actual, expected, `Served production bytes differ from frozen dist: ${name}`);
  return { expected_sha256: expected, received_sha256: actual };
}
/** Keep the original intercepted request's HTTP body alive until verification
 * and fulfillment finish. A worker's later destruction cannot discard this
 * APIResponse; every acquired response is disposed, including rejected ones.
 */
async function forwardProductionAsset(route, origin, inventory, record) {
  const request = route.request(), requested = new URL(request.url());
  Object.assign(record, { url: request.url(), resource_type: request.resourceType(), clock: 'node_performance_now',
    phase: 'declare', started_ms: performance.now(), fulfilled: false, disposed: false });
  let response, result, failure;
  try {
    assert.equal(requested.origin, origin, 'Production request must remain same-origin');
    assert.equal(request.method(), 'GET', 'Production asset must use the original GET');
    const name = productionAssetPath(requested.pathname, inventory); record.asset = name;
    record.phase = 'fetch'; record.fetch_started_ms = performance.now();
    response = await route.fetch({ maxRedirects: 0 }); record.fetch_finished_ms = performance.now();
    record.http_status = response.status(); record.response_url = response.url();
    record.phase = 'status';
    assert.equal(record.response_url, request.url(), 'Original production asset URL changed');
    assert.equal(record.http_status, 200, `Production asset HTTP status: ${name}; redirects are not followed`);
    record.phase = 'read'; record.read_started_ms = performance.now();
    const body = await response.body(); record.read_finished_ms = performance.now(); record.bytes = body.length;
    record.phase = 'verify'; const verified = verifyProductionAsset(name, inventory, body, record.http_status);
    Object.assign(record, verified, { verified: true });
    record.phase = 'fulfill'; record.fulfill_started_ms = performance.now();
    await route.fulfill({ response, body }); record.fulfill_finished_ms = performance.now(); record.fulfilled = true;
    result = { name, ...verified, delivery: 'original_route_fetch_bytes_verified_before_fulfill' };
  } catch (error) {
    failure = error; record.failure_phase = record.phase; record.error = String(error.stack || error);
  } finally {
    if (response) {
      record.dispose_started_ms = performance.now();
      try { await response.dispose(); record.disposed = true; }
      catch (error) {
        record.dispose_error = String(error.stack || error);
        if (!failure) { failure = error; record.failure_phase = 'dispose'; }
      }
      record.dispose_finished_ms = performance.now();
    }
    record.finished_ms = performance.now();
  }
  if (failure) throw failure;
  record.phase = 'complete'; return result;
}
async function verifyNativeDocument(response, expectedUrl, inventory, record) {
  try {
    record.phase = 'native_document_status';
    assert.ok(response, 'Native navigation did not return its Response');
    const request = response.request();
    assert.ok(record.native_navigation === true, 'Native document route was not observed');
    assert.ok(request.isNavigationRequest() && request.resourceType() === 'document' && request.frame().parentFrame() === null,
      'Use only the original top-level document Response');
    assert.equal(request.method(), 'GET', 'Native document must be the original GET');
    assert.equal(request.redirectedFrom(), null, 'Native document redirects are not accepted');
    assert.equal(request.url(), expectedUrl, 'Native document request URL changed');
    assert.equal(response.url(), expectedUrl, 'Native document response URL changed');
    record.http_status = response.status();
    assert.equal(record.http_status, 200, 'Native document HTTP status must be 200');
    const name = productionAssetPath(new URL(expectedUrl).pathname, inventory);
    assert.equal(name, 'index.html', 'Native navigation must resolve to the sealed index');
    record.asset = name; record.phase = 'native_document_read'; record.read_started_ms = performance.now();
    const body = await response.body(); record.read_finished_ms = performance.now(); record.bytes = body.length;
    record.phase = 'native_document_verify'; const verified = verifyProductionAsset(name, inventory, body, record.http_status);
    Object.assign(record, verified, { verified: true, phase: 'complete', finished_ms: performance.now(),
      disposal_scope: 'Browser-owned original navigation Response; not an acquired APIResponse' });
    return { name, ...verified, delivery: 'same_native_page_goto_response_verified_before_ui_operations' };
  } catch (error) {
    record.failure_phase = record.phase; record.error = String(error.stack || error); record.finished_ms = performance.now(); throw error;
  }
}
function fixtures() {
  const stamp = new Date().toISOString();
  const bridge = { connected: true, telemetryOnline: true, endpoint: 'fixture://no-network', lastMessage: stamp, statusMessage: 'fixture' };
  return {
    connection: { rosbridgeConnected: true, robotOnline: true, rosbridgeUrl: 'fixture://station', lastMessage: stamp, statusMessage: 'fixture', controlBridge: bridge, laserBridge: bridge },
    robot: { x: 0, y: 0, yaw: 0, linearVelocity: 0, angularVelocity: 0, accelX: 0, accelY: 0, accelZ: 9.81, angularVelX: 0, angularVelY: 0, angularVelZ: 0, timestamp: stamp },
    navigation: {
      map: { ready: true, width: 100, height: 100, resolution: .05, originX: -2.5, originY: -2.5, originYaw: 0, sampleStride: 1, lastUpdate: stamp, statusMessage: 'fixed fixture map', sampledCells: [] },
      tf: { ready: true, mapToOdomPresent: true, odomToBasePresent: true, transformCount: 2, staticTransformCount: 0, lastUpdate: stamp, statusMessage: 'presence only; no sensor extrinsics' },
      localization: { ready: true, x: .2, y: -.1, yaw: .3, covarianceScore: .01, lastUpdate: stamp, statusMessage: 'fixed fixture pose' },
      navStatus: { ready: true, activeGoals: 0, totalGoals: 0, statusSummary: 'idle', lastUpdate: stamp, statusMessage: 'no task' },
      path: { ready: true, frameId: 'map', poseCount: 3, points: [{ x: .2, y: -.1 }, { x: .8, y: .4 }, { x: 1.2, y: .7 }], lastUpdate: stamp, statusMessage: 'fixed fixture path' },
    },
    perception: {
      scan: { ready: true, frameId: 'fixture_laser', beamCount: 360, angleMin: -Math.PI, angleMax: Math.PI, rangeMin: .1, rangeMax: 5, observedRange: 2, lastUpdate: stamp, statusMessage: 'fixed 72 sample LaserScan fixture',
        samplePoints: Array.from({ length: 72 }, (_, i) => { const angleRad = -Math.PI + i * Math.PI * 2 / 72; return { angleRad, rangeMeters: 2, x: 2 * Math.cos(angleRad), y: 2 * Math.sin(angleRad) }; }) },
      ultrasonic: { ready: false, sourceTopic: '', frameId: '', distanceMeters: 0, maxRangeMeters: 0, blocked: false, lastUpdate: stamp, statusMessage: 'not in fixture' },
      infrared: { ready: false, sourceTopic: '', frameId: '', distanceMeters: 0, maxRangeMeters: 0, blocked: false, lastUpdate: stamp, statusMessage: 'not in fixture' },
    }, diagnostics: { generatedAt: stamp, entries: [] },
  };
}
function pcd() { return Buffer.from('VERSION .7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\nWIDTH 3\nHEIGHT 1\nPOINTS 3\nDATA ascii\n0 0 0\n1 0 0\n0 1 1\n'); }
function urdf() { return Buffer.from('<robot name="project_fixture"><link name="base"><visual><geometry><box size=".2 .1 .1"/></geometry><material name="test"><color rgba=".7 .1 .1 1"/></material></visual></link></robot>'); }
/** Chrome trusted Event.timeStamp and performance.now share the same time origin.
 * Reject clock/order mismatches; never clamp a negative component to zero.
 */
function trustedFeedbackTiming(value) {
  assert.equal(value.trusted, true, 'Feedback requires a trusted input event');
  const { event_ms: event, listener_ms: listener, aria_ms: aria, raf_ms: raf } = value;
  assert.ok([event, listener, aria, raf].every(number => Number.isFinite(number) && number >= 0), 'Feedback clocks must be finite monotonic milliseconds');
  assert.ok(event <= listener && listener <= aria && aria <= raf, 'Input, listener, aria and RAF clocks are not ordered');
  assert.ok(listener - event <= 5000, 'Input timestamp is outside the declared 5s same-clock queue window');
  return { ...value, input_to_listener_ms: listener - event, listener_to_aria_ms: aria - listener,
    aria_to_raf_ms: raf - aria, input_to_raf_ms: raf - event,
    legacy_capture_to_aria_ms: aria - listener, legacy_capture_to_raf_ms: raf - listener };
}
function percentile(values, proportion) { const ordered = [...values].sort((a, b) => a - b); return ordered[Math.max(0, Math.ceil(ordered.length * proportion) - 1)]; }
function slope(values) {
  if (values.length < 2) return null;
  const x = values.map(v => v.elapsed_s / 60), y = values.map(v => v.after_gc_bytes / 1048576), mx = x.reduce((a, b) => a + b) / x.length, my = y.reduce((a, b) => a + b) / y.length;
  return x.reduce((sum, value, i) => sum + (value - mx) * (y[i] - my), 0) / x.reduce((sum, value) => sum + (value - mx) ** 2, 0);
}

function graphicsLaunchOptions(graphics) {
  assert.ok(graphics === 'software' || graphics === 'hardware', 'Graphics mode is software or hardware');
  if (graphics === 'software') return { args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] };
  // Probe-c established this exact native NVIDIA combination without DISPLAY.
  // Remove Playwright defaults explicitly; do not relax Chromium's blocklist.
  return { chromiumSandbox: true, args: ['--enable-gpu', '--use-angle=vulkan'],
    ignoreDefaultArgs: ['--enable-unsafe-swiftshader', '--disable-ipc-flooding-protection', '--unsafely-disable-devtools-self-xss-warnings'] };
}
function validateGraphicsObservation(graphics, observation) {
  graphicsLaunchOptions(graphics);
  const renderer = observation.webgl?.renderer;
  assert.equal(typeof renderer, 'string', 'An actual WebGL renderer is required');
  if (graphics === 'software') {
    assert.ok(/swiftshader/i.test(renderer), 'Record the expected software renderer'); return;
  }
  assert.ok(/nvidia/i.test(renderer) && /nvidia/i.test(observation.webgl?.vendor ?? '')
    && !/swiftshader|llvmpipe|softpipe|software/i.test(renderer), 'Hardware panel requires the observed native NVIDIA renderer; no fallback');
  const args = observation.actual_args;
  assert.ok(Array.isArray(args) && args.every(value => typeof value === 'string'), 'Hardware requires actual browser argv');
  assert.ok(args.includes('--enable-gpu') && args.includes('--use-angle=vulkan'), 'Hardware argv differs from the established probe');
  assert.ok(!args.some(arg => /^--(?:no-sandbox|disable-setuid-sandbox|ignore-gpu-blocklist|enable-unsafe-swiftshader|disable-web-security|disable-ipc-flooding-protection|unsafely-disable-devtools-self-xss-warnings|disable-gpu)(?:=|$)/.test(arg)
    || (/^--(?:use-angle|use-gl)(?:=|$)/.test(arg) && arg !== '--use-angle=vulkan')), 'Hardware argv contains an unapproved safety/driver override');
  assert.ok(observation.gpu?.devices?.some(device => device.vendorId === 0x10de && /nvidia/i.test(device.deviceString ?? '')),
    'CDP must independently identify the native NVIDIA device');
}
function feedbackCriterion(samples) {
  const values = [], pointer = [], keyboard = [], errors = [];
  for (const [index, sample] of samples.entries()) {
    try {
      assert.ok(sample.input === 'pointer' || sample.input === 'keyboard', 'Missing input identity');
      assert.equal(sample.clock_validated, true, 'Input clock was not validated');
      assert.equal(sample.raw_timing?.event_type, sample.input === 'pointer' ? 'pointerdown' : 'keydown', 'Input identity differs from its raw event');
      const timing = trustedFeedbackTiming(sample.raw_timing);
      assert.equal(sample.milliseconds, timing.input_to_raf_ms, 'Derived feedback differs from its raw timestamps');
      values.push(timing.input_to_raf_ms); (sample.input === 'pointer' ? pointer : keyboard).push(timing.input_to_raf_ms);
    } catch (error) { errors.push({ sample: index, reason: String(error.message) }); }
  }
  const metrics = { pointer_p95_ms: percentile(pointer, .95) ?? null, keyboard_p95_ms: percentile(keyboard, .95) ?? null,
    aggregate_p95_ms: percentile(values, .95) ?? null, pointer_samples: pointer.length, keyboard_samples: keyboard.length, invalid_samples: errors };
  const complete = pointer.length > 0 && keyboard.length > 0;
  const passed = complete && !errors.length && metrics.pointer_p95_ms <= 100 && metrics.keyboard_p95_ms <= 100 && metrics.aggregate_p95_ms <= 100;
  return { status: passed ? 'passed' : errors.length || complete ? 'failed' : 'incomplete', threshold_ms: 100, ...metrics };
}
function longRunCriterion(value) {
  const finite = key => Number.isFinite(value?.[key]);
  const checks = {
    wall_duration: finite('elapsed_s') && value.elapsed_s >= 1800,
    samples_observed: finite('sample_count') && value.sample_count > 0,
    offered_20hz: finite('offered_hz') && value.offered_hz >= 18 && value.offered_hz <= 22,
    received_20hz: finite('received_hz') && value.received_hz >= 18 && value.received_hz <= 22,
    independent_render_cap: finite('rendered_hz') && value.rendered_hz > 0 && value.rendered_hz <= 20.5,
    post_gc_growth: finite('post_gc_growth_bytes') && value.post_gc_growth_bytes <= 32 * 1048576,
    post_gc_slope: finite('post_gc_slope_mib_per_min') && value.post_gc_slope_mib_per_min <= 2,
    listener_growth: finite('listener_delta') && value.listener_delta <= 50,
  };
  return { requested_s: 1800, status: Object.values(checks).every(Boolean) ? 'passed' : 'failed', checks };
}
function sceneCriteriaPassed(criteria) {
  return criteria.C03?.preflight?.status === 'passed' && criteria.C03?.final?.status === 'passed'
    && (criteria.C04?.requested_s === 0 ? criteria.C04.status === 'not_requested'
      : criteria.C04?.requested_s === 1800 && criteria.C04.status === 'passed')
    && ['graphics', 'functional', 'cleanup', 'source'].every(name => criteria[name]?.status === 'passed');
}

async function main(options) {
  const { chromium } = require('playwright');
  const report = { passed: false, scope: 'Read-only browser fixture contract; graphics backend explicitly observed. No ROS/physical task or leak-freedom claim; hardware is a separate panel, not an algorithm improvement or a software-result reclassification',
    fixed_input_hz: 20, fixture_panel: 'Native EventSource from independent loopback Node SSE: 20Hz perception + four 1Hz resources (24 events/s nominal); differs from old 100events/s browser timer and 24events/s CDP injection panels',
    duration_requested_s: options.duration, execution_mode: options.mode, graphics_requested: options.graphics,
    launch_options: graphicsLaunchOptions(options.graphics),
    criteria: { C03: { preflight: { status: 'not_run' }, final: { status: 'not_run' } },
      C04: { requested_s: options.duration, status: options.duration ? 'not_run' : 'not_requested' },
      graphics: { status: 'not_run' }, functional: { status: 'not_run' }, cleanup: { status: 'not_run' }, source: { status: 'not_run' } },
    production_build: options.mode === 'production' ? validateProductionBuild(options.dist, options.buildReceipt) : null,
    served_assets: {}, asset_requests: [], asset_delivery: options.mode === 'production' ? 'Top-level document retains native navigation and verifies the same page.goto Response before UI operations; other assets use original route.fetch(maxRedirects=0), verified bytes then fulfill/dispose' : null,
    source_start: executedSourceManifest(options), checks: [], errors: [], posts: [], api_counts: {}, screenshots: [],
    click_feedback_ms: [], pointer_feedback_ms: [], keyboard_feedback_ms: [], feedback_samples: [], feedback_metric_version: 3,
    legacy_capture_to_raf_ms: [],
    prior_feedback_metric_scope: 'Retained preflight a-f measured synthetic click-to-aria, not trusted input-to-frame. The unexecuted handler-to-frame candidate excluded input queue. No same-metric improvement claim.',
    metric_definitions: { input_feedback: 'Trusted pointerdown or Enter keydown Event.timeStamp to the first animation frame after aria-pressed becomes true; validates finite same-origin ordered timestamps, queue <=5s, no negative clamp; local UI feedback, not model readiness',
      startup: 'Monotonic time from this view preparation effect to renderer setup/model load/first actual WebGL draw; includes deferred setup wait',
      render_limit: 'Local actual WebGL draws, capped at 20Hz independently from source, EventSource receipt and Worker outputs' },
    startup_samples: [], gc_samples: [], samples: 0, react_module_urls: [], started_epoch: Date.now() / 1000 };
  let browser, page, cdp, instance = 'scene-fixture-a', workerCreated = 0;
  let sourceTimer = null, sourceBegan = null, sourceClosed = false, lastSlow = -Infinity, fixtureServer = null, fixtureOrigin = null, sourceSequence = 0;
  let movingGeometry = false, longBegan = null, navigationRecord = null;
  const clients = new Set(), assetChecks = [];
  const source = { offered: 0, sent: 0, overwritten: 0, slow_sent: 0, clients_created: 0, clients_closed: 0 };
  const raw = fixtures(), output = name => path.join(options.output, name);
  const samples = fs.openSync(output('samples.jsonl'), 'wx', 0o600);
  function check(name) { report.checks.push(name); console.log(`PASS ${name}`); }
  function writeResult() { fs.writeFileSync(output('browser-result.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 }); }
  async function screenshot(name) { await page.screenshot({ path: output(name + '.png'), fullPage: true }); report.screenshots.push(name + '.png'); }
  async function metrics() {
    const values = (await cdp.send('Performance.getMetrics')).metrics;
    const heap = values.find(value => value.name === 'JSHeapUsedSize')?.value ?? null;
    const dom = await cdp.send('Memory.getDOMCounters');
    const ui = await page.evaluate(() => ({ view: document.querySelector('.scene-webgl')?.dataset ?? null,
      sse: { created: window.__sceneFixture.created, closed: window.__sceneFixture.closed, active: window.__sceneFixture.active, received: window.__sceneFixture.received },
      pipeline: { worker_created: window.__sceneFixture.workerCreated, worker_terminated: window.__sceneFixture.workerTerminated,
        processed_worker_results: window.__sceneFixture.processed, rendered: window.__sceneFixture.rendered },
      main_thread: { long_tasks: window.__sceneFixture.longTasks, event_to_raf_ms: window.__sceneFixture.frameLatencies },
      canvases: document.querySelectorAll('.scene-webgl canvas').length }));
    return { heap_bytes: heap, documents: dom.documents, nodes: dom.nodes, listeners: dom.jsEventListeners, workers: page.workers().length, worker_created: workerCreated,
      source: { ...source, active_clients: clients.size, pending_frames: [...clients].filter(value => value.pending !== null).length,
        buffered_bytes: [...clients].reduce((sum, value) => sum + value.response.writableLength, 0) }, ...ui };
  }
  async function gc(elapsed_s) {
    const before = await metrics(); await cdp.send('HeapProfiler.collectGarbage'); const after = await metrics();
    const value = { elapsed_s, before_gc_bytes: before.heap_bytes, after_gc_bytes: after.heap_bytes, listeners: after.listeners, nodes: after.nodes, documents: after.documents, workers: after.workers };
    report.gc_samples.push(value); return after;
  }
  const view = () => page.locator('.scene-viewport');
  async function ready() {
    await view().locator('canvas').waitFor()
    const value = await until(() => metrics(), m => Number(m.view?.sceneRenderCount) > 0 && Number(m.view?.sceneGeometries) >= 6, 'actual preview URDF draw')
    const number = item => item === undefined || item === 'null' || !Number.isFinite(Number(item)) ? null : Number(item)
    report.startup_samples.push({ scene_setup_ms: number(value.view.sceneSetupMs), model_ready_ms: number(value.view.sceneModelReadyMs),
      scene_first_draw_ms: number(value.view.sceneFirstDrawMs), model_first_draw_ms: number(value.view.sceneFirstModelDrawMs) })
  }
  async function scan() { await view().getByRole('button', { name: '激光局部', exact: true }).click(); await until(() => metrics(), m => Number(m.view?.scenePoints) === 72 && Number(m.view?.sceneWorkerDelivered) > 0, 'actual scan worker'); }
  async function feedback(name, selector = '.scene-view-switch button', input = 'pointer') {
    assert.ok(input === 'pointer' || input === 'keyboard');
    await page.evaluate(({ name, selector, input }) => {
      const button = [...document.querySelectorAll(selector)].find(node => node.textContent === name);
      if (!button) throw new Error('Feedback button missing');
      if (button.getAttribute('aria-pressed') === 'true') throw new Error('Feedback must measure an actual selection change');
      window.__sceneFeedback = { promise: new Promise((resolve, reject) => {
        let timing = null, frame = null;
        const eventName = input === 'pointer' ? 'pointerdown' : 'keydown';
        const clean = () => { observer.disconnect(); document.removeEventListener(eventName, start, true); clearTimeout(timer); if (frame !== null) cancelAnimationFrame(frame); };
        const observe = () => {
          if (timing === null || button.getAttribute('aria-pressed') !== 'true' || frame !== null) return;
          timing.aria_ms = performance.now(); observer.disconnect();
          frame = requestAnimationFrame(() => { timing.raf_ms = performance.now(); clean(); resolve(timing); });
        };
        const start = event => {
          if (!event.isTrusted || !button.contains(event.target) || (input === 'keyboard' && event.key !== 'Enter')) return;
          timing = { trusted: event.isTrusted, event_type: event.type, event_ms: event.timeStamp, listener_ms: performance.now(), aria_ms: null, raf_ms: null };
          document.removeEventListener(eventName, start, true); observe();
        };
        const observer = new MutationObserver(observe);
        observer.observe(button, { attributes: true, attributeFilter: ['aria-pressed'] });
        const timer = setTimeout(() => { clean(); reject(new Error('Trusted input feedback deadline')); }, 2500);
        document.addEventListener(eventName, start, true);
      }) };
    }, { name, selector, input });
    const button = page.locator(selector).filter({ hasText: name });
    if (input === 'keyboard') { await button.focus(); await button.press('Enter'); } else await button.click();
    const rawTiming = await page.evaluate(() => window.__sceneFeedback.promise);
    const sample = { input, name, raw_timing: rawTiming, clock_validated: false }; report.feedback_samples.push(sample);
    const timing = trustedFeedbackTiming(rawTiming), value = timing.input_to_raf_ms;
    Object.assign(sample, { milliseconds: value, ...timing, clock_validated: true });
    report.click_feedback_ms.push(value); report[`${input}_feedback_ms`].push(value); report.legacy_capture_to_raf_ms.push(timing.legacy_capture_to_raf_ms);
  }
  try {
    fixtureServer = http.createServer((request, response) => {
      if (request.method !== 'GET' || request.url !== '/events') { response.writeHead(404); response.end(); return; }
      response.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', Connection: 'keep-alive', 'Access-Control-Allow-Origin': options.base });
      response.flushHeaders(); response.write(': isolated no-ROS fixture\n\n');
      const client = { response, blocked: false, pending: null }; clients.add(client); source.clients_created++;
      response.on('close', () => { clients.delete(client); source.clients_closed++; });
      response.on('drain', () => {
        client.blocked = false;
        if (client.pending) { const packet = client.pending; client.pending = null; send(client, packet); }
      });
    });
    await new Promise((resolve, reject) => { fixtureServer.once('error', reject); fixtureServer.listen(0, '127.0.0.1', resolve); });
    fixtureOrigin = `http://127.0.0.1:${fixtureServer.address().port}`;
    function send(client, packet) {
      if (sourceClosed || client.response.destroyed) return;
      if (client.blocked) { if (client.pending) source.overwritten++; client.pending = packet; return; }
      client.blocked = !client.response.write(packet.body); source.sent++;
      if (packet.slow) source.slow_sent++;
    }
    function offer() {
      source.offered++; const stamp = new Date().toISOString(), slow = performance.now() - lastSlow >= 1000;
      const shift = movingGeometry ? .08 * Math.sin(source.offered * .05) : 0;
      const scan = { ...raw.perception.scan, lastUpdate: stamp,
        samplePoints: movingGeometry ? raw.perception.scan.samplePoints.map(point => ({ ...point, x: point.x + shift, y: point.y - shift })) : raw.perception.scan.samplePoints };
      const values = [['perception-state', { ...raw.perception, scan }]];
      if (slow) {
        lastSlow = performance.now();
        values.push(['connection', { ...raw.connection, lastMessage: stamp }], ['robot-state', { ...raw.robot, timestamp: stamp }],
          ['navigation-state', { ...raw.navigation, localization: { ...raw.navigation.localization, lastUpdate: stamp }, path: { ...raw.navigation.path, lastUpdate: stamp,
            points: movingGeometry ? raw.navigation.path.points.map(point => ({ x: point.x + shift, y: point.y - shift })) : raw.navigation.path.points } }], ['diagnostic', raw.diagnostics]);
      }
      const body = values.map(([name, value]) => `id: ${instance}:${++sourceSequence}\nevent: ${name}\ndata: ${JSON.stringify(value)}\n\n`).join('');
      for (const client of clients) send(client, { body, slow });
    }
    browser = await chromium.launch({ headless: true, executablePath: options.chromium, ...report.launch_options });
    report.browser_version = browser.version();
    let systemSession;
    try {
      systemSession = await browser.newBrowserCDPSession();
      report.browser_system_info = await systemSession.send('SystemInfo.getInfo');
      const processes = (await systemSession.send('SystemInfo.getProcessInfo')).processInfo.filter(value => value.type === 'browser');
      assert.equal(processes.length, 1, 'Identify exactly this CDP browser process');
      const pid = processes[0].id, args = fs.readFileSync(`/proc/${pid}/cmdline`, 'utf8').split('\0').filter(Boolean);
      assert.equal(fs.realpathSync(args[0]), fs.realpathSync(options.chromium), 'CDP browser executable identity differs');
      report.actual_browser = { pid, args, args_source: 'SystemInfo browser PID and exact /proc cmdline',
        proc_start_ticks: fs.readFileSync(`/proc/${pid}/stat`, 'utf8').split(') ').at(-1).split(' ')[19] };
    } catch (error) {
      report.graphics_metadata_error = String(error.stack || error);
      if (options.graphics === 'hardware') throw error;
    } finally { if (systemSession) await systemSession.detach(); }
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, serviceWorkers: 'block' });
    await context.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      if (url.origin !== options.base) { report.errors.push(`Blocked external URL ${url.origin}`); return route.abort(); }
      if (request.method() !== 'GET') { report.posts.push({ path: url.pathname, method: request.method() }); return route.abort(); }
      if (url.pathname.startsWith('/workbench-service/')) {
        report.api_counts[url.pathname] = (report.api_counts[url.pathname] || 0) + 1;
        return route.fulfill({ status: 503, json: { error: 'unsupported isolated tool fixture' }, headers: { 'Cache-Control': 'no-store' } });
      }
      if (!/^\/(api|sim-api|coop-api|voice-api)\//.test(url.pathname)) {
        if (/react|vite\/deps/.test(url.pathname) && !report.react_module_urls.includes(url.pathname + url.search)) report.react_module_urls.push(url.pathname + url.search);
        if (options.mode === 'production') {
          // A synthetic top-level response loses Chromium's Loopback initiator
          // address space and blocks the original cross-port native SSE route.
          if (request.isNavigationRequest() && request.resourceType() === 'document' && request.frame() === page.mainFrame()) {
            const record = navigationRecord = { url: request.url(), resource_type: 'document', native_navigation: true,
              clock: 'node_performance_now', phase: 'native_continue', continue_started_ms: performance.now() };
            report.asset_requests.push(record);
            try {
              assert.equal(productionAssetPath(url.pathname, report.production_build.dist), 'index.html');
              await route.continue(); record.continue_finished_ms = performance.now();
            } catch (error) {
              record.failure_phase = record.phase; record.error = String(error.stack || error);
              report.errors.push(`Production document ${record.url}: ${record.error}`);
              await route.abort().catch(abortError => { record.abort_error = String(abortError); });
            }
            return;
          }
          const record = {}; report.asset_requests.push(record);
          const pending = forwardProductionAsset(route, options.base, report.production_build.dist, record)
            .then(({ name, ...verified }) => { report.served_assets[name] = verified; })
            .catch(async error => {
              report.errors.push(`Production asset ${record.url} (${record.resource_type}) phase=${record.failure_phase}: ${String(error.stack || error)}`);
              if (!record.fulfilled) {
                try { await route.abort(); record.aborted = true; }
                catch (abortError) { record.abort_error = String(abortError.stack || abortError); }
              }
            });
          assetChecks.push(pending); return pending;
        }
        return route.continue();
      }
      report.api_counts[url.pathname] = (report.api_counts[url.pathname] || 0) + 1;
      if (url.pathname === '/api/v1/stream/events') return route.continue({ url: fixtureOrigin + '/events' });
      const headers = { 'X-Fishbot-Instance': instance, 'Cache-Control': 'no-store' };
      if (url.pathname.endsWith('/runtime')) {
        const service = url.pathname.startsWith('/sim-api') ? 'mission' : url.pathname.startsWith('/coop-api') ? 'cooperation' : url.pathname.startsWith('/voice-api') ? 'voice' : 'station';
        return route.fulfill({ json: { schema_version: 1, service, instance_id: instance, mode: 'simulation', domain: options.domain, scene_id: 'fixed-browser-fixture', episode_id: 'no-action', capabilities: [] }, headers });
      }
      const value = { '/api/v1/connection': raw.connection, '/api/v1/state': raw.robot, '/api/v1/navigation': raw.navigation, '/api/v1/perception': raw.perception, '/api/v1/diagnostics': raw.diagnostics }[url.pathname];
      if (value) return route.fulfill({ json: value, headers });
      return route.fulfill({ status: 503, json: { error: 'unsupported isolated browser fixture' }, headers });
    });
    if (context.routeWebSocket) await context.routeWebSocket('**/*', socket => socket.close());
    await context.addInitScript(({ raw, instance }) => {
      window.__sceneFixture = { instance, sequence: 0, received: 0, created: 0, closed: 0, active: 0, workerCreated: 0, workerTerminated: 0, processed: 0, rendered: 0, longTasks: [], frameLatencies: [], framePending: false };
      new PerformanceObserver(list => {
        for (const entry of list.getEntries()) { window.__sceneFixture.longTasks.push({ start_ms: entry.startTime, duration_ms: entry.duration }); if (window.__sceneFixture.longTasks.length > 256) window.__sceneFixture.longTasks.shift(); }
      }).observe({ entryTypes: ['longtask'] });
      const NativeEventSource = window.EventSource;
      class FixtureEventSource extends NativeEventSource {
        stopped = false;
        constructor(...args) { super(...args); window.__sceneFixture.created++; window.__sceneFixture.active++;
          this.addEventListener('perception-state', () => {
            const f = window.__sceneFixture; f.received++;
            if (!f.framePending) { f.framePending = true; const began = performance.now(); requestAnimationFrame(() => {
              f.framePending = false; f.frameLatencies.push(performance.now() - began); if (f.frameLatencies.length > 256) f.frameLatencies.shift();
            }); }
          }); }
        close() { if (!this.stopped) { this.stopped = true; window.__sceneFixture.closed++; window.__sceneFixture.active--; } return super.close(); }
      }
      window.EventSource = FixtureEventSource;
      const NativeWorker = window.Worker;
      window.Worker = class extends NativeWorker {
        stopped = false;
        constructor(...args) { super(...args); window.__sceneFixture.workerCreated++;
          this.addEventListener('message', event => { if (event.data?.points) window.__sceneFixture.processed++; }); }
        terminate() { if (!this.stopped) { this.stopped = true; window.__sceneFixture.workerTerminated++; } return super.terminate(); }
      };
      const lastCounts = new WeakMap();
      new MutationObserver(records => {
        for (const record of records) {
          const element = record.target;
          if (!element.classList?.contains('scene-webgl')) continue;
          const value = Number(element.dataset.sceneRenderCount || 0), prior = lastCounts.get(element) || 0;
          window.__sceneFixture.rendered += value >= prior ? value - prior : value; lastCounts.set(element, value);
        }
      }).observe(document, { subtree: true, attributes: true, attributeFilter: ['data-scene-render-count'] });
    }, { raw, instance });
    page = await context.newPage(); page.setDefaultTimeout(20000);
    page.on('pageerror', error => report.errors.push(error.stack || error.message)); page.on('worker', () => workerCreated++);
    cdp = await context.newCDPSession(page); await cdp.send('Performance.enable');
    const navigation = await page.goto(options.base + '/radar', { waitUntil: 'domcontentloaded' });
    if (options.mode === 'production') {
      const { name, ...verified } = await verifyNativeDocument(navigation, options.base + '/radar', report.production_build.dist, navigationRecord);
      report.served_assets[name] = verified;
    }
    sourceBegan = performance.now(); sourceTimer = setInterval(offer, 50);
    if (options.diagnose) {
      report.diagnostic_only = true; report.acceptance_performed = false;
      const began = performance.now(), phases = []; let profile;
      await cdp.send('Profiler.enable'); await cdp.send('Profiler.setSamplingInterval', { interval: 1000 }); await cdp.send('Profiler.start');
      async function phase(name, operation) {
        const start_s = (performance.now() - began) / 1000;
        try { await operation(); phases.push({ name, start_s, end_s: (performance.now() - began) / 1000 }); }
        catch (error) { phases.push({ name, start_s, end_s: (performance.now() - began) / 1000, error: String(error.stack || error) }); }
      }
      page.setDefaultTimeout(2500);
      await phase('enter_3d_setup', async () => { await page.getByRole('button', { name: '三维观测', exact: true }).click(); await ready(); await scan(); });
      movingGeometry = true;
      let round = 0;
      while (performance.now() - began < (options.diagnose - 2) * 1000) {
        if (!(await page.locator('.scene-viewport').count())) break;
        await phase(`map_pointer_${round}`, () => feedback('地图与模型', '.scene-view-switch button', 'pointer'));
        await phase(`scan_keyboard_${round}`, () => feedback('激光局部', '.scene-view-switch button', 'keyboard'));
        if (round % 3 === 0) {
          await phase(`exit_3d_dispose_${round}`, () => feedback('二维地图', '.radar-view-switch button', 'pointer'));
          await phase(`enter_3d_setup_${round}`, async () => { await feedback('三维观测', '.radar-view-switch button', 'pointer'); await ready(); await scan(); });
        }
        round++; await sleep(100);
      }
      ({ profile } = await cdp.send('Profiler.stop'));
      const byId = new Map(profile.nodes.map(node => [node.id, node.callFrame])), weights = new Map();
      (profile.samples || []).forEach((id, index) => { const frame = byId.get(id), key = JSON.stringify(frame); weights.set(key, (weights.get(key) || 0) + (profile.timeDeltas[index] || 1000)); });
      report.diagnostic = { elapsed_s: (performance.now() - began) / 1000, phases,
        top_cpu_frames: [...weights].sort((a, b) => b[1] - a[1]).slice(0, 40).map(([frame, us]) => ({ frame: JSON.parse(frame), sample_ms: us / 1000 })),
        snapshot: await Promise.race([metrics(), sleep(2000).then(() => ({ diagnostic_read_timeout: true }))]) };
      const profileText = JSON.stringify(profile); assert.ok(Buffer.byteLength(profileText) <= 8 * 1024 * 1024, 'Bound CPU profile output');
      fs.writeFileSync(output('cpu-profile.json'), profileText, { mode: 0o600, flag: 'wx' });
      report.diagnostic_completed = true;
      report.source_end = executedSourceManifest(options); assert.deepEqual(report.source_end, report.source_start); return;
    }
    await page.getByRole('button', { name: '三维观测', exact: true }).click(); await ready();
    report.webgl = await view().locator('canvas').evaluate(canvas => { const gl = canvas.getContext('webgl2'), ext = gl?.getExtension('WEBGL_debug_renderer_info');
      return { version: gl?.getParameter(gl.VERSION), vendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : null,
        renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null }; });
    validateGraphicsObservation(options.graphics, { webgl: report.webgl, actual_args: report.actual_browser?.args, gpu: report.browser_system_info?.gpu });
    report.criteria.graphics = { status: 'passed', requested: options.graphics, actual_renderer: report.webgl.renderer };
    await screenshot('actual-urdf-preview'); check(`real_browser_urdf_and_${options.graphics}_webgl`);
    await scan(); await screenshot('actual-sensor-frame-scan'); check('real_scan_worker_sensor_frame_no_tf_guess');
    movingGeometry = true;
    for (let i = 0; i < 4; i++) {
      await page.getByRole('button', { name: '二维地图', exact: true }).click(); await page.locator('.radar-viewport svg').waitFor();
      await sleep(350); await page.getByRole('button', { name: '三维观测', exact: true }).click(); await ready();
    }
    await feedback('二维地图', '.radar-view-switch button');
    await page.getByRole('button', { name: 'scan+map', exact: true }).click();
    const pathLine = page.locator('[data-testid="navigation-path"]'); await pathLine.waitFor();
    const beforePath = await pathLine.getAttribute('points'); await until(() => pathLine.getAttribute('points'), value => value !== beforePath, 'moving real map-frame path fixture');
    await feedback('三维观测', '.radar-view-switch button'); await ready(); await scan();
    movingGeometry = false; check('moving_geometry_and_path_allow_real_2d_3d_switches_at_source_20hz');
    await view().locator('input[type=file]').setInputFiles({ name: 'project-fixture.pcd', mimeType: 'application/octet-stream', buffer: pcd() });
    await until(() => metrics(), m => Number(m.view?.scenePoints) === 3, 'PCD worker display');
    await view().getByText('文件原始坐标；单位未知', { exact: true }).waitFor(); check('real_pcd_local_file_without_ros_claim');
    await view().locator('input[type=file]').setInputFiles({ name: 'project-fixture.urdf', mimeType: 'application/xml', buffer: urdf() });
    await until(() => metrics(), m => Number(m.view?.sceneGeometries) >= 3 && Number(m.view?.sceneRenderCount) > 0, 'local URDF rendered');
    await view().getByText('URDF；米；+Z 向上', { exact: true }).waitFor(); assert.equal(await view().getByRole('alert').count(), 0); check('real_local_primitive_urdf_loader');
    await view().locator('input[type=file]').setInputFiles({ name: 'broken.pcd', mimeType: 'application/octet-stream', buffer: Buffer.from('broken PCD') });
    await view().getByRole('alert').filter({ hasText: 'PCD' }).waitFor(); check('bad_file_explicit_failure');
    await view().getByRole('button', { name: '激光局部', exact: true }).click(); await scan();
    const old = await page.locator('.scene-webgl').elementHandle();
    instance = 'scene-fixture-b'; await page.evaluate(value => { window.__sceneFixture.instance = value; }, instance);
    await until(() => old.evaluate(element => element.isConnected), value => !value, 'source generation replaces canvas');
    await scan(); check('new_instance_replaces_old_renderer_and_worker');
    const contextLoss = await view().locator('canvas').evaluate(canvas => {
      const ext = canvas.getContext('webgl2')?.getExtension('WEBGL_lose_context'); if (!ext) return false;
      window.__sceneLossExtension = ext; ext.loseContext(); return true;
    });
    assert.equal(contextLoss, true); await view().getByRole('alert').filter({ hasText: '上下文' }).waitFor();
    await page.evaluate(() => window.__sceneLossExtension.restoreContext()); await scan();
    await until(() => metrics(), m => m.view?.sceneContextLost === 'false' && Number(m.view?.sceneRenderCount) > 0, 'context restored');
    check('webgl_context_loss_restore_render_only');
    await page.getByRole('button', { name: '成果验收', exact: true }).click();
    await until(() => page.workers().length, value => value === 0, 'route hidden releases workers');
    assert.equal(await page.locator('.scene-webgl canvas').count(), 0);
    assert.equal((await metrics()).sse.active, 1); check('hidden_canvas_releases_worker_preserves_single_telemetry_session');
    await page.getByRole('button', { name: '雷达与地图', exact: true }).click();
    if (!(await page.locator('.scene-viewport').count())) await page.getByRole('button', { name: '三维观测', exact: true }).click();
    await ready(); await scan(); check('route_restore_reads_latest_without_actions');
    for (let i = 0; i < 12; i++) { await feedback(i % 2 ? '激光局部' : '地图与模型', '.scene-view-switch button', i % 2 ? 'keyboard' : 'pointer'); }
    await scan(); assert.equal(report.posts.length, 0); assert.deepEqual(report.errors, []);
    check('preflight_zero_motion_posts_and_no_page_errors');
    const preflightSnapshot = await metrics(), preflightSeconds = (performance.now() - sourceBegan) / 1000;
    report.preflight_rates = { elapsed_s: preflightSeconds, offered_hz: source.offered / preflightSeconds,
      received_hz: preflightSnapshot.sse.received / preflightSeconds, rendered_hz: preflightSnapshot.pipeline.rendered / preflightSeconds,
      scope: 'Whole preflight including 2D/3D, local files, source generation and context-loss transitions; not a steady-state or 30-minute score',
      snapshot: preflightSnapshot };
    await Promise.all(assetChecks);
    if (options.mode === 'production') {
      report.index_reference_status = report.production_build.dist.index_references.map(reference => ({
        ...reference, requested_and_verified: !!report.served_assets[reference.path],
      }));
      for (const reference of report.index_reference_status) if (/\.(?:js|css)$/.test(reference.path)) {
        assert.ok(reference.requested_and_verified, `Index JS/CSS was not verified over HTTP: ${reference.path}`);
      }
      // Browsers may skip icons/prefetches. Their references and local bytes are
      // frozen, but an unrequested asset is not described as an HTTP receipt.
      assert.ok(report.served_assets['index.html']); assert.deepEqual(report.errors, []);
      check('production_index_and_actual_served_assets_match_sealed_build');
    }
    report.criteria.functional = { status: 'passed' };
    report.criteria.C03.preflight = feedbackCriterion(report.feedback_samples);
    report.preflight_contract_passed = true;
    report.preflight_passed = report.criteria.C03.preflight.status === 'passed'; writeResult();
    if (options.duration) {
      movingGeometry = true; report.long_input_geometry = 'Deterministic 72-point nonzero sinusoid at 20Hz, map-frame path follows the same sequence at 1Hz';
      const began = performance.now(), initial = await metrics();
      longBegan = began;
      let nextGc = 300, nextClick = 60, peakWorkers = 0, peakPoints = 0, peakListeners = 0;
      const baseline = await gc(0); report.long_started_epoch = Date.now() / 1000;
      console.log(`LONG_TEST_STARTED ${JSON.stringify({ seconds: options.duration, output: options.output })}`);
      while (performance.now() - began < options.duration * 1000) {
        const elapsed_s = (performance.now() - began) / 1000;
        const value = { elapsed_s, ...await metrics() };
        fs.writeSync(samples, JSON.stringify(value) + '\n'); report.samples++;
        peakWorkers = Math.max(peakWorkers, value.workers); peakPoints = Math.max(peakPoints, Number(value.view?.scenePoints) || 0); peakListeners = Math.max(peakListeners, value.listeners);
        assert.equal(value.sse.active, 1); assert.ok(value.workers <= 1); assert.ok(Number(value.view?.scenePoints) <= 4096);
        assert.equal(value.source.active_clients, 1); assert.ok(value.source.pending_frames <= 1); assert.ok(value.source.buffered_bytes <= 128 * 1024)
        assert.ok(['true', 'false'].includes(value.view?.sceneWorkerPending));
        if (elapsed_s >= nextClick) { await feedback('地图与模型', '.scene-view-switch button', 'pointer'); await feedback('激光局部', '.scene-view-switch button', 'keyboard'); nextClick += 60; }
        if (elapsed_s >= nextGc) { await gc(elapsed_s); nextGc += 300; }
        await sleep(Math.min(5000, Math.max(0, options.duration * 1000 - (performance.now() - began))));
      }
      const elapsed_s = (performance.now() - began) / 1000, final = await gc(elapsed_s), last = report.gc_samples.at(-1);
      report.long = { elapsed_s, offered_hz: (final.source.offered - initial.source.offered) / elapsed_s,
        sample_count: report.samples,
        sent_hz: (final.source.sent - initial.source.sent) / elapsed_s,
        received_hz: (final.sse.received - initial.sse.received) / elapsed_s,
        processed_worker_results_hz: (final.pipeline.processed_worker_results - initial.pipeline.processed_worker_results) / elapsed_s,
        rendered_hz: (final.pipeline.rendered - initial.pipeline.rendered) / elapsed_s,
        source_queue_overwritten: final.source.overwritten - initial.source.overwritten,
        slow_resources_hz: (final.source.slow_sent - initial.source.slow_sent) / elapsed_s,
        processed_scope: 'Worker output and local draw counters; not a controller or physical consumption receipt',
        peak_workers: peakWorkers, peak_points: peakPoints, peak_listeners: peakListeners,
        post_gc_growth_bytes: last.after_gc_bytes - report.gc_samples[0].after_gc_bytes, post_gc_slope_mib_per_min: slope(report.gc_samples),
        listener_delta: final.listeners - baseline.listeners, heap_scope: 'GC checkpoints and trend only; not a proof of absence of leaks' };
      report.criteria.C04 = longRunCriterion(report.long);
      report.long_completed = elapsed_s >= 1800;
      if (report.criteria.C04.status === 'passed') check('thirty_minute_fixed_input_queue_gc_and_listener_bounds');
    }
    report.input_queue_p95_ms = percentile(report.feedback_samples.map(value => value.input_to_listener_ms), .95);
    report.legacy_capture_to_raf_p95_ms = percentile(report.legacy_capture_to_raf_ms, .95);
    report.pointer_feedback_p95_ms = percentile(report.pointer_feedback_ms, .95);
    report.keyboard_feedback_p95_ms = percentile(report.keyboard_feedback_ms, .95);
    report.click_feedback_p95_ms = percentile(report.click_feedback_ms, .95);
    report.criteria.C03.final = feedbackCriterion(report.feedback_samples);
    if (report.criteria.C03.preflight.status === 'passed' && report.criteria.C03.final.status === 'passed') check('trusted_pointer_and_keyboard_feedback_p95_under_100ms');
    await screenshot('final-scan');
    await page.getByRole('button', { name: '成果验收', exact: true }).click();
    await until(() => page.workers().length, count => count === 0, 'final worker disposal'); report.final_hidden = await metrics();
    assert.equal(report.final_hidden.canvases, 0); assert.equal(report.final_hidden.sse.active, 1);
    report.criteria.cleanup = { status: 'passed', hidden_canvas_count: 0, hidden_worker_count: 0, telemetry_sessions: 1 };
    assert.equal(report.posts.length, 0); assert.deepEqual(report.errors, []);
    await Promise.all(assetChecks); assert.deepEqual(report.errors, []);
    if (options.mode === 'production') validateProductionBuild(options.dist, options.buildReceipt);
    report.source_end = executedSourceManifest(options); assert.deepEqual(report.source_end, report.source_start, 'Execution source changed');
  } catch (error) {
    report.errors.push(String(error.stack || error));
    if (longBegan !== null && !report.long_completed) report.long_interrupted = { elapsed_s: (performance.now() - longBegan) / 1000, sample_count: report.samples };
    if (page && !page.isClosed()) await screenshot('failure').catch(() => {});
    throw error;
  } finally {
    sourceClosed = true; if (sourceTimer) clearInterval(sourceTimer);
    if (browser) { await browser.close(); report.browser_closed = !browser.isConnected(); }
    for (const client of clients) client.response.destroy();
    if (fixtureServer) await new Promise(resolve => fixtureServer.close(resolve));
    report.source_counters = { ...source, active_clients: clients.size };
    await Promise.all(assetChecks);
    try {
      report.source_end = executedSourceManifest(options);
      assert.deepEqual(report.source_end, report.source_start, 'Final source/artifact closure changed');
      report.source_unchanged = true;
      report.criteria.source = { status: 'passed' };
    } catch (error) {
      report.source_unchanged = false; report.criteria.source = { status: 'failed' }; report.errors.push(String(error.stack || error));
    }
    if (!report.diagnostic_only) {
      if (options.duration && report.criteria.C04.status === 'not_run') report.criteria.C04.status = 'incomplete';
      report.passed = report.errors.length === 0 && report.posts.length === 0 && report.browser_closed === true && sceneCriteriaPassed(report.criteria);
      if (!report.passed) process.exitCode = 1;
    } else if (report.errors.length || report.source_unchanged !== true) process.exitCode = 1;
    report.finished_epoch = Date.now() / 1000; fs.closeSync(samples); writeResult();
  }
  console.log(JSON.stringify({ passed: report.passed, checks: report.checks.length, samples: report.samples, output: options.output, long: report.long ?? null }));
}
if (require.main === module) {
  let options;
  try { options = argumentsFrom(process.argv.slice(2)); } catch (error) { console.error(error.message); process.exitCode = 1; }
  if (options) main(options).catch(error => { console.error(error.stack || error); process.exitCode = 1; });
}
module.exports = { argumentsFrom, fixtures, pcd, urdf, trustedFeedbackTiming, sourceManifest, distManifest,
  freezeBuildSource, sealProductionBuild, validateProductionBuild, executedSourceManifest, productionAssetPath, verifyProductionAsset,
  forwardProductionAsset, verifyNativeDocument, graphicsLaunchOptions, validateGraphicsObservation, feedbackCriterion, longRunCriterion, sceneCriteriaPassed };
