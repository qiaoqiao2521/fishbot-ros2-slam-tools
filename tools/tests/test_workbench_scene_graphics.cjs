'use strict';

// Pure argument/identity contracts. No browser, server, build, driver or ROS.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { graphicsLaunchOptions, validateGraphicsObservation } = require('../fishbot_workbench_scene_ui_contract.cjs');

function hardware() {
  return { webgl: { vendor: 'Google Inc. (NVIDIA)', renderer: 'ANGLE (NVIDIA, Vulkan 1.4.329 (NVIDIA GeForce RTX 3050 Laptop GPU), NVIDIA)' },
    actual_args: ['/opt/google/chrome/chrome', '--enable-gpu', '--use-angle=vulkan'],
    gpu: { devices: [{ vendorId: 4318, deviceString: 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3050 Laptop GPU)' }] } };
}

test('software remains the exact original launch panel; hardware removes unsafe defaults without a blocklist override', () => {
  assert.deepEqual(graphicsLaunchOptions('software'), { args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const result = graphicsLaunchOptions('hardware');
  assert.equal(result.chromiumSandbox, true);
  assert.deepEqual(result.args, ['--enable-gpu', '--use-angle=vulkan']);
  assert.deepEqual(result.ignoreDefaultArgs, ['--enable-unsafe-swiftshader', '--disable-ipc-flooding-protection', '--unsafely-disable-devtools-self-xss-warnings']);
  assert.throws(() => graphicsLaunchOptions('automatic'), /software or hardware/);
});

test('hardware needs positive WebGL, CDP device and original argv identity', () => {
  assert.doesNotThrow(() => validateGraphicsObservation('hardware', hardware()));
  for (const observation of [
    { ...hardware(), webgl: { renderer: '' } },
    { ...hardware(), webgl: { vendor: 'NVIDIA', renderer: 'NVIDIA software SwiftShader' } },
    { ...hardware(), webgl: { vendor: 'NVIDIA', renderer: 'ANGLE llvmpipe' } },
    { ...hardware(), webgl: { vendor: 'unknown', renderer: 'ANGLE NVIDIA' } },
    { ...hardware(), actual_args: undefined },
    { ...hardware(), actual_args: ['--enable-gpu'] },
    { ...hardware(), gpu: { devices: [{ vendorId: 65535, deviceString: 'SwiftShader' }] } },
  ]) assert.throws(() => validateGraphicsObservation('hardware', observation));
});

test('hardware refuses quiet software, alternate backends and safety overrides in actual argv', () => {
  for (const flag of ['--no-sandbox', '--disable-setuid-sandbox', '--ignore-gpu-blocklist', '--ignore-gpu-blocklist=true',
    '--enable-unsafe-swiftshader', '--disable-web-security', '--disable-ipc-flooding-protection',
    '--unsafely-disable-devtools-self-xss-warnings', '--disable-gpu', '--use-angle=swiftshader', '--use-gl=desktop']) {
    const observation = hardware(); observation.actual_args.push(flag);
    assert.throws(() => validateGraphicsObservation('hardware', observation), /unapproved/, flag);
  }
});

test('software identity remains software and cannot silently pass on the new hardware panel', () => {
  const software = { webgl: { vendor: 'Google', renderer: 'ANGLE SwiftShader' } };
  assert.doesNotThrow(() => validateGraphicsObservation('software', software));
  assert.throws(() => validateGraphicsObservation('hardware', software));
  assert.throws(() => validateGraphicsObservation('software', hardware()));
});
