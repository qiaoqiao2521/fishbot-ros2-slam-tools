import { lazy, Suspense, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { ArrowLeft, Map, Radar, Route, Send } from 'lucide-react'

import { RadarQualityPanel } from '@/components/radar/radar-quality-panel'
import { RadarViewport } from '@/components/radar/radar-viewport'
import { RadarWorkbenchControls } from '@/components/radar/radar-workbench-controls'
import { Button } from '@/components/ui/button'
import { WorkspaceSurface } from '@/components/workspace/workspace-surface'
import { useWorkspaceVisible } from '@/components/workspace/workspace-visibility'
import { runtimeRegistry } from '@/lib/runtime-context'
import { useRuntimeWriteCapability } from '@/hooks/use-runtime-capability'
import { CommandEvidencePanel } from '@/components/status/command-evidence-panel'
import { projectLegacyPublicationEvidence } from '@/lib/command-evidence'
import './radar-workspace.css'
import { MapPublicationUnconfirmedError, postInitialPose, postNavigationGoal } from '@/lib/api'
import {
  createDefaultRadarWorkbenchConfig,
  isPointInsideMap,
  mapPublicationBlocksDraft,
  type MapPublicationStatus,
  type RadarMapMode,
  type RadarMapPose,
  type RadarSelectedPoint,
  type RadarWorkbenchConfig,
} from '@/lib/radar-workbench'
import { useStationStore } from '@/store/station-store'
import type { LaserScanSnapshot } from '@/types/station'

const SceneViewport = lazy(() => import('@/components/scene/scene-viewport').then((module) => ({ default: module.SceneViewport })))

type MapRequestFeedback = {
  mode: Exclude<RadarMapMode, 'observe'>
  status: Exclude<MapPublicationStatus, 'idle'>
  localizationBefore: string
  error?: string
}

export function RadarWorkbenchPage({
  onBack,
  onPatrol,
  active = true,
}: {
  active?: boolean
  onBack: () => void
  onPatrol: () => void
}) {
  const { connection, navigation, perception, robotState, usingFallbackData, resourceProvenance } = useStationStore()
  const runtime = useSyncExternalStore(runtimeRegistry.subscribe, runtimeRegistry.getSnapshot, runtimeRegistry.getSnapshot).station
  const [view, setView] = useState<'2d' | '3d'>('2d')
  const descriptor = runtime.descriptor
  const source = { key: descriptor ? JSON.stringify([descriptor.instance_id, runtime.generation, descriptor.domain, descriptor.scene_id, descriptor.episode_id]) : null, live: runtime.status === 'verified' && !usingFallbackData && connection.mode === 'live' && resourceProvenance.navigation.status === 'received' && resourceProvenance.perception.status === 'received', label: usingFallbackData ? '示例摘要' : connection.mode === 'offline' ? '离线模拟摘要' : 'ROS 接收摘要' }
  const [config, setConfig] = useState<RadarWorkbenchConfig>(createDefaultRadarWorkbenchConfig)
  const [history, setHistory] = useState<LaserScanSnapshot[]>([])
  const [selectedPoint, setSelectedPoint] = useState<RadarSelectedPoint | null>(null)
  const [hz, setHz] = useState(0)
  const [lastUpdate, setLastUpdate] = useState<string | null>(null)
  const [mapMode, setMapMode] = useState<RadarMapMode>('observe')
  const [draftPose, setDraftPose] = useState<RadarMapPose | null>(null)
  const [requestFeedback, setRequestFeedback] = useState<MapRequestFeedback | null>(null)
  const requestLock = useRef(false)
  const goalEnabled = useRuntimeWriteCapability('station', 'navigation')
  const initialPoseEnabled = useRuntimeWriteCapability('station', 'initial_pose')
  const sending = requestFeedback?.status === 'sending'
  const draftBlocked = mapPublicationBlocksDraft(requestFeedback?.status ?? 'idle')
  const mapInteractive = config.layerMode === 'scan+map' && navigation.map.ready && !config.freeze
  const controlReady = !usingFallbackData && connection.mode === 'live' && connection.controlBridge.connected
  const canSend = view === '2d' && (mapMode === 'initial-pose' ? initialPoseEnabled : goalEnabled) && mapMode !== 'observe' && !!draftPose && mapInteractive && controlReady
    && !draftBlocked && isPointInsideMap(draftPose, navigation.map)
  const localizationUpdated = requestFeedback?.mode === 'initial-pose' && requestFeedback.status === 'published'
    && navigation.localization.ready && navigation.localization.lastUpdate !== requestFeedback.localizationBefore

  function changeMapMode(mode: RadarMapMode) {
    if (requestLock.current) return
    setMapMode(mode)
    setDraftPose(null)
    setRequestFeedback(null)
    if (mode !== 'observe') setConfig((current) => ({ ...current, layerMode: 'scan+map', freeze: false }))
  }

  async function sendMapPose() {
    if (!canSend || !draftPose || requestLock.current) return
    requestLock.current = true
    const mode = mapMode
    const localizationBefore = navigation.localization.lastUpdate
    setRequestFeedback({ mode, status: 'sending', localizationBefore })
    try {
      if (mode === 'initial-pose') await postInitialPose({ ...draftPose, source: 'radar-workbench' })
      else await postNavigationGoal({ ...draftPose, source: 'radar-workbench' })
      setRequestFeedback({ mode, status: 'published', localizationBefore })
    } catch (error) {
      setRequestFeedback({ mode, status: error instanceof MapPublicationUnconfirmedError ? 'unconfirmed' : 'error', localizationBefore,
        error: error instanceof Error ? error.message : '请求未获确认' })
    } finally {
      requestLock.current = false
    }
  }

  useEffect(() => {
    if (!active || !perception.scan.ready || config.freeze || perception.scan.lastUpdate === lastUpdate) {
      return
    }

    if (lastUpdate) {
      const deltaMs = new Date(perception.scan.lastUpdate).getTime() - new Date(lastUpdate).getTime()
      if (deltaMs > 0) {
        setHz(1000 / deltaMs)
      }
    }

    setLastUpdate(perception.scan.lastUpdate)
    setHistory((current) => [...current.slice(-5), { ...perception.scan, samplePoints: [...perception.scan.samplePoints] }])
  }, [active, config.freeze, lastUpdate, perception.scan])

  const feedback = requestFeedback?.status === 'sending' ? '正在等待发布回执…'
    : requestFeedback?.status === 'error' ? `请求未获确认：${requestFeedback.error}。请先核对当前反馈。`
      : requestFeedback?.status === 'unconfirmed' ? '未收到发布回执，结果未知。同一草稿禁止再次发送；请先核对反馈。'
        : requestFeedback?.status === 'published' ? requestFeedback.mode === 'initial-pose'
          ? localizationUpdated ? '重定位位姿已发布；收到新定位，请核对车身方向。' : '重定位位姿已发布，等待定位反馈。'
          : '导航目标已发布，等待 Nav2 反馈。发布回执不代表已到达。' : null
  const modes = [['observe', '观察'], ['goal', '导航目标'], ['initial-pose', '重定位']] as const
  return <WorkspaceSurface id="radar" title="雷达与地图" subtitle="观测、目标与重定位" active={active}
    toolbar={<><div className="radar-view-switch" role="group" aria-label="画布视图"><Button variant="outline" aria-pressed={view === '2d'} onClick={() => setView('2d')}>二维地图</Button><Button variant="outline" aria-pressed={view === '3d'} onClick={() => setView('3d')}>三维观测</Button></div>
      {mapMode !== 'observe' && <Button disabled={!canSend} onClick={() => void sendMapPose()}><Send size={15} />{sending ? '正在发布…' : mapMode === 'initial-pose' ? '发布重定位位姿' : '发送导航目标'}</Button>}
      <Button variant="outline" onClick={onPatrol}><Route size={15} />地图巡逻</Button>
      <Button variant="outline" onClick={onBack}><ArrowLeft size={15} />控制总览</Button>
    </>}
    notice={<><p className="radar-write-capability">{!goalEnabled && !initialPoseEnabled ? '当前为只读观测；导航任务请从“地图巡逻”进入。' : '旧话题发布已显式启用；发布回执不等于动作接纳。'}</p><div className="radar-source-notice" role="status"><Radar size={14} />{usingFallbackData ? '示例数据 · 不可派发' : connection.mode === 'offline' ? '离线模拟数据' : 'ROS 链路'}<span>{perception.scan.ready ? `${perception.scan.samplePoints.length} 个显示点 · ${hz.toFixed(1)} Hz` : '等待扫描'}</span>{feedback && <strong>{feedback}</strong>}</div></>}
    canvas={<VisibleRadarCanvas>{view === '3d' ? <Suspense fallback={<p className="workspace-loading">正在载入三维观测…</p>}><SceneViewport scan={perception.scan} navigation={navigation} robotState={robotState} source={source} active={!config.freeze} /></Suspense> : <RadarViewport config={config} mapMode={mapMode} draftPose={draftPose}
      selectionDisabled={draftBlocked || config.freeze} pathTelemetryLive={!usingFallbackData && connection.mode === 'live'}
      history={history} navigation={navigation} onPoseSelect={setDraftPose} onPointSelect={setSelectedPoint}
      robotState={robotState} scan={perception.scan} selectedPoint={selectedPoint} />}</VisibleRadarCanvas>}
    objects={<div className="radar-workspace-objects"><h2>地图操作</h2><div className="workspace-object-list" role="group" aria-label="地图操作模式">
      {modes.map(([mode, label]) => <button key={mode} aria-pressed={mapMode === mode} disabled={sending || view === '3d'} onClick={() => changeMapMode(mode)}><Map size={15} />{label}</button>)}
      </div><p className="radar-workspace-hint">{view === '3d' ? '三维视图只读。切回二维地图进行位姿草稿操作。' : '先选模式，再点地图选位置和朝向。选点只更新草稿。'}</p>
      <h2>显示图层</h2><RadarWorkbenchControls config={config} onClearHistory={() => setHistory([])} onConfigChange={setConfig} />
      <details><summary>扫描质量</summary><RadarQualityPanel perception={perception} /></details>
    </div>}
    properties={<div className="workspace-properties"><h2>{draftPose ? '位姿草稿' : selectedPoint ? '扫描点属性' : '对象属性'}</h2>
      {mapMode !== 'observe' && <><p>{draftPose ? `位置 (${draftPose.x.toFixed(2)}, ${draftPose.y.toFixed(2)}) 米` : '在地图上选择位置，再拖动确定方向。'}</p>
        <label className="radar-angle-input">方向（度）<input aria-label="方向（度）" type="number" min={-180} max={180} step="1" disabled={!draftPose || draftBlocked}
          value={draftPose ? Number((draftPose.yaw * 180 / Math.PI).toFixed(1)) : 0}
          onChange={(event) => { const value = event.currentTarget.valueAsNumber; if (draftPose && Number.isFinite(value)) setDraftPose({ ...draftPose, yaw: Math.max(-180, Math.min(180, value)) * Math.PI / 180 }) }} /></label>
        <p className="radar-workspace-hint">0° 向右，90° 向上</p>
        <Button variant="outline" size="sm" disabled={!draftPose || sending} onClick={() => { setDraftPose(null); setRequestFeedback(null) }}>重新选点</Button>
        {!mapInteractive && <p>切换到实时 scan+map 图层并等待地图后才能发送。</p>}
        {!controlReady && <p>控制桥未连接或当前为示例数据，发送暂不可用。</p>}
      </>}
      {selectedPoint ? <dl><div><dt>距离</dt><dd>{selectedPoint.rangeMeters.toFixed(3)} m</dd></div><div><dt>角度</dt><dd>{(selectedPoint.angleRad * 180 / Math.PI).toFixed(2)}°</dd></div><div><dt>局部 X / Y</dt><dd>{selectedPoint.x.toFixed(3)} / {selectedPoint.y.toFixed(3)} m</dd></div></dl> : <p className="radar-workspace-hint">悬停扫描点可查看距离与坐标。</p>}
      <details><summary>坐标与数据边界</summary><p>当前显示LaserScan采样点。地图为后端采样栅格，最多6000格。TF只报告存在性；扫描按基座原点对齐，laser→base偏移尚待TF数值接入。</p></details>
    </div>}
    task={<div className="radar-workspace-task"><div><h2>发布与定位反馈</h2><p role="status">{feedback || '尚未提交位姿；选点不会自动发送。'}</p>
      <CommandEvidencePanel evidence={projectLegacyPublicationEvidence({ state: requestFeedback?.status === 'published' ? 'published' : requestFeedback?.status === 'sending' ? 'pending' : requestFeedback ? 'unknown' : 'idle', reason: feedback ?? undefined })} />
      <p className="radar-workspace-hint">巡逻、返航和原任务取消使用地图巡逻工作面。各服务运行环境分别核对。</p></div>
      <dl><div><dt>地图</dt><dd>{navigation.map.ready ? `${navigation.map.width} × ${navigation.map.height}` : '等待 /map'}</dd></div>
        <div><dt>定位</dt><dd>{navigation.localization.statusMessage}</dd></div><div><dt>TF</dt><dd>{navigation.tf.statusMessage}</dd></div>
        <div><dt>导航报告</dt><dd>{navigation.navStatus.statusSummary}</dd></div><div><dt>路径报告</dt><dd>{navigation.path?.statusMessage || '服务未提供路径'}</dd></div></dl>
    </div>} />
}

function VisibleRadarCanvas({ children }: { children: ReactNode }) {
  const visible = useWorkspaceVisible()
  return visible ? <div className="radar-canvas-host">{children}</div> : null
}
