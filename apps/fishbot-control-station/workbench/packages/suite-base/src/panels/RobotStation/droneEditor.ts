/* eslint-disable @lichtblick/license-header -- Project-owned MPL adaptation. */
// SPDX-FileCopyrightText: Copyright (C) 2026 SO101/FishBot contributors
// SPDX-License-Identifier: MPL-2.0
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v2.0. https://mozilla.org/MPL/2.0/

import type { Station, Vec3 } from "./station";

// One mounted PX4 draft owns the native 3D edit handles. Nothing is published
// to a flight controller; committing a handle uses the normal draft editor.
export type DroneEditorSession = {
  owner: object;
  enabled: boolean;
  station: Station;
  selectedId: string;
  mode: "translate" | "scale";
  setMode: (mode: "translate" | "scale") => void;
  select: (id: string) => void;
  transform: (id: string, worldPosition: Vec3, size: Vec3) => void;
};

let session: DroneEditorSession | undefined;
const listeners = new Set<() => void>();

export const getDroneEditor = (): DroneEditorSession | undefined => session;

export const subscribeDroneEditor = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

export function setDroneEditor(value: DroneEditorSession): void {
  session = value;
  listeners.forEach((listener) => {
    listener();
  });
}

export function clearDroneEditor(owner: object): void {
  if (session?.owner === owner) {
    session = undefined;
    listeners.forEach((listener) => {
      listener();
    });
  }
}
