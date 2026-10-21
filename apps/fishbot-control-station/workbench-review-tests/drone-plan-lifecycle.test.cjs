const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const { createRequire } = require('node:module');
const upstream = createRequire(path.join(__dirname, '../workbench/package.json'));
const ts = upstream('typescript');
const file = path.join(__dirname, '../workbench/packages/suite-base/src/panels/RobotStation/index.tsx');
const source = ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let initializer;
function visit(node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'startPlan') initializer = node.initializer;
  ts.forEachChild(node, visit);
}
visit(source);
assert(initializer, 'Use the production plan handler');
const code = ts.transpileModule(`const run = ${initializer.getText(source)}; run;`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText;

function fixture() {
  const jobs = new Map();
  const config = {};
  const events = [];
  class TaskRequestError extends Error {
    constructor(message, status) { super(message); this.status = status; }
  }
  const context = {
    planController: { current: undefined }, planSubmitting: false, planTask: undefined, task: undefined,
    taskIsActive: task => task?.status === 'running',
    crypto: { randomUUID: () => 'original-plan-id' }, AbortController,
    station: { platform: 'px4', name: 'editable-station' },
    window: { location: { href: 'http://127.0.0.1:5187/drone-station' }, history: { replaceState() {} } },
    URL, TaskRequestError,
    saveConfig: value => Object.assign(config, value),
    setPlanSubmitting: value => { context.planSubmitting = value; },
    setPlanError: value => { context.error = value; },
    setPlanTask: value => { context.planTask = value; },
    requestSimulation: async (endpoint, signal, body) => {
      if (signal.aborted) throw new Error('unmounted before submission');
      assert.equal(endpoint, '/plans');
      events.push('submit');
      jobs.set(body.taskId, body.station);
      return { id: body.taskId, status: 'pending' };
    },
    changeScene: async mode => {
      assert.equal(mode, 'draft');
      events.push('source-remount');
      context.planController.current.abort(); // Production unmount cleanup.
    },
  };
  return { context, jobs, config, events, run: vm.runInNewContext(code, context) };
}

test('source remount leaves exactly one server job under the saved plan ID', async () => {
  const f = fixture();
  await f.run();
  assert.equal(f.jobs.size, 1);
  assert.equal(f.jobs.get(f.config.previewPlanId), f.context.station);
  assert.deepEqual(f.events, ['submit', 'source-remount']);
  assert.equal(f.context.planController.current, undefined);
  assert.equal(f.context.error, '');
});

test('rejected submission keeps its ID and does not switch the source or retry', async () => {
  const f = fixture();
  let calls = 0;
  f.context.requestSimulation = async () => {
    calls++;
    throw new f.context.TaskRequestError('invalid draft', 422);
  };
  await f.run();
  assert.equal(calls, 1);
  assert.equal(f.jobs.size, 0);
  assert.deepEqual(f.events, []);
  assert.equal(f.context.planTask.id, f.config.previewPlanId);
  assert.equal(f.context.planTask.status, 'failed');
  assert.equal(f.context.planSubmitting, false);
});

test('unmount after admission preserves a queryable saved ID without resubmission', async () => {
  const f = fixture();
  const submit = f.context.requestSimulation;
  f.context.requestSimulation = async (...args) => {
    const result = await submit(...args);
    f.context.planController.current.abort();
    return result;
  };
  await f.run();
  assert.equal(f.jobs.size, 1);
  assert.equal(f.jobs.get(f.config.previewPlanId), f.context.station);
  assert.deepEqual(f.events, ['submit']);
  assert.equal(f.context.planController.current, undefined);
});
