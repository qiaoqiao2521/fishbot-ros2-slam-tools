#!/usr/bin/env node
// Local workbench and thin adapter for the existing SO101 simulator CLI.
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");
const { createSo101Runtime } = require("./so101-runtime.cjs");
const { createSo101Live } = require("./so101-live.cjs");
const { createDroneRuntime } = require("./drone-runtime.cjs");
const { createDroneLive } = require("./drone-live.cjs");
const { createDronePlanning } = require("./drone-planning.cjs");

const workbench = path.join(__dirname, "workbench");
const serveHandler = createRequire(path.join(workbench, "web", "package.json"))("serve-handler");
const build = process.env.WORKBENCH_BUILD_DIR
  ? path.resolve(process.env.WORKBENCH_BUILD_DIR)
  : path.join(workbench, "web", ".webpack");
const layouts = process.env.WORKBENCH_LAYOUTS_DIR
  ? path.resolve(process.env.WORKBENCH_LAYOUTS_DIR)
  : path.join(workbench, "robot-layouts");
const recordings = process.env.WORKBENCH_RECORDINGS_DIR;
const port = Number(process.env.WORKBENCH_PORT ?? 5186);
if (!Number.isInteger(port) || port < 1024 || port > 65535) {
  throw new Error("WORKBENCH_PORT must be an integer between 1024 and 65535");
}
if (!fs.existsSync(path.join(build, "index.html"))) {
  throw new Error("Build the workbench first: ./workbench-dev.sh web:build:prod");
}

let live;
const runtime = createSo101Runtime({onTaskCreated: id => live?.selectTask(id)});
live = createSo101Live({runtime});
let droneLive;
const dronePlanning=createDronePlanning();
const droneRuntime=createDroneRuntime({
  onTaskCreated:id=>droneLive?.selectTask(id),
  sceneOptions:()=>droneLive?.sceneOptions()??{},
  validateSubmission:dronePlanning.validateFlight,
});
droneLive=createDroneLive({runtime:droneRuntime,planning:dronePlanning});
const server = http.createServer(async (request, response) => {
  if (await live.handle(request, response, serveHandler)) return;
  if (await runtime.handle(request, response, serveHandler)) return;
  if (await droneLive.handle(request, response, serveHandler)) return;
  if (await dronePlanning.handle(request, response, serveHandler)) return;
  if (await droneRuntime.handle(request, response, serveHandler)) return;
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { Allow: "GET, HEAD" });
    response.end("Read-only preview");
    return;
  }
  response.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  response.setHeader("Cross-Origin-Embedder-Policy", "credentialless");
  const pathname = new URL(request.url, "http://localhost").pathname;
  if (["/so101", "/so101-mobile", "/so101-station", "/so101-station-mobile", "/drone-station", "/drone-station-mobile"].includes(pathname)) {
    const base = `http://127.0.0.1:${port}`;
    const layout = pathname === "/so101" ? "so101-review" : pathname.slice(1);
    const station = pathname.includes("-station");
    const platform=pathname.startsWith("/drone-")?"drone":"so101";
    const query = new URLSearchParams({
      ...(station ? {ds:"foxglove-websocket", "ds.url":`ws://127.0.0.1:${port}/api/${platform}/scene`} :
        recordings ? {ds:"remote-file", "ds.url":`${base}/records/so101.mcap`, time:"0.04"} : {}),
      layoutUrl: `${base}/layouts/${layout}.json`,
    });
    response.writeHead(302, { Location: `/?${query}` });
    response.end();
    return;
  }
  let publicPath = build;
  if (pathname === "/") {
    request.url = "/index.html";
  } else if (pathname === "/records/so101.mcap" && recordings) {
    publicPath = path.resolve(recordings);
    request.url = "/so101.mcap";
  } else if (["/layouts/so101-review.json", "/layouts/so101-mobile.json", "/layouts/so101-station.json", "/layouts/so101-station-mobile.json", "/layouts/drone-station.json", "/layouts/drone-station-mobile.json", "/layouts/drone-review.json"].includes(pathname)) {
    publicPath = layouts;
    request.url = `/${path.basename(pathname)}`;
  } else if (pathname.startsWith("/records/") || pathname.startsWith("/layouts/")) {
    response.writeHead(404);
    response.end("Unknown local artifact");
    return;
  }
  try {
    // serve-handler owns range requests and path traversal checks.
    await serveHandler(request, response, {
      public: publicPath,
      directoryListing: false,
      cleanUrls: false,
      etag: true,
    });
  } catch (error) {
    console.error("Static preview request failed:", error);
    if (!response.headersSent) response.writeHead(500);
    response.end("Preview request failed");
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
server.listen(port, "127.0.0.1", () => {
  const base = `http://127.0.0.1:${port}`;
  console.log(`Workbench preview: ${base}`);
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
