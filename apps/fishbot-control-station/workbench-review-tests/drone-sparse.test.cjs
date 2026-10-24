// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { readSparse, sparseAt, sparseEntities } = require('../drone-sparse.cjs');
const data = { available: true, task_id: 'sparse-flight-123', clock_epochs: 1,
  samples: [{ stream: 'front', source_stamp_s: 10, available_sim_s: 10.1, epoch: 0,
    pose_frame: 'world', pose_state: 'recorded_source_pose', origin_world: [1, 2, 3],
    rays: [{ id: 'front-left', state: 'hit', range_m: 4, endpoint_world: [5, 2, 3] }] },
  { stream: 'down', source_stamp_s: 9.5, available_sim_s: 9.7, epoch: 0,
    pose_frame: 'world', pose_state: 'recorded_source_pose', origin_world: [1, 2, 3],
    rays: [{ id: 'down', state: 'hit', endpoint_world: [1, 2, 0] }] }].sort((a, b) => a.available_sim_s - b.available_sim_s) };
test('no future observations, independent streams and expiring source-pose rays', () => {
  assert.equal(sparseAt(data, 10.05).streams.front, undefined);
  const snap = sparseAt(data, 10.15);
  assert.equal(snap.streams.front.fresh, true);
  assert.equal(snap.streams.down.fresh, false);
  const scene = sparseEntities(snap, 10.15);
  assert.equal(scene.length, 1);
  assert(Math.abs(scene[0].lifetime.nsec - 100000000) <= 1);
  assert.equal(sparseAt(data, 10.25).streams.front.fresh, false);
  assert.equal(sparseEntities(sparseAt(data, 10.25), 10.25).length, 0);
  assert.equal(sparseEntities(sparseAt(data, 10.3), 10.3).length, 0);
});
test('missing, mismatched, or multiple-epoch exports do not contaminate the original recording', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'sparse-view-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'sparse.json');
  assert.equal(readSparse(file, data.task_id).available, false);
  fs.writeFileSync(file, JSON.stringify({ ...data, schema_version: 1 }));
  assert.equal(readSparse(file, data.task_id).available, true);
  assert.equal(readSparse(file, 'other-flight-123').available, false);
  fs.writeFileSync(file, JSON.stringify({ ...data, schema_version: 1, clock_epochs: 2 }));
  assert.equal(readSparse(file, data.task_id).available, false);
});
test('unsupported pose frames and invalid rays never become world-space measurements', () => {
  const snap = sparseAt(data, 10.1);
  snap.streams.front = { ...snap.streams.front, pose_frame: 'unknown' };
  assert.equal(sparseEntities(snap, 10.1).length, 0);
  assert.equal(sparseEntities(sparseAt(undefined, 10), 10).length, 0);
});
