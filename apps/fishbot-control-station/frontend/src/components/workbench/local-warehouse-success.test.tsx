import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import catalog from '../../../public/workbench/delivery-results.json'
import result from '../../../public/workbench/f2-warehouse-local-183948-result.json'
import chain from '../../../public/workbench/f2-warehouse-local-183948/visual/visual-chain.json'
import score from '../../../public/workbench/f2-warehouse-local-183948/original-components.json'
import timing from '../../../public/workbench/f2-warehouse-local-183948/timing.json'
import sensor from '../../../public/workbench/f2-warehouse-local-183948/sensor/sensor-experience.json'
import native from '../../../public/workbench/f2-warehouse-local-183948/native-lidar-consumer.json'
import workshop from '../../../public/workbench/f2-workshop-local-185131-result.json'
import workshopScore from '../../../public/workbench/f2-workshop-local-185131/original-components.json'
import { parseVisualEvidence } from '@/lib/visual-evidence'
import { VisualEvidencePanel } from './visual-evidence-panel'

describe('actual warehouse D whole visual transport success and separate workshop failure', () => {
  it('retains the two original passed orders and all earlier failure/partial records', () => {
    expect(result.run_id).toBe('ecfa94dd-0570-4691-b5f2-542e923f1a7f')
    expect(result.orders.map(o => o.passed)).toEqual([true, true])
    expect(score.original_whole_task_passed).toBe(true)
    expect(timing.original_run_passed).toBe(true); expect(timing.source_run_id).toBe(result.run_id)
    expect(result.orders.map(o => o.position_error_m)).toEqual([0.008658546665959235, 0.005642282842137417])
    expect(catalog.groups).toHaveLength(4)
    for (const id of ['f2-warehouse-v4', 'f2-warehouse-v5', 'f2-warehouse-v6', 'f2-warehouse-local-175145', 'f2-warehouse-local-183948', 'f2-workshop-local-185131']) expect(catalog.experiments.some(c => c.id === id)).toBe(true)
    expect('archive_url' in result).toBe(false); expect(result.provenance.raw_backup.confirmed).toBe(false)
  })
  it('binds all four actual visual chains and eight original physical milestone images to the right task/episode', () => {
    expect(chain.entries).toHaveLength(4); expect(chain.run_id).toBe(result.run_id)
    for (const order of result.orders) {
      const entries = chain.entries.filter(e => e.task_id === order.task_id)
      expect(entries.map(e => e.phase).sort()).toEqual(['load', 'unload'])
      for (const e of entries) {
        expect(e.observation.episode_id).toBe(result.provenance.episode_ids[0])
        expect(e.images.rgb).toBeTruthy(); expect(e.images.depth).toBeTruthy()
        for (const m of Object.values(e.milestones)) { expect(m?.original_passed).toBe(true); expect(m?.image).toBeTruthy(); expect(m?.image_gate_source_delta_s).toBeLessThanOrEqual(1) }
      }
    }
  })
  it('keeps actual inference separate from OBB-selected proposals and task-scopes all queries', () => {
    const parsed = parseVisualEvidence(chain)
    for (const order of result.orders) {
      const html = renderToStaticMarkup(<VisualEvidencePanel sourceUrl={result.assets.visual_chain} initialReport={chain} expectedRunId={result.run_id} taskId={order.task_id} />)
      expect(html).toContain('OBB几何候选（原来源 obb）'); expect(html).toContain('不能写成神经网络生成的最终抓取')
      expect(html).toContain('原候选分数'); expect(html).toContain('不解释为成功概率')
      for (const q of parsed.queries.filter(q => q.taskId !== order.task_id)) expect(html).not.toContain(`查询 ${q.id}`)
    }
    expect(chain.entries.filter(e => e.task_id === result.orders[0].task_id).map(e => e.selected?.index)).toEqual([51, 49])
    expect(chain.entries.filter(e => e.task_id === result.orders[1].task_id).map(e => e.selected?.index)).toEqual([51, 97])
    expect(chain.entries.every(e => e.selected?.origin === 'obb' && e.inference.status === 'inference_completed')).toBe(true)
  })
  it('limits sensor and native consumer evidence to the actual startup window', () => {
    expect(sensor.frames).toHaveLength(6); expect(sensor.tf).toEqual({ requested: 6, matched_source: 1, failed: 5 })
    expect(sensor.frames.every(f => f.identity.episode_id === result.provenance.episode_ids[0])).toBe(true)
    expect(native.pointcloud.messages).toBe(43); expect(native.pointcloud.source_stamp_sec).toBe(6)
    expect(result.warnings.join(' ')).toContain('启动阶段'); expect(result.warnings.join(' ')).toContain('逐消息消费ACK')
  })
  it('does not turn the separate ideal workshop unload IK failure into a model/physical unload success', () => {
    expect(workshop.observation_mode).toBe('ideal'); expect(workshop.orders[0].passed).toBe(false)
    expect(workshop.orders[0].failure_reason).toContain('0.100121')
    expect(workshopScore.original_whole_task_passed).toBe(false)
    expect(workshopScore.orders[0].phase_evidence.pickup_and_transport_observed.passed).toBe(true)
    expect('visual_chain' in workshop.assets).toBe(false)
    expect(workshop.warnings.join(' ')).toContain('没有RGB-D模型调用')
  })
})
