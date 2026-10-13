import { useEffect, useRef, useState } from 'react'

import {
  missionReceiptResolved, requestSimulation, simulationRequestRejected, validateSimulationMap, validateSimulationState,
  type Pose, type SimulationMap, type SimulationState, type UnknownMissionReceipt,
} from '@/lib/simulation'

export function useSimulation() {
  const [state, setState] = useState<SimulationState | null>(null)
  const [map, setMap] = useState<SimulationMap | null>(null)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const [mapError, setMapError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [missionRequestUnknown, setMissionRequestUnknown] = useState(false)
  const unknownMission = useRef<UnknownMissionReceipt | null>(null)
  const stateRef = useRef<SimulationState | null>(null)
  stateRef.current = state
  const [pending, setPending] = useState<string | null>(null)
  const requestSequence = useRef(0)
  const acceptedSequence = useRef(0)
  const mounted = useRef(false)
  const busy = useRef(false)
  const controllers = useRef(new Set<AbortController>())

  function acceptState(value: SimulationState, sequence: number) {
    if (!mounted.current || sequence < acceptedSequence.current) return
    acceptedSequence.current = sequence
    const validated = validateSimulationState(value)
    if (unknownMission.current && missionReceiptResolved(unknownMission.current, validated)) {
      unknownMission.current = null
      setMissionRequestUnknown(false)
      setActionError(null)
    }
    setState(validated)
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
    if (busy.current || (action === 'mission' && unknownMission.current)) return
    busy.current = true
    setPending(action)
    setActionError(null)
    const sequence = ++requestSequence.current
    const previousMissionId = stateRef.current?.mission.id ?? null
    acceptedSequence.current = sequence
    const controller = new AbortController()
    controllers.current.add(controller)
    const timeout = setTimeout(() => controller.abort(), 5000)
    try {
      const value = await requestSimulation<SimulationState>(action, body, controller.signal)
      acceptState(value, sequence)
    } catch (error) {
      if (mounted.current) {
        if (action === 'mission' && !simulationRequestRejected(error)) {
          const requested = body as { waypoints?: Pose[]; return_home?: boolean }
          unknownMission.current = { previousId: previousMissionId, waypoints: requested.waypoints?.map((point) => ({ ...point })) ?? [], returnHome: !!requested.return_home }
          setMissionRequestUnknown(true)
          setActionError('派发回执未知，正在读取原任务状态；不能重复派发。')
        } else setActionError(error instanceof Error && error.name !== 'AbortError'
          ? error.message : '请求超时，请查看当前任务状态。')
      }
    } finally {
      clearTimeout(timeout)
      controllers.current.delete(controller)
      busy.current = false
      if (mounted.current) setPending(null)
    }
  }

  return { state, map, connectionError, mapError, actionError, pending, missionRequestUnknown, act }
}
