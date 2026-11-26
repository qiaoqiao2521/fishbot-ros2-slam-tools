#!/usr/bin/env node
// SPDX-License-Identifier: MPL-2.0
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const { spawn, spawnSync } = require('node:child_process');
const { resolveWorkbenchConfig, applyWorkbenchConfig } = require('./workbench-config.cjs');

const HELP = `FishBot / SO101 / Drone workbench
  ./fishbot.sh workbench doctor [--project fishbot|so101|drone|all] [--json]
  ./fishbot.sh workbench start [--host 127.0.0.1] [--port 5186] [--public-url ORIGIN]
  ./fishbot.sh workbench help

Both doctor and start accept --config FILE. Environment values override the JSON
configuration; command options override the environment. See docs/WORKBENCH_START.md.
doctor is read-only: it checks source, builds, dependencies and executor descriptions.
start serves the existing workbench and /start; it does not submit a simulation task.
Install/build steps are explicit and are printed for missing requirements.
`;

const exists = filename => { try { return fs.statSync(filename).isFile(); } catch { return false; } };
function executable(filename) {
  try { fs.accessSync(filename, fs.constants.X_OK); return exists(filename); } catch { return false; }
}
function packageVersion(filename) {
  try { return JSON.parse(fs.readFileSync(filename, 'utf8')).version; } catch { return undefined; }
}
function lastJSON(output) {
  return JSON.parse(String(output ?? '').trim().split('\n').at(-1));
}

function doctor(config, { project = 'all', env = process.env, sharedOnly = false } = {}) {
  if (!['all', 'fishbot', 'so101', 'drone'].includes(project)) throw new Error('Unknown doctor project: ' + project);
  const checks = [];
  const add = (id, group, ok, message, fix, details) => checks.push({
    id, project: group, status: ok ? 'ok' : 'missing', message,
    ...(!ok && fix ? { fix } : {}), ...(details !== undefined ? { details } : {}),
  });
  const selected = name => !sharedOnly && (project === 'all' || project === name);
  const source = path.join(config.stationDir, 'workbench');
  const setup = 'cd apps/fishbot-control-station && ./workbench-dev.sh install --immutable';
  add('node', 'shared', Number(process.versions.node.split('.')[0]) >= 20,
    `Node ${process.versions.node}; workbench requires Node >=20`, 'Use Node 20 or newer.');
  add('workbench-source', 'shared', exists(path.join(source, 'package.json')),
    `Lichtblick source ${packageVersion(path.join(source, 'package.json')) ?? 'not found'}`,
    'Restore the tracked apps/fishbot-control-station/workbench source.');
  add('preview-source', 'shared', exists(path.join(config.stationDir, 'workbench-preview.cjs')),
    'Existing workbench preview server', 'Restore apps/fishbot-control-station/workbench-preview.cjs.');
  for (const name of ['serve-handler', '@foxglove/ws-protocol', 'ws', '@mcap/core', '@foxglove/schemas/jsonschema']) {
    try {
      const anchor = name === 'serve-handler' ? 'web/package.json' : 'package.json';
      const requireFromWorkbench = createRequire(path.join(source, anchor));
      // A package entry may exist after an interrupted install while a required
      // transitive dependency is absent. Load the same CJS module as the server.
      requireFromWorkbench(name);
      const resolved = requireFromWorkbench.resolve(name);
      add(`node-dependency:${name}`, 'shared', true, `${name}: ${resolved}`);
    } catch (error) {
      add(`node-dependency:${name}`, 'shared', false, `${name} cannot load in this workbench: ${error.message}`, setup);
    }
  }
  add('workbench-build', 'shared', exists(path.join(config.workbenchBuild, 'index.html')),
    `Workbench build: ${config.workbenchBuild}`,
    'cd apps/fishbot-control-station && ./workbench-dev.sh web:build:prod');

  if (selected('fishbot')) {
    const frontend = path.join(config.stationDir, 'frontend');
    add('fishbot-source', 'fishbot', exists(path.join(frontend, 'package.json')),
      'FishBot frontend source', 'Restore the tracked frontend directory.');
    add('fishbot-build', 'fishbot', exists(path.join(config.frontendDist, 'index.html')),
      `FishBot frontend build: ${config.frontendDist}`,
      'npm --prefix apps/fishbot-control-station/frontend ci && npm --prefix apps/fishbot-control-station/frontend run build');
    const installed = packageVersion(path.join(frontend, 'node_modules/react/package.json'));
    add('fishbot-frontend-dependencies', 'fishbot', Boolean(installed),
      `Frontend React: ${installed ?? 'not installed'}`, 'npm --prefix apps/fishbot-control-station/frontend ci');
  }

  const childEnv = applyWorkbenchConfig(config, { ...env, PYTHONDONTWRITEBYTECODE: '1',
    MPLBACKEND: 'agg', MUJOCO_GL: env.MUJOCO_GL ?? 'egl' });
  function describe(group, binary, script) {
    if (!executable(binary) || !exists(script)) return;
    const result = spawnSync(binary, [script, '--describe-json'], {
      encoding: 'utf8', timeout: 10000, maxBuffer: 1024 * 1024, env: childEnv,
    });
    let description;
    try { if (result.status === 0) description = lastJSON(result.stdout); } catch {}
    const ok = Boolean(description && typeof description === 'object' && !Array.isArray(description));
    add(`${group}-describe`, group, ok && description.ready !== false,
      ok ? description.message ?? `${group} executor description read successfully` :
        `${group} --describe-json failed: ${result.error?.message || result.stderr?.trim().slice(-1200) || 'invalid JSON or nonzero exit'}`,
      `Check the selected ${group} source and its documented runtime environment; no task was started.`, description);
    if (ok && group === 'so101' && description.execution_boundary?.version !== 1) {
      checks.push({ id: 'so101-contract', project: group, status: 'warning',
        message: 'SO101 uses the older description contract; the UI will retain its compatibility guidance.',
        fix: 'Update the SO101 checkout to include execution_boundary version 1.' });
    }
  }

  if (selected('so101')) {
    const script = path.join(config.so101Root, 'experiments/colab-twin/station_executor.py');
    const requirements = path.join(config.so101Root, 'experiments/colab-twin/requirements-station-runtime.txt');
    add('so101-source', 'so101', exists(script), `SO101 executor: ${script}`, 'Set SO101_ROOT to the SO101 checkout.');
    add('so101-python', 'so101', executable(config.so101Python), `SO101 Python: ${config.so101Python}`,
      'In SO101: python3 -m venv .venv-station; set SO101_PYTHON if using another environment.');
    add('so101-requirements', 'so101', exists(requirements), 'Pinned SO101 station requirements',
      'Update the SO101 checkout; requirements-station-runtime.txt is required for the station.');
    if (executable(config.so101Python) && exists(requirements)) {
      const probe = [
        'import importlib.metadata as m, json, pathlib, re, sys',
        'rows=[]',
        'for line in pathlib.Path(sys.argv[1]).read_text().splitlines():',
        ' match=re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\\s;]+)", line.strip())',
        ' if not match: continue',
        ' name, expected=match.groups()',
        ' try: installed=m.version(name)',
        ' except m.PackageNotFoundError: installed=None',
        ' rows.append({"package":name,"expected":expected,"installed":installed,"ok":installed==expected})',
        'print(json.dumps({"packages":rows,"ready":bool(rows) and all(r["ok"] for r in rows)}))',
      ].join('\n');
      const result = spawnSync(config.so101Python, ['-c', probe, requirements], {
        encoding: 'utf8', timeout: 10000, maxBuffer: 1024 * 1024, env: childEnv,
      });
      let versions;
      try { if (result.status === 0) versions = lastJSON(result.stdout); } catch {}
      const mismatch = versions?.packages?.filter(item => !item.ok)
        .map(item => `${item.package}: expected ${item.expected}, found ${item.installed ?? 'missing'}`).join('; ');
      add('so101-dependencies', 'so101', versions?.ready === true,
        versions?.ready ? 'SO101 installed package versions match its pinned station requirements' :
          `SO101 dependencies missing or mismatched${mismatch ? ': ' + mismatch : result.error ? ': ' + result.error.message : ''}`,
        'In SO101: .venv-station/bin/python -m pip install -r experiments/colab-twin/requirements-station-runtime.txt', versions);
    }
    describe('so101', config.so101Python, script);
  }
  if (selected('drone')) {
    const cerlab = config.droneBackend === 'cerlab';
    const root = cerlab ? config.cerlabRoot : config.droneRoot;
    const binary = cerlab ? '/usr/bin/python3' : '/bin/bash';
    const script = path.join(root, cerlab ? 'cerlab/run_station.py' : 'scripts/run_executor.sh');
    add('drone-source', 'drone', exists(script), `Drone ${config.droneBackend} executor: ${script}`,
      `Set ${cerlab ? 'CERLAB_ROOT' : 'DRONE_ROOT'} to the checkout containing this executor.`);
    add('drone-interpreter', 'drone', executable(binary), `Drone interpreter: ${binary}`,
      `Install ${cerlab ? 'Python 3' : 'Bash'} in the current execution environment.`);
    describe('drone', binary, script);
  }
  return {
    schema_version: 1, project: sharedOnly ? 'shared' : project,
    ready: checks.every(check => check.status === 'ok' || check.status === 'warning'),
    scope: 'Read-only environment checks; no simulation, ROS graph or hardware task was started.',
    config, checks,
  };
}

function printReport(report, json) {
  if (json) { console.log(JSON.stringify(report, null, 2)); return; }
  console.log(`Workbench doctor (${report.project}): ${report.ready ? 'ready' : 'needs preparation'}`);
  for (const check of report.checks) {
    console.log(`[${check.status}] ${check.message}`);
    if (check.fix) console.log(`  ${check.fix}`);
  }
  console.log(report.scope);
}

function startWorkbench(config, { env = process.env } = {}) {
  const report = doctor(config, { sharedOnly: true, env });
  if (!report.ready) { printReport(report, false); return Promise.resolve(1); }
  console.log(`Workbench: ${config.publicUrl}/start`);
  if (!exists(path.join(config.frontendDist, 'index.html'))) {
    console.log('FishBot results frontend is not built; SO101/Drone pages remain available. See workbench doctor --project fishbot.');
  }
  const child = spawn(process.execPath, [path.join(config.stationDir, 'workbench-preview.cjs')], {
    cwd: config.stationDir, stdio: 'inherit', env: applyWorkbenchConfig(config, { ...env }),
  });
  return new Promise(resolve => {
    const stop = signal => { if (!child.killed) child.kill(signal); };
    const onInterrupt = () => stop('SIGINT'), onTerminate = () => stop('SIGTERM');
    process.on('SIGINT', onInterrupt); process.on('SIGTERM', onTerminate);
    const finish = code => {
      process.removeListener('SIGINT', onInterrupt); process.removeListener('SIGTERM', onTerminate);
      resolve(code);
    };
    child.once('error', error => { console.error(`Cannot start workbench: ${error.message}`); finish(1); });
    child.once('exit', (code, signal) => finish(code ?? (signal === 'SIGINT' ? 130 : signal === 'SIGTERM' ? 143 : 1)));
  });
}

async function main(args = process.argv.slice(2), env = process.env) {
  const command = args[0] ?? 'help';
  if (['help', '-h', '--help'].includes(command)) { console.log(HELP); return 0; }
  if (!['doctor', 'start'].includes(command)) throw new Error(`Unknown workbench command: ${command}`);
  const options = { project: 'all', json: false }, effectiveEnv = { ...env };
  const variables = { '--config': 'WORKBENCH_CONFIG', '--host': 'WORKBENCH_HOST',
    '--port': 'WORKBENCH_PORT', '--public-url': 'WORKBENCH_PUBLIC_URL' };
  for (let i = 1; i < args.length; i++) {
    const [flag, ...inline] = args[i].split('=');
    if (flag === '--json' && command === 'doctor' && !inline.length) { options.json = true; continue; }
    if (flag !== '--project' && !variables[flag]) throw new Error(`Unknown option: ${args[i]}`);
    const value = inline.length ? inline.join('=') : args[++i];
    if (!value || value.startsWith('--')) throw new Error(`Missing value for ${flag}`);
    if (flag === '--project') {
      if (command !== 'doctor') throw new Error('--project is only available with doctor');
      options.project = value;
    } else effectiveEnv[variables[flag]] = value;
  }
  const config = resolveWorkbenchConfig({ env: effectiveEnv });
  if (command === 'doctor') {
    const report = doctor(config, { ...options, env: effectiveEnv });
    printReport(report, options.json); return report.ready ? 0 : 1;
  }
  return startWorkbench(config, { env: effectiveEnv });
}

if (require.main === module) {
  main().then(code => { process.exitCode = code; }).catch(error => {
    console.error(error.message); process.exitCode = 2;
  });
}
module.exports = { doctor, startWorkbench, main };
