#!/usr/bin/env node
// Shared project entry with thin adapters for the existing simulator CLIs.
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");
const { resolveWorkbenchConfig, applyWorkbenchConfig } = require("./workbench-config.cjs");
const config = resolveWorkbenchConfig();
applyWorkbenchConfig(config);
const { requestAllowed, stationRedirect } = require("./workbench-origin.cjs");
const { createFishbotGateway } = require("./fishbot-gateway.cjs");
const { doctor } = require("./workbench-launcher.cjs");
const { createSo101Runtime } = require("./so101-runtime.cjs");
const { createSo101Live } = require("./so101-live.cjs");
const { createDroneRuntime } = require("./drone-runtime.cjs");
const { createDroneLive } = require("./drone-live.cjs");
const { createDronePlanning } = require("./drone-planning.cjs");
const { createDroneDiagnostics } = require("./drone-diagnostics.cjs");

const workbench = path.join(__dirname, "workbench");
const serveHandler = createRequire(path.join(workbench, "web", "package.json"))("serve-handler");
const build = config.workbenchBuild;
const layouts = process.env.WORKBENCH_LAYOUTS_DIR
  ? path.resolve(process.env.WORKBENCH_LAYOUTS_DIR)
  : path.join(workbench, "robot-layouts");
const recordings = process.env.WORKBENCH_RECORDINGS_DIR;
const port = config.port;
if (!fs.existsSync(path.join(build, "index.html"))) {
  throw new Error("Build the workbench first in apps/fishbot-control-station: ./workbench-dev.sh web:build:prod");
}
const gateway = createFishbotGateway({frontendDist:config.frontendDist, port});
const home = fs.readFileSync(path.join(__dirname, "workbench-home.html"));

let live;
const runtime = createSo101Runtime({onTaskCreated: id => live?.selectTask(id)});
live = createSo101Live({runtime});
let droneLive;
const dronePlanning=createDronePlanning();
const droneRuntime=createDroneRuntime({
  backend:process.env.DRONE_BACKEND??'cerlab',
  onTaskCreated:id=>droneLive?.selectTask(id),
  sceneOptions:()=>droneLive?.sceneOptions()??{},
  validateSubmission:dronePlanning.validateFlight,
});
droneLive=createDroneLive({runtime:droneRuntime,planning:dronePlanning});
const droneDiagnostics=createDroneDiagnostics({runtime:droneRuntime,sceneOptions:()=>droneLive.sceneOptions()});
const server = http.createServer(async (request, response) => {
 try {
  if (!requestAllowed(request)) {
    response.writeHead(403, {"Content-Type":"application/json; charset=utf-8"});
    response.end(JSON.stringify({error:"请从已配置的工作台地址访问。"}));
    return;
  }
  response.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  response.setHeader("Cross-Origin-Embedder-Policy", "credentialless");
  const pathname = new URL(request.url, "http://localhost").pathname;
  if (pathname === "/api/workbench/status") {
    if (request.method !== "GET" && request.method !== "HEAD") {
      response.writeHead(405, {Allow:"GET, HEAD"}); response.end(); return;
    }
    const so101 = runtime.runtime(), drone = droneRuntime.runtime();
    // A responding --describe-json alone does not prove pinned Python packages exist.
    const so101Check = so101.ready ? doctor(config, {project:"so101"}) : undefined;
    const so101Ready = so101.ready && so101Check?.ready === true;
    const so101Missing = so101Check?.checks.find(check => check.status !== "ok" && check.status !== "warning");
    response.writeHead(200, {"Content-Type":"application/json; charset=utf-8", "Cache-Control":"no-store"});
    response.end(JSON.stringify({projects:{
      fishbot:{ready:gateway.ready(),message:gateway.ready()
        ? "完整成果可查看；运行配送任务需另行连接对应仿真服务。"
        : "FishBot 成果页面尚未构建，请运行 workbench doctor --project fishbot 查看缺项。"},
      so101:{ready:so101Ready,message:so101Ready ? "SO101 环境检查通过；新任务仍需逐回合检查可达性与实际抓放。"
        : (so101Missing?.message ?? so101.message) + " 请运行 workbench doctor --project so101 查看缺项。"},
      drone:{ready:drone.ready,message:drone.ready ? drone.message : drone.message + " 请运行 workbench doctor --project drone 查看缺项。"},
    }}));
    return;
  }
  if (pathname === "/start" || pathname === "/start/") {
    if (request.method !== "GET" && request.method !== "HEAD") {
      response.writeHead(405, {Allow:"GET, HEAD"}); response.end(); return;
    }
    response.writeHead(200, {"Content-Type":"text/html; charset=utf-8", "Cache-Control":"no-store"});
    response.end(home);
    return;
  }
  if (await droneDiagnostics.handle(request, response, serveHandler)) return;
  if (await live.handle(request, response, serveHandler)) return;
  if (await runtime.handle(request, response, serveHandler)) return;
  if (await droneLive.handle(request, response, serveHandler)) return;
  if (await dronePlanning.handle(request, response, serveHandler)) return;
  if (await droneRuntime.handle(request, response, serveHandler)) return;
  if (await gateway.handle(request, response, serveHandler)) return;
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { Allow: "GET, HEAD" });
    response.end("Read-only preview");
    return;
  }
  if (["/so101", "/so101-mobile", "/so101-station", "/so101-station-mobile", "/drone-station", "/drone-station-mobile"].includes(pathname)) {
    response.writeHead(302, { Location: stationRedirect(request, pathname, recordings) });
    response.end();
    return;
  }
  let publicPath = build;
  if (pathname === "/drone-showcase" || pathname === "/drone-showcase/") {
    publicPath = path.join(__dirname, "drone-showcase");
    request.url = "/index.html";
  } else if (pathname.startsWith("/drone-showcase/")) {
    publicPath = path.join(__dirname, "workbench-tools/output/drone-showcase");
    request.url = pathname.slice("/drone-showcase".length);
  } else if (pathname === "/") {
    request.url = "/index.html";
  } else if (pathname === "/records/so101.mcap" && recordings) {
    publicPath = path.resolve(recordings);
    request.url = "/so101.mcap";
  } else if (["/layouts/so101-review.json", "/layouts/so101-task-review.json", "/layouts/so101-mobile.json", "/layouts/so101-station.json", "/layouts/so101-station-mobile.json", "/layouts/drone-station.json", "/layouts/drone-station-mobile.json", "/layouts/drone-review.json", "/layouts/drone-perception.json", "/layouts/drone-diagnostics.json", "/layouts/drone-diagnostics-mobile.json"].includes(pathname)) {
    publicPath = layouts;
    request.url = `/${path.basename(pathname)}`;
  } else if (pathname.startsWith("/records/") || pathname.startsWith("/layouts/")) {
    response.writeHead(404);
    response.end("Unknown local artifact");
    return;
  }
    // serve-handler owns range requests and path traversal checks.
    await serveHandler(request, response, {
      public: publicPath,
      directoryListing: false,
      cleanUrls: false,
      etag: true,
    });
 } catch (error) {
   console.error("Workbench request failed:", error);
   if (!response.headersSent) response.writeHead(500);
   response.end("Workbench request failed");
 }
});

live.attach(server,{routeUpgrade:false});
droneLive.attach(server);
server.on("upgrade",(request,socket,head)=>{
  const route=new URL(request.url,"http://localhost").pathname;
  if(route==="/api/so101/scene")live.handleUpgrade(request,socket,head);
  else if(route==="/api/drone/scene")droneLive.handleUpgrade(request,socket,head);
  else socket.destroy();
});
server.listen(port, config.host, () => {
  const base = config.publicUrl;
  console.log(`Workbench projects: ${base}/start`);
  console.log(`Lichtblick workspace: ${base}/`);
  if (recordings) {
    const query = new URLSearchParams({
      ds: "remote-file",
      "ds.url": `${base}/records/so101.mcap`,
      layoutUrl: `${base}/layouts/so101-review.json`,
      time: "0.04",
    });
    console.log(`SO101 recording: ${base}/?${query}`);
  }
});
