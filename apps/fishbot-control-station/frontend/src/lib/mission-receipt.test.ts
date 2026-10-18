import { describe, expect, it } from 'vitest'
import { decodeMissionReceipt, readMissionReceipt, receiptMatches, saveMissionReceipt } from './mission-receipt'
const receipt = { version: 1 as const, domain: 127, missionId: '10b0dcd5-2bc7-4e17-a31e-7a0891c31300', instanceId: 'instance-a', mapId: 'map-a' }
describe('mission receipt recovery', () => {
  it('keeps only identity, without a replayable command', () => {
    let raw: string | null = null
    saveMissionReceipt({ setItem: (_key, value) => { raw = value } }, receipt)
    expect(readMissionReceipt({ getItem: () => raw }, 127)).toEqual(receipt)
    expect(raw).not.toMatch(/waypoint|issued_at|return_home|action/)
  })
  it('requires the exact task and runtime, even for identical waypoints', () => {
    expect(receiptMatches(receipt, 127, 'instance-a', receipt.missionId)).toBe(true)
    expect(receiptMatches(receipt, 128, 'instance-a', receipt.missionId)).toBe(false)
    expect(receiptMatches(receipt, 127, 'instance-b', receipt.missionId)).toBe(false)
    expect(receiptMatches(receipt, 127, 'instance-a', 'another-task')).toBe(false)
  })
  it('rejects corrupt, cross-domain, oversized and action-bearing records', () => {
    for (const raw of ['{broken', ' '.repeat(2049), JSON.stringify({ ...receipt, domain: 128 }), JSON.stringify({ ...receipt, action: 'start' }), JSON.stringify({ ...receipt, missionId: 'invalid' })]) {
      expect(() => decodeMissionReceipt(raw, 127)).toThrow()
    }
  })
  it('does not hide storage failure or turn it into a saved receipt', () => {
    expect(() => saveMissionReceipt({ setItem: () => { throw new Error('quota') } }, receipt)).toThrow('quota')
    expect(readMissionReceipt({ getItem: () => null }, 127)).toBeNull()
  })
})

describe('original task ledger readback', () => {
 it('accepts only matching terminal records; old active and cleanup unknown remain unresolved', async () => {
  const { recoveredTerminal } = await import('./mission-receipt')
  const lookup = { task_id: receipt.missionId, source: 'persisted', runtime_instance_id: receipt.instanceId, current_runtime_instance_id: 'new-instance', mission: { id: receipt.missionId, map_id: receipt.mapId, status: 'succeeded' } }
  expect(recoveredTerminal(receipt, lookup)).toContain('物理验收需另看报告')
  for (const status of ['running', 'canceling', 'unknown', 'idle']) expect(recoveredTerminal(receipt, { ...lookup, mission: { ...lookup.mission, status } })).toBeNull()
  expect(recoveredTerminal(receipt, { ...lookup, mission: { ...lookup.mission, cleanup_state: 'unresolved' } })).toBeNull()
  expect(() => recoveredTerminal(receipt, { ...lookup, runtime_instance_id: 'another-instance' })).toThrow()
  expect(() => recoveredTerminal(receipt, { ...lookup, mission: { ...lookup.mission, id: 'another-task' } })).toThrow()
 })
})
