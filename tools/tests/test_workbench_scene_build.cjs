'use strict';

// Filesystem/byte-contract fixtures only. No frontend build, browser, server or ROS.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');
const { argumentsFrom, distManifest, freezeBuildSource, sealProductionBuild, validateProductionBuild,
  executedSourceManifest, productionAssetPath, verifyProductionAsset } = require('../fishbot_workbench_scene_ui_contract.cjs');

function fixture(run) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'fishbot-scene-build-test-'));
  const dist = path.join(directory, 'dist'), start = path.join(directory, 'source-start.json'), receipt = path.join(directory, 'build.json');
  function writeDist(html = '<script type="module" src="/assets/main.js"></script><link rel="stylesheet" href="/assets/main.css">') {
    fs.mkdirSync(path.join(dist, 'assets'), { recursive: true }); fs.mkdirSync(path.join(dist, 'unrequested'));
    fs.writeFileSync(path.join(dist, 'index.html'), html); fs.writeFileSync(path.join(dist, 'assets/main.js'), 'export const fixture=1;');
    fs.writeFileSync(path.join(dist, 'assets/main.css'), 'body{color:black}'); fs.writeFileSync(path.join(dist, 'unrequested/retained.json'), '{"fixture":true}');
  }
  try { return run({ directory, dist, start, receipt, writeDist }); }
  finally { fs.rmSync(directory, { recursive: true, force: true }); }
}

test('fresh before/after source receipt freezes every built file, including unrequested assets', () => fixture(f => {
  const before = freezeBuildSource(f.start, f.dist); assert.equal(before.planned_dist, f.dist); assert.ok(!fs.existsSync(f.dist));
  f.writeDist(); const sealed = sealProductionBuild(f.start, f.dist, f.receipt), validated = validateProductionBuild(f.dist, f.receipt);
  assert.deepEqual(sealed.source_start, sealed.source_end); assert.deepEqual(validated.dist, distManifest(f.dist));
  assert.equal(Object.keys(validated.dist.files).length, 4); assert.ok(validated.dist.files['unrequested/retained.json']);
  assert.equal(validated.dist.index_references.length, 2); assert.equal(fs.statSync(f.receipt).mode & 0o077, 0);
  const closure = executedSourceManifest({ mode: 'production', dist: f.dist, buildReceipt: f.receipt });
  assert.equal(closure['@production-dist/unrequested/retained.json'], validated.dist.files['unrequested/retained.json']);
  assert.equal(closure['@production-build-receipt'], validated.receipt_sha256);
}));

test('stale output, overwritten receipts and a different output directory cannot be sealed', () => fixture(f => {
  f.writeDist(); assert.throws(() => freezeBuildSource(f.start, f.dist), /Preserve/);
  fs.rmSync(f.dist, { recursive: true }); freezeBuildSource(f.start, f.dist);
  assert.throws(() => freezeBuildSource(f.start, f.dist), /Preserve/);
  f.writeDist(); const alternate = path.join(f.directory, 'other'); fs.renameSync(f.dist, alternate);
  assert.throws(() => sealProductionBuild(f.start, alternate, f.receipt), /declared fresh dist/);
}));

test('changed source receipts and any changed dist bytes are rejected', () => fixture(f => {
  freezeBuildSource(f.start, f.dist); f.writeDist(); sealProductionBuild(f.start, f.dist, f.receipt);
  fs.appendFileSync(path.join(f.dist, 'unrequested/retained.json'), ' ');
  assert.throws(() => validateProductionBuild(f.dist, f.receipt), /artifact differs/);
  fs.writeFileSync(path.join(f.dist, 'unrequested/retained.json'), '{"fixture":true}');
  const value = JSON.parse(fs.readFileSync(f.receipt)); value.source_end['invented.ts'] = 'invalid';
  fs.writeFileSync(f.receipt, JSON.stringify(value)); assert.throws(() => validateProductionBuild(f.dist, f.receipt), /during compilation/);
}));

test('same but stale source hashes cannot prove that current source produced the build', () => fixture(f => {
  freezeBuildSource(f.start, f.dist); f.writeDist(); sealProductionBuild(f.start, f.dist, f.receipt);
  const value = JSON.parse(fs.readFileSync(f.receipt));
  value.source_start['invented.ts'] = '0'.repeat(64); value.source_end['invented.ts'] = '0'.repeat(64);
  fs.writeFileSync(f.receipt, JSON.stringify(value));
  assert.throws(() => validateProductionBuild(f.dist, f.receipt), /Current source differs/);
}));

test('missing, external or mutable index references and symlinked output are rejected', () => fixture(f => {
  f.writeDist(); const index = path.join(f.dist, 'index.html');
  for (const html of ['<script src="/assets/missing.js"></script>', '<script src="https://remote.invalid/main.js"></script>',
    '<script src="/assets/main.js?development=1"></script>', '<script src="http://production.invalid/assets/main.js"></script>',
    '<script src="//production.invalid/assets/main.js"></script>', '<script src="' + '\\'.repeat(2) + 'production.invalid/assets/main.js"></script>']) {
    fs.writeFileSync(index, html); assert.throws(() => distManifest(f.dist));
  }
  fs.writeFileSync(index, '<!-- <script src="/not-used.js"></script> --><script src="/assets/main.js"></script>');
  assert.equal(distManifest(f.dist).index_references.length, 1);
  fs.symlinkSync(f.start, path.join(f.dist, 'linked')); assert.throws(() => distManifest(f.dist), /symlinks/);
}));

test('served HTTP bytes must match the frozen entry; SPA routes cannot allow development modules', () => fixture(f => {
  f.writeDist(); const inventory = distManifest(f.dist), name = productionAssetPath('/radar', inventory);
  assert.equal(name, 'index.html'); assert.equal(productionAssetPath('/assets/main.js', inventory), 'assets/main.js');
  assert.throws(() => productionAssetPath('/@vite/client', inventory), /absent/);
  assert.throws(() => productionAssetPath('/%2e%2e/secret', inventory), /absent/);
  const body = fs.readFileSync(path.join(f.dist, name));
  assert.equal(verifyProductionAsset(name, inventory, body, 200).received_sha256, inventory.files[name]);
  assert.throws(() => verifyProductionAsset(name, inventory, Buffer.from('stale response'), 200), /differ/);
  assert.throws(() => verifyProductionAsset(name, inventory, body, 404), /HTTP status/);
}));

test('production mode is explicit and requires both provenance inputs before any browser', () => fixture(f => {
  assert.throws(() => argumentsFrom(['--mode', 'production', '--output', path.join(f.directory, 'output')]), /requires/);
  assert.throws(() => argumentsFrom(['--mode', 'development', '--dist', f.dist, '--output', path.join(f.directory, 'output')]), /cannot carry/);
  freezeBuildSource(f.start, f.dist); f.writeDist(); sealProductionBuild(f.start, f.dist, f.receipt);
  const args = argumentsFrom(['--mode', 'production', '--dist', f.dist, '--build-receipt', f.receipt,
    '--base', 'http://127.0.0.1:5183', '--duration', '0', '--output', path.join(f.directory, 'output')]);
  assert.equal(args.mode, 'production'); assert.equal(args.dist, f.dist); assert.equal(args.buildReceipt, f.receipt);
}));

test('graphics defaults to the original software panel and accepts hardware only by explicit selection', () => fixture(f => {
  const common = ['--duration', '0'];
  assert.equal(argumentsFrom([...common, '--output', path.join(f.directory, 'software')]).graphics, 'software');
  assert.equal(argumentsFrom([...common, '--graphics', 'hardware', '--output', path.join(f.directory, 'hardware')]).graphics, 'hardware');
  assert.throws(() => argumentsFrom([...common, '--graphics', 'automatic', '--output', path.join(f.directory, 'invalid')]), /software or hardware/);
  assert.ok(!fs.existsSync(path.join(f.directory, 'invalid')));
}));
