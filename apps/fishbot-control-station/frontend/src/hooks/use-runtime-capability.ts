import { useSyncExternalStore } from 'react'
import { runtimeRegistry, type RuntimeService } from '@/lib/runtime-context'
export function useRuntimeWriteCapability(service: RuntimeService, capabilityId: string) {
  const snapshot = useSyncExternalStore(runtimeRegistry.subscribe, runtimeRegistry.getSnapshot, runtimeRegistry.getSnapshot)
  const entry = snapshot[service]
  const capability = entry.descriptor?.capabilities.find((item) => item.id === capabilityId)
  return entry.status === 'verified' && !!capability && capability.submission !== 'read_only'
}
