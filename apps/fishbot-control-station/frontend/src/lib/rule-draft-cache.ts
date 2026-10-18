import { validateMapRules, type MapZone } from './simulation-workspace'
export type RuleDraft = { version: 1; domain: number; mapId: string; baseRevision: number; zones: MapZone[] }
export const ruleDraftKey = (domain: number, mapId: string) => `fishbot.rule-draft.v1:${domain}:${encodeURIComponent(mapId)}`
/** Per-tab session storage: unpublished rule drafts never overwrite another tab. */
export function decodeRuleDraft(raw: string, domain: number, mapId: string): RuleDraft {
  if (raw.length > 65536) throw new Error('规则草稿缓存超过大小上限。')
  const value = JSON.parse(raw)
  if (!value || value.version !== 1 || value.domain !== domain || value.mapId !== mapId
    || Object.keys(value).some((key) => !['version', 'domain', 'mapId', 'baseRevision', 'zones'].includes(key))) throw new Error('规则草稿缓存与当前地图不匹配。')
  const checked = validateMapRules({ map_id: mapId, revision: value.baseRevision, zones: value.zones, apply_state: 'unavailable', message: '' }, mapId)
  return { version: 1, domain, mapId, baseRevision: checked.revision, zones: structuredClone(checked.zones) }
}
export function readRuleDraft(storage: Pick<Storage, 'getItem'>, domain: number, mapId: string): RuleDraft | null {
  const raw = storage.getItem(ruleDraftKey(domain, mapId))
  return raw === null ? null : decodeRuleDraft(raw, domain, mapId)
}
export function writeRuleDraft(storage: Pick<Storage, 'setItem'>, draft: RuleDraft): void {
  const raw = JSON.stringify(draft)
  decodeRuleDraft(raw, draft.domain, draft.mapId)
  storage.setItem(ruleDraftKey(draft.domain, draft.mapId), raw)
}
