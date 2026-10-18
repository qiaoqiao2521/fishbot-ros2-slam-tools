import { useEffect, useRef, useState } from 'react'
import { runtimeRegistry } from '@/lib/runtime-context'
import { missionReceiptKey, recoveredTerminal, readMissionReceipt, receiptMatches, saveMissionReceipt, type MissionReceipt } from '@/lib/mission-receipt'

import {
  SIMULATION_DOMAIN, requestSimulation, simulationRequestRejected, SimulationRejectedRequest, validateSimulationMap, validateSimulationState,
  type SimulationGoalIssue, type SimulationMap, type SimulationState,
} from '@/lib/simulation'

export function useSimulation() {
  const [state, setState] = useState<SimulationState | null>(null)
  const [map, setMap] = useState<SimulationMap | null>(null)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const [mapError, setMapError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [goalIssue, setGoalIssue] = useState<SimulationGoalIssue | null>(null)
  const [recoveryMessage, setRecoveryMessage] = useState('')
  const [missionRequestUnknown, setMissionRequestUnknown] = useState(false)
  const unknownMission = useRef<MissionReceipt | null>(null)
  const stateRef = useRef<SimulationState | null>(null)
  const mapId = useRef<string | undefined>(undefined)
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
    if (unknownMission.current && receiptMatches(unknownMission.current, validated.domain, runtimeRegistry.getSnapshot().mission.descriptor?.instance_id ?? null, validated.mission.id)) {
      unknownMission.current = null
      setMissionRequestUnknown(false)
      setRecoveryMessage('已按原任务 ID 核对当前导航状态。')
      setActionError(null)
      setGoalIssue(null)
      // Keep the original receipt through an active task, including later refreshes.
      if (['succeeded', 'failed', 'canceled'].includes(validated.mission.status)) {
        try { sessionStorage.removeItem(missionReceiptKey(SIMULATION_DOMAIN)) } catch { /* Read-only evidence is safe to recheck. */ }
      }
    }
    setState(validated)
    setConnectionError(null)
  }

  useEffect(() => {
    mounted.current = true
    try {
      unknownMission.current = readMissionReceipt(sessionStorage, SIMULATION_DOMAIN)
      if (unknownMission.current) { setMissionRequestUnknown(true); setActionError('正在核对刷新前的原任务；不会重发。') }
    } catch (error) { setActionError(error instanceof Error ? error.message : '原任务缓存读取失败，请核对任务记录。') }
    let stopped = false
    let stateTimer: ReturnType<typeof setTimeout>
    let mapTimer: ReturnType<typeof setTimeout>
    let lastLookup = 0

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
        const receipt = unknownMission.current
        if (receipt && Date.now() - lastLookup >= 2000 && !stopped) {
          lastLookup = Date.now()
          try {
            const mapQuery = receipt.mapId === null ? '' : `?map_id=${encodeURIComponent(receipt.mapId)}`
            const lookup = await requestSimulation<unknown>(`tasks/${receipt.missionId}${mapQuery}`, undefined, controller.signal)
            const terminal = recoveredTerminal(receipt, lookup)
            if (!stopped) setRecoveryMessage(terminal ?? '原任务记录尚无可确认终态，继续读取；未重发。')
            if (!stopped && unknownMission.current === receipt && terminal) {
              unknownMission.current = null
              setMissionRequestUnknown(false)
              setActionError(terminal)
              try { sessionStorage.removeItem(missionReceiptKey(SIMULATION_DOMAIN)) } catch { /* Read-only evidence remains safe to recheck. */ }
            }
          } catch (error) {
            if (!stopped) setRecoveryMessage(`原任务核对未完成：${error instanceof Error ? error.message : '查询失败'}；保留未知状态。`)
          }
        }
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
          if (mapId.current !== value.map_id) setGoalIssue(null)
          mapId.current = value.map_id
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
    setGoalIssue(null)
    const sequence = ++requestSequence.current
    const requestedId = action === 'mission' ? crypto.randomUUID() : null
    const payload = action === 'mission' ? { ...body, mission_id: requestedId }
      : action === 'cancel' && stateRef.current?.mission.id ? { mission_id: stateRef.current.mission.id, issued_at: Date.now() / 1000 } : body
    acceptedSequence.current = sequence
    const controller = new AbortController()
    controllers.current.add(controller)
    const timeout = setTimeout(() => controller.abort(), 5000)
    let sent = false
    try {
      if (requestedId) {
        const receipt: MissionReceipt = { version: 1, domain: SIMULATION_DOMAIN, missionId: requestedId, instanceId: runtimeRegistry.getSnapshot().mission.descriptor?.instance_id ?? null, mapId: mapId.current ?? null }
        saveMissionReceipt(sessionStorage, receipt)
        unknownMission.current = receipt
      }
      sent = true
      const value = await requestSimulation<SimulationState>(action, payload, controller.signal)
      acceptState(value, sequence)
      if (requestedId && unknownMission.current) { setMissionRequestUnknown(true); setActionError('派发回执未包含原任务 ID，正在核对；不会重发。') }
    } catch (error) {
      if (mounted.current) {
        if (action === 'mission' && sent && !simulationRequestRejected(error)) {
          setMissionRequestUnknown(true)
          setActionError('派发回执未知，正在读取原任务状态；不能重复派发。')
        } else {
          if (action === 'mission') {
            unknownMission.current = null
            setMissionRequestUnknown(false)
            try { sessionStorage.removeItem(missionReceiptKey(SIMULATION_DOMAIN)) } catch { /* No action was sent or it was explicitly rejected. */ }
          }
          if (action === 'mission' && error instanceof SimulationRejectedRequest) setGoalIssue(error.issue)
          setActionError(error instanceof Error && error.name !== 'AbortError'
            ? error.message : '请求超时，请查看当前任务状态。')
        }
      }
    } finally {
      clearTimeout(timeout)
      controllers.current.delete(controller)
      busy.current = false
      if (mounted.current) setPending(null)
    }
  }

  return { state, map, recoveryMessage, connectionError, mapError, actionError, goalIssue, pending, missionRequestUnknown, act }
}
