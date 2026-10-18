'use strict';

// Acceptance boundaries only. These tests do not claim a real 1800s run.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { feedbackCriterion, longRunCriterion, sceneCriteriaPassed } = require('../fishbot_workbench_scene_ui_contract.cjs');

function sample(input, milliseconds) {
  return { input, milliseconds, clock_validated: true, raw_timing: { trusted: true,
    event_type: input === 'pointer' ? 'pointerdown' : 'keydown', event_ms: 10, listener_ms: 11, aria_ms: 12, raf_ms: 10 + milliseconds } };
}
const goodLong = { elapsed_s: 1800, sample_count: 360, offered_hz: 20, received_hz: 20, rendered_hz: 20.5,
  post_gc_growth_bytes: 32 * 1048576, post_gc_slope_mib_per_min: 2, listener_delta: 50 };
function criteria(preflight = [sample('pointer', 100), sample('keyboard', 100)]) {
  return { C03: { preflight: feedbackCriterion(preflight), final: feedbackCriterion(preflight) }, C04: longRunCriterion(goodLong),
    graphics: { status: 'passed' }, functional: { status: 'passed' }, cleanup: { status: 'passed' }, source: { status: 'passed' } };
}

test('the exact 100ms boundary passes; queue time and either input type over 100ms fail independently', () => {
  assert.equal(feedbackCriterion([sample('pointer', 100), sample('keyboard', 100)]).status, 'passed');
  for (const input of ['pointer', 'keyboard']) {
    const result = feedbackCriterion([sample('pointer', input === 'pointer' ? 100.001 : 20), sample('keyboard', input === 'keyboard' ? 100.001 : 20)]);
    assert.equal(result.status, 'failed');
  }
});

test('missing, untrusted, stale clocks and altered derived values cannot yield a feedback pass', () => {
  assert.equal(feedbackCriterion([]).status, 'incomplete');
  assert.equal(feedbackCriterion([sample('pointer', 20)]).status, 'incomplete');
  for (const changed of [
    { ...sample('pointer', 20), clock_validated: false },
    { ...sample('pointer', 20), milliseconds: 1 },
    { ...sample('pointer', 20), raw_timing: { ...sample('pointer', 20).raw_timing, event_type: 'keydown' } },
    { ...sample('pointer', 20), raw_timing: { ...sample('pointer', 20).raw_timing, trusted: false } },
    { ...sample('pointer', 20), raw_timing: { ...sample('pointer', 20).raw_timing, event_ms: 1792263000000 } },
  ]) assert.equal(feedbackCriterion([changed, sample('keyboard', 20)]).status, 'failed');
});

test('C03 failure survives later fast samples while independent C04 can pass its original boundaries', () => {
  const value = criteria([sample('pointer', 108.8), sample('keyboard', 65.6)]);
  const later = Array.from({ length: 100 }, (_, i) => sample(i % 2 ? 'pointer' : 'keyboard', 20));
  value.C03.final = feedbackCriterion([sample('pointer', 108.8), sample('keyboard', 65.6), ...later]);
  assert.equal(value.C03.final.status, 'passed');
  assert.equal(value.C03.preflight.status, 'failed');
  assert.equal(value.C04.status, 'passed');
  assert.equal(sceneCriteriaPassed(value), false);
});

test('all original long-run boundaries stay required, and missing finite measurements cannot pass', () => {
  assert.equal(longRunCriterion(goodLong).status, 'passed');
  for (const change of [{ elapsed_s: 1799.999 }, { sample_count: 0 }, { offered_hz: 17.999 }, { offered_hz: 22.001 }, { received_hz: 17.999 },
    { received_hz: 22.001 }, { rendered_hz: 0 }, { rendered_hz: 20.501 }, { post_gc_growth_bytes: 32 * 1048576 + 1 },
    { post_gc_slope_mib_per_min: 2.001 }, { post_gc_slope_mib_per_min: null }, { listener_delta: 51 }]) {
    assert.equal(longRunCriterion({ ...goodLong, ...change }).status, 'failed', JSON.stringify(change));
  }
  assert.equal(longRunCriterion().status, 'failed');
});

test('incomplete long runs, missing cleanup and unknown source remain failures even when input feedback passes', () => {
  assert.equal(sceneCriteriaPassed(criteria()), true);
  for (const state of ['failed', 'incomplete', 'not_run', 'unknown']) {
    const value = criteria(); value.C04.status = state; assert.equal(sceneCriteriaPassed(value), false);
    for (const key of ['graphics', 'functional', 'cleanup', 'source']) {
      const changed = criteria(); changed[key].status = state; assert.equal(sceneCriteriaPassed(changed), false, `${key}/${state}`);
    }
  }
  const short = criteria(); short.C04 = { requested_s: 0, status: 'not_requested' }; assert.equal(sceneCriteriaPassed(short), true);
  short.C04.requested_s = 1800; assert.equal(sceneCriteriaPassed(short), false);
});
