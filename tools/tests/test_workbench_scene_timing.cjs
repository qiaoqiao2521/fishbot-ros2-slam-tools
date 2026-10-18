'use strict';

// Pure contract checks. Importing the runner neither loads Playwright nor opens
// a browser/server, creates evidence files, or sends a ROS/API request.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { trustedFeedbackTiming } = require('../fishbot_workbench_scene_ui_contract.cjs');

const sample = { trusted: true, event_ms: 100, listener_ms: 180, aria_ms: 200, raf_ms: 220 };

test('input feedback includes queue time that a listener-only measurement omits', () => {
  const result = trustedFeedbackTiming(sample);
  assert.equal(result.input_to_listener_ms, 80);
  assert.equal(result.listener_to_aria_ms, 20);
  assert.equal(result.aria_to_raf_ms, 20);
  assert.equal(result.input_to_raf_ms, 120);
  assert.equal(result.legacy_capture_to_aria_ms, 20);
  assert.equal(result.legacy_capture_to_raf_ms, 40);
  assert.ok(result.input_to_raf_ms > 100);
  assert.ok(result.legacy_capture_to_raf_ms < 100);
});

test('untrusted, NaN, infinite and negative timestamps cannot produce a score', () => {
  assert.throws(() => trustedFeedbackTiming({ ...sample, trusted: false }));
  for (const field of ['event_ms', 'listener_ms', 'aria_ms', 'raf_ms']) {
    for (const value of [NaN, Infinity, -1, '100', null]) {
      assert.throws(() => trustedFeedbackTiming({ ...sample, [field]: value }), `${field}=${value}`);
    }
  }
});

test('mixed epoch and monotonic clocks, reversed order and over-budget queue are rejected without clamping', () => {
  for (const change of [
    { event_ms: 1792263000000 }, { listener_ms: 99 }, { aria_ms: 179 }, { raf_ms: 199 },
    { event_ms: 0, listener_ms: 5001, aria_ms: 5002, raf_ms: 5003 },
  ]) assert.throws(() => trustedFeedbackTiming({ ...sample, ...change }));
});

test('equal clock ticks and the exact declared queue boundary remain representable', () => {
  const equal = trustedFeedbackTiming({ trusted: true, event_ms: 0, listener_ms: 0, aria_ms: 0, raf_ms: 0 });
  assert.equal(equal.input_to_raf_ms, 0);
  const edge = trustedFeedbackTiming({ trusted: true, event_ms: 100, listener_ms: 5100, aria_ms: 5100, raf_ms: 5100 });
  assert.equal(edge.input_to_listener_ms, 5000);
  assert.equal(edge.input_to_raf_ms, 5000);
});

test('retained raw timestamp evidence is never mutated by timing validation', () => {
  const input = Object.freeze({ ...sample });
  const result = trustedFeedbackTiming(input);
  assert.notEqual(result, input);
  assert.deepEqual(input, sample);
});
