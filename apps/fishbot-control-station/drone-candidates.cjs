// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// Optional offline comparison. This module cannot submit a flight.
const fs = require('node:fs');
const { stamp } = require('./drone-scene.cjs');
function readCandidates(file, id) {
  let data;
  try { data = JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch { return { available: false, reason: '此回合未生成离线刹停对照。' }; }
  if (data?.schema_version !== 1 || data.archive_task_id !== id || !Array.isArray(data.rows)) {
    return { available: false, reason: '离线候选身份或格式不符，保留原回放。' };
  }
  const rows = data.rows.filter(row => row && typeof row === 'object' && !Array.isArray(row));
  if (rows.length !== data.rows.length) console.warn('WARNING: skipped unreadable offline candidate rows; original playback retained.');
  return { ...data, rows, available: true };
}
function candidateAt(data, parentId, seconds) {
  if (!data?.available) return { schema_version: 1, available: false, reason: data?.reason };
  const row = data.rows.find(value => value.trajectory_id === parentId);
  const base = { schema_version: 1, available: true, task_id: data.archive_task_id, summary: data.summary,
    parent_id: parentId, occupancy: 'unverified', execution_admission: 'not_performed' };
  if (parentId === undefined || !row) return { ...base, state: 'no_parent_candidate' };
  if (row.status !== 'generated') return { ...base, state: row.status, reason: row.reason };
  if (!row.full_math_gate || !Number.isFinite(row.source_received_sim_s) || !Number.isFinite(row.end_sim_s)) {
    return { ...base, state: 'candidate_incomplete' };
  }
  if (row.recorded_task_id !== data.archive_task_id || row.source_received_sim_s > seconds ||
      !Number.isFinite(row.start_sim_s) || seconds < row.start_sim_s || seconds > row.end_sim_s) {
    return { ...base, state: 'unavailable_at_source_time' };
  }
  return { ...base, state: 'offline_candidate', cut_sim_s: row.cut_sim_s,
    mathematical_passed: row.full_math_gate.passed, failed_checks: row.full_math_gate.failed_checks,
    speed_max: row.full_math_gate.speed_max, acceleration_max: row.full_math_gate.acceleration_max,
    height_max: row.full_math_gate.height_max, cut_pvaj_error: row.cut_pvaj_error,
    cut_c3_passed: row.cut_c3_passed, offline_wall_ms: row.offline_wall_ms, preview_points: row.preview_points };
}
function candidateEntities(snapshot, seconds) {
  if (snapshot.state !== 'offline_candidate' || !Array.isArray(snapshot.preview_points) ||
      !snapshot.preview_points.every(p => Array.isArray(p) && p.length === 3 && p.every(Number.isFinite))) return [];
  return [{ id: `offline-stop-${snapshot.parent_id}`, frame_id: 'world', timestamp: stamp(seconds),
    lifetime: { sec: 0, nsec: 0 }, frame_locked: false,
    metadata: [{ key: 'scope', value: 'offline counterfactual; occupancy unknown; never executed' }],
    lines: [{ type: 0, pose: { position: { x: 0, y: 0, z: 0 }, orientation: { x: 0, y: 0, z: 0, w: 1 } },
      thickness: 3, scale_invariant: true, points: snapshot.preview_points.map(p => ({ x: p[0], y: p[1], z: p[2] })),
      colors: [], indices: [], color: snapshot.mathematical_passed ? { r: .85, g: .08, b: .85, a: 1 } : { r: 1, g: .08, b: .12, a: 1 } }] }];
}
function candidateMessage(snapshot) { const { preview_points, ...message } = snapshot; return message; }
module.exports = { readCandidates, candidateAt, candidateEntities, candidateMessage };
