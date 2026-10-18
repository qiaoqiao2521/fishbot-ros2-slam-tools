import { useEffect, useState, useSyncExternalStore } from 'react'
import { ManualController } from '@/lib/manual-control'
import { runtimeRegistry } from '@/lib/runtime-context'
import { SIMULATION_DOMAIN } from '@/lib/simulation'

/** Own the lease above view lifetimes; reads can recover receipts, never gestures. */
export function useManualOwner() {
  const [controller] = useState(() => {
    let storage: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
    try { storage = window.sessionStorage } catch {
      storage = { getItem: () => { throw new Error('原请求缓存不可用，人工控制未启用。') }, setItem: () => { throw new Error('原请求缓存不可用。') }, removeItem: () => {} }
    }
    return new ManualController({ domain: SIMULATION_DOMAIN, storage })
  })
  const runtime = useSyncExternalStore(runtimeRegistry.subscribe, runtimeRegistry.getSnapshot, runtimeRegistry.getSnapshot).mission
  const capability = runtime.descriptor?.capabilities.find(item => item.id === 'teleop')
  const enabled = runtime.status === 'verified' && runtime.descriptor?.mode === 'simulation'
    && runtime.descriptor.domain === SIMULATION_DOMAIN && capability?.protocol === 'manual_lease_v1'
    && capability.profile_id === 'passage_manual'
  useEffect(() => {
    let disposed = false, timer: ReturnType<typeof setTimeout> | undefined
    const read = async () => {
      await controller.refresh()
      if (!disposed) timer = setTimeout(read, 500)
    }
    if (enabled) void read()
    else void controller.release()
    return () => { disposed = true; clearTimeout(timer); void controller.release() }
  }, [controller, enabled, runtime.generation])
  return { controller, enabled }
}
