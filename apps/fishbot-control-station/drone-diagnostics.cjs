// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// Read recorded evidence only. This module has no flight-control client or command writer.
const fs = require('node:fs');
const path = require('node:path');
const { sceneFor, schema, telemetrySchema, stamp } = require('./drone-scene.cjs');
const { writeFrames } = require('./drone-recording.cjs');
const VALID_ID = /^[a-zA-Z0-9][a-zA-Z0-9_-]{7,79}$/;
const TOPIC = '/drone/diagnostics';
const SCHEMA = 'drone.Diagnostics';
const finite = value => typeof value === 'number' && Number.isFinite(value);
const vector = value => Array.isArray(value) && value.length === 3 && value.every(finite);
function json(file) { try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return undefined; } }
function text(file) { try { return fs.readFileSync(file, 'utf8'); } catch { return ''; } }
function rows(file, warnings) {
  const result = [];
  for (const [i, line] of text(file).split('\n').entries()) {
    if (!line.trim()) continue;
    try { result.push(JSON.parse(line)); }
    catch { warnings.push(`${path.basename(file)}:${i + 1} 无法解析，已跳过该行。`); }
  }
  return result;
}
// de Boor evaluation is for displaying the recorded curve, never collision acceptance.
function curvePoints(curve) {
  const { order: degree, knots, control_points: points } = curve;
  if (!Number.isInteger(degree) || degree < 1 || degree > 7 || !Array.isArray(points) ||
      points.length <= degree || !points.every(vector) || !Array.isArray(knots) ||
      knots.length !== points.length + degree + 1 || !knots.every(finite) ||
      knots.some((x, i) => i && x < knots[i - 1])) return [];
  const start = knots[degree], end = knots[points.length];
  if (!(end > start)) return [];
  return Array.from({ length: 81 }, (_, i) => {
    const t = start + (end - start) * i / 80;
    let k = degree;
    while (k < points.length - 1 && knots[k + 1] <= t) k++;
    const d = Array.from({ length: degree + 1 }, (_, j) => [...points[k - degree + j]]);
    for (let r = 1; r <= degree; r++) for (let j = degree; j >= r; j--) {
      const q = k - degree + j, den = knots[q + degree - r + 1] - knots[q];
      const a = den === 0 ? 0 : (t - knots[q]) / den;
      d[j] = d[j].map((x, axis) => (1 - a) * d[j - 1][axis] + a * x);
    }
    return d[degree];
  });
}
function readEvidence(dir) {
  const warnings = [], request = json(path.join(dir, 'request.json')) ?? {};
  const recordedReport = json(path.join(dir, 'report.json')) ?? {}, status = json(path.join(dir, 'status.json')) ?? {};
  const mismatchedReport = recordedReport.task_id && recordedReport.task_id !== request.id;
  const report = mismatchedReport ? {} : recordedReport;
  if (mismatchedReport) warnings.push('report.json的task_id与原请求不同，仅跳过该报告；轨迹仍可回放。');
  const timed = name => rows(path.join(dir, name), warnings)
    .filter(row => finite(row.simulation_s) && row.simulation_s >= 0).sort((a, b) => a.simulation_s - b.simulation_s);
  const telemetry = timed('telemetry.jsonl'), truth = timed('truth.jsonl');
  const hasTruth = truth.some(row => vector(row.pose?.position));
  const actual = (hasTruth ? truth : telemetry).filter(row => vector(row.pose?.position));
  const actualSource = hasTruth ? 'Gazebo' : 'MAVSDK';
  const curves = rows(path.join(dir, 'ego/trajectory-events.jsonl'), warnings)
    .filter(curve => (!curve.task_id || curve.task_id === request.id) && finite(curve.start_sim_s) && finite(curve.received_sim_s) && curve.duration_s > 0)
    .map(curve => ({ ...curve, points: curvePoints(curve) })).filter(curve => curve.points.length)
    .sort((a, b) => a.received_sim_s - b.received_sim_s);
  const events = [], perception = [];
  const add = event => events.push({ id: `event-${events.length}`, ...event });
  let phase;
  for (const sample of telemetry) if (sample.phase && sample.phase !== phase) {
    phase = sample.phase;
    add({ kind: 'phase', time_s: sample.simulation_s, label: phase, source: 'telemetry.jsonl' });
  }
  for (const event of report.failure_events ?? []) add({ kind: 'failure', time_s: event.simulation_s,
    label: event.error ?? '任务失败', detail: event.phase, source: 'report.json' });
  const log = text(path.join(dir, 'ego/planner.log')).replace(/\x1b\[[0-9;]*m/g, '');
  for (const [i, line] of log.split('\n').entries()) {
    const lost = /odom or depth lost! now=([\d.]+), last_occ_update_time=([\d.]+), last_depth_stamp=([\d.]+)/.exec(line);
    if (lost) {
      const receive = /depth_rx=\(stamp=([\d.]+),time=([\d.]+)/.exec(line);
      const matched = /matched=\(pose_stamp=([\d.]+),time=([\d.]+)/.exec(line);
      const value = { time_s: +lost[1], depth_stamp_s: +lost[3], fused_s: +lost[2],
        ...(receive ? { received_s: +receive[2] } : {}), source: `ego/planner.log:${i + 1}` };
      perception.push(value);
      add({ kind: 'perception', time_s: value.time_s, label: '深度/里程计失流', source: value.source,
        detail: `源 ${value.depth_stamp_s.toFixed(3)}s；接收 ${value.received_s?.toFixed(3) ?? '未知'}s；位姿匹配 ${matched ? (+matched[2]).toFixed(3) : '未知'}s；融合 ${value.fused_s.toFixed(3)}s；均为仿真时钟` });
    }
    if (line.includes('RefineGeometry {') || line.includes('ReboundCollision {')) {
      let value;
      try { value = JSON.parse(line.slice(line.indexOf('{'))); }
      catch { warnings.push(`ego/planner.log:${i + 1} 诊断JSON损坏，已跳过。`); continue; }
      const collision = value.first_collision_t >= 0;
      add({ kind: collision ? 'collision' : 'candidate', ...(finite(value.sim) ? { time_s: value.sim } : {}),
        label: collision ? '候选碰撞见证' : `候选界诊断 · ${value.stage ?? 'unknown'}`,
        local_time_s: collision ? value.first_collision_t : undefined,
        detail: collision ? `局部曲线时间 ${value.first_collision_t.toFixed(3)}s；缺绝对时刻时不映射到播放轴。` :
          `V界 ${value.speed_bound?.toFixed(3) ?? '?'}；A界 ${value.acceleration_bound?.toFixed(3) ?? '?'}；Z界 ${value.max_z?.toFixed(3) ?? '?'}。阶段诊断不等同最终拒绝。`,
        source: `ego/planner.log:${i + 1}` });
    }
  }
  for (const curve of curves) add({ kind: 'curve', time_s: curve.received_sim_s,
    label: `收到名义曲线 #${curve.trajectory_id}`, detail: `曲线起点 ${curve.start_sim_s.toFixed(3)}s；时长 ${curve.duration_s.toFixed(3)}s；不代表整段已执行。`,
    source: 'ego/trajectory-events.jsonl' });
  const times = [...telemetry, ...actual].map(row => row.simulation_s).sort((a, b) => a - b);
  const start = times[0], end = times.at(-1);
  const limits = [];
  if (!hasTruth) limits.push('未记录Gazebo真值；橙色轨迹仅为MAVSDK估计。');
  if (!curves.length) limits.push('未记录可显示的名义B样条；不以航点折线替代。');
  limits.push('青色备份轨迹未记录；离线MINCO候选不属于本次飞行。');
  limits.push(perception.length ? '深度时序仅含失流日志见证，非全帧延迟统计；不与墙钟相减。' : '未记录可对齐的感知时序，延迟保持未知。');
  limits.push('实际轨迹来自已保存的位姿样本；原报告全频评分与此显示采样分开。');
  const summary = { schema_version: 1, task_id: request.id, task_name: request.station?.name ?? request.id,
    clock: 'simulation_seconds_not_unix', status: status.status ?? report.status ?? 'unknown',
    passed: report.passed, function_verdict: report.verdicts?.function?.verdict ?? 'unknown',
    safety: report.verdicts?.safety ?? {}, landed: report.landed, disarmed: report.disarmed,
    maximum_altitude_m: report.maximum_altitude_m, altitude_limit_m: report.acceptance?.max_altitude_m,
    primary_failure: report.failure_events?.[0], actual_source: actualSource,
    nominal_count: curves.length, backup_available: false, perception_samples: perception.length,
    unaligned_events: events.filter(event => !finite(event.time_s)).length,
    recording: { start_s: start, end_s: end, truth_samples: truth.length, telemetry_samples: telemetry.length },
    events: events.sort((a, b) => (a.time_s ?? Infinity) - (b.time_s ?? Infinity)), limitations: limits, warnings };
  return { dir, request, report, summary, telemetry, actual, curves, perception };
}
function* diagnosticFrames(evidence, sceneOptions = {}) {
  const { telemetry, actual, curves, summary } = evidence;
  const times = [...new Set([...telemetry.map(s => s.simulation_s), ...actual.map(s => s.simulation_s),
    ...summary.events.filter(e => finite(e.time_s) && e.time_s >= summary.recording.start_s && e.time_s <= summary.recording.end_s).map(e => e.time_s)])].sort((a, b) => a - b);
  let ti = -1, ai = -1, ci = -1;
  const trajectory = [];
  for (const seconds of times) {
    while (ti + 1 < telemetry.length && telemetry[ti + 1].simulation_s <= seconds) ti++;
    while (ai + 1 < actual.length && actual[ai + 1].simulation_s <= seconds) {
      ai++; trajectory.push(actual[ai].pose.position);
    }
    while (ci + 1 < curves.length && curves[ci + 1].received_sim_s <= seconds) ci++;
    const sample = telemetry[ti] ?? {}, poseSample = actual[ai];
    const fresh = poseSample && seconds - poseSample.simulation_s <= .25;
    const currentCurve = curves[ci], activeCurve = currentCurve && seconds <= currentCurve.start_sim_s + currentCurve.duration_s;
    const scene = sceneFor(evidence.request.station, { ...sample, simulation_s: seconds,
      pose: fresh ? poseSample.pose : undefined, trajectory: [], obstacles: sample.obstacles ?? [] },
      { ...sceneOptions, assetBase: '', ...(activeCurve ? { plan: { points: currentCurve.points, planner: 'recorded EGO' } } : {}) });
    scene.deletions = [{ type: 1, id: '', timestamp: stamp(seconds) }];
    // Waypoints are goals, not the nominal planner output.
    scene.entities = scene.entities.filter(entity => entity.id !== 'planned-waypoints');
    const placeholder = scene.entities.find(entity => entity.id === 'x500-pose-marker');
    if (placeholder) placeholder.texts[0].text = 'X500 位姿示意（无网格）';
    if (trajectory.length > 1) scene.entities.push({ id: 'diagnostic-actual', frame_id: 'world', timestamp: stamp(seconds),
      lifetime: { sec: 0, nsec: 0 }, frame_locked: false, metadata: [],
      lines: [{ type: 0, pose: { position: { x: 0, y: 0, z: 0 }, orientation: { x: 0, y: 0, z: 0, w: 1 } },
        thickness: .04, scale_invariant: false, points: trajectory.map(p => ({ x: p[0], y: p[1], z: p[2] })),
        color: summary.actual_source === 'Gazebo' ? { r: .15, g: .8, b: .4, a: 1 } : { r: 1, g: .55, b: .15, a: 1 }, colors: [], indices: [] }] });
    const current = { phase: sample.phase ?? 'unknown', actual_stamp_s: poseSample?.simulation_s,
      pose_age_s: poseSample ? seconds - poseSample.simulation_s : undefined,
      nominal_id: activeCurve ? currentCurve.trajectory_id : undefined,
      reference_age_s: finite(sample.reference?.simulation_s) ? seconds - sample.reference.simulation_s : undefined };
    yield { simulation_s: seconds, values: { scene, telemetry: { ...sample.telemetry,
      truth_altitude_m: fresh ? poseSample.pose.position[2] : undefined }, diagnostics: { ...summary, current } } };
  }
}
function createDroneDiagnostics({ runtime, cacheRoot, archiveRoot = path.join(runtime.paths.sourceRoot, 'output'), sceneOptions = () => ({}) }) {
  cacheRoot ??= path.join(path.dirname(runtime.paths.tasksRoot), 'drone-diagnostics');
  const pending = new Map(), cached = new Map();
  function catalogue() {
    const found = new Map();
    for (const root of [runtime.paths.tasksRoot, archiveRoot]) {
      let entries; try { entries = fs.readdirSync(root, { withFileTypes: true }); } catch { continue; }
      for (const entry of entries) {
        if (!entry.isDirectory()) continue;
        const dir = path.join(root, entry.name), request = json(path.join(dir, 'request.json'));
        if (!VALID_ID.test(request?.id ?? '') || found.has(request.id)) continue;
        const status = json(path.join(dir, 'status.json')) ?? {}, report = json(path.join(dir, 'report.json'));
        if (!['failed', 'succeeded', 'cancelled'].includes(status.status) && !report) continue;
        found.set(request.id, { id: request.id, name: request.station?.name ?? request.id,
          status: status.status ?? report?.status ?? 'unknown', dir });
      }
    }
    return [...found.values()];
  }
  async function recording(item) {
    if (pending.has(item.id)) return pending.get(item.id);
    const promise = (async () => {
      const inputs = ['request.json', 'status.json', 'report.json', 'truth.jsonl', 'telemetry.jsonl', 'ego/trajectory-events.jsonl', 'ego/planner.log'];
      const renderOptions = sceneOptions();
      const version = inputs.map(name => { try { const s = fs.statSync(path.join(item.dir, name)); return `${name}:${s.size}:${s.mtimeMs}`; } catch { return name; } }).join('|') + JSON.stringify(renderOptions.models ?? []);
      const dir = path.join(cacheRoot, item.id), file = path.join(dir, 'diagnostics.mcap');
      if (cached.get(item.id) === version && fs.existsSync(file)) return file;
      const evidence = readEvidence(item.dir);
      if (!finite(evidence.summary.recording.start_s)) throw new Error('原记录没有可回放的带时刻位姿或遥测。');
      fs.mkdirSync(dir, { recursive: true });
      await writeFrames(file, {
        scene: { name: 'foxglove.SceneUpdate', topic: '/drone/live/scene', schema },
        telemetry: { name: 'drone.Telemetry', topic: '/drone/live/telemetry', schema: { ...telemetrySchema,
          properties: { ...telemetrySchema.properties, truth_altitude_m: { type: 'number' } } } },
        diagnostics: { name: SCHEMA, topic: TOPIC, schema: { type: 'object', properties: {} } },
      }, diagnosticFrames(evidence, renderOptions));
      cached.set(item.id, version); return file;
    })().finally(() => pending.delete(item.id));
    pending.set(item.id, promise); return promise;
  }
  async function handle(req, res, serveHandler) {
    const url = new URL(req.url, 'http://localhost'), route = url.pathname;
    if (route !== '/drone-diagnostics' && !route.startsWith('/api/drone/diagnostics')) return false;
    const send = (code, value) => { res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(value)); };
    const host = new URL(`http://${req.headers.host ?? 'localhost'}`);
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(host.hostname) || (req.headers.origin && req.headers.origin !== host.origin)) {
      send(403, { error: '请从本机工作台读取诊断。' }); return true;
    }
    if (!['GET', 'HEAD'].includes(req.method)) { send(405, { error: '诊断只读，不接受控制请求。' }); return true; }
    try {
      const items = catalogue();
      if (route === '/api/drone/diagnostics') {
        send(200, { tasks: items.map(({ dir: _dir, ...item }) => ({ ...item, url: `/drone-diagnostics?taskId=${item.id}` })) }); return true;
      }
      const match = /^\/api\/drone\/diagnostics\/([a-zA-Z0-9_-]+)(\/diagnostics\.mcap)?$/.exec(route);
      const id = route === '/drone-diagnostics' ? url.searchParams.get('taskId') ?? items[0]?.id : match?.[1];
      const item = items.find(value => value.id === id);
      if (!item) { send(404, { error: '未找到原任务记录，请从历史任务选择可用回合。' }); return true; }
      if (route === '/drone-diagnostics') {
        await recording(item);
        const layout = url.searchParams.get('mobile') === '1' ? 'drone-diagnostics-mobile' : 'drone-diagnostics';
        const query = new URLSearchParams({ ds: 'remote-file', 'ds.url': `${host.origin}/api/drone/diagnostics/${item.id}/diagnostics.mcap`, layoutUrl: `${host.origin}/layouts/${layout}.json` });
        res.writeHead(302, { Location: `/?${query}` }); res.end(); return true;
      }
      if (!match[2]) { send(200, readEvidence(item.dir).summary); return true; }
      const file = await recording(item);
      req.url = '/diagnostics.mcap';
      await serveHandler(req, res, { public: path.dirname(file), directoryListing: false, cleanUrls: false, etag: true });
    } catch (error) { send(500, { error: `无法读取历史诊断：${error.message}` }); }
    return true;
  }
  return { handle, catalogue, recording };
}
module.exports = { createDroneDiagnostics, readEvidence, diagnosticFrames, curvePoints };
