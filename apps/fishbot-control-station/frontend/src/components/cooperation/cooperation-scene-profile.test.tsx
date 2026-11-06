import { isValidElement, type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { CooperationSceneProfileView } from './cooperation-scene-profile'
import { DEFAULT_COOPERATION_SCENE_PROFILE, type CooperationSceneProfile, type CooperationScanPattern } from '@/lib/cooperation-scene-profile'

function select(node: ReactNode, id: string): { value: string; onChange: (event: { target: { value: string } }) => void } | null {
  if (Array.isArray(node)) return node.map((item) => select(item, id)).find(Boolean) ?? null
  if (!isValidElement<{ id?: string; value?: string; onChange?: (event: { target: { value: string } }) => void; children?: ReactNode }>(node)) return null
  if (node.type === 'select' && node.props.id === id) return node.props as ReturnType<typeof select>
  return select(node.props.children, id)
}

describe('scene configuration draft panel', () => {
  it('updates and downloads a draft without requests or changing the actual running combination', () => {
    const fetcher = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    let draft: CooperationSceneProfile = { ...DEFAULT_COOPERATION_SCENE_PROFILE }
    const state = { scene_profile: DEFAULT_COOPERATION_SCENE_PROFILE, vehicle_profile: { id: 'fishbot', label: 'FishBot' } }
    const tree = () => CooperationSceneProfileView({ state, draft, onDraftChange: (next) => { draft = next } })
    select(tree(), 'cooperation-draft-vehicle')!.onChange({ target: { value: 'jackal_j100' } })
    select(tree(), 'cooperation-draft-sensors')!.onChange({ target: { value: 'lidar3d' } })
    select(tree(), 'cooperation-draft-task')!.onChange({ target: { value: 'three_batch_transport' } })
    const html = renderToStaticMarkup(tree())
    const live = html.split('data-scene-profile-kind="live"')[1].split('data-scene-profile-kind="draft"')[0]
    expect(live).toContain('FishBot')
    expect(live).toContain('2D 平面雷达')
    expect(live).not.toContain('Jackal')
    expect(html).toContain('2D + 3D 雷达')
    expect(html).toContain('download="cooperation-profile.json"')
    expect(html).toContain('现有 workflow 执行')
    expect(html).toContain('不会热替换当前实验')
    expect(html).toContain('--scene-profile /path/to/cooperation-profile.json')
    const href = html.match(/href="(data:application\/json[^"]+)" download="cooperation-profile.json"/)![1]
    expect(JSON.parse(decodeURIComponent(href.split(',').slice(1).join(',')))).toEqual(draft)
    expect(fetcher).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('reads the live combination only from service fields and keeps missing fields labeled legacy', () => {
    const draft = DEFAULT_COOPERATION_SCENE_PROFILE
    const live = renderToStaticMarkup(<CooperationSceneProfileView draft={draft} onDraftChange={() => {}}
      state={{ scene_profile: { schema: 1, vehicle: 'jackal_j100', sensors: 'lidar3d', task: 'transport' }, vehicle_profile: { id: 'jackal_j100', label: 'Clearpath Jackal J100' } }} />)
    expect(live).toContain('Clearpath Jackal J100')
    expect(live).toContain('来自当前服务 manifest')
    const legacy = renderToStaticMarkup(<CooperationSceneProfileView state={{}} draft={draft} onDraftChange={() => {}} />)
    expect(legacy).toContain('旧接口未上报场景组合')
    expect(legacy).toContain('不代表已应用配置草稿')
  })

  it('offers mecanum without silently applying the browser draft to the running vehicle', () => {
    let draft: CooperationSceneProfile = { ...DEFAULT_COOPERATION_SCENE_PROFILE }
    const tree = () => CooperationSceneProfileView({ state: { scene_profile: DEFAULT_COOPERATION_SCENE_PROFILE }, draft, onDraftChange: (next) => { draft = next } })
    select(tree(), 'cooperation-draft-vehicle')!.onChange({ target: { value: 'robot_base_mecanum' } })
    const html = renderToStaticMarkup(tree())
    expect(draft.vehicle).toBe('robot_base_mecanum')
    expect(html).toContain('<option value="robot_base_mecanum" selected="">麦克纳姆 robot_base</option>')
    expect(html).toContain('不会热替换当前实验')
    const live = html.split('data-scene-profile-kind="live"')[1].split('data-scene-profile-kind="draft"')[0]
    expect(live).toContain('FishBot')
    expect(live).not.toContain('robot_base')
  })
  it('downloads the independent scan draft without changing live scan identity or four-field scene JSON', () => {
    let scanPattern: CooperationScanPattern = 'uniform_16_line'
    const draft: CooperationSceneProfile = { ...DEFAULT_COOPERATION_SCENE_PROFILE, sensors: 'lidar3d' }
    const tree = () => CooperationSceneProfileView({ draft, onDraftChange: () => {}, scanPattern,
      onScanPatternChange: next => { scanPattern = next },
      state: { scene_profile: draft, lidar3d: { scan_pattern: 'uniform_16_line' } } })
    select(tree(), 'cooperation-draft-scan')!.onChange({ target: { value: 'livox_mid360_csv_stride5' } })
    const html = renderToStaticMarkup(tree())
    const href = html.match(/href="(data:application\/json[^"]+)" download="lidar3d-config.json"/)![1]
    const config = JSON.parse(decodeURIComponent(href.split(',').slice(1).join(',')))
    expect(config.scan_pattern).toBe('livox_mid360_csv_stride5'); expect(config.lines).toBe(1)
    expect(html).toContain('--lidar3d-config /path/to/lidar3d-config.json')
    expect(html).toContain('不会重启当前场景')
    const live = html.split('data-scene-profile-kind="live"')[1].split('data-scene-profile-kind="draft"')[0]
    expect(live).toContain('均匀16线'); expect(live).not.toContain('MID-360')
  })

})
