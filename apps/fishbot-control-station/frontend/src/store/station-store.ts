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

export type StationResource = 'connection' | 'robotState' | 'navigation' | 'perception' | 'diagnostics'
export type ResourceProvenance = { status: 'example' | 'received' | 'stale' | 'invalid'; receivedAt: number | null; error: string | null }
const resources: StationResource[] = ['connection', 'robotState', 'navigation', 'perception', 'diagnostics']
const initialProvenance = () => Object.fromEntries(resources.map((name) => [name, { status: 'example', receivedAt: null, error: null }])) as Record<StationResource, ResourceProvenance>
function received(state: StationStore, resource: StationResource) {
  const resourceProvenance = { ...state.resourceProvenance, [resource]: { status: 'received' as const, receivedAt: Date.now(), error: null } }
  return { resourceProvenance, usingFallbackData: resources.some((name) => resourceProvenance[name].receivedAt === null) }
}

type StationStore = {
  resourceProvenance: Record<StationResource, ResourceProvenance>
  markResourceError: (resource: StationResource, error: string, invalid?: boolean) => void
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
  resourceProvenance: initialProvenance(),
  markResourceError: (resource, error, invalid = false) => set((state) => ({
    resourceProvenance: { ...state.resourceProvenance, [resource]: {
      ...state.resourceProvenance[resource], status: invalid ? 'invalid' : state.resourceProvenance[resource].receivedAt === null ? 'example' : 'stale', error,
    } },
  })),
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
  setConnection: (connection) => set((state) => ({ connection, ...received(state, 'connection') })),
  setRobotState: (robotState) => set((state) => ({ robotState, ...received(state, 'robotState') })),
  setNavigation: (navigation) => set((state) => ({ navigation, ...received(state, 'navigation') })),
  setPerception: (perception) => set((state) => ({ perception, ...received(state, 'perception') })),
  setDiagnostics: (diagnostics) => set((state) => ({ diagnostics, ...received(state, 'diagnostics') })),
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
