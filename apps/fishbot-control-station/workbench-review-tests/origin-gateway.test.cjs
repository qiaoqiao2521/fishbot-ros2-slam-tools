// SPDX-License-Identifier: MPL-2.0
// These fixtures serve only synthetic HTTP responses and recorded telemetry. No executor runs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const { createRequire } = require('node:module');
const { test } = require('node:test');
const { publicOrigin, requestAllowed, requestOrigin, serverOrigin, stationRedirect } = require('../workbench-origin.cjs');
const { createFishbotGateway } = require('../fishbot-gateway.cjs');
const { createDroneDiagnostics } = require('../drone-diagnostics.cjs');
const upstreamRequire = createRequire(path.join(__dirname, '../workbench/package.json'));
const PUBLIC_ORIGIN = 'https://workbench.example:8443';
const PUBLIC_ENV = { WORKBENCH_PUBLIC_URL: PUBLIC_ORIGIN + '/' };

function request(host, origin, extraHeaders = {}, encrypted = false) {
  return { headers: { host, ...(origin === undefined ? {} : { origin }), ...extraHeaders }, socket: { encrypted } };
}

async function listen(t, handler) {
  const server = http.createServer((req, res) => {
    Promise.resolve(handler(req, res)).catch(error => {
      if (!res.headersSent) res.writeHead(500);
      res.end(String(error));
    });
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  t.after(async () => {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  });
  return server;
}

function get(server, route, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.get({ hostname: '127.0.0.1', port: server.address().port, path: route, headers, agent: false }, res => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.once('aborted', () => reject(new Error('HTTP response aborted before completion')));
      res.once('error', reject);
      res.once('end', () => resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks) }));
    });
    req.setTimeout(10000, () => req.destroy(new Error('Fixture HTTP request timed out')));
    req.once('error', reject);
  });
}

test('a public HTTPS origin survives TLS termination without trusting forwarding headers', () => {
  const req = request('workbench.example:8443', PUBLIC_ORIGIN, {
    'x-forwarded-host': 'attacker.example', 'x-forwarded-proto': 'http',
  });
  assert.equal(req.socket.encrypted, false);
  assert.equal(publicOrigin(PUBLIC_ENV), PUBLIC_ORIGIN);
  assert.equal(requestAllowed(req, PUBLIC_ENV), true);
  assert.equal(requestOrigin(req, PUBLIC_ENV), PUBLIC_ORIGIN);
  assert.equal(serverOrigin(5186, PUBLIC_ENV), PUBLIC_ORIGIN);
  assert.equal(requestAllowed(request('workbench.example:8443'), {}), false);
});

test('pure local and public-configured local entrypoints keep their own origin', () => {
  for (const host of ['127.0.0.1:5186', '127.0.0.2:5186', 'localhost:5191', '[::1]:5192']) {
    const ownOrigin = 'http://' + host;
    for (const env of [{}, PUBLIC_ENV]) {
      const req = request(host, ownOrigin, { 'x-forwarded-host': 'workbench.example:8443', 'x-forwarded-proto': 'https' });
      assert.equal(requestAllowed(req, env), true, host);
      assert.equal(requestOrigin(req, env), ownOrigin, host);
      assert.equal(requestOrigin(request(host), env), ownOrigin, host);
    }
  }
  assert.equal(requestOrigin(request('localhost:5186', 'https://localhost:5186', {}, true), PUBLIC_ENV), 'https://localhost:5186');
  assert.equal(serverOrigin(5186, {}), 'http://127.0.0.1:5186');
});

test('unrecognized or malformed Host and Origin headers cannot select an environment', () => {
  const denied = [
    request(undefined),
    request(['127.0.0.1:5186', 'attacker.example']),
    request('attacker.example'),
    request('localhost.attacker.example'),
    request('workbench.example.attacker.example:8443'),
    request('workbench.example:9443', PUBLIC_ORIGIN),
    request('user@127.0.0.1:5186'),
    request('127.0.0.1:5186/path'),
    request('127.0.0.1:5186?target=workbench.example'),
    request('127.0.0.1:5186#fragment'),
    request('127.0.0.1:5186', 'https://attacker.example'),
    request('127.0.0.1:5186', 'null'),
    request('workbench.example:8443', 'http://workbench.example:8443'),
    request('workbench.example:8443', 'http://127.0.0.1:5186'),
    request('attacker.example', PUBLIC_ORIGIN, { 'x-forwarded-host': 'workbench.example:8443', 'x-forwarded-proto': 'https' }),
  ];
  for (const req of denied) {
    assert.equal(requestAllowed(req, PUBLIC_ENV), false, JSON.stringify(req.headers));
    assert.throws(() => requestOrigin(req, PUBLIC_ENV), /Unrecognized workbench origin/);
  }
  for (const url of ['ftp://workbench.example', 'https://user:password@workbench.example', 'https://workbench.example/path', 'https://workbench.example/?query=1']) {
    assert.throws(() => publicOrigin({ WORKBENCH_PUBLIC_URL: url }), /http\(s\) origin/);
    assert.equal(requestAllowed(request('127.0.0.1:5186'), { WORKBENCH_PUBLIC_URL: url }), false);
  }
});

test('station redirects keep layouts, live WebSockets and recorded files on the selected entrypoint', () => {
  const entries = [
    { req: request('workbench.example:8443', PUBLIC_ORIGIN), env: PUBLIC_ENV, base: PUBLIC_ORIGIN, ws: 'wss://workbench.example:8443' },
    { req: request('127.0.0.1:5186'), env: {}, base: 'http://127.0.0.1:5186', ws: 'ws://127.0.0.1:5186' },
    { req: request('localhost:5191', 'http://localhost:5191'), env: PUBLIC_ENV, base: 'http://localhost:5191', ws: 'ws://localhost:5191' },
  ];
  for (const { req, env, base, ws } of entries) {
    for (const platform of ['so101', 'drone']) {
      for (const suffix of ['', '-mobile']) {
        const route = `/${platform}-station${suffix}`;
        const redirect = new URL(stationRedirect(req, route, undefined, env), base);
        assert.equal(redirect.origin, base);
        assert.equal(redirect.searchParams.get('layoutUrl'), `${base}/layouts${route}.json`);
        assert.equal(redirect.searchParams.get('ds'), 'foxglove-websocket');
        assert.equal(redirect.searchParams.get('ds.url'), `${ws}/api/${platform}/scene`);
      }
    }
    const replay = new URL(stationRedirect(req, '/so101', '/fixture-recordings', env), base);
    assert.equal(replay.searchParams.get('layoutUrl'), `${base}/layouts/so101-review.json`);
    assert.equal(replay.searchParams.get('ds'), 'remote-file');
    assert.equal(replay.searchParams.get('ds.url'), `${base}/records/so101.mcap`);
    assert.equal(replay.searchParams.get('time'), '0.04');
    const empty = new URL(stationRedirect(req, '/so101-mobile', undefined, env), base);
    assert.equal(empty.searchParams.has('ds'), false);
    assert.equal(empty.searchParams.get('layoutUrl'), `${base}/layouts/so101-mobile.json`);
  }
});

test('the real diagnostics handle redirects and serves recorded MCAP through public and local origins', async t => {
  const previousOrigin = process.env.WORKBENCH_PUBLIC_URL;
  t.after(() => {
    if (previousOrigin === undefined) delete process.env.WORKBENCH_PUBLIC_URL;
    else process.env.WORKBENCH_PUBLIC_URL = previousOrigin;
  });
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'workbench-origin-diagnostics-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const tasksRoot = path.join(root, 'tasks'), archiveRoot = path.join(root, 'archive');
  const id = 'origin-review-fixture', dir = path.join(archiveRoot, 'recorded-copy');
  fs.mkdirSync(tasksRoot);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'request.json'), JSON.stringify({ id, station: { name: 'recorded fixture', nodes: [], program: [] } }));
  fs.writeFileSync(path.join(dir, 'status.json'), JSON.stringify({ status: 'cancelled' }));
  fs.writeFileSync(path.join(dir, 'report.json'), JSON.stringify({ task_id: id, passed: false, landed: true, disarmed: true }));
  fs.writeFileSync(path.join(dir, 'telemetry.jsonl'), [1, 2].map(simulation_s => JSON.stringify({
    simulation_s, phase: 'recovery', pose: { position: [0, 0, 1] }, telemetry: { altitude_m: 1 }, obstacles: [],
  })).join('\n') + '\n');
  const diagnostics = createDroneDiagnostics({
    runtime: { paths: { tasksRoot, sourceRoot: root } }, archiveRoot, cacheRoot: path.join(root, 'diagnostic-cache'),
  });
  const serve = upstreamRequire('serve-handler');
  const server = await listen(t, async (req, res) => {
    if (!await diagnostics.handle(req, res, serve)) { res.writeHead(404); res.end(); }
  });
  const localHost = `127.0.0.1:${server.address().port}`, localOrigin = 'http://' + localHost;
  const entries = [
    { configured: false, host: localHost, base: localOrigin, mobile: false },
    { configured: true, host: 'workbench.example:8443', base: PUBLIC_ORIGIN, mobile: true },
    { configured: true, host: localHost, base: localOrigin, mobile: false },
  ];
  for (const { configured, host, base, mobile } of entries) {
    if (configured) process.env.WORKBENCH_PUBLIC_URL = PUBLIC_ORIGIN;
    else delete process.env.WORKBENCH_PUBLIC_URL;
    const headers = { Host: host, Origin: base };
    const response = await get(server, `/drone-diagnostics?taskId=${id}${mobile ? '&mobile=1' : ''}`, headers);
    assert.equal(response.status, 302, response.body.toString());
    const redirect = new URL(response.headers.location, base);
    assert.equal(redirect.searchParams.get('ds'), 'remote-file');
    assert.equal(redirect.searchParams.get('layoutUrl'), `${base}/layouts/drone-diagnostics${mobile ? '-mobile' : ''}.json`);
    const recording = new URL(redirect.searchParams.get('ds.url'));
    assert.equal(recording.origin, base);
    assert.equal(recording.pathname, `/api/drone/diagnostics/${id}/diagnostics.mcap`);
    const artifact = await get(server, recording.pathname, { ...headers, Range: 'bytes=0-7' });
    assert.equal(artifact.status, 206, artifact.body.toString());
    assert.equal(artifact.body.toString('hex'), '894d434150300d0a');
  }
  assert.equal((await get(server, `/drone-diagnostics?taskId=${id}`, { Host: 'attacker.example' })).status, 403);
  assert.equal((await get(server, `/drone-diagnostics?taskId=${id}`, { Host: localHost, Origin: 'https://attacker.example' })).status, 403);
  assert.equal(fs.existsSync(path.join(dir, 'cancel.request')), false);
  assert.equal(fs.existsSync(path.join(dir, 'flight.mcap')), false);
});

test('gateway rejects foreign origins and keeps a reused upstream socket alive beyond its five-second connection timeout', { timeout: 15000 }, async t => {
  // Force keep-alive even on Node versions whose global agent defaults differ.
  const previousAgent = http.globalAgent;
  const agent = new http.Agent({ keepAlive: true, maxSockets: 1 });
  http.globalAgent = agent;
  t.after(() => { http.globalAgent = previousAgent; agent.destroy(); });
  const connections = [], seen = [];
  const service = await listen(t, (req, res) => {
    seen.push({ url: req.url, headers: req.headers, socket: req.socket });
    if (req.url === '/api/v1/stream') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
      res.write('data: connected\n\n');
      const timer = setTimeout(() => res.end('data: still-connected\n\n'), 5700);
      res.once('close', () => clearTimeout(timer));
    } else if (req.url === '/api/v1/broken-stream') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream' });
      res.write('data: interrupted\n\n');
      setImmediate(() => res.destroy());
    } else { res.writeHead(200, { 'Content-Type': 'text/plain' }); res.end('fixture-ready'); }
  });
  service.keepAliveTimeout = 15000;
  service.on('connection', socket => connections.push(socket));
  let gateway;
  const proxy = await listen(t, async (req, res) => {
    if (!await gateway.handle(req, res, () => { throw new Error('The HTTP fixture must not serve static files'); })) {
      res.writeHead(404); res.end();
    }
  });
  const servicePort = service.address().port, proxyPort = proxy.address().port;
  const unused = [];
  for (let port = 19000; unused.length < 3; port++) {
    if (port !== servicePort && port !== proxyPort) unused.push(port);
  }
  gateway = createFishbotGateway({ port: proxyPort, env: {
    ...PUBLIC_ENV, BACKEND_PORT: String(servicePort), FISHBOT_MISSION_PORT: String(unused[0]),
    FISHBOT_COOP_PORT: String(unused[1]), FISHBOT_VOICE_PORT: String(unused[2]),
  } });
  assert.equal((await get(proxy, '/api/v1/ping', { Host: 'attacker.example', Origin: PUBLIC_ORIGIN })).status, 403);
  assert.equal((await get(proxy, '/api/v1/ping', { Host: 'workbench.example:8443', Origin: 'https://attacker.example' })).status, 403);
  assert.equal(seen.length, 0, 'rejected browser requests must never reach a backend');
  const headers = { Host: 'workbench.example:8443', Origin: PUBLIC_ORIGIN,
    'X-Forwarded-Host': 'attacker.example', 'X-Forwarded-Proto': 'https' };
  const ping = await get(proxy, '/api/v1/ping?probe=1', headers);
  assert.equal(ping.status, 200, ping.body.toString());
  assert.equal(ping.body.toString(), 'fixture-ready');
  assert.equal(seen[0].url, '/api/v1/ping?probe=1');
  assert.equal(seen[0].headers.host, `127.0.0.1:${servicePort}`);
  assert.equal(seen[0].headers.origin, `http://127.0.0.1:${servicePort}`);
  assert.equal(seen[0].headers['x-forwarded-host'], undefined);
  assert.equal(seen[0].headers['x-forwarded-proto'], undefined);
  const started = Date.now();
  const stream = await get(proxy, '/api/v1/stream', headers);
  assert.equal(stream.status, 200);
  assert.match(stream.headers['content-type'], /^text\/event-stream/);
  assert.equal(stream.body.toString(), 'data: connected\n\ndata: still-connected\n\n');
  assert(Date.now() - started >= 5500, 'fixture must outlast the five-second connection timeout');
  assert.equal(connections.length, 1, 'the stream must reuse the warmed upstream connection');
  assert.equal(seen[1].socket, seen[0].socket);
  await assert.rejects(get(proxy, '/api/v1/broken-stream', headers), /aborted|hang up|reset/i);
  assert.equal((await get(proxy, '/api/v1/ping', headers)).status, 200, 'an interrupted upstream must not crash the gateway');
});
