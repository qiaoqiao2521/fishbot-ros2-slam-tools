/** Server-owned configuration only. Browser requests cannot choose proxy destinations. */
export type WorkbenchService = 'station' | 'mission' | 'cooperation' | 'voice'
export type WorkbenchProfile = {
  schema_version: 1; label: string
  services: Record<WorkbenchService, { port: number; domain: number | null }>
  tools: { spatiallm: number | null; video: number | null }
}
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const keys = (value: Record<string, unknown>, allowed: string[]) => Object.keys(value).length === allowed.length && Object.keys(value).every((key) => allowed.includes(key))
const port = (value: unknown): value is number => Number.isInteger(value) && Number(value) >= 1024 && Number(value) <= 65535
export function validateWorkbenchProfile(value: unknown, frontendPort: number): WorkbenchProfile {
  if (!object(value) || !keys(value, ['schema_version', 'label', 'services', 'tools']) || value.schema_version !== 1
    || typeof value.label !== 'string' || !value.label.trim() || value.label.length > 80
    || !object(value.services) || !keys(value.services, ['station', 'mission', 'cooperation', 'voice'])
    || !object(value.tools) || !keys(value.tools, ['spatiallm', 'video'])) throw new Error('Invalid server workbench profile schema')
  const ports = [frontendPort]
  for (const [name, service] of Object.entries(value.services)) {
    if (!object(service) || !keys(service, ['port', 'domain']) || !port(service.port)
      || !(name === 'station' && service.domain === null || Number.isInteger(service.domain) && Number(service.domain) >= 1 && Number(service.domain) <= 232)) throw new Error(`Invalid ${name} service port or isolated domain`)
    ports.push(service.port)
  }
  for (const entry of Object.values(value.tools)) {
    if (entry !== null && !port(entry)) throw new Error('Invalid tool service port')
    if (entry !== null) ports.push(entry)
  }
  if (!port(frontendPort) || new Set(ports).size !== ports.length) throw new Error('Workbench services require distinct local ports')
  return structuredClone(value) as WorkbenchProfile
}
export function workbenchProxy(profile: WorkbenchProfile) {
  const target = (number: number) => ({ target: `http://127.0.0.1:${number}`, changeOrigin: true })
  return {
    '/voice-api': target(profile.services.voice.port), '/coop-api': target(profile.services.cooperation.port),
    '/sim-api': target(profile.services.mission.port), '/api': target(profile.services.station.port),
    ...(profile.tools.spatiallm === null ? {} : { '/workbench-service/spatiallm': { ...target(profile.tools.spatiallm), rewrite: () => '/api/health' } }),
    ...(profile.tools.video === null ? {} : { '/workbench-service/video': { ...target(profile.tools.video), rewrite: () => '/api/run' } }),
  }
}
