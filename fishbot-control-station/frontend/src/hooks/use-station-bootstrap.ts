import { useEffect, useRef } from 'react'

import {
  fetchConnection,
  fetchDiagnostics,
  fetchNavigation,
  fetchPerception,
  fetchRobotState,
  mapConnectionSnapshot,
  mapDiagnosticSnapshot,
  mapNavigationSnapshot,
  mapPerceptionSnapshot,
  mapRobotStateSnapshot,
  type RawConnectionSnapshot,
  type RawDiagnosticSnapshot,
  type RawNavigationSnapshot,
  type RawPerceptionSnapshot,
  type RawRobotStateSnapshot,
} from '@/lib/api'
import { useStationStore } from '@/store/station-store'

export function useStationBootstrap() {
  const hydratedRef = useRef(false)
  const {
    appendError,
    appendTransport,
    setConnection,
    setDiagnostics,
    setNavigation,
    setPerception,
    setRobotState,
    setUsingFallbackData,
  } = useStationStore()

  useEffect(() => {
    let closed = false

    function markHydrated() {
      hydratedRef.current = true
      setUsingFallbackData(false)
    }

    async function bootstrap() {
      const [connection, state, navigation, perception, diagnostics] = await Promise.allSettled([
        fetchConnection(),
        fetchRobotState(),
        fetchNavigation(),
        fetchPerception(),
        fetchDiagnostics(),
      ])

      if (closed) {
        return
      }

      let liveData = false

      if (connection.status === 'fulfilled') {
        setConnection(connection.value)
        liveData = true
      }

      if (state.status === 'fulfilled') {
        setRobotState(state.value)
        liveData = true
      }

      if (navigation.status === 'fulfilled') {
        setNavigation(navigation.value)
        liveData = true
      }

      if (perception.status === 'fulfilled') {
        setPerception(perception.value)
        liveData = true
      }

      if (diagnostics.status === 'fulfilled') {
        setDiagnostics(diagnostics.value)
        liveData = true
      }

      if (liveData) {
        markHydrated()
      } else {
        setUsingFallbackData(true)
      }
    }

    bootstrap().catch(() => {
      if (closed) {
        return
      }
      appendError({
        id: crypto.randomUUID(),
        level: 'warning',
        message: 'Backend bootstrap unavailable, showing fallback telemetry',
        timestamp: new Date().toISOString(),
      })
    })

    const eventSource = new EventSource('/api/v1/stream/events')

    eventSource.addEventListener('connection', (event) => {
      if (closed) {
        return
      }
      const payload = JSON.parse((event as MessageEvent).data) as RawConnectionSnapshot
      setConnection(mapConnectionSnapshot(payload))
      markHydrated()
    })

    eventSource.addEventListener('robot-state', (event) => {
      if (closed) {
        return
      }
      const payload = JSON.parse((event as MessageEvent).data) as RawRobotStateSnapshot
      setRobotState(mapRobotStateSnapshot(payload))
      markHydrated()
    })

    eventSource.addEventListener('navigation-state', (event) => {
      if (closed) {
        return
      }
      const payload = JSON.parse((event as MessageEvent).data) as RawNavigationSnapshot
      setNavigation(mapNavigationSnapshot(payload))
      markHydrated()
    })

    eventSource.addEventListener('perception-state', (event) => {
      if (closed) {
        return
      }
      const payload = JSON.parse((event as MessageEvent).data) as RawPerceptionSnapshot
      setPerception(mapPerceptionSnapshot(payload))
      markHydrated()
    })

    eventSource.addEventListener('diagnostic', (event) => {
      if (closed) {
        return
      }
      const payload = JSON.parse((event as MessageEvent).data) as RawDiagnosticSnapshot
      setDiagnostics(mapDiagnosticSnapshot(payload))
      markHydrated()
    })

    eventSource.onerror = () => {
      if (closed) {
        return
      }
      appendTransport({
        id: crypto.randomUUID(),
        level: 'warning',
        message: 'Event stream disconnected, waiting for reconnection',
        timestamp: new Date().toISOString(),
      })
      if (!hydratedRef.current) {
        setUsingFallbackData(true)
      }
    }

    return () => {
      closed = true
      eventSource.close()
    }
  }, [appendError, appendTransport, setConnection, setDiagnostics, setNavigation, setPerception, setRobotState, setUsingFallbackData])
}
