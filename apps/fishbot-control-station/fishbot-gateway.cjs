// SPDX-License-Identifier: MPL-2.0
// Serve the existing FishBot frontend alongside Lichtblick. No ROS owner is started here.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {requestAllowed} = require('./workbench-origin.cjs');

const ROUTES = new Set(['/fishbot', '/results', '/workbench', '/radar', '/cooperation', '/simulation', '/regression']);
function servicePorts(env, listenPort) {
  const profile = env.FISHBOT_WORKBENCH_PROFILE
    ? JSON.parse(fs.readFileSync(env.FISHBOT_WORKBENCH_PROFILE, 'utf8')) : undefined;
  if (profile && profile.schema_version !== 1) throw new Error('Unsupported FishBot service profile.');
  const values = {
    station: Number(profile ? profile.services?.station?.port : env.BACKEND_PORT || 8080),
    mission: Number(profile ? profile.services?.mission?.port : env.FISHBOT_MISSION_PORT || 9070),
    cooperation: Number(profile ? profile.services?.cooperation?.port : env.FISHBOT_COOP_PORT || 9086),
    voice: Number(profile ? profile.services?.voice?.port : env.FISHBOT_VOICE_PORT || 9094),
  };
  const ports = Object.values(values);
  if (ports.some(port => !Number.isInteger(port) || port < 1024 || port > 65535 || port === listenPort) || new Set(ports).size !== ports.length) {
    throw new Error('FishBot services need distinct valid ports, separate from WORKBENCH_PORT.');
  }
  return values;
}

function createFishbotGateway({stationDir = __dirname, frontendDist, port, env = process.env} = {}) {
  const build = frontendDist ?? path.join(stationDir, 'frontend/dist');
  const publicDir = path.join(stationDir, 'frontend/public');
  const ports = servicePorts(env, port);
  const services = [['/voice-api', ports.voice], ['/coop-api', ports.cooperation], ['/sim-api', ports.mission], ['/api', ports.station]];
  function ready() { return fs.existsSync(path.join(build, 'index.html')); }
  async function handle(request, response, serve) {
    const pathname = new URL(request.url, 'http://localhost').pathname;
    const service = services.find(([prefix]) => pathname === prefix || pathname.startsWith(prefix + '/'));
    if (service) {
      if (!requestAllowed(request, env)) {
        response.writeHead(403, {'Content-Type':'application/json'});
        response.end(JSON.stringify({error:'请从已配置的工作台地址访问服务。'}));
        return true;
      }
      // The browser cannot choose the target. Only the existing local service profile can.
      const headers = {...request.headers, host:'127.0.0.1:' + service[1]};
      if (headers.origin) headers.origin = 'http://' + headers.host;
      for (const name of ['connection', 'proxy-connection', 'transfer-encoding', 'upgrade', 'x-forwarded-host', 'x-forwarded-proto']) delete headers[name];
      const upstream = http.request({host:'127.0.0.1', port:service[1], method:request.method, path:request.url, headers}, incoming => {
        const responseHeaders = {...incoming.headers};
        delete responseHeaders['connection'];
        response.writeHead(incoming.statusCode ?? 502, responseHeaders);
        incoming.on('error', () => response.destroy());
        incoming.pipe(response);
      });
      upstream.on('error', () => {
        if (response.destroyed) return;
        if (response.headersSent) { response.destroy(); return; }
        response.writeHead(503, {'Content-Type':'application/json; charset=utf-8', 'Cache-Control':'no-store'});
        response.end(JSON.stringify({error:'所选 FishBot 服务尚未启动；当前页面保留历史成果，运行需连接对应仿真服务。'}));
      });
      // Bound initial connection, while allowing an established SSE stream to remain open.
      const connectTimeout = setTimeout(() => upstream.destroy(new Error('Service connection timeout')), 5000);
      upstream.on('socket', socket => {
        if (!socket.connecting) clearTimeout(connectTimeout);
        else socket.once('connect', () => clearTimeout(connectTimeout));
      });
      upstream.on('error', () => clearTimeout(connectTimeout));
      response.on('close', () => { clearTimeout(connectTimeout); upstream.destroy(); });
      request.pipe(upstream);
      return true;
    }
    if (!['GET', 'HEAD'].includes(request.method)) return false;
    let root;
    if (ROUTES.has(pathname)) {
      if (!ready()) {
        response.writeHead(503, {'Content-Type':'text/html; charset=utf-8'});
        response.end('<h1>FishBot 页面尚未构建</h1><p>在仓库根运行 ./fishbot.sh workbench doctor --project fishbot 查看缺项。构建页面：cd apps/fishbot-control-station/frontend &amp;&amp; npm ci &amp;&amp; npm run build。</p><a href="/start">返回项目入口</a>');
        return true;
      }
      root = build;
      request.url = '/index.html';
    } else if (pathname.startsWith('/assets/')) root = build;
    else if (pathname.startsWith('/workbench/') || pathname.startsWith('/hardware-lab/')) root = publicDir;
    else return false;
    await serve(request, response, {public:root, directoryListing:false, cleanUrls:false, etag:true});
    return true;
  }
  return {handle, ready, ports};
}
module.exports = {createFishbotGateway, servicePorts};
