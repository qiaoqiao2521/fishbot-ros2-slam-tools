// SPDX-License-Identifier: MPL-2.0
// One explicit deployment origin shared by HTTP, WebSocket and asset URLs.
const {isLoopback} = require('./workbench-config.cjs');

function publicOrigin(env = process.env) {
  if (!env.WORKBENCH_PUBLIC_URL) return undefined;
  const value = new URL(env.WORKBENCH_PUBLIC_URL);
  if (!['http:', 'https:'].includes(value.protocol) || value.username || value.password ||
      value.pathname !== '/' || value.search || value.hash) {
    throw new Error('WORKBENCH_PUBLIC_URL must be an http(s) origin without a path or credentials.');
  }
  return value.origin;
}

function hostUrl(request) {
  const host = request.headers.host;
  if (typeof host !== 'string' || !host) throw new Error('Missing Host header.');
  const url = new URL((request.socket?.encrypted ? 'https://' : 'http://') + host);
  if (url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Invalid Host header.');
  }
  return url;
}

function requestAllowed(request, env = process.env) {
  try {
    const host = hostUrl(request);
    const configured = publicOrigin(env);
    const local = isLoopback(host.hostname.replace(/^\[|\]$/g, ''));
    if (!local && (!configured || host.host !== new URL(configured).host)) return false;
    const origin = request.headers.origin;
    if (origin !== undefined && origin !== configured && !(local && origin === host.origin)) return false;
    return true;
  } catch { return false; }
}

function requestOrigin(request, env = process.env) {
  if (!requestAllowed(request, env)) throw new Error('Unrecognized workbench origin.');
  const host = hostUrl(request);
  const configured = publicOrigin(env);
  // A TLS-terminating proxy supplies the configured Host. Direct local access
  // keeps its own origin; forwarding headers are never used as a URL authority.
  return configured && host.host === new URL(configured).host ? configured : host.origin;
}

function serverOrigin(port, env = process.env) {
  return publicOrigin(env) ?? 'http://127.0.0.1:' + port;
}

function stationRedirect(request, pathname, recordings, env = process.env) {
  const base = requestOrigin(request, env);
  const layout = pathname === '/so101' ? 'so101-review' : pathname.slice(1);
  const station = pathname.includes('-station');
  const platform = pathname.startsWith('/drone-') ? 'drone' : 'so101';
  const query = new URLSearchParams({layoutUrl: base + '/layouts/' + layout + '.json'});
  if (station) {
    const websocket = new URL('/api/' + platform + '/scene', base);
    websocket.protocol = websocket.protocol === 'https:' ? 'wss:' : 'ws:';
    query.set('ds', 'foxglove-websocket');
    query.set('ds.url', websocket.href);
  } else if (recordings) {
    query.set('ds', 'remote-file');
    query.set('ds.url', base + '/records/so101.mcap');
    query.set('time', '0.04');
  }
  return '/?' + query.toString();
}

module.exports = {publicOrigin, requestAllowed, requestOrigin, serverOrigin, stationRedirect};
