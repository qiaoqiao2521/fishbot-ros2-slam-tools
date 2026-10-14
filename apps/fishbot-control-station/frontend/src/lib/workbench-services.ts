import { workbenchSnapshot, type ServiceId } from './workbench-catalog'

export interface ServiceState {
  status: 'unchecked' | 'checking' | 'available' | 'unavailable' | 'unexpected'
  message: string
  checkedAt: number | null
}

export const EMPTY_WORKBENCH_SERVICES: Record<ServiceId, ServiceState> = {
  spatiallm: { status: 'unchecked', message: '尚未检查当前入口', checkedAt: null },
  video: { status: 'unchecked', message: '尚未检查当前入口', checkedAt: null },
}

function matchesService(id: ServiceId, value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const item = value as Record<string, unknown>
  if (id === 'spatiallm') {
    return item.status === 'ready' && item.mode === 'offline'
      && item.model_inference === 'not_run' && typeof item.render_requested === 'boolean'
  }
  return item.version === 'offline-person-events-v1' && typeof item.run_id === 'string'
    && /^[a-f0-9]{32}$/.test(item.run_id) && ['completed', 'failed', 'limited'].includes(String(item.state))
    && Number.isInteger(item.event_count) && Number(item.event_count) >= 0
}

export async function checkWorkbenchService(id: ServiceId, options: {
  fetcher?: typeof fetch; signal?: AbortSignal; timeoutMs?: number; now?: () => number
} = {}): Promise<ServiceState> {
  const fetcher = options.fetcher ?? fetch
  const controller = new AbortController()
  const relayAbort = () => controller.abort()
  options.signal?.addEventListener('abort', relayAbort, { once: true })
  if (options.signal?.aborted) controller.abort()
  const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? 2000)
  const checkedAt = () => (options.now ?? Date.now)()
  try {
    const response = await fetcher(workbenchSnapshot.services[id].probe, {
      method: 'GET', cache: 'no-store', signal: controller.signal,
    })
    if (!response.ok) {
      return { status: 'unavailable', checkedAt: checkedAt(), message: response.status === 409
        ? '原件或复核记录校验未通过，请在原工具核对' : `入口不可用（HTTP ${response.status}），已保存的验收记录仍可查看` }
    }
    let value: unknown
    try {
      value = await response.json()
    } catch (error) {
      if (error instanceof SyntaxError) return { status: 'unexpected', message: '入口返回的内容无法识别，未标为在线', checkedAt: checkedAt() }
      throw error
    }
    if (!matchesService(id, value)) return { status: 'unexpected', message: '入口响应与工具身份不符，未标为在线', checkedAt: checkedAt() }
    return { status: 'available', message: '本机工具入口可访问；不代表新任务已经运行', checkedAt: checkedAt() }
  } catch {
    return { status: 'unavailable', message: '当前入口未启动、无法连接或检查超时', checkedAt: checkedAt() }
  } finally {
    clearTimeout(timeout)
    options.signal?.removeEventListener('abort', relayAbort)
  }
}
