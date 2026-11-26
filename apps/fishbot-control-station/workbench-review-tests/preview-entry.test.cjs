// SPDX-License-Identifier: MPL-2.0
// HTTP routing fixtures only: no browser rendering, simulator, or robot is started.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
const {spawn} = require('node:child_process');

async function freePort() {
  const server = http.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}
function request(port, route, headers = {}, method = 'GET') {
  return new Promise((resolve, reject) => {
    const req = http.request({hostname:'127.0.0.1', port, path:route, headers, method}, res => {
      let body = '';
      res.setEncoding('utf8'); res.on('data', chunk => { body += chunk; });
      res.on('end', () => resolve({status:res.statusCode, headers:res.headers, body}));
    });
    req.setTimeout(6000, () => req.destroy(new Error('HTTP fixture timed out')));
    req.on('error', reject); req.end();
  });
}

test('shared preview routes project entry, existing frontends and remote layouts without starting a task', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'workbench-entry-'));
  const native = path.join(root, 'native'), fishbot = path.join(root, 'fishbot');
  fs.mkdirSync(native); fs.mkdirSync(path.join(fishbot, 'assets'), {recursive:true});
  fs.writeFileSync(path.join(native, 'index.html'), '<title>Native routing fixture</title>');
  fs.writeFileSync(path.join(fishbot, 'index.html'), '<title>FishBot routing fixture</title>');
  fs.writeFileSync(path.join(fishbot, 'assets/app.js'), 'routing fixture');
  const port = await freePort();
  const child = spawn(process.execPath, [path.join(__dirname, '../workbench-preview.cjs')], {
    env:{...process.env, WORKBENCH_CONFIG:'', WORKBENCH_BUILD_DIR:native,
      WORKBENCH_FRONTEND_DIST:fishbot, WORKBENCH_HOST:'127.0.0.1', WORKBENCH_PORT:String(port),
      WORKBENCH_PUBLIC_URL:'https://workbench.example', DRONE_BACKEND:'cerlab',
      SO101_ROOT:root, SO101_PYTHON:path.join(root, 'missing-python'),
      DRONE_ROOT:root, CERLAB_ROOT:root,
      SO101_TASKS_DIR:path.join(root, 'so101-tasks'), DRONE_TASKS_DIR:path.join(root, 'drone-tasks'),
      DRONE_PLANS_DIR:path.join(root, 'drone-plans'), DRONE_DIAGNOSTICS_DIR:path.join(root, 'diagnostics')},
    stdio:['ignore', 'pipe', 'pipe'],
  });
  let logs = '';
  t.after(async () => {
    if (child.exitCode === null && child.signalCode === null) {
      const exited = new Promise(resolve => child.once('exit', resolve));
      child.kill('SIGTERM'); await exited;
    }
    fs.rmSync(root, {recursive:true, force:true});
  });
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Preview did not start: ' + logs)), 10000);
    const collect = chunk => {
      logs += chunk;
      if (logs.includes('Workbench projects:')) {clearTimeout(timer); resolve();}
    };
    child.stdout.on('data', collect); child.stderr.on('data', collect);
    child.once('error', error => {clearTimeout(timer); reject(error);});
    child.once('exit', code => {clearTimeout(timer); reject(new Error('Preview exited ' + code + ': ' + logs));});
  });
  const remote = {Host:'workbench.example', Origin:'https://workbench.example'};
  const home = await request(port, '/start', remote);
  assert.equal(home.status, 200);
  for (const route of ['/results', '/cooperation', '/so101-station', '/drone-station', '/drone-showcase']) {
    assert.ok(home.body.includes('href="' + route + '"'), route);
  }
  const status = await request(port, '/api/workbench/status', remote);
  assert.equal(status.status, 200);
  const projects = JSON.parse(status.body).projects;
  assert.equal(projects.fishbot.ready, true);
  assert.equal(projects.so101.ready, false);
  assert.equal(projects.drone.ready, false);
  assert.match(projects.so101.message, /doctor --project so101/);
  assert.match(projects.drone.message, /doctor --project drone/);
  for (const route of ['/results', '/fishbot', '/cooperation']) {
    assert.match((await request(port, route, remote)).body, /FishBot routing fixture/);
  }
  assert.equal((await request(port, '/assets/app.js', remote)).body, 'routing fixture');
  assert.match((await request(port, '/', remote)).body, /Native routing fixture/);
  assert.equal((await request(port, '/drone-showcase', remote)).status, 200);
  for (const platform of ['so101', 'drone']) {
    const response = await request(port, '/' + platform + '-station', remote);
    assert.equal(response.status, 302);
    const target = new URL(response.headers.location, 'https://workbench.example');
    assert.equal(target.searchParams.get('ds.url'), 'wss://workbench.example/api/' + platform + '/scene');
    assert.equal(target.searchParams.get('layoutUrl'), 'https://workbench.example/layouts/' + platform + '-station.json');
    const layout = await request(port, '/layouts/' + platform + '-station.json', remote);
    assert.equal(layout.status, 200); assert.equal(typeof JSON.parse(layout.body), 'object');
  }
  const local = await request(port, '/so101-station');
  const target = new URL(local.headers.location, 'http://127.0.0.1:' + port);
  assert.equal(target.searchParams.get('ds.url'), 'ws://127.0.0.1:' + port + '/api/so101/scene');
  assert.equal((await request(port, '/start', {Host:'untrusted.example'})).status, 403);
  assert.equal((await request(port, '/api/workbench/status', remote, 'POST')).status, 405);
  assert.equal((await request(port, '/layouts/missing.json', remote)).status, 404);
  for (const name of ['so101-tasks', 'drone-tasks', 'drone-plans']) {
    assert.deepEqual(fs.readdirSync(path.join(root, name)), []);
  }
});
