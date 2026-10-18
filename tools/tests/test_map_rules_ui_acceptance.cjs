'use strict';

// Pure boundary tests. Importing the companion must not load Playwright or create ROS participants.
const assert = require('node:assert/strict');
const test = require('node:test');
const { assertMissionBody, inactive } = require('../fishbot_map_rules_ui_acceptance.cjs');

const expected = { waypoints: [{ x: .6, y: 0, yaw: 0 }, { x: .15, y: .4, yaw: 0 }],
  return_home: false, map_id: 'map-a', rules_revision: 3, timeout_s: 360 };
const body = () => ({ ...structuredClone(expected), mission_id: '3493539a-c09d-400b-972d-81ef6045c9c0', issued_at: 100 });

test('accepts exactly the frontend waypoint contract with one client UUID and original deadline', () => {
  assert.doesNotThrow(() => assertMissionBody(body(), expected, 100));
});

test('rejects missing, malformed and additional mission identity fields', () => {
  for (const value of ['', 'legacy-id', '3493539A-C09D-400B-972D-81EF6045C9C0', 1, null]) {
    assert.throws(() => assertMissionBody({ ...body(), mission_id: value }, expected, 100));
  }
  const missing = body(); delete missing.mission_id;
  assert.throws(() => assertMissionBody(missing, expected, 100));
  assert.throws(() => assertMissionBody({ ...body(), operation: 'backup' }, expected, 100));
});

test('rejects altered persisted route, return option, map or rules revision before forwarding', () => {
  for (const change of [{ waypoints: [{ x: .6, y: .1, yaw: 0 }] }, { return_home: true }, { map_id: 'another-map' }, { rules_revision: 4 }]) {
    assert.throws(() => assertMissionBody({ ...body(), ...change }, expected, 100));
  }
});

test('does not silently accept an absent, shorter or expanded task deadline', () => {
  const missing = body(); delete missing.timeout_s;
  assert.throws(() => assertMissionBody(missing, expected, 100));
  for (const timeout_s of [30, 361, Infinity, NaN, true]) assert.throws(() => assertMissionBody({ ...body(), timeout_s }, expected, 100));
});

test('rejects stale, future and nonfinite issued timestamps', () => {
  for (const issued_at of [97.99, 102.01, NaN, Infinity, '100', true]) {
    assert.throws(() => assertMissionBody({ ...body(), issued_at }, expected, 100));
  }
});

test('preserves the existing no-active-owner and unresolved-cleanup preflight', () => {
  const state = { mode: 'mujoco', domain: 127, ready: true, mission: { id: null, status: 'idle' } };
  assert.doesNotThrow(() => inactive(state, 127));
  for (const status of ['running', 'canceling', 'unknown']) assert.throws(() => inactive({ ...state, mission: { status } }, 127));
  assert.throws(() => inactive({ ...state, mission: { status: 'succeeded', cleanup_state: 'unresolved' } }, 127));
  assert.throws(() => inactive({ ...state, mission: { status: 'failed', dispatch_state: 'unavailable' } }, 127));
  assert.throws(() => inactive({ ...state, domain: 128 }, 127));
});
