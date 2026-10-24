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

  it('retains the mecanum vehicle and selected sensors through draft export and service readback', () => {
    const profile = { schema: 1, vehicle: 'robot_base_mecanum', sensors: 'lidar3d', task: 'transport' } as const
    expect(parseCooperationSceneProfile(JSON.parse(cooperationSceneProfileDocument(profile)))).toEqual(profile)
    const live = cooperationLiveProfile({ scene_profile: profile, vehicle_profile: { id: 'robot_base_mecanum', label: 'robot_base Mecanum' } })
    expect(live.reported).toBe(true)
    expect(live.vehicleName).toBe('robot_base Mecanum')
    expect(live.sensorsLabel).toContain('3D')
    expect(live.note).not.toContain('不一致')
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
