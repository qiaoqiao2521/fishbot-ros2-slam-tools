import { useEffect, useReducer, useRef, useState } from 'react'
import { MapZonesManager } from '@/lib/map-zones'

import { posesEquivalent, requestSimulation, simulationRequestRejected, SimulationRejectedRequest, type Pose, type SimulationMap } from '@/lib/simulation'
import {
  emptyRulesEditor, mapGeneration, rulesDirty, rulesReducer, validateMapRules, validateRoutes, validateRuns, zonesEqual,
  type MapRules, type RouteCollection, type RunCollection, type SavedRoute,
} from '@/lib/simulation-workspace'

export function useSimulationWorkspace(map: SimulationMap | null, blocked: boolean) {
  const [editor, dispatch] = useReducer(rulesReducer, undefined, emptyRulesEditor)
  const [rulesError, setRulesError] = useState<string | null>(null)
  const [routesError, setRoutesError] = useState<string | null>(null)
  const [runsError, setRunsError] = useState<string | null>(null)
  const [routes, setRoutes] = useState<SavedRoute[]>([])
  const [runs, setRuns] = useState<RunCollection['runs']>([])
  const [routeWrite, setRouteWrite] = useState<'idle' | 'saving' | 'unknown' | 'rejected'>('idle')
  const [routeMessage, setRouteMessage] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportMessage, setExportMessage] = useState('')
  const exportBusy = useRef(false)
  const generation = mapGeneration(map)
  const editorRef = useRef(editor)
  const blockedRef = useRef(blocked)
  const liveGeneration = useRef(generation)
  const readSequence = useRef(0)
  const writeBusy = useRef(false)
  const mounted = useRef(false)
  const controllers = useRef(new Set<AbortController>())
  const unknownRoute = useRef<{ id: string; name: string; waypoints: Pose[]; returnHome: boolean } | null>(null)
  editorRef.current = editor
  blockedRef.current = blocked
  liveGeneration.current = generation

  async function readResources(expectedGeneration = generation, expectedMap = map?.map_id) {
    if (!expectedGeneration) return
    const sequence = ++readSequence.current
    const controller = new AbortController()
    controllers.current.add(controller)
    const timeout = setTimeout(() => controller.abort(), 3000)
    const results = await Promise.allSettled([
      requestSimulation<MapRules>('map-rules', undefined, controller.signal).then((value) => validateMapRules(value, expectedMap)),
      requestSimulation<RouteCollection>('routes', undefined, controller.signal).then((value) => validateRoutes(value, expectedMap)),
      requestSimulation<RunCollection>('runs', undefined, controller.signal).then(validateRuns),
    ])
    clearTimeout(timeout)
    controllers.current.delete(controller)
    if (!mounted.current || liveGeneration.current !== expectedGeneration || sequence !== readSequence.current) return
    const message = (reason: unknown, name: string) => reason instanceof SimulationRejectedRequest && reason.status === 404
      ? `当前仿真尚未接入${name}服务。` : reason instanceof Error && reason.name !== 'AbortError'
        ? reason.message : `${name}读取超时，请重新读取。`
    const [ruleResult, routeResult, runResult] = results
    if (ruleResult.status === 'fulfilled') {
      dispatch({ type: 'received', value: ruleResult.value })
      setRulesError(null)
    } else setRulesError(message(ruleResult.reason, '地图规则'))
    if (routeResult.status === 'fulfilled') {
      setRoutes(routeResult.value.routes)
      setRoutesError(null)
      const attempted = unknownRoute.current
      if (attempted && routeResult.value.routes.some((route) => route.id === attempted.id
        && route.name === attempted.name && route.return_home === attempted.returnHome
        && route.waypoints.length === attempted.waypoints.length && route.waypoints.every((point, index) => posesEquivalent(point, attempted.waypoints[index])))) {
        unknownRoute.current = null
        setRouteWrite('idle')
        setRouteMessage('已读取到保存的路线；尚未派发任务。')
      }
    } else setRoutesError(message(routeResult.reason, '路线模板'))
    if (runResult.status === 'fulfilled') { setRuns(runResult.value.runs); setRunsError(null) }
    else setRunsError(message(runResult.reason, '任务记录'))
  }

  useEffect(() => {
    mounted.current = true
    dispatch({ type: 'reset' })
    setRoutes([])
    setRuns([])
    setRouteWrite('idle')
    setRouteMessage('')
    setExportMessage('')
    setRulesError(null)
    setRoutesError(null)
    setRunsError(null)
    unknownRoute.current = null
    writeBusy.current = false
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    async function poll() {
      await readResources(generation, map?.map_id)
      if (!stopped) timer = setTimeout(poll, 2000)
    }
    if (generation) void poll()
    const activeControllers = controllers.current
    return () => {
      stopped = true
      mounted.current = false
      clearTimeout(timer)
      activeControllers.forEach((controller) => controller.abort())
      activeControllers.clear()
    }
    // Only map generation changes reset drafts. Polling an identical map does not.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generation])

  async function refresh() {
    if (refreshing) return
    setRefreshing(true)
    try { await readResources() } finally { if (mounted.current) setRefreshing(false) }
  }

  async function saveRules() {
    const current = editorRef.current
    if (writeBusy.current || blockedRef.current || !current.saved || !rulesDirty(current) || current.anchor
      || current.writeState === 'unknown' || current.writeState === 'saving'
      || current.baseRevision !== current.saved.revision || rulesError) return
    let zones
    try { zones = MapZonesManager.fromMapRulesZones(current.zones).toMapRulesZones() }
    catch (error) { dispatch({ type: 'rejected', message: error instanceof Error ? error.message : '规则草稿无效。' }); return }
    const expectedGeneration = generation
    writeBusy.current = true
    ++readSequence.current
    dispatch({ type: 'saving' })
    const controller = new AbortController()
    controllers.current.add(controller)
    const timeout = setTimeout(() => controller.abort(), 5000)
    try {
      const value = validateMapRules(await requestSimulation<MapRules>('map-rules', {
        map_id: current.saved.map_id, base_revision: current.baseRevision, zones,
      }, controller.signal), current.saved.map_id)
      if (value.revision <= (current.baseRevision ?? -1) || !zonesEqual(value.zones, current.zones)) throw new Error('保存回执未确认新版本。')
      if (mounted.current && liveGeneration.current === expectedGeneration) {
        ++readSequence.current
        dispatch({ type: 'saved', value })
      }
    } catch (error) {
      if (mounted.current && liveGeneration.current === expectedGeneration) {
        ++readSequence.current
        const rejected = simulationRequestRejected(error)
        dispatch({ type: rejected ? 'rejected' : 'unknown', message: rejected && error instanceof Error ? error.message
          : '规则保存结果未知。不会自动重发；请读取规则确认。' })
      }
    } finally {
      clearTimeout(timeout)
      controllers.current.delete(controller)
      if (mounted.current && liveGeneration.current === expectedGeneration) {
        writeBusy.current = false
        void readResources()
      }
    }
  }

  async function saveRoute(name: string, waypoints: Pose[], returnHome: boolean) {
    const current = editorRef.current
    if (writeBusy.current || blockedRef.current || !current.saved || routeWrite === 'unknown'
      || !name.trim() || !waypoints.length || routesError) return
    const expectedGeneration = generation
    writeBusy.current = true
    ++readSequence.current
    setRouteWrite('saving')
    setRouteMessage('')
    const attempted = { id: crypto.randomUUID(), name: name.trim(), waypoints: waypoints.map((point) => ({ ...point })), returnHome }
    const controller = new AbortController()
    controllers.current.add(controller)
    const timeout = setTimeout(() => controller.abort(), 5000)
    try {
      const result = validateRoutes(await requestSimulation<RouteCollection>('routes', {
        id: attempted.id, map_id: current.saved.map_id, name: attempted.name, waypoints: attempted.waypoints, return_home: returnHome,
      }, controller.signal), current.saved.map_id)
      if (!result.routes.some((route) => route.id === attempted.id && route.name === attempted.name
        && route.return_home === attempted.returnHome && route.waypoints.length === attempted.waypoints.length && route.waypoints.every((point, index) => posesEquivalent(point, attempted.waypoints[index])))) {
        throw new Error('路线保存回执未确认本次模板。')
      }
      if (mounted.current && liveGeneration.current === expectedGeneration) {
        ++readSequence.current
        setRoutes(result.routes)
        setRouteWrite('idle')
        setRouteMessage('路线已保存；尚未派发任务。')
      }
    } catch (error) {
      if (mounted.current && liveGeneration.current === expectedGeneration) {
        ++readSequence.current
        const rejected = simulationRequestRejected(error)
        unknownRoute.current = rejected ? null : attempted
        setRouteWrite(rejected ? 'rejected' : 'unknown')
        setRouteMessage(rejected && error instanceof Error ? error.message : '路线保存结果未知。不会自动重发；请读取路线确认。')
      }
    } finally {
      clearTimeout(timeout)
      controllers.current.delete(controller)
      if (mounted.current && liveGeneration.current === expectedGeneration) {
        writeBusy.current = false
        void readResources()
      }
    }
  }

  async function exportRules() {
    const current = editorRef.current
    if (exportBusy.current || !current.saved || rulesDirty(current) || current.saved.apply_state !== 'applied') return
    exportBusy.current = true
    setExporting(true)
    setExportMessage('')
    const expectedGeneration = generation
    const controller = new AbortController()
    controllers.current.add(controller)
    const timeout = setTimeout(() => controller.abort(), 5000)
    try {
      const raw = await requestSimulation<unknown>('map-rules/export', undefined, controller.signal)
      const latest = editorRef.current
      if (!mounted.current || liveGeneration.current !== expectedGeneration) return
      if (latest.saved?.revision !== current.saved.revision || rulesDirty(latest)) throw new Error('导出期间规则已变化，请重新确认。')
      const value = MapZonesManager.fromMapRulesZones(current.saved.zones)
        .toCostmapFilterPayload(raw, current.saved.map_id, current.saved.revision)
      const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }))
      try {
        const link = document.createElement('a')
        link.href = url
        link.download = `fishbot-nav2-keepout-r${value.revision}.json`
        link.click()
      } finally { URL.revokeObjectURL(url) }
      setExportMessage(`已导出导航实际发布的规则版本 ${value.revision}，包含 OccupancyGrid 与 CostmapFilterInfo。`)
    } catch (error) {
      if (mounted.current && liveGeneration.current === expectedGeneration) setExportMessage(error instanceof Error ? error.message : '导出失败，请重新读取规则。')
    } finally {
      clearTimeout(timeout)
      controllers.current.delete(controller)
      exportBusy.current = false
      if (mounted.current) setExporting(false)
    }
  }

  return { editor, dispatch, rulesError, routes, routesError, runs, runsError, routeWrite, routeMessage,
    refreshing, refresh, saveRules, saveRoute, exporting, exportMessage, exportRules }
}
