type LabStatus = 'passed' | 'failed' | 'incomplete'
type SectionId = 'real_map' | 'new_base' | 'suction'
type LabCase = { id: string; label: string; status: LabStatus; reason: string; metrics: Record<string, unknown> }
type LabSection = { id: SectionId; title: string; status: LabStatus; basis: string; summary: string; cases: LabCase[]; retained: boolean }
export type HardwareLabReport = { scope: string; sections: LabSection[]; warnings: string[] }

const sectionTitles: Record<SectionId, string> = { real_map: '真实场地图', new_base: '新底盘', suction: '负压与爬壁' }
const record = (value: unknown): Record<string, unknown> | null => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null
const text = (value: unknown, fallback: string) => typeof value === 'string' && value.trim() ? value : fallback
const validStatus = (value: unknown): value is LabStatus => value === 'passed' || value === 'failed' || value === 'incomplete'

export function hardwareLabMetric(value: unknown): string {
  if (value === null || value === undefined) return '未提供'
  if (typeof value === 'string') return value || '未提供'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '非有限数值'
  try { return JSON.stringify(value) ?? '未提供' } catch { return '无法显示该指标' }
}

export function parseHardwareLabReport(value: unknown, previous?: HardwareLabReport | null): HardwareLabReport {
  const input = record(value)
  if (!input) throw new Error('实验报告应为 JSON 对象。已有报告继续保留。')
  const warnings: string[] = []
  const rows = Array.isArray(input.sections) ? input.sections : []
  if (!Array.isArray(input.sections)) warnings.push('缺少 sections 数组；保留上次读取的分项，其他分项显示待补齐。')
  const known = Object.keys(sectionTitles) as SectionId[]
  for (const row of rows) {
    const item = record(row)
    if (!item || !known.includes(item.id as SectionId)) warnings.push('一个分项缺少可识别 ID；其余分项仍可查看。')
  }
  const sections = known.map((id): LabSection => {
    const old = previous?.sections.find((section) => section.id === id)
    const matches = rows.filter((row) => record(row)?.id === id)
    if (matches.length > 1) warnings.push(`${sectionTitles[id]}存在重复分项，显示本次最后一条。`)
    const row = record(matches.at(-1))
    if (!row) {
      if (old) {
        warnings.push(`${sectionTitles[id]}本次缺失，沿用上次读取的证据。`)
        return { ...old, retained: true }
      }
      warnings.push(`${sectionTitles[id]}尚未提供证据。`)
      return { id, title: sectionTitles[id], status: 'incomplete', basis: '依据未提供', summary: '等待该分项的实际验收报告。', cases: [], retained: false }
    }
    if (!validStatus(row.status)) warnings.push(`${sectionTitles[id]}状态缺失或无法识别，显示待补齐。`)
    if (!row.basis) warnings.push(`${sectionTitles[id]}缺少证据依据，请补齐来源。`)
    let retained = false
    let cases: LabCase[]
    if (!Array.isArray(row.cases)) {
      warnings.push(`${sectionTitles[id]}缺少 cases 数组；${old?.cases.length ? '沿用上次案例。' : '补齐后可重新读取。'}`)
      cases = old?.cases ?? []
      retained = Boolean(old?.cases.length)
    } else {
      cases = row.cases.map((candidate, index): LabCase => {
        const item = record(candidate)
        if (!item) warnings.push(`${sectionTitles[id]}第 ${index+1} 个案例格式有误，保留为待补齐。`)
        else if (!validStatus(item.status)) warnings.push(`${sectionTitles[id]}第 ${index+1} 个案例状态无法识别，显示待补齐。`)
        return {
          id: text(item?.id, `case-${index+1}`), label: text(item?.label, `案例 ${index+1}`),
          status: validStatus(item?.status) ? item.status : 'incomplete',
          reason: text(item?.reason, '尚未提供具体原因。'), metrics: record(item?.metrics) ?? {},
        }
      })
    }
    let status = validStatus(row.status) ? row.status : 'incomplete'
    if (status === 'passed') {
      if (!Array.isArray(row.cases) || cases.length === 0) {
        status = 'incomplete'
        warnings.push(`${sectionTitles[id]}本次缺少有效案例，分项“通过”已改为待补齐。`)
      } else if (cases.some((item) => item.status === 'failed')) {
        status = 'failed'
        warnings.push(`${sectionTitles[id]}存在未通过案例，分项“通过”已改为未通过。`)
      } else if (cases.some((item) => item.status === 'incomplete')) {
        status = 'incomplete'
        warnings.push(`${sectionTitles[id]}存在待补齐案例，分项“通过”已改为待补齐。`)
      }
    }
    return { id, title: text(row.title, sectionTitles[id]), status,
      basis: text(row.basis, '依据未提供'), summary: text(row.summary, '尚未提供分项说明。'), cases, retained }
  })
  if (input.scope !== 'simulation') warnings.push('报告未声明 simulation 范围，不能据此判断真机能力。')
  return { scope: text(input.scope, '未声明'), sections, warnings }
}

export async function readHardwareLabReport(previous?: HardwareLabReport | null, fetcher: typeof fetch = fetch): Promise<HardwareLabReport> {
  const response = await fetcher('/hardware-lab/report', { method: 'GET', cache: 'no-store' })
  if (!response.ok) throw new Error(`实验报告读取失败（HTTP ${response.status}）。已有报告继续保留，请稍后重试。`)
  return parseHardwareLabReport(await response.json(), previous)
}
