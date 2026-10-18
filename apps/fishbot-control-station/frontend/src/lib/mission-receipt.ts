/** A receipt identifier is evidence to read back, never an action to replay. */
export type MissionReceipt = { version: 1; domain: number; missionId: string; instanceId: string | null; mapId: string | null }
export const missionReceiptKey = (domain: number) => `fishbot.mission-receipt.v1:${domain}`
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
export function decodeMissionReceipt(raw: string, domain: number): MissionReceipt {
  if (raw.length > 2048) throw new Error('原任务回执缓存过大。')
  const value = JSON.parse(raw)
  if (!value || value.version !== 1 || value.domain !== domain || !UUID.test(value.missionId)
    || !(value.instanceId === null || typeof value.instanceId === 'string' && value.instanceId.length <= 256)
    || !(value.mapId === null || typeof value.mapId === 'string' && value.mapId.length <= 128)
    || Object.keys(value).some((key) => !['version', 'domain', 'missionId', 'instanceId', 'mapId'].includes(key))) {
    throw new Error('原任务回执缓存无效；请核对任务记录。')
  }
  return value
}
export function readMissionReceipt(storage: Pick<Storage, 'getItem'>, domain: number): MissionReceipt | null {
  const raw = storage.getItem(missionReceiptKey(domain))
  return raw === null ? null : decodeMissionReceipt(raw, domain)
}
export function saveMissionReceipt(storage: Pick<Storage, 'setItem'>, receipt: MissionReceipt): void {
  const value = decodeMissionReceipt(JSON.stringify(receipt), receipt.domain)
  storage.setItem(missionReceiptKey(receipt.domain), JSON.stringify(value))
}
export function receiptMatches(receipt: MissionReceipt, domain: number, instanceId: string | null, missionId: string | null): boolean {
  return receipt.domain === domain && receipt.missionId === missionId
    && (receipt.instanceId === null || receipt.instanceId === instanceId)
}
export type MissionLookup = { task_id: string; source: 'current' | 'persisted'; runtime_instance_id: string | null; current_runtime_instance_id: string; mission: Record<string, unknown> }
export function recoveredTerminal(receipt: MissionReceipt, value: unknown): string | null {
  if (!value || typeof value !== 'object') throw new Error('原任务查询回执无效。')
  const lookup = value as MissionLookup
  if (lookup.task_id !== receipt.missionId || !['current', 'persisted'].includes(lookup.source)
    || !lookup.mission || lookup.mission.id !== receipt.missionId
    || receipt.instanceId !== null && lookup.runtime_instance_id !== receipt.instanceId
    || receipt.mapId !== null && lookup.mission.map_id !== receipt.mapId) throw new Error('原任务查询身份不匹配，继续保留未知状态。')
  const status = lookup.mission.status
  if (!['succeeded', 'failed', 'canceled'].includes(String(status)) || lookup.mission.cleanup_state === 'unresolved') return null
  return `原任务 ${receipt.missionId.slice(0, 8)} 已读回${status === 'succeeded' ? '导航完成' : status === 'canceled' ? '取消终态' : '失败终态'}；来源为原任务账本，物理验收需另看报告。`
}
