import catalog from '../../public/workbench/recent-results.json'
import type { AppRoute } from '@/lib/app-route'

export type ServiceId = 'spatiallm' | 'video'
export type CaseStatus = 'completed' | 'safe-cancel' | 'failed'
export type CaseFilter = 'all' | 'failed' | 'completed' | 'safe-cancel'
export type CapabilityAction = { label: string; route: AppRoute } | { label: string; service: ServiceId } | { label: string; href: string }
export interface Capability {
  id: string; title: string; summary: string; status: 'verified' | 'partial' | 'pipeline'
  statusLabel: string; highlights: string[]; boundary: string; action: CapabilityAction; evidenceUrl: string
}
export interface VisualCase { id: string; label: string; stage: string; status: CaseStatus; reason: string; scoreSha256: string }
export interface WorkflowCase {
  id: string; title: string; outcome: 'completed' | 'safe-cancel'; passed: boolean
  durationSeconds: number; cargoDistanceMeters: number | null; scoreSha256: string
}
export interface WorkbenchCatalog {
  schemaVersion: number; updatedAt: string; period: string; sourceRevision: string; snapshotLabel: string
  capabilities: Capability[]
  visual: { total: number; completed: number; safeCanceled: number; failed: number; shortCount: number; fullCount: number; qualified: boolean; shortCompleted: number; fullCompleted: number; reportSha256: string; cases: VisualCase[] }
  workflow: { total: number; completed: number; safeCanceled: number; failed: number; qualified: boolean; elapsedSeconds: number; reportSha256: string; cases: WorkflowCase[] }
  services: Record<ServiceId, { label: string; url: string; probe: string }>
  insights: { title: string; body: string }[]
  nextSteps: { title: string; detail: string }[]
  provenance: { id: string; source: string; sha256: string; classification: string }[]
}

export const workbenchSnapshot = catalog as WorkbenchCatalog
export const caseStatusLabels: Record<CaseStatus, string> = { completed: '任务完成', 'safe-cancel': '正确取消', failed: '未通过' }

export function selectVisualCases(filter: CaseFilter, snapshot = workbenchSnapshot): VisualCase[] {
  return snapshot.visual.cases.filter((item) => filter === 'all' || item.status === filter)
}

export function isWorkbenchLocalHost(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]' || hostname === '::1'
}
