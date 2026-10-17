import { useEffect } from 'react'

import {
  fetchConnection, fetchDiagnostics, fetchNavigation, fetchPerception, fetchRobotState,
  mapConnectionSnapshot, mapDiagnosticSnapshot, mapNavigationSnapshot, mapPerceptionSnapshot, mapRobotStateSnapshot,
} from '@/lib/api'
import { runtimeRegistry } from '@/lib/runtime-context'
import { validateStationResource } from '@/lib/station-validation'
import { useStationStore, type StationResource } from '@/store/station-store'

/** Reads only. Commands and task recovery stay with their existing execution owners. */
export function useStationBootstrap() {
  const { appendTransport, setConnection, setDiagnostics, setNavigation, setPerception, setRobotState, markResourceError } = useStationStore()

  useEffect(() => {
    let closed = false
    let lastEventSequence = -1
    let instance = runtimeRegistry.getSnapshot().station.descriptor?.instance_id ?? null
    const versions: Record<StationResource, number> = { connection: 0, robotState: 0, navigation: 0, perception: 0, diagnostics: 0 }
    let hydration: AbortController | null = null
    let timeout: ReturnType<typeof setTimeout> | undefined
    const resources = Object.keys(versions) as StationResource[]
    const unsubscribeRuntime = runtimeRegistry.subscribe(() => {
      const current = runtimeRegistry.getSnapshot().station.descriptor?.instance_id ?? null
      if (current === instance) return
      instance = current
      lastEventSequence = -1
      for (const resource of resources) {
        versions[resource]++
        markResourceError(resource, '服务代次变化，等待当前实例的数据。')
      }
      hydrate()
    })

    async function read<T>(resource: StationResource, fetcher: (signal?: AbortSignal) => Promise<T>, accept: (value: T) => void, signal: AbortSignal) {
      const version = versions[resource]
      try {
        const value = await fetcher(signal)
        if (!closed && !signal.aborted && version === versions[resource]) accept(value)
      } catch (error) {
        if (!closed && !signal.aborted && version === versions[resource]) markResourceError(resource, error instanceof Error ? error.message : '资源读取失败。')
      }
    }
    function hydrate() {
      hydration?.abort()
      clearTimeout(timeout)
      const batch = new AbortController()
      hydration = batch
      const pendingResources = new Set(resources)
      const batchVersions = { ...versions }
      const batchTimeout = setTimeout(() => {
        if (!closed && hydration === batch) {
          for (const resource of pendingResources) {
            if (versions[resource] === batchVersions[resource]) markResourceError(resource, '快照读取超时，等待当前服务的数据。')
          }
        }
        batch.abort()
      }, 5000)
      timeout = batchTimeout
      void Promise.all([
        read('connection', fetchConnection, setConnection, batch.signal).finally(() => pendingResources.delete('connection')),
        read('robotState', fetchRobotState, setRobotState, batch.signal).finally(() => pendingResources.delete('robotState')),
        read('navigation', fetchNavigation, setNavigation, batch.signal).finally(() => pendingResources.delete('navigation')),
        read('perception', fetchPerception, setPerception, batch.signal).finally(() => pendingResources.delete('perception')),
        read('diagnostics', fetchDiagnostics, setDiagnostics, batch.signal).finally(() => pendingResources.delete('diagnostics')),
      ]).finally(() => clearTimeout(batchTimeout))
    }
    hydrate()

    const stream = new EventSource('/api/v1/stream/events')
    function listen(eventName: string, resource: StationResource, accept: (value: unknown) => void) {
      stream.addEventListener(eventName, (event) => {
        if (closed) return
        const message = event as MessageEvent
        try {
          const descriptor = runtimeRegistry.getSnapshot().station.descriptor
          let acceptedSequence: number | null = null
          if (descriptor) {
            const prefix = `${descriptor.instance_id}:`
            const sequence = Number(message.lastEventId?.slice(prefix.length))
            if (!message.lastEventId?.startsWith(prefix) || !Number.isSafeInteger(sequence) || sequence < 0) {
              throw new Error('遥测来源与当前服务实例不一致，等待新数据。')
            }
            if (sequence <= lastEventSequence) return
            acceptedSequence = sequence
          }
          versions[resource]++
          accept(JSON.parse(message.data))
          if (acceptedSequence !== null) lastEventSequence = acceptedSequence
        } catch (error) {
          markResourceError(resource, error instanceof Error ? error.message : '遥测格式错误。', true)
        }
      })
    }
    listen('connection', 'connection', (raw) => setConnection(mapConnectionSnapshot(validateStationResource('connection', raw))))
    listen('robot-state', 'robotState', (raw) => setRobotState(mapRobotStateSnapshot(validateStationResource('robotState', raw))))
    listen('navigation-state', 'navigation', (raw) => setNavigation(mapNavigationSnapshot(validateStationResource('navigation', raw))))
    listen('perception-state', 'perception', (raw) => setPerception(mapPerceptionSnapshot(validateStationResource('perception', raw))))
    listen('diagnostic', 'diagnostics', (raw) => setDiagnostics(mapDiagnosticSnapshot(validateStationResource('diagnostics', raw))))
    stream.onerror = () => {
      if (closed) return
      for (const resource of resources) markResourceError(resource, '订阅已断开，保留最近数据并等待重连。')
      appendTransport({ id: crypto.randomUUID(), level: 'warning', message: '遥测订阅断开，等待重连；不重发动作。', timestamp: new Date().toISOString() })
    }
    return () => {
      closed = true; clearTimeout(timeout); hydration?.abort(); unsubscribeRuntime(); stream.close()
    }
  }, [appendTransport, setConnection, setDiagnostics, setNavigation, setPerception, setRobotState, markResourceError])
}
