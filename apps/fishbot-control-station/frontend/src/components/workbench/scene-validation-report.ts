export type BusinessResult = 'route_completed' | 'route_incomplete' | 'delivered' | 'undelivered' | 'unknown'
export type AcceptanceResult = 'passed' | 'failed' | 'incomplete'

export interface SceneValidationCase {
  id: string
  label: string
  expected: string
  businessResult: BusinessResult
  acceptanceResult: AcceptanceResult
  reason: string
  metrics: Record<string, unknown>
  taskId: string
  nativeGoalId: string
  nativeStatus: string
}

export interface SceneValidationReport {
  scope: string
  businessScope: string
  source: { label: string; basis: string; assumptionCells: string }
  lidarProfile: string
  cases: SceneValidationCase[]
  warnings: string[]
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : null
}

export function sceneValidationValue(value: unknown, fallback = '未提供'): string {
  if (typeof value === 'string') return value.trim() || fallback
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (value !== null && typeof value === 'object') return JSON.stringify(value)
  return fallback
}

export function parseSceneValidationReport(input: unknown): SceneValidationReport {
  const warnings: string[] = []
  const report = record(input) ?? {}
  if (!record(input)) warnings.push('报告主体无法识别，先显示可补齐的空报告。')
  if (report.schema_version !== 1) warnings.push('报告版本未确认，已按可识别字段展示。')
  if (report.scope !== 'simulation') warnings.push('报告未标明仿真范围，不能据此判断现实交付。')
  const source = record(report.source) ?? {}
  if (!source.label || !source.basis || source.assumption_cells === undefined) {
    warnings.push('来源或实测补全说明不完整，请补充后再解释结果。')
  }
  const lidar = record(report.lidar) ?? {}
  if (!lidar.profile) warnings.push('未提供雷达配置，本报告不能用于硬件升级对照。')
  if (!Array.isArray(report.cases)) warnings.push('未提供案例列表。')
  const cases = (Array.isArray(report.cases) ? report.cases : []).map((inputCase, index) => {
    const item = record(inputCase)
    const label = sceneValidationValue(item?.label, `案例 ${index + 1}`)
    if (!item) warnings.push(`${label} 的内容无法识别，其余案例仍可查看。`)
    const businessResult: BusinessResult = item?.business_result === 'route_completed' || item?.business_result === 'route_incomplete'
      || item?.business_result === 'delivered' || item?.business_result === 'undelivered'
      ? item.business_result : 'unknown'
    const acceptanceResult: AcceptanceResult = item?.acceptance_result === 'passed' || item?.acceptance_result === 'failed'
      ? item.acceptance_result : 'incomplete'
    if (item && (!['route_completed', 'route_incomplete', 'delivered', 'undelivered', 'unknown'].includes(String(item.business_result))
      || !['passed', 'failed', 'incomplete'].includes(String(item.acceptance_result)))) {
      warnings.push(`${label} 的结果字段不完整，未知结果已保留为待确认。`)
    }
    return {
      id: sceneValidationValue(item?.id, `case-${index + 1}`), label,
      expected: sceneValidationValue(item?.expected, '预期未说明'),
      businessResult, acceptanceResult,
      reason: sceneValidationValue(item?.reason, item ? '未提供具体原因。' : '本条内容无法识别，请修正后重新导入。'),
      metrics: record(item?.metrics) ?? {},
      taskId: sceneValidationValue(item?.task_id),
      nativeGoalId: sceneValidationValue(item?.native_goal_id),
      nativeStatus: sceneValidationValue(item?.native_status),
    }
  })
  return {
    scope: sceneValidationValue(report.scope, '未确认'),
    businessScope: sceneValidationValue(report.business_scope ?? source.business_scope, '未说明'),
    source: {
      label: sceneValidationValue(source.label, '来源未标明'),
      basis: sceneValidationValue(source.basis, '未提供实测依据，请按仿真补全内容理解。'),
      assumptionCells: sceneValidationValue(source.assumption_cells, '未说明哪些区域经过补全'),
    },
    lidarProfile: sceneValidationValue(lidar.profile, '配置未提供'), cases, warnings,
  }
}

export async function readLatestSceneValidationReport(fetcher: typeof fetch = fetch): Promise<SceneValidationReport> {
  const response = await fetcher('/scene-validation/report', { method: 'GET', cache: 'no-store' })
  if (!response.ok) throw new Error(`报告读取失败（HTTP ${response.status}），可稍后重试或导入本地 JSON。`)
  return parseSceneValidationReport(await response.json())
}

export async function readLocalSceneValidationReport(file: Pick<File, 'text'>): Promise<SceneValidationReport> {
  return parseSceneValidationReport(JSON.parse(await file.text()))
}
