import { describe, it, expect } from 'vitest'
import { decodeRuleDraft, readRuleDraft, writeRuleDraft } from './rule-draft-cache'
const draft = { version: 1 as const, domain: 127, mapId: 'map-a', baseRevision: 4, zones: [{ id: 'wall-a', kind: 'wall' as const, points: [{ x: 1, y: 1 }, { x: 2, y: 1 }] }] }
describe('unpublished map rule cache', () => {
 it('retains original revision and no application or motion state', () => {
  let raw: string | null = null
  writeRuleDraft({ setItem: (_key, value) => { raw = value } }, draft)
  expect(readRuleDraft({ getItem: () => raw }, 127, 'map-a')).toEqual(draft)
  expect(raw).not.toMatch(/applied|mission|issued_at/)
 })
 it('rejects a different domain/map, bad geometry, extra actions and oversized cache', () => {
  for (const value of [{ ...draft, domain: 128 }, { ...draft, mapId: 'other' }, { ...draft, zones: [{ ...draft.zones[0], points: [] }] }, { ...draft, action: 'save' }]) {
   expect(() => decodeRuleDraft(JSON.stringify(value), 127, 'map-a')).toThrow()
  }
  expect(() => decodeRuleDraft(' '.repeat(65537), 127, 'map-a')).toThrow()
 })
 it('does not hide storage failure', () => {
  expect(() => writeRuleDraft({ setItem: () => { throw new Error('quota') } }, draft)).toThrow('quota')
 })
})
