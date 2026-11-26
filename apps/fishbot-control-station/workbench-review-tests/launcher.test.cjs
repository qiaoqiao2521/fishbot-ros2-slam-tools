// SPDX-License-Identifier: MPL-2.0
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { test } = require('node:test');
const { resolveWorkbenchConfig, applyWorkbenchConfig } = require('../workbench-config.cjs');
const { doctor, startWorkbench } = require('../workbench-launcher.cjs');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'workbench launcher '));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const fishbotRoot = path.join(root, 'fishbot');
  const stationDir = path.join(fishbotRoot, 'apps/fishbot-control-station');
  function write(relative, content = '') {
    const filename = path.join(root, relative);
    fs.mkdirSync(path.dirname(filename), { recursive: true });
    fs.writeFileSync(filename, content);
    return filename;
  }
  const prefix = 'fishbot/apps/fishbot-control-station/';
  write(prefix + 'workbench/package.json', JSON.stringify({ name: 'fixture-workbench', version: '1.29.1' }));
  write(prefix + 'workbench/web/package.json', '{"private":true}');
  write(prefix + 'workbench/web/.webpack/index.html', '<!doctype html><title>fixture</title>');
  write(prefix + 'workbench-preview.cjs',
    'require("node:fs").writeFileSync(process.env.WORKBENCH_TEST_TRACE, JSON.stringify({' +
    'root:process.env.SO101_ROOT,python:process.env.SO101_PYTHON,' +
    'origin:process.env.WORKBENCH_PUBLIC_URL,backend:process.env.DRONE_BACKEND}));');
  for (const module of ['serve-handler', '@foxglove/ws-protocol', 'ws', '@mcap/core', '@foxglove/schemas']) {
    write(prefix + `workbench/node_modules/${module}/package.json`, JSON.stringify({ name: module, version: '1.0.0', main: 'index.js' }));
    write(prefix + `workbench/node_modules/${module}/index.js`, 'module.exports = {};');
  }
  write(prefix + 'workbench/node_modules/@foxglove/schemas/jsonschema.js', 'module.exports = {};');
  for (const filename of ['workbench-config.cjs', 'workbench-launcher.cjs']) {
    fs.copyFileSync(path.join(__dirname, '..', filename), path.join(stationDir, filename));
  }
  function python({ contract = 1 } = {}) {
    const binary = write('so101/.venv-station/bin/python', '#!/usr/bin/python3\n' +
      'import json, os, sys\n' +
      'with open(os.environ["WORKBENCH_PYTHON_TRACE"], "a") as trace: trace.write(json.dumps(sys.argv[1:])+"\\n")\n' +
      'if sys.argv[1] == "-c":\n' +
      ' print(json.dumps({"ready":os.environ.get("FIXTURE_MISMATCH") != "1","packages":[' +
      '{"package":"fixture","expected":"1","installed":"2" if os.environ.get("FIXTURE_MISMATCH") == "1" else "1",' +
      '"ok":os.environ.get("FIXTURE_MISMATCH") != "1"}]}))\n' +
      'elif sys.argv[-1] == "--describe-json":\n' +
      ` print(json.dumps({"executor":"fixture","execution_boundary":{"version":${contract}}}))\n` +
      'else: raise SystemExit("unexpected task command")\n');
    fs.chmodSync(binary, 0o755);
    write('so101/experiments/colab-twin/station_executor.py', '# fixture described by the isolated interpreter\n');
    write('so101/experiments/colab-twin/requirements-station-runtime.txt', 'fixture==1\n');
    return binary;
  }
  const env = { ...process.env };
  for (const key of Object.keys(env)) {
    if (/^(WORKBENCH_|SO101_|CERLAB_ROOT$|DRONE_ROOT$|DRONE_BACKEND$)/.test(key)) delete env[key];
  }
  env.WORKBENCH_TEST_TRACE = path.join(root, 'server.json');
  env.WORKBENCH_PYTHON_TRACE = path.join(root, 'python.jsonl');
  return { root, fishbotRoot, stationDir, write, python, env,
    config: extra => resolveWorkbenchConfig({ env: extra ?? {}, stationDir }) };
}

test('automatic sibling discovery selects existing venv and CERLAB source without home-directory assumptions', t => {
  const f = fixture(t);
  f.write('so101/.venv/bin/python');
  f.write('drone/cerlab/run_station.py');
  const config = f.config();
  assert.equal(config.so101Root, path.join(f.root, 'so101'));
  assert.equal(config.so101Python, path.join(f.root, 'so101/.venv/bin/python'));
  assert.equal(config.droneRoot, path.join(f.root, 'drone'));
  assert.equal(config.cerlabRoot, config.droneRoot);
  assert.equal(config.droneBackend, 'cerlab');
  assert.equal(config.publicUrl, 'http://127.0.0.1:5186');
  f.write('so101/.venv-station/bin/python');
  assert.equal(f.config().so101Python, path.join(f.root, 'so101/.venv-station/bin/python'));
});

test('JSON paths are relative to the file; explicit environment paths win without fallback', t => {
  const f = fixture(t);
  const filename = f.write('settings/local.json', JSON.stringify({
    so101Root: '../json-arm', so101Python: '../json-arm/bin/python', port: 5191,
  }));
  const fromFile = f.config({ WORKBENCH_CONFIG: filename });
  assert.equal(fromFile.so101Root, path.join(f.root, 'json-arm'));
  assert.equal(fromFile.port, 5191);
  const explicit = path.join(f.root, 'missing-explicit-python');
  const override = f.config({ WORKBENCH_CONFIG: filename, SO101_PYTHON: explicit, WORKBENCH_PORT: '5192' });
  assert.equal(override.so101Python, explicit);
  assert.equal(override.port, 5192);
  assert.equal(fs.existsSync(override.so101Python), false);
});

test('default local config is optional but explicit missing, malformed and non-object files fail clearly', t => {
  const f = fixture(t);
  assert.equal(f.config().port, 5186);
  f.write('fishbot/workbench.local.json', '{"port":5193}');
  assert.equal(f.config().port, 5193);
  assert.throws(() => f.config({ WORKBENCH_CONFIG: path.join(f.root, 'missing.json') }), /does not exist/);
  const broken = f.write('bad.json', '{invalid');
  assert.throws(() => f.config({ WORKBENCH_CONFIG: broken }), /Cannot read/);
  f.write('bad.json', '[]');
  assert.throws(() => f.config({ WORKBENCH_CONFIG: broken }), /JSON object/);
});

test('public origin cannot silently widen exposure or accept path, credentials or non-HTTP schemes', t => {
  const f = fixture(t);
  assert.throws(() => f.config({ WORKBENCH_HOST: '0.0.0.0' }), /explicitly/);
  const config = f.config({ WORKBENCH_HOST: '0.0.0.0', WORKBENCH_PUBLIC_URL: 'https://workbench.example:8443/' });
  assert.equal(config.publicUrl, 'https://workbench.example:8443');
  assert.equal(f.config({ WORKBENCH_HOST: '::1' }).publicUrl, 'http://[::1]:5186');
  for (const origin of ['ftp://host', 'https://user:pass@host', 'https://host/path', 'https://host/?x=1', 'https://host/#x']) {
    assert.throws(() => f.config({ WORKBENCH_PUBLIC_URL: origin }), /root origin/);
  }
  assert.throws(() => f.config({ WORKBENCH_PORT: '80' }), /1024/);
  assert.throws(() => f.config({ DRONE_BACKEND: 'unknown' }), /cerlab or px4/);
});

test('environment application preserves task directories and does not make an absent default config explicit', t => {
  const f = fixture(t), config = f.config();
  const env = { SO101_TASKS_DIR: '/already/selected/tasks', KEEP: 'yes' };
  assert.equal(applyWorkbenchConfig(config, env), env);
  assert.equal(env.SO101_TASKS_DIR, '/already/selected/tasks');
  assert.equal(env.SO101_PYTHON, config.so101Python);
  assert.equal(env.WORKBENCH_PORT, '5186');
  assert.equal(env.WORKBENCH_CONFIG, undefined);
  assert.equal(env.KEEP, 'yes');
});

test('shared readiness and actual server subprocess do not require optional SO101/Drone/FishBot backends', async t => {
  const f = fixture(t), config = f.config();
  const shared = doctor(config, { sharedOnly: true, env: f.env });
  assert.equal(shared.ready, true, JSON.stringify(shared));
  assert(shared.checks.every(check => check.project === 'shared'));
  const code = await startWorkbench(config, { env: f.env });
  assert.equal(code, 0);
  const actual = JSON.parse(fs.readFileSync(f.env.WORKBENCH_TEST_TRACE, 'utf8'));
  assert.equal(actual.root, config.so101Root);
  assert.equal(actual.python, config.so101Python);
  assert.equal(actual.origin, 'http://127.0.0.1:5186');
  assert.equal(actual.backend, 'cerlab');
});

test('missing shared build blocks start with a preparation command before spawning the server', async t => {
  const f = fixture(t), config = f.config();
  fs.rmSync(path.join(config.workbenchBuild, 'index.html'));
  const report = doctor(config, { sharedOnly: true, env: f.env });
  assert.equal(report.ready, false);
  assert.match(report.checks.find(check => check.id === 'workbench-build').fix, /web:build:prod/);
  assert.equal(await startWorkbench(config, { env: f.env }), 1);
  assert.equal(fs.existsSync(f.env.WORKBENCH_TEST_TRACE), false);
});

test('a resolvable package with a missing transitive dependency is not reported ready', t => {
  const f = fixture(t);
  f.write('fishbot/apps/fishbot-control-station/workbench/node_modules/serve-handler/index.js',
    'module.exports = require("./missing-transitive-dependency.cjs");');
  const report = doctor(f.config(), { sharedOnly: true, env: f.env });
  assert.equal(report.ready, false);
  const check = report.checks.find(item => item.id === 'node-dependency:serve-handler');
  assert.equal(check.status, 'missing');
  assert.match(check.message, /missing-transitive-dependency/);
  assert.match(check.fix, /install --immutable/);
});

test('SO101 doctor uses only metadata and --describe-json subprocesses; mismatches stay visible', t => {
  const f = fixture(t);
  f.python();
  const config = f.config();
  const report = doctor(config, { project: 'so101', env: f.env });
  assert.equal(report.ready, true, JSON.stringify(report));
  assert(!report.checks.some(check => check.project === 'drone' || check.project === 'fishbot'));
  const calls = fs.readFileSync(f.env.WORKBENCH_PYTHON_TRACE, 'utf8').trim().split('\n').map(JSON.parse);
  assert.equal(calls.length, 2);
  assert.equal(calls[0][0], '-c');
  assert.equal(calls[1].at(-1), '--describe-json');
  const mismatch = doctor(config, { project: 'so101', env: { ...f.env, FIXTURE_MISMATCH: '1' } });
  assert.equal(mismatch.ready, false);
  assert.match(mismatch.checks.find(check => check.id === 'so101-dependencies').message, /expected 1, found 2/);
});

test('older SO101 description is a compatibility warning, not fabricated new-contract support', t => {
  const f = fixture(t);
  f.python({ contract: 0 });
  const report = doctor(f.config(), { project: 'so101', env: f.env });
  assert.equal(report.ready, true);
  assert.equal(report.checks.find(check => check.id === 'so101-contract').status, 'warning');
});

test('Drone doctor preserves backend not-ready instead of declaring source existence sufficient', t => {
  const f = fixture(t);
  f.write('drone/cerlab/run_station.py', 'import json, sys\nassert sys.argv == [__file__, "--describe-json"]\nprint(json.dumps({"ready":False,"message":"fixture cache missing"}))\n');
  const report = doctor(f.config(), { project: 'drone', env: f.env });
  assert.equal(report.ready, false);
  assert.equal(report.checks.find(check => check.id === 'drone-describe').message, 'fixture cache missing');
  assert(!report.checks.some(check => check.project === 'so101'));
});

test('real CLI returns JSON and exit status for selected capability without starting a task', t => {
  const f = fixture(t);
  f.python();
  const command = path.join(f.stationDir, 'workbench-launcher.cjs');
  const result = spawnSync(process.execPath, [command, 'doctor', '--project=so101', '--json'], {
    encoding: 'utf8', env: f.env, timeout: 10000,
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).project, 'so101');
  assert.equal(fs.existsSync(f.env.WORKBENCH_TEST_TRACE), false);
  const invalid = spawnSync(process.execPath, [command, 'doctor', '--project', 'unknown', '--json'], {
    encoding: 'utf8', env: f.env, timeout: 10000,
  });
  assert.equal(invalid.status, 2);
  assert.match(invalid.stderr, /Unknown doctor project/);
});
