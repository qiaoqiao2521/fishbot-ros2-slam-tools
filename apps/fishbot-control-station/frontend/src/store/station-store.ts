import { create } from 'zustand'

import {
  mockControlFeedback,
  mockConnection,
  mockDiagnostics,
  mockNavigation,
  mockPerception,
  mockRobotState,
} from '@/lib/mock-station'
import type {
  ConnectionSnapshot,
  ControlFeedbackSnapshot,
  DiagnosticEntry,
  DiagnosticSnapshot,
  NavigationSnapshot,
  PerceptionSnapshot,
  RobotStateSnapshot,
} from '@/types/station'

type StationStore = {
  connection: ConnectionSnapshot
  robotState: RobotStateSnapshot
  navigation: NavigationSnapshot
  perception: PerceptionSnapshot
  diagnostics: DiagnosticSnapshot
  controlFeedback: ControlFeedbackSnapshot
  linearSpeed: number
  angularSpeed: number
  activeDirection: string | null
  usingFallbackData: boolean
  setConnection: (connection: ConnectionSnapshot) => void
  setRobotState: (robotState: RobotStateSnapshot) => void
  setNavigation: (navigation: NavigationSnapshot) => void
  setPerception: (perception: PerceptionSnapshot) => void
  setDiagnostics: (diagnostics: DiagnosticSnapshot) => void
  patchControlFeedback: (feedback: Partial<ControlFeedbackSnapshot>) => void
  setLinearSpeed: (value: number) => void
  setAngularSpeed: (value: number) => void
  setActiveDirection: (direction: string | null) => void
  appendCommand: (entry: DiagnosticEntry) => void
  appendError: (entry: DiagnosticEntry) => void
  appendTransport: (entry: DiagnosticEntry) => void
  setUsingFallbackData: (value: boolean) => void
}

function trimEntries(entries: DiagnosticEntry[]) {
  return entries.slice(0, 8)
}

export const useStationStore = create<StationStore>((set) => ({
  connection: mockConnection,
  robotState: mockRobotState,
  navigation: mockNavigation,
  perception: mockPerception,
  diagnostics: mockDiagnostics,
  controlFeedback: mockControlFeedback,
  linearSpeed: 0.32,
  angularSpeed: 1.0,
  activeDirection: null,
  usingFallbackData: true,
  setConnection: (connection) => set({ connection }),
  setRobotState: (robotState) => set({ robotState }),
  setNavigation: (navigation) => set({ navigation }),
  setPerception: (perception) => set({ perception }),
  setDiagnostics: (diagnostics) => set({ diagnostics }),
  patchControlFeedback: (feedback) =>
    set((state) => ({
      controlFeedback: {
        ...state.controlFeedback,
        ...feedback,
      },
    })),
  setLinearSpeed: (linearSpeed) => set({ linearSpeed }),
  setAngularSpeed: (angularSpeed) => set({ angularSpeed }),
  setActiveDirection: (activeDirection) => set({ activeDirection }),
  appendCommand: (entry) =>
    set((state) => ({
      diagnostics: {
        ...state.diagnostics,
        commands: trimEntries([entry, ...state.diagnostics.commands]),
      },
    })),
  appendError: (entry) =>
    set((state) => ({
      diagnostics: {
        ...state.diagnostics,
        errors: trimEntries([entry, ...state.diagnostics.errors]),
      },
    })),
  appendTransport: (entry) =>
    set((state) => ({
      diagnostics: {
        ...state.diagnostics,
        transport: trimEntries([entry, ...state.diagnostics.transport]),
      },
    })),
  setUsingFallbackData: (usingFallbackData) => set({ usingFallbackData }),
}))
