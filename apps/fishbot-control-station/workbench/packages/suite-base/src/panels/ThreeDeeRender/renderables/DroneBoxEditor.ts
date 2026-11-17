/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

import * as THREE from "three";
import { TransformControls } from "three/examples/jsm/controls/TransformControls.js";

import {
  getDroneEditor,
  subscribeDroneEditor,
} from "@lichtblick/suite-base/panels/RobotStation/droneEditor";
import { worldPosition } from "@lichtblick/suite-base/panels/RobotStation/station";

import type { IRenderer } from "../IRenderer";
import { SceneExtension } from "../SceneExtension";

/**
 * Uses the native renderer and upstream Three.js handles to edit a PX4 draft.
 * The wire box is a temporary drag outline. The normal SceneEntity remains
 * authoritative after the draft commit and its existing preview update.
 */
export class DroneBoxEditor extends SceneExtension {
  public static extensionId = "robot.DroneBoxEditor";
  #controls?: TransformControls;
  #outline = new THREE.Mesh(
    new THREE.BoxGeometry(1, 1, 1),
    new THREE.MeshBasicMaterial({
      color: 0xffdb58,
      wireframe: true,
      depthTest: false,
      transparent: true,
      opacity: 0.9,
    }),
  );
  #unsubscribe: () => void;
  #selectedId?: string;
  #changed = false;

  public constructor(renderer: IRenderer) {
    super(DroneBoxEditor.extensionId, renderer);
    this.#outline.visible = false;
    this.add(this.#outline);
    this.#unsubscribe = subscribeDroneEditor(this.#sync);
    renderer.on("topicsChanged", this.#sync);
    renderer.gl.domElement.addEventListener("pointerdown", this.#capturePointerDown, true);
    renderer.gl.domElement.addEventListener("lostpointercapture", this.#lostPointerCapture);
    window.addEventListener("pointerup", this.#restoreInteraction);
    window.addEventListener("pointercancel", this.#cancelDrag);
    window.addEventListener("blur", this.#cancelDrag);
  }

  #capturePointerDown = (): void => {
    if (this.#controls?.visible === true && this.#controls.axis != undefined) {
      this.renderer.cameraHandler.setInteractionEnabled?.({ enabled: false });
    }
  };

  #restoreInteraction = (): void => {
    // A normal canvas pointerup has already ended the upstream gesture. A
    // release delivered elsewhere must not leave its dragging state latched.
    if (this.#controls?.dragging === true) {
      this.#cancelDrag();
    }
    if (this.#controls) {
      this.renderer.cameraHandler.setInteractionEnabled?.({ enabled: true });
    }
  };

  #cancelDrag = (): void => {
    const controls = this.#controls;
    if (controls?.dragging === true) {
      if (controls.object) {
        controls.reset();
      }
      controls.dragging = false;
      controls.axis = null;
    }
    this.#changed = false;
    if (controls) {
      this.renderer.cameraHandler.setInteractionEnabled?.({ enabled: true });
      this.renderer.queueAnimationFrame();
    }
  };

  #lostPointerCapture = (): void => {
    // releasePointerCapture runs before the upstream pointerup finishes.
    queueMicrotask(() => {
      if (this.#controls?.dragging === true) {
        this.#cancelDrag();
      }
    });
  };

  #draggingChanged = (): void => {
    this.renderer.cameraHandler.setInteractionEnabled?.({
      enabled: this.#controls?.dragging !== true,
    });
  };

  #sync = (): void => {
    const state = getDroneEditor();
    const enabled =
      state?.enabled === true && this.renderer.topicsByName?.has("/drone/live/scene") === true;
    const node = enabled
      ? state.station.nodes.find(
          (item) =>
            item.id === state.selectedId && item.kind === "obstacle" && item.enabled !== false,
        )
      : undefined;
    if (!node || !state) {
      this.#cancelDrag();
      this.#controls?.detach();
      this.#outline.visible = false;
      this.#selectedId = undefined;
      if (this.#controls) {
        this.renderer.cameraHandler.setInteractionEnabled?.({ enabled: true });
      }
      this.renderer.queueAnimationFrame();
      return;
    }
    if (!this.#controls) {
      const controls = new TransformControls(
        this.renderer.cameraHandler.getActiveCamera(),
        this.renderer.gl.domElement,
      );
      controls.setSpace("world");
      controls.setSize(0.9);
      controls.addEventListener("change", this.#render);
      controls.addEventListener("objectChange", this.#objectChanged);
      controls.addEventListener("mouseUp", this.#commit);
      controls.addEventListener("dragging-changed", this.#draggingChanged);
      this.#controls = controls;
      this.add(controls);
    }
    if (this.#selectedId !== node.id) {
      this.#cancelDrag();
    }
    if (!this.#controls.dragging) {
      this.#selectedId = node.id;
      this.#outline.position.fromArray(worldPosition(node, state.station.nodes));
      this.#outline.scale.fromArray(node.size ?? [1, 1, 2]);
      this.#outline.visible = true;
      this.#controls.attach(this.#outline);
      this.#controls.setMode(state.mode);
    }
    this.renderer.queueAnimationFrame();
  };

  #render = (): void => {
    this.renderer.queueAnimationFrame();
  };

  #objectChanged = (): void => {
    this.#changed = true;
    this.#outline.scale.clampScalar(0.05, 100);
    this.#render();
  };

  #commit = (): void => {
    this.renderer.cameraHandler.setInteractionEnabled?.({ enabled: true });
    const state = getDroneEditor();
    if (this.#changed && state?.enabled === true && this.#selectedId) {
      state.transform(
        this.#selectedId,
        this.#outline.position.toArray(),
        this.#outline.scale.toArray(),
      );
    }
    this.#changed = false;
  };

  public override startFrame(): void {
    if (this.#controls) {
      this.#controls.camera = this.renderer.cameraHandler.getActiveCamera();
    }
  }

  public override dispose(): void {
    this.#unsubscribe();
    this.renderer.off("topicsChanged", this.#sync);
    this.renderer.gl.domElement.removeEventListener("pointerdown", this.#capturePointerDown, true);
    this.renderer.gl.domElement.removeEventListener("lostpointercapture", this.#lostPointerCapture);
    window.removeEventListener("pointerup", this.#restoreInteraction);
    window.removeEventListener("pointercancel", this.#cancelDrag);
    window.removeEventListener("blur", this.#cancelDrag);
    if (this.#controls) {
      this.renderer.cameraHandler.setInteractionEnabled?.({ enabled: true });
    }
    this.#controls?.dispose();
    this.#controls = undefined;
    this.#outline.geometry.dispose();
    this.#outline.material.dispose();
    super.dispose();
  }
}
