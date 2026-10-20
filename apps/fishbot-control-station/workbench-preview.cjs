#!/usr/bin/env node
// Local read-only preview using the upstream web package's static server dependency.
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");

const workbench = path.join(__dirname, "workbench");
const serveHandler = createRequire(path.join(workbench, "web", "package.json"))("serve-handler");
const build = path.join(workbench, "web", ".webpack");
const recordings = process.env.WORKBENCH_RECORDINGS_DIR;
const port = Number(process.env.WORKBENCH_PORT ?? 5186);
if (!Number.isInteger(port) || port < 1024 || port > 65535) {
  throw new Error("WORKBENCH_PORT must be an integer between 1024 and 65535");
}
if (!fs.existsSync(path.join(build, "index.html"))) {
  throw new Error("Build the workbench first: ./workbench-dev.sh web:build:prod");
}

const server = http.createServer(async (request, response) => {
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { Allow: "GET, HEAD" });
    response.end("Read-only preview");
    return;
  }
  response.setHeader("Cross-Origin-Opener-Policy", "same-origin");
  response.setHeader("Cross-Origin-Embedder-Policy", "credentialless");
  const pathname = new URL(request.url, "http://localhost").pathname;
  if (["/so101", "/so101-mobile", "/so101-station", "/so101-station-mobile"].includes(pathname)) {
    const base = `http://127.0.0.1:${port}`;
    const layout = pathname === "/so101" ? "so101-review" : pathname.slice(1);
    const query = new URLSearchParams({
      ...(recordings ? { ds: "remote-file", "ds.url": `${base}/records/so101.mcap` } : {}),
      layoutUrl: `${base}/layouts/${layout}.json`,
      time: "0.04",
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
  } else if (["/layouts/so101-review.json", "/layouts/so101-mobile.json", "/layouts/so101-station.json", "/layouts/so101-station-mobile.json"].includes(pathname)) {
    publicPath = path.join(workbench, "robot-layouts");
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
