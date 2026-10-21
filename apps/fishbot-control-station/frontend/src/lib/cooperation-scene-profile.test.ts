import { describe, expect, it } from 'vitest'
import {
  DEFAULT_COOPERATION_SCENE_PROFILE, cooperationLiveProfile,
  cooperationSceneProfileDocument, cooperationSceneProfileHref, parseCooperationSceneProfile,
} from './cooperation-scene-profile'

describe('cooperation scene profile contract', () => {
  it('downloads only the selected four-field configuration with the legacy default', () => {
    expect(JSON.parse(cooperationSceneProfileDocument(DEFAULT_COOPERATION_SCENE_PROFILE))).toEqual({
      schema: 1, vehicle: 'fishbot', sensors: 'planar', task: 'transport',
    })
    const selected = { schema: 1, vehicle: 'jackal_j100', sensors: 'lidar3d', task: 'three_batch_transport' } as const
    expect(JSON.parse(decodeURIComponent(cooperationSceneProfileHref(selected).split(',').slice(1).join(',')))).toEqual(selected)
  })

  it('does not accept unsupported or malformed fields as a real running profile', () => {
    for (const value of [null, {}, { ...DEFAULT_COOPERATION_SCENE_PROFILE, schema: 2 },
      { ...DEFAULT_COOPERATION_SCENE_PROFILE, vehicle: 'unknown' },
      { ...DEFAULT_COOPERATION_SCENE_PROFILE, sensors: { toString: null } },
      { ...DEFAULT_COOPERATION_SCENE_PROFILE, domain: 136 }]) {
      expect(parseCooperationSceneProfile(value)).toBeNull()
    }
  })

  it('uses actual vehicle metadata and reports conflicts without granting browser workflow ownership', () => {
    const live = cooperationLiveProfile({
      scene_profile: { ...DEFAULT_COOPERATION_SCENE_PROFILE, task: 'three_batch_transport' },
      vehicle_profile: { id: 'jackal_j100', label: 'Clearpath Jackal J100' },
    })
    expect(live.vehicleName).toBe('Clearpath Jackal J100')
    expect(live.note).toContain('不一致')
    expect(live.workflowOwned).toBe(true)
  })

  it('labels legacy and missing reports explicitly instead of inferring the draft was applied', () => {
    expect(cooperationLiveProfile({}).vehicleName).toBe('FishBot')
    expect(cooperationLiveProfile({}).note).toContain('旧接口')
    expect(cooperationLiveProfile({}).sensorsLabel).toBe('未上报')
    expect(cooperationLiveProfile(null).reported).toBe(false)
    expect(cooperationLiveProfile(null).note).toContain('等待协同服务')
    expect(cooperationLiveProfile({ vehicle_profile: { id: 'future-robot' } }).vehicleName).toBe('未识别车型')
  })
})
