// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// A viewer for offline exports. No image synthesis, policy, or flight-control dependency.
const fs = require('node:fs');
const { stamp } = require('./drone-scene.cjs');
function readSparse(file, id) {
  let value;
  try { value = JSON.parse(fs.readFileSync(file, 'utf8')); }
  catch { return { available: false, reason: '未生成可读的稀疏观测导出。', samples: [] }; }
  if (value.schema_version !== 1 || value.task_id !== id || !Array.isArray(value.samples)) {
    return { available: false, reason: '稀疏导出的任务或格式不匹配，保留原诊断。', samples: [] };
  }
  if (value.clock_epochs !== 1) return { available: false, reason: '原包含多个时钟回合，未合并到单回合播放轴。', samples: [] };
  return { ...value, available: true, samples: value.samples.filter(row =>
    Number.isFinite(row.available_sim_s) && Number.isFinite(row.source_stamp_s) &&
    row.epoch === 0 && row.available_sim_s >= row.source_stamp_s && Array.isArray(row.rays))
    .sort((a, b) => a.available_sim_s - b.available_sim_s) };
}
function sparseAt(data, seconds) {
  if (!data?.available) return { schema_version: 1, available: false, reason: data?.reason ?? '未记录稀疏观测。' };
  const streams = {};
  for (const row of data.samples) {
    if (row.available_sim_s > seconds) break;
    streams[row.stream] = { ...row, age_s: seconds - row.source_stamp_s, fresh: seconds - row.source_stamp_s < .25 };
  }
  return { schema_version: 1, available: true, task_id: data.task_id, kind: data.kind,
    method: data.method, summary: data.summary, limitations: data.limitations, calibration: data.calibration,
    source_pose_provenance: data.source_pose_provenance, streams };
}
function sparseEntities(snapshot, seconds) {
  const entities = [];
  for (const [stream, sample] of Object.entries(snapshot.streams ?? {})) {
    const remaining = .25 - (seconds - sample.source_stamp_s);
    if (!sample.fresh || remaining <= 0 || sample.pose_state !== 'recorded_source_pose' || sample.pose_frame !== 'world' || !Array.isArray(sample.origin_world)) continue;
    const origin = sample.origin_world;
    for (const ray of sample.rays) {
      if (!Array.isArray(ray.endpoint_world) || !ray.endpoint_world.every(Number.isFinite)) continue;
      const point = p => ({ x: p[0], y: p[1], z: p[2] });
      entities.push({ id: `sparse-${stream}-${ray.id}`, frame_id: 'world', timestamp: stamp(seconds),
        lifetime: { sec: 0, nsec: Math.round(remaining * 1e9) }, frame_locked: false,
        metadata: [{ key: 'source_stamp_s', value: String(sample.source_stamp_s) }, { key: 'sensor_state', value: ray.state },
          { key: 'pose_source', value: 'recorded optical pose; ideal Gazebo positioning' }],
        lines: [{ type: 0, pose: { position: { x: 0, y: 0, z: 0 }, orientation: { x: 0, y: 0, z: 0, w: 1 } },
          thickness: 2, scale_invariant: true, points: [point(origin), point(ray.endpoint_world)], colors: [], indices: [],
          color: sample.fresh ? { r: .75, g: .4, b: .9, a: ray.state === 'hit' ? 1 : .35 } : { r: .5, g: .5, b: .5, a: .3 } }],
      });
    }
  }
  return entities;
}
module.exports = { readSparse, sparseAt, sparseEntities };
