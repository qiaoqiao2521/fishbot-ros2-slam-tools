import { useCallback, useEffect, useRef, useState } from 'react'
import { checkWorkbenchService, EMPTY_WORKBENCH_SERVICES, type ServiceState } from '@/lib/workbench-services'
import type { ServiceId } from '@/lib/workbench-catalog'

export function useWorkbenchServices() {
  const [services, setServices] = useState<Record<ServiceId, ServiceState>>(EMPTY_WORKBENCH_SERVICES)
  const active = useRef<AbortController | null>(null)
  useEffect(() => () => { active.current?.abort() }, [])

  const refresh = useCallback(() => {
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setServices({
      spatiallm: { status: 'checking', message: '正在检查入口', checkedAt: null },
      video: { status: 'checking', message: '正在检查入口', checkedAt: null },
    })
    void Promise.all((['spatiallm', 'video'] as const).map(async (id) => {
      const value = await checkWorkbenchService(id, { signal: controller.signal })
      return [id, value] as const
    })).then((values) => {
      if (!controller.signal.aborted && active.current === controller) setServices(Object.fromEntries(values) as Record<ServiceId, ServiceState>)
    })
  }, [])

  return { services, refresh, checking: Object.values(services).some((item) => item.status === 'checking') }
}
