const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { createRequire } = require('node:module');
const upstream = createRequire(path.join(__dirname, '../workbench/package.json'));
const { FoxgloveClient } = upstream('@foxglove/ws-protocol');
const WebSocket = upstream('ws');
const serveHandler = upstream('serve-handler');
const { createSo101Live } = require('../so101-live.cjs');

async function until(check, message = 'Expected live update did not arrive') {
  const deadline = Date.now() + 4000;
  while (Date.now() < deadline) {
    const result = check();
    if (result) return result;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(message);
}

// These are transport fixtures, not reconstructed robot geometry. MuJoCo geometry
// is covered by SO101's independent XML/STL tests and the real browser acceptance.
function scene(x = 0) {
  return { entities: [{
    id: 'so101-workcell', frame_id: 'world', timestamp: { sec: 0, nsec: 0 },
    metadata: [{ key: 'simulation_s', value: String(x) }],
    models: Array.from({ length: 17 }, (_, i) => ({
      pose: { position: { x, y: i, z: 0 }, orientation: { x: 0, y: 0, z: 0, w: 1 } },
      scale: { x: 1, y: 1, z: 1 }, color: { r: 1, g: 1, b: 1, a: 1 },
      url: `/api/so101/meshes/part-${i % 13}.stl`, media_type: 'model/stl', data: '',
    })),
  }] };
}

async function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'so101-live-test-'));
  const script = path.join(root, 'experiments/colab-twin/station_scene.py');
  const meshDirectory = path.join(root, 'meshes');
  fs.mkdirSync(path.dirname(script), { recursive: true });
  fs.mkdirSync(meshDirectory);
  const meshes = Array.from({ length: 13 }, (_, i) => ({ file: `part-${i}.stl` }));
  for (const mesh of meshes) fs.writeFileSync(path.join(meshDirectory, mesh.file), `solid ${mesh.file}\nendsolid\n`);
  fs.writeFileSync(path.join(meshDirectory, 'unadvertised.stl'), 'must not be served');
  fs.writeFileSync(path.join(root, 'secret.stl'), 'must not be served');
  fs.writeFileSync(script, `const fs=require('node:fs');
const scene=${scene.toString()};
if(process.argv.includes('--model-json')){
 console.log(JSON.stringify(${JSON.stringify({ mesh_directory: meshDirectory, meshes, scene: scene() })}));
}else{
 const file=process.argv[process.argv.indexOf('--preview')+1];
 const {station}=JSON.parse(fs.readFileSync(file));
 const finish=()=>console.log(JSON.stringify(scene(station.x)));
 if(station.started){fs.writeFileSync(station.started,'ready');const timer=setInterval(()=>{if(fs.existsSync(station.release)){clearInterval(timer);finish();}},10);}else finish();
}`);
  const tasks = new Map();
  const runtime = {
    paths: { python: process.execPath, sourceRoot: root, tasksRoot: path.join(root, 'tasks') },
    task: (id) => tasks.get(id),
  };
  const live = createSo101Live({ runtime });
  const server = http.createServer(async (req, res) => {
    if (!await live.handle(req, res, serveHandler)) { res.writeHead(404); res.end(); }
  });
  live.attach(server);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const clients = [];
  t.after(async () => {
    for (const ws of clients) ws.terminate();
    await new Promise((resolve) => server.close(resolve));
    fs.rmSync(root, { recursive: true, force: true });
  });
  await live.loadModel();
  async function request(route, value) {
    const response = await fetch(origin + route, {
      method: value === undefined ? 'GET' : 'POST',
      ...(value === undefined ? {} : { headers: { 'Content-Type': 'application/json', Origin: origin }, body: JSON.stringify(value) }),
      signal: AbortSignal.timeout(5000),
    });
    return { status: response.status, body: await response.json() };
  }
  async function connect() {
    const ws = new WebSocket(origin.replace('http:', 'ws:') + '/api/so101/scene', FoxgloveClient.SUPPORTED_SUBPROTOCOL);
    clients.push(ws);
    const client = new FoxgloveClient({ ws });
    const channels = new Map(), subscriptions = new Map(), messages = [];
    const errors = [];
    client.on('error', (error) => errors.push(error));
    client.on('advertise', (advertised) => {
      for (const channel of advertised) {
        channels.set(channel.topic, channel);
        subscriptions.set(client.subscribe(channel.id), channel.topic);
      }
    });
    client.on('message', (message) => messages.push({
      topic: subscriptions.get(message.subscriptionId), value: JSON.parse(new TextDecoder().decode(message.data)),
    }));
    await until(() => channels.size === 4 && messages.some((m) => m.topic === '/so101/live/scene'));
    return { channels, messages, errors, read: (topic, predicate = () => true, after = 0) => until(() => messages.slice(after).find((m) => m.topic === topic && predicate(m.value))?.value) };
  }
  return { root, origin, live, tasks, request, connect };
}

test('standard Foxglove client receives native SceneUpdate and only advertised STL files are served', async (t) => {
  const f = await fixture(t);
  const wire = await f.connect();
  const channel = wire.channels.get('/so101/live/scene');
  assert.equal(channel.schemaName, 'foxglove.SceneUpdate');
  assert.equal(channel.encoding, 'json');
  assert.equal(JSON.parse(channel.schema).properties.entities.type, 'array');
  const update = await wire.read('/so101/live/scene', (value) => value.entities.length === 1);
  assert.equal(update.entities[0].models.length, 17);
  assert.equal(new Set(update.entities[0].models.map((m) => m.url)).size, 13);
  assert.ok(update.entities[0].models.every((m) => m.url.startsWith(f.origin + '/api/so101/meshes/')));
  for (let i = 0; i < 13; i++) {
    const url = `${f.origin}/api/so101/meshes/part-${i}.stl`;
    const response = await fetch(url);
    assert.equal(response.status, 200);
    assert.equal(await response.text(), `solid part-${i}.stl\nendsolid\n`);
    assert.equal((await fetch(url, { method: 'HEAD' })).status, 200);
  }
  for (const name of ['unadvertised.stl', '%2e%2e%2fsecret.stl', 'missing.stl']) {
    assert.equal((await f.request(`/api/so101/meshes/${name}`)).status, 404);
  }
  assert.deepEqual(wire.errors, []);
});

test('editing a draft never replaces the selected task or its physical scene', async (t) => {
  const f = await fixture(t);
  f.tasks.set('running', { status: 'running', phase: 'approach', scene: scene(7), scene_time_s: 1.5, q6: [1, 2, 3, 4, 5, 6] });
  f.live.selectTask('running');
  const wire = await f.connect();
  const before = wire.messages.length;
  const response = await f.request('/api/so101/preview', { station: { x: 99 } });
  assert.equal(response.status, 200);
  assert.equal(response.body.mode, 'task');
  assert.equal(response.body.taskId, 'running');
  const update = await wire.read('/so101/live/scene', (v) => v.entities[0]?.models[0].pose.position.x === 7, before);
  assert.equal(update.entities[0].metadata.find((m) => m.key === 'task_id').value, 'running');
  assert.equal((await wire.read('/so101/live/joints')).position.elbow_flex, 3);
  await f.request('/api/so101/scene-mode', { mode: 'draft' });
  await wire.read('/so101/live/scene', (v) => v.entities[0]?.models[0].pose.position.x === 99, wire.messages.length);
});

test('a slow draft-mode request cannot override a newer task selection', async (t) => {
  const f = await fixture(t);
  f.tasks.set('first', { status: 'running', scene: scene(1) });
  f.tasks.set('newer', { status: 'running', scene: scene(2) });
  f.live.selectTask('first');
  const started = path.join(f.root, 'started'), release = path.join(f.root, 'release');
  const draft = f.request('/api/so101/scene-mode', { mode: 'draft', station: { x: 99, started, release } });
  await until(() => fs.existsSync(started));
  f.live.selectTask('newer');
  fs.writeFileSync(release, 'release');
  const response = await draft;
  assert.equal(response.body.mode, 'task');
  assert.equal(response.body.taskId, 'newer');
});

test('reselecting the current task also supersedes a pending draft-mode action', async (t) => {
  const f = await fixture(t);
  f.tasks.set('current', { status: 'running', scene: scene(1) });
  f.live.selectTask('current');
  const started = path.join(f.root, 'started'), release = path.join(f.root, 'release');
  const draft = f.request('/api/so101/scene-mode', { mode: 'draft', station: { x: 99, started, release } });
  await until(() => fs.existsSync(started));
  await f.request('/api/so101/scene-mode', { mode: 'task', taskId: 'current' });
  fs.writeFileSync(release, 'release');
  const response = await draft;
  assert.equal(response.body.mode, 'task');
  assert.equal(response.body.taskId, 'current');
});

test('cancelled final geometry repeats without drift; legacy records clear geometry and publish no invented joint/contact data', async (t) => {
  const f = await fixture(t);
  f.tasks.set('cancelled', { status: 'cancelled', phase: 'stopped', scene: scene(8), scene_final: true, scene_time_s: 4.16, q6: [1, 2, 3, 4, 5, 6], tip_forces_n: [0.12, 0.34] });
  f.tasks.set('legacy', { status: 'succeeded', simulation_s: 70 });
  f.live.selectTask('cancelled');
  const wire = await f.connect();
  const first = await wire.read('/so101/live/scene');
  const second = await wire.read('/so101/live/scene', () => true, wire.messages.length);
  assert.deepEqual(second.entities[0].models, first.entities[0].models);
  assert.equal((await wire.read('/so101/live/status')).simulation_s, 4.16);
  assert.deepEqual(await wire.read('/so101/live/contact'), { fixed_finger_n: 0.12, moving_finger_n: 0.34 });
  const after = wire.messages.length;
  const selected = await f.request('/api/so101/scene-mode', { mode: 'task', taskId: 'legacy' });
  assert.equal(selected.body.ready, false);
  const cleared = await wire.read('/so101/live/scene', (v) => v.entities.length === 0, after);
  assert.deepEqual(cleared.deletions.map(({ type, id }) => ({ type, id })), [{ type: 0, id: 'so101-workcell' }]);
  const clearedIndex = wire.messages.findIndex((m, i) => i >= after && m.value === cleared);
  await wire.read('/so101/live/scene', (v) => v.entities.length === 0 && v.deletions.length === 0, wire.messages.length);
  assert.equal(wire.messages.slice(clearedIndex).filter((m) => ['/so101/live/joints', '/so101/live/contact'].includes(m.topic)).length, 0);
  assert.equal((await f.request('/api/so101/scene-state')).body.scene, undefined);
});
