import { describe, it, expect } from 'vitest'
import { validateWorkbenchProfile, workbenchProxy } from './workbench-profile'
const profile = () => ({ schema_version: 1, label: '本地验收', services: { station: { port: 8087, domain: null }, mission: { port: 9097, domain: 127 }, cooperation: { port: 9098, domain: 128 }, voice: { port: 9099, domain: 127 } }, tools: { spatiallm: null, video: null } })
describe('server-owned workbench profile', () => {
 it('creates only fixed loopback same-origin proxy routes', () => {
  const value = validateWorkbenchProfile(profile(), 5182)
  const proxy = workbenchProxy(value)
  expect(proxy['/sim-api'].target).toBe('http://127.0.0.1:9097')
  expect(proxy['/workbench-service/video']).toBeUndefined()
  expect(value.services.cooperation.domain).toBe(128)
 })
 it('rejects browser-selectable URLs, unknown keys, occupied aliases and unsafe domains', () => {
  const cases = [profile(), profile(), profile(), profile(), profile()]
  Object.assign(cases[0].services.mission, { url: 'http://remote/' })
  cases[1].services.mission.port = 5182
  cases[2].services.voice.port = cases[2].services.mission.port
  cases[3].services.mission.domain = 0
  Object.assign(cases[4], { credentials: 'unaccepted' })
  for (const value of cases) expect(() => validateWorkbenchProfile(value, 5182)).toThrow()
 })
 it('keeps different domains explicit instead of combining all services into one robot', () => {
  const value = validateWorkbenchProfile(profile(), 5182)
  expect(value.services.mission.domain).not.toBe(value.services.cooperation.domain)
 })
})
