// SPDX-License-Identifier: MPL-2.0
// Shared configuration for the launcher and the existing preview server.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');

function isLoopback(host) {
  return host === 'localhost' || host === '::1' || (net.isIP(host) === 4 && host.startsWith('127.'));
}

function resolveWorkbenchConfig({ env = process.env, stationDir = __dirname } = {}) {
  stationDir = path.resolve(stationDir);
  const fishbotRoot = path.resolve(stationDir, '../..');
  const configPath = env.WORKBENCH_CONFIG
    ? path.resolve(env.WORKBENCH_CONFIG)
    : path.join(fishbotRoot, 'workbench.local.json');
  let file = {};
  if (fs.existsSync(configPath)) {
    try { file = JSON.parse(fs.readFileSync(configPath, 'utf8')); }
    catch (error) { throw new Error(`Cannot read workbench configuration ${configPath}: ${error.message}`); }
    if (!file || Array.isArray(file) || typeof file !== 'object') {
      throw new Error(`Workbench configuration must be a JSON object: ${configPath}`);
    }
  } else if (env.WORKBENCH_CONFIG) {
    throw new Error(`WORKBENCH_CONFIG does not exist: ${configPath}`);
  }
  const configured = (key, variable) => env[variable] !== undefined && env[variable] !== ''
    ? { value: env[variable], base: process.cwd() }
    : file[key] !== undefined ? { value: file[key], base: path.dirname(configPath) } : undefined;
  const value = (key, variable, fallback) => configured(key, variable)?.value ?? fallback;
  function location(key, variable, fallback) {
    const option = configured(key, variable);
    if (!option) return fallback;
    if (typeof option.value !== 'string' || !option.value.trim()) {
      throw new Error(`${variable}/${key} must be a non-empty filesystem path`);
    }
    const expanded = option.value.startsWith('~/')
      ? path.join(os.homedir(), option.value.slice(2)) : option.value;
    return path.resolve(option.base, expanded);
  }
  const firstExisting = (candidates, marker) => candidates.find(candidate =>
    fs.existsSync(marker ? path.join(candidate, marker) : candidate)) ?? candidates[0];
  const sibling = name => path.resolve(fishbotRoot, '..', name);
  const so101Root = location('so101Root', 'SO101_ROOT', sibling('so101'));
  const so101Python = location('so101Python', 'SO101_PYTHON', firstExisting([
    path.join(so101Root, '.venv-station/bin/python'), path.join(so101Root, '.venv/bin/python'),
  ]));
  const droneRoot = location('droneRoot', 'DRONE_ROOT', firstExisting([
    sibling('drone-px4-ego'), sibling('drone'),
  ]));
  const cerlabRoot = location('cerlabRoot', 'CERLAB_ROOT', firstExisting([
    droneRoot, sibling('drone-cerlab'), sibling('drone-cerlab-20261031'),
  ], 'cerlab/run_station.py'));
  const droneBackend = value('droneBackend', 'DRONE_BACKEND', 'cerlab');
  if (!['cerlab', 'px4'].includes(droneBackend)) throw new Error('DRONE_BACKEND must be cerlab or px4');
  const host = value('host', 'WORKBENCH_HOST', '127.0.0.1');
  if (typeof host !== 'string' || (!net.isIP(host) && !/^[a-zA-Z0-9.-]+$/.test(host))) {
    throw new Error('WORKBENCH_HOST must be an IP address or hostname, without a URL scheme or port');
  }
  const port = Number(value('port', 'WORKBENCH_PORT', 5186));
  if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    throw new Error('WORKBENCH_PORT must be an integer between 1024 and 65535');
  }
  const explicitPublicUrl = configured('publicUrl', 'WORKBENCH_PUBLIC_URL');
  if (!isLoopback(host) && !explicitPublicUrl) {
    throw new Error('Set WORKBENCH_PUBLIC_URL explicitly when WORKBENCH_HOST is not loopback');
  }
  let publicUrl;
  try {
    const url = new URL(explicitPublicUrl?.value ?? `http://${net.isIP(host) === 6 ? `[${host}]` : host}:${port}`);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password ||
        url.pathname !== '/' || url.search || url.hash) throw new Error('expected an http(s) root origin');
    publicUrl = url.origin;
  } catch (error) {
    throw new Error(`WORKBENCH_PUBLIC_URL must be an http(s) root origin without credentials, path, query or fragment: ${error.message}`);
  }
  return {
    stationDir, fishbotRoot, so101Root, so101Python, droneRoot, cerlabRoot, droneBackend,
    host, port, publicUrl,
    frontendDist: location('frontendDist', 'WORKBENCH_FRONTEND_DIST', path.join(stationDir, 'frontend/dist')),
    workbenchBuild: location('workbenchBuild', 'WORKBENCH_BUILD_DIR', path.join(stationDir, 'workbench/web/.webpack')),
    configPath,
  };
}

function applyWorkbenchConfig(config, env = process.env) {
  for (const [variable, key] of Object.entries({
    SO101_ROOT: 'so101Root', SO101_PYTHON: 'so101Python',
    DRONE_ROOT: 'droneRoot', CERLAB_ROOT: 'cerlabRoot', DRONE_BACKEND: 'droneBackend',
    WORKBENCH_HOST: 'host', WORKBENCH_PORT: 'port', WORKBENCH_PUBLIC_URL: 'publicUrl',
    WORKBENCH_FRONTEND_DIST: 'frontendDist', WORKBENCH_BUILD_DIR: 'workbenchBuild',
  })) env[variable] = String(config[key]);
  return env;
}

module.exports = { resolveWorkbenchConfig, applyWorkbenchConfig, isLoopback };
