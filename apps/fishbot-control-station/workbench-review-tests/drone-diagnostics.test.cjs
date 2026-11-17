// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { createRequire } = require('node:module');
const { test } = require('node:test');
const upstream = createRequire(path.join(__dirname, '../workbench/package.json'));
const { McapIndexedReader } = upstream('@mcap/core');
const { createDroneDiagnostics, readEvidence, diagnosticFrames, curvePoints } = require('../drone-diagnostics.cjs');

function fixture(t, options = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'drone-diagnostics-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const id = 'historical-flight-123', dir = path.join(root, 'archive', 'recorded-copy');
  fs.mkdirSync(path.join(dir, 'ego'), { recursive: true });
  const save = (name, value) => fs.writeFileSync(path.join(dir, name), JSON.stringify(value));
  const lines = (name, values) => fs.writeFileSync(path.join(dir, name), values.map(v => JSON.stringify(v)).join('\n') + '\n');
  save('request.json', { id, station: { name: 'historical fixture', nodes: [], program: [] } });
  save('status.json', { status: 'failed' });
  save('report.json', { passed: false, landed: true, disarmed: true, maximum_altitude_m: 2.21,
    acceptance: { max_altitude_m: 2.2 }, verdicts: { safety: { height_ok: false, clearance_ok: true } },
    failure_events: [{ error: 'planner_emergency', phase: 'waypoint', simulation_s: 11 }] });
  lines('telemetry.jsonl', [10, 11, 12].map(s => ({ simulation_s: s, phase: s === 10 ? 'waypoint' : 'recovery_hover',
    pose: { position: [s + 100, 0, 1] }, telemetry: { altitude_m: 1 }, obstacles: [] })));
  if (options.truth !== false) lines('truth.jsonl', [10, 11].map(s => ({ simulation_s: s, pose: { position: [s, 0, 2] } })));
  lines('ego/trajectory-events.jsonl', [{ trajectory_id: 8, start_sim_s: 10, received_sim_s: 10.1,
    duration_s: 1, order: 3, knots: [-3, -2, -1, 0, 1, 2, 3, 4],
    control_points: [[-1, 0, 2], [0, 0, 2], [1, 0, 2], [2, 0, 2]] }]);
  fs.writeFileSync(path.join(dir, 'ego/planner.log'),
    'odom or depth lost! now=10.2, last_occ_update_time=9.6, last_depth_stamp=9.5; depth_rx=(stamp=9.5,time=9.6,count=10)\n' +
    'ReboundCollision {"first_collision_t":0.04}\n' +
    'RefineGeometry {"stage":"optimized","sim":10.5,"first_collision_t":-1,"speed_bound":1.8,"acceleration_bound":1.01,"max_z":2.19}\n');
  return { root, dir, id };
}

test('recorded curves use their source B-spline, not control polygons or waypoint lines', () => {
  const points = curvePoints({ order: 3, knots: [-3, -2, -1, 0, 1, 2, 3, 4],
    control_points: [[-1, 0, 0], [0, 0, 0], [1, 0, 0], [2, 0, 0]] });
  assert(Math.abs(points[0][0]) < 1e-12);
  assert(Math.abs(points[40][0] - .5) < 1e-12);
  assert(Math.abs(points.at(-1)[0] - 1) < 1e-12);
  assert.deepEqual(curvePoints({ order: 3, knots: [], control_points: [] }), []);
});

test('failure, recovery, source time and unaligned collision witnesses remain separate', t => {
  const { dir } = fixture(t), e = readEvidence(dir);
  assert.equal(e.summary.passed, false);
  assert.equal(e.summary.landed, true);
  assert.equal(e.summary.disarmed, true);
  assert.equal(e.summary.maximum_altitude_m, 2.21);
  assert.equal(e.summary.primary_failure.simulation_s, 11);
  assert.equal(e.summary.backup_available, false);
  assert.equal(e.summary.perception_samples, 1);
  assert.equal(e.summary.events.find(v => v.kind === 'perception').time_s, 10.2);
  const collision = e.summary.events.find(v => v.kind === 'collision');
  assert.equal(collision.time_s, undefined);
  assert.equal(collision.local_time_s, .04);
  assert.equal(e.summary.unaligned_events, 1);
  assert.equal(e.summary.events.find(v => v.kind === 'candidate').kind, 'candidate');
});

test('playback never uses future curves, estimated poses as truth, or stale pose markers', t => {
  const { dir } = fixture(t), frames = [...diagnosticFrames(readEvidence(dir))];
  const early = frames.find(f => f.simulation_s === 10);
  assert(!early.values.scene.entities.some(e => e.id === 'ego-offline-trajectory'));
  const received = frames.find(f => f.simulation_s === 10.1);
  assert(received.values.scene.entities.some(e => e.id === 'ego-offline-trajectory'));
  const last = frames.at(-1);
  assert.equal(last.values.diagnostics.actual_source, 'Gazebo');
  assert(!last.values.scene.entities.some(e => e.id === 'x500-pose-marker'));
  assert(!last.values.scene.entities.some(e => e.id === 'ego-offline-trajectory'));
  const trail = last.values.scene.entities.find(e => e.id === 'diagnostic-actual').lines[0].points;
  assert.deepEqual(trail.map(p => p.x), [10, 11]);
  assert.equal(last.values.diagnostics.current.pose_age_s, 1);
});

test('missing truth and optional logs degrade independently; corrupt rows do not lose the task', t => {
  const { dir } = fixture(t, { truth: false });
  fs.appendFileSync(path.join(dir, 'telemetry.jsonl'), '{broken\n');
  fs.unlinkSync(path.join(dir, 'ego/planner.log'));
  fs.unlinkSync(path.join(dir, 'ego/trajectory-events.jsonl'));
  const evidence = readEvidence(dir);
  assert.equal(evidence.summary.actual_source, 'MAVSDK');
  assert.equal(evidence.summary.nominal_count, 0);
  assert.equal(evidence.summary.perception_samples, 0);
  assert.equal(evidence.summary.warnings.length, 1);
  assert.equal([...diagnosticFrames(evidence)].at(-1).values.diagnostics.passed, false);
});

test('a report for another task cannot change this task verdict or block its playback', t => {
  const { dir } = fixture(t);
  fs.writeFileSync(path.join(dir, 'report.json'), JSON.stringify({ task_id: 'other-flight-456', passed: true }));
  const evidence = readEvidence(dir);
  assert.equal(evidence.summary.passed, undefined);
  assert.equal(evidence.summary.warnings.length, 1);
  assert([...diagnosticFrames(evidence)].length > 0);
});

test('read-only HTTP export keeps original ID, range reads and backward source-time records', async t => {
  const { root, dir, id } = fixture(t);
  const tasksRoot = path.join(root, 'tasks'); fs.mkdirSync(tasksRoot);
  const adapter = createDroneDiagnostics({ runtime: { paths: { tasksRoot, sourceRoot: root } }, archiveRoot: path.join(root, 'archive') });
  const serve = upstream('serve-handler');
  const server = http.createServer(async (req, res) => {
    if (await adapter.handle(req, res, serve)) return;
    res.writeHead(404);res.end();
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { await new Promise(resolve => server.close(resolve)); });
  const base = `http://127.0.0.1:${server.address().port}`;
  const list = await (await fetch(`${base}/api/drone/diagnostics`)).json();
  assert.equal(list.tasks[0].id, id);
  assert.equal(list.tasks[0].dir, undefined);
  const redirect = await fetch(`${base}/drone-diagnostics?taskId=${id}`, { redirect: 'manual' });
  assert.equal(redirect.status, 302);
  assert(redirect.headers.get('location').includes('ds=remote-file'));
  assert(!redirect.headers.get('location').includes('websocket'));
  const url = `${base}/api/drone/diagnostics/${id}/diagnostics.mcap`;
  const range = await fetch(url, { headers: { Range: 'bytes=0-7' } });
  assert.equal(range.status, 206);
  assert.equal(Buffer.from(await range.arrayBuffer()).toString('hex'), '894d434150300d0a');
  const bytes = Buffer.from(await (await fetch(url)).arrayBuffer());
  const reader = await McapIndexedReader.Initialize({ readable: { size: async () => BigInt(bytes.length), read: async (o, n) => bytes.subarray(Number(o), Number(o + n)) } });
  const decoded = [];
  for await (const msg of reader.readMessages({ topics: ['/drone/diagnostics'], reverse: true, validateCrcs: true })) {
    decoded.push({ time: msg.logTime, value: JSON.parse(Buffer.from(msg.data)) });
  }
  assert.equal(decoded[0].time, 12000000000n);
  assert.equal(decoded.at(-1).time, 10000000000n);
  assert(decoded.every(v => v.value.task_id === id && v.value.passed === false));
  assert.equal((await fetch(`${base}/api/drone/diagnostics/${id}`, { method: 'POST' })).status, 405);
  assert.equal((await fetch(`${base}/api/drone/diagnostics/missing-id-123`)).status, 404);
  assert.equal((await fetch(`${base}/api/drone/diagnostics/${id}`, { headers: { Origin: 'https://unrelated.example' } })).status, 403);
  assert(!fs.existsSync(path.join(dir, 'cancel.request')));
  assert(!fs.existsSync(path.join(dir, 'flight.mcap')));
  const original = JSON.parse(fs.readFileSync(path.join(dir, 'report.json')));
  fs.writeFileSync(path.join(dir, 'report.json'), JSON.stringify({ ...original, maximum_altitude_m: 2.3 }));
  const updated = await (await fetch(`${base}/api/drone/diagnostics/${id}`)).json();
  assert.equal(updated.maximum_altitude_m, 2.3);
  await fetch(url);
});
