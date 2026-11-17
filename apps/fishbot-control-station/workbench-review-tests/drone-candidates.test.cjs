// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs'), os = require('node:os'), path = require('node:path');
const { readCandidates, candidateAt, candidateEntities, candidateMessage } = require('../drone-candidates.cjs');
const data = { available: true, archive_task_id: 'original-task', rows: [
  { trajectory_id: 1, status: 'generated', recorded_task_id: 'original-task', source_received_sim_s: 10,
    start_sim_s: 10, end_sim_s: 14, full_math_gate: { passed: false, failed_checks: ['acceleration'] },
    preview_points: [[0,0,1],[1,0,1]] }, { trajectory_id: 2, status: 'unscored', reason: 'source_task_identity_unrecorded' }] };
test('candidates follow original parent and source time; replacement never inherits the previous tail', () => {
  assert.equal(candidateEntities(candidateAt(data, 1, 9), 9).length, 0);
  assert.equal(candidateEntities(candidateAt(data, 1, 10), 10).length, 1);
  assert.equal(candidateEntities(candidateAt(data, 2, 11), 11).length, 0);
  assert.equal(candidateEntities(candidateAt(data, undefined, 11), 11).length, 0);
  assert.equal(candidateEntities(candidateAt(data, 1, 15), 15).length, 0);
  assert.equal(candidateAt(data, 2, 11).reason, 'source_task_identity_unrecorded');
});
test('a mathematical rejection is visible while every candidate retains non-admission', () => {
  const snap = candidateAt(data, 1, 11);
  assert.equal(snap.mathematical_passed, false);
  assert.equal(snap.occupancy, 'unverified');
  assert.equal(snap.execution_admission, 'not_performed');
  assert.equal(candidateEntities(snap, 11)[0].lines[0].color.r, 1);
  assert.equal(candidateMessage(snap).preview_points, undefined);
  assert.equal(candidateEntities({ ...snap, preview_points: [[NaN,0,1]] }, 11).length, 0);
});
test('missing, mismatched and incomplete optional comparisons degrade without changing the task', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'drone-candidates-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'candidates.json');
  assert.equal(readCandidates(file, 'original-task').available, false);
  fs.writeFileSync(file, 'null');
  assert.equal(readCandidates(file, 'original-task').available, false);
  fs.writeFileSync(file, JSON.stringify({ ...data, schema_version: 1 }));
  assert.equal(readCandidates(file, 'original-task').available, true);
  assert.equal(readCandidates(file, 'another-task').available, false);
  fs.writeFileSync(file, JSON.stringify({ ...data, schema_version: 1, rows: [null, ...data.rows] }));
  assert.equal(readCandidates(file, 'original-task').rows.length, 2);
  assert.equal(candidateAt({ ...data, rows: [{ ...data.rows[0], full_math_gate: null }] }, 1, 11).state, 'candidate_incomplete');
});
