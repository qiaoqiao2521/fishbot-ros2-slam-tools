"use strict";
const assert = require("node:assert/strict");
const { test } = require("node:test");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const vm = require("node:vm");

function editorState() {
  const fields = Object.fromEntries(["position_x", "position_y", "position_z", "angle_z"]
    .map(name => [name, { name, value: "0", addEventListener() {} }]));
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      hidden: true, disabled: false, addEventListener() {}, removeAttribute() {},
      querySelector(selector) { return fields[selector.match(/name="([^"]+)"/)[1]]; },
      querySelectorAll() { return id === "robot-fields" ? Object.values(fields) : []; },
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    document: { getElementById: element, querySelectorAll() { return []; } },
    window: { addEventListener() {} },
  });
  vm.runInContext(readFileSync(join(__dirname, "../static/editor.js"), "utf8"), context);
  // Only presentation is stubbed; document identity and pose logic stay real.
  vm.runInContext("renderSource=renderWarnings=renderSelection=renderHistory=renderDrawing=()=>{}", context);
  return {
    fields,
    load(doc) {
      context.nextDocument = doc;
      vm.runInContext("setDocument(nextDocument)", context);
    },
  };
}

function layout(id, revision, origin) {
  return {
    document_id: id, revision,
    entities: [{ id: "wall_0", kind: "wall", params: {
      ax: origin, ay: origin, az: 0, bx: origin + 4, by: origin, bz: 0,
      height: 3, thickness: .12,
    } }],
  };
}

test("single and bulk correction revisions preserve the user's robot pose", () => {
  const editor = editorState();
  editor.load(layout("same-scene", 1, 0));
  const chosen = { position_x: "3.25", position_y: "-2.8", position_z: "0.002", angle_z: "0.4" };
  for (const [name, value] of Object.entries(chosen)) editor.fields[name].value = value;
  editor.load(layout("same-scene", 2, 1));
  editor.load(layout("same-scene", 3, -2));
  assert.deepEqual(Object.fromEntries(Object.entries(editor.fields).map(([name, field]) => [name, field.value])), chosen);
});

test("loading another document initializes a fresh suggested planar pose", () => {
  const editor = editorState();
  editor.load(layout("first-scene", 1, 0));
  editor.fields.position_x.value = "3.25";
  editor.fields.position_y.value = "-2.8";
  editor.load(layout("another-scene", 1, 10));
  assert.equal(editor.fields.position_x.value, "10.500");
  assert.equal(editor.fields.position_y.value, "9.500");
});
