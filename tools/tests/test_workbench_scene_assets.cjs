'use strict';

// Adversarial route/response lifecycle doubles only. No server or browser.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { test } = require('node:test');
const { forwardProductionAsset, verifyNativeDocument } = require('../fishbot_workbench_scene_ui_contract.cjs');
const origin = 'http://127.0.0.1:5185';
const body = Buffer.from('export const originalAsset = 1;\n');
const digest = value => crypto.createHash('sha256').update(value).digest('hex');

function fixture(options = {}) {
  const calls = { fetch: 0, fulfill: [], body: 0, dispose: 0 };
  const response = { status: () => options.status ?? 200, url: () => options.responseUrl ?? origin + '/assets/original.js',
    body: async () => { calls.body++; if (options.read) return options.read(); return options.body ?? body; },
    dispose: async () => { calls.dispose++; if (options.disposeError) throw options.disposeError; } };
  const request = { url: () => options.url ?? origin + '/assets/original.js', method: () => options.method ?? 'GET', resourceType: () => 'script' };
  const route = { request: () => request, fetch: async value => { calls.fetch++; calls.fetchOptions = value; return response; },
    fulfill: async value => { calls.fulfill.push(value); if (options.fulfillError) throw options.fulfillError; } };
  return { route, response, calls, record: {}, inventory: { files: { 'assets/original.js': digest(body) } } };
}

test('an original intercepted response is fully verified before the same bytes can reach its route', async () => {
  let release, started;
  const reading = new Promise(resolve => { started = resolve; }), gate = new Promise(resolve => { release = resolve; });
  const f = fixture({ read: async () => { started(); await gate; return body; } });
  const task = forwardProductionAsset(f.route, origin, f.inventory, f.record);
  await reading;
  assert.equal(f.calls.fulfill.length, 0, 'No early bytes before hash validation');
  assert.equal(f.record.verified, undefined);
  release(); const result = await task;
  assert.deepEqual(f.calls.fetchOptions, { maxRedirects: 0 });
  assert.equal(f.calls.fulfill.length, 1);
  assert.equal(f.calls.fulfill[0].response, f.response, 'Use the response from this intercepted route');
  assert.equal(f.calls.fulfill[0].body, body, 'Forward the actual validated buffer, not another GET or disk substitute');
  assert.equal(result.received_sha256, digest(body));
  assert.equal(f.calls.dispose, 1); assert.equal(f.record.disposed, true);
  assert.equal(f.record.url, origin + '/assets/original.js'); assert.equal(f.record.resource_type, 'script');
  assert.ok(f.record.read_finished_ms <= f.record.fulfill_started_ms);
  assert.ok(f.record.fulfill_finished_ms <= f.record.dispose_started_ms);
});

test('changed bytes never fulfill and their response is still disposed', async () => {
  const f = fixture({ body: Buffer.from('changed asset') });
  await assert.rejects(forwardProductionAsset(f.route, origin, f.inventory, f.record), /differ from frozen/);
  assert.equal(f.calls.fulfill.length, 0); assert.equal(f.calls.dispose, 1);
  assert.equal(f.record.failure_phase, 'verify'); assert.equal(f.record.disposed, true);
});

test('redirects are not followed, read or fulfilled, and a changed response URL cannot impersonate the original request', async () => {
  for (const options of [{ status: 302 }, { responseUrl: origin + '/assets/other.js' }]) {
    const f = fixture(options);
    await assert.rejects(forwardProductionAsset(f.route, origin, f.inventory, f.record));
    assert.deepEqual(f.calls.fetchOptions, { maxRedirects: 0 });
    assert.equal(f.calls.body, 0); assert.equal(f.calls.fulfill.length, 0); assert.equal(f.calls.dispose, 1);
    assert.equal(f.record.failure_phase, 'status');
  }
});

test('undeclared assets, external origins and mutations are rejected before any HTTP fetch', async () => {
  for (const options of [{ url: origin + '/undeclared.js' }, { url: 'https://outside.invalid/assets/original.js' }, { method: 'POST' }]) {
    const f = fixture(options);
    await assert.rejects(forwardProductionAsset(f.route, origin, f.inventory, f.record));
    assert.equal(f.calls.fetch, 0); assert.equal(f.calls.fulfill.length, 0); assert.equal(f.calls.dispose, 0);
    assert.equal(f.record.failure_phase, 'declare');
  }
});

test('read failure and route termination retain the exact phase and dispose the acquired response once', async () => {
  const readError = new Error('read failed'), closed = new Error('Target page, context or browser has been closed');
  for (const [options, phase, expected] of [[{ read: async () => { throw readError; } }, 'read', readError],
    [{ fulfillError: closed }, 'fulfill', closed]]) {
    const f = fixture(options);
    await assert.rejects(forwardProductionAsset(f.route, origin, f.inventory, f.record), error => error === expected);
    assert.equal(f.calls.dispose, 1); assert.equal(f.record.disposed, true);
    assert.equal(f.record.failure_phase, phase); assert.equal(f.record.fulfilled, false);
    assert.ok(f.record.error.includes(expected.message));
  }
});

test('dispose errors are visible and cannot overwrite an earlier body failure', async () => {
  const disposeError = new Error('dispose failed');
  const good = fixture({ disposeError });
  await assert.rejects(forwardProductionAsset(good.route, origin, good.inventory, good.record), error => error === disposeError);
  assert.equal(good.record.fulfilled, true); assert.equal(good.record.disposed, false); assert.equal(good.record.failure_phase, 'dispose');
  const readError = new Error('original read failure'), bad = fixture({ read: async () => { throw readError; }, disposeError });
  await assert.rejects(forwardProductionAsset(bad.route, origin, bad.inventory, bad.record), error => error === readError);
  assert.equal(bad.record.failure_phase, 'read'); assert.ok(bad.record.dispose_error.includes('dispose failed'));
  assert.equal(bad.calls.dispose, 1);
});

function document(options = {}) {
  const url = origin + '/radar', calls = { body: 0 }, record = { native_navigation: true };
  const request = { url: () => options.requestUrl ?? url, method: () => options.method ?? 'GET',
    isNavigationRequest: () => options.navigation ?? true, resourceType: () => options.resourceType ?? 'document',
    frame: () => ({ parentFrame: () => options.parentFrame ?? null }), redirectedFrom: () => options.redirect ?? null };
  const response = { request: () => request, url: () => options.responseUrl ?? url, status: () => options.status ?? 200,
    body: async () => { calls.body++; if (options.readError) throw options.readError; return options.body ?? body; } };
  return { url, response, record, calls, inventory: { files: { 'index.html': digest(body) } } };
}

test('the original native page.goto document is verified without fetching or synthesizing another response', async () => {
  const f = document(), result = await verifyNativeDocument(f.response, f.url, f.inventory, f.record);
  assert.equal(f.calls.body, 1); assert.equal(result.received_sha256, digest(body));
  assert.equal(result.name, 'index.html'); assert.equal(f.record.phase, 'complete');
  assert.equal(f.record.verified, true); assert.ok(f.record.disposal_scope.includes('Browser-owned'));
});

test('a worker/subframe, redirect or changed native document identity is rejected before its body is trusted', async () => {
  for (const options of [{ navigation: false }, { resourceType: 'script' }, { parentFrame: {} }, { redirect: {} },
    { requestUrl: origin + '/other' }, { responseUrl: origin + '/other' }, { method: 'POST' }, { status: 302 }]) {
    const f = document(options);
    await assert.rejects(verifyNativeDocument(f.response, f.url, f.inventory, f.record));
    assert.equal(f.calls.body, 0); assert.equal(f.record.failure_phase, 'native_document_status');
  }
  const f = document(); f.record.native_navigation = false;
  await assert.rejects(verifyNativeDocument(f.response, f.url, f.inventory, f.record), /route was not observed/);
});

test('native index bytes retain the same complete hash check and read failures remain explicit', async () => {
  const changed = document({ body: Buffer.from('changed index') });
  await assert.rejects(verifyNativeDocument(changed.response, changed.url, changed.inventory, changed.record), /differ from frozen/);
  assert.equal(changed.record.failure_phase, 'native_document_verify');
  const error = new Error('original navigation read failed'), failed = document({ readError: error });
  await assert.rejects(verifyNativeDocument(failed.response, failed.url, failed.inventory, failed.record), value => value === error);
  assert.equal(failed.record.failure_phase, 'native_document_read'); assert.ok(failed.record.error.includes(error.message));
});
