import { useEffect, useRef, useState } from 'react'

import {
  requestSimulation, validateSimulationMap, validateSimulationState,
  type SimulationMap, type SimulationState,
} from '@/lib/simulation'

export function useSimulation() {
  const [state, setState] = useState<SimulationState | null>(null)
  const [map, setMap] = useState<SimulationMap | null>(null)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const [mapError, setMapError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const requestSequence = useRef(0)
  const acceptedSequence = useRef(0)
  const mounted = useRef(false)
  const busy = useRef(false)
  const controllers = useRef(new Set<AbortController>())

  function acceptState(value: SimulationState, sequence: number) {
    if (!mounted.current || sequence < acceptedSequence.current) return
    acceptedSequence.current = sequence
    setState(validateSimulationState(value))
    setConnectionError(null)
  }

  useEffect(() => {
    mounted.current = true
    let stopped = false
    let stateTimer: ReturnType<typeof setTimeout>
    let mapTimer: ReturnType<typeof setTimeout>

    async function pollState() {
      if (busy.current) {
        stateTimer = setTimeout(pollState, 250)
        return
      }
      const controller = new AbortController()
      controllers.current.add(controller)
      const timeout = setTimeout(() => controller.abort(), 3000)
      const sequence = ++requestSequence.current
      try {
        const value = await requestSimulation<SimulationState>('state', undefined, controller.signal)
        acceptState(value, sequence)
      } catch (error) {
        if (!stopped && sequence >= acceptedSequence.current) {
          setConnectionError(error instanceof Error && error.name !== 'AbortError'
            ? error.message : '仿真连接超时，正在重新连接。')
        }
      } finally {
        clearTimeout(timeout)
        controllers.current.delete(controller)
        if (!stopped) stateTimer = setTimeout(pollState, 250)
      }
    }

    async function pollMap() {
      const controller = new AbortController()
      controllers.current.add(controller)
      const timeout = setTimeout(() => controller.abort(), 3000)
      let nextPoll = 1000
      try {
        const value = validateSimulationMap(await requestSimulation<SimulationMap>('map', undefined, controller.signal))
        if (!stopped) {
          setMap(value)
          setMapError(null)
        }
        nextPoll = 10000
      } catch (error) {
        if (!stopped) setMapError(error instanceof Error && error.name !== 'AbortError'
          ? error.message : '地图暂未收到，正在重试。')
      } finally {
        clearTimeout(timeout)
        controllers.current.delete(controller)
        if (!stopped) mapTimer = setTimeout(pollMap, nextPoll)
      }
    }

    void pollState()
    void pollMap()
    const activeControllers = controllers.current
    return () => {
      stopped = true
      mounted.current = false
      clearTimeout(stateTimer)
      clearTimeout(mapTimer)
      activeControllers.forEach((controller) => controller.abort())
      activeControllers.clear()
    }
  }, [])

  async function act(action: 'mission' | 'cancel' | 'obstacle', body: object = {}) {
    if (busy.current) return
    busy.current = true
    setPending(action)
    setActionError(null)
    const sequence = ++requestSequence.current
    acceptedSequence.current = sequence
    const controller = new AbortController()
    controllers.current.add(controller)
    const timeout = setTimeout(() => controller.abort(), 5000)
    try {
      const value = await requestSimulation<SimulationState>(action, body, controller.signal)
      acceptState(value, sequence)
    } catch (error) {
      if (mounted.current) setActionError(error instanceof Error && error.name !== 'AbortError'
        ? error.message : '请求超时，请查看当前任务状态后重试。')
    } finally {
      clearTimeout(timeout)
      controllers.current.delete(controller)
      busy.current = false
      if (mounted.current) setPending(null)
    }
  }

  return { state, map, connectionError, mapError, actionError, pending, act }
}
