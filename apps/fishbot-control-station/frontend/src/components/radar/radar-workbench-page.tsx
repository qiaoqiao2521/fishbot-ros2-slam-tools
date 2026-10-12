import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Box, Map, Radar, Route, Send } from 'lucide-react'

import { RadarQualityPanel } from '@/components/radar/radar-quality-panel'
import { RadarStatusStrip } from '@/components/radar/radar-status-strip'
import { RadarViewport } from '@/components/radar/radar-viewport'
import { RadarWorkbenchControls } from '@/components/radar/radar-workbench-controls'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardTitle } from '@/components/ui/card'
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

type MapRequestFeedback = {
  mode: Exclude<RadarMapMode, 'observe'>
  status: Exclude<MapPublicationStatus, 'idle'>
  localizationBefore: string
  error?: string
}

export function RadarWorkbenchPage({
  onBack,
  onPatrol,
}: {
  onBack: () => void
  onPatrol: () => void
}) {
  const { connection, navigation, perception, robotState, usingFallbackData } = useStationStore()
  const [config, setConfig] = useState<RadarWorkbenchConfig>(createDefaultRadarWorkbenchConfig)
  const [history, setHistory] = useState<LaserScanSnapshot[]>([])
  const [selectedPoint, setSelectedPoint] = useState<RadarSelectedPoint | null>(null)
  const [hz, setHz] = useState(0)
  const [lastUpdate, setLastUpdate] = useState<string | null>(null)
  const [mapMode, setMapMode] = useState<RadarMapMode>('observe')
  const [draftPose, setDraftPose] = useState<RadarMapPose | null>(null)
  const [requestFeedback, setRequestFeedback] = useState<MapRequestFeedback | null>(null)
  const requestLock = useRef(false)
  const sending = requestFeedback?.status === 'sending'
  const draftBlocked = mapPublicationBlocksDraft(requestFeedback?.status ?? 'idle')
  const mapInteractive = config.layerMode === 'scan+map' && navigation.map.ready && !config.freeze
  const controlReady = !usingFallbackData && connection.mode === 'live' && connection.controlBridge.connected
  const canSend = mapMode !== 'observe' && !!draftPose && mapInteractive && controlReady
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
    if (!perception.scan.ready || config.freeze || perception.scan.lastUpdate === lastUpdate) {
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
  }, [config.freeze, lastUpdate, perception.scan])

  return (
    <div className="relative min-h-screen overflow-hidden text-foreground">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-52 bg-[linear-gradient(180deg,rgba(78,56,28,0.16),transparent)]" />
      <div className="pointer-events-none absolute left-[8%] top-20 h-40 w-40 rounded-full bg-[rgba(196,132,34,0.16)] blur-3xl" />
      <div className="pointer-events-none absolute bottom-16 right-[9%] h-48 w-48 rounded-full bg-[rgba(58,87,82,0.14)] blur-3xl" />

      <div className="mx-auto flex min-h-screen max-w-[1680px] flex-col gap-5 px-4 py-5 md:px-6 lg:px-8">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button variant="outline" onClick={onBack}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to Console
          </Button>

          <div className="flex flex-wrap items-center gap-3">
            <Button variant="outline" onClick={onPatrol}><Route className="mr-2 h-4 w-4" />仿真巡逻</Button>
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">
            <Radar className="h-4 w-4" />
            /radar
            </div>
          </div>
        </div>

        <RadarStatusStrip connection={connection} scan={perception.scan} hz={hz} />

        <div className="grid flex-1 gap-5 xl:grid-cols-[340px_minmax(0,1fr)_340px]">
          <div className="order-2 grid gap-5 xl:order-1">
            <RadarQualityPanel perception={perception} />
            <Card>
              <div className="panel-header">
                <div>
                  <div className="station-kicker mb-2">mapping hooks / nav handoff / future slots</div>
                  <CardTitle>Mapping Prep</CardTitle>
                  <CardDescription>这页先把建图前观察和后续 Nav2 接入位都留好。</CardDescription>
                </div>
              </div>

              <div className="grid gap-3">
                <PrepRow title="SLAM source" value={navigation.map.ready ? `${navigation.map.width} x ${navigation.map.height}` : 'waiting /map'} />
                <PrepRow title="TF graph" value={navigation.tf.ready ? navigation.tf.statusMessage : 'waiting /tf'} />
                <PrepRow title="Localization" value={navigation.localization.ready ? navigation.localization.statusMessage : 'waiting /amcl_pose'} />
                <PrepRow title="Nav status" value={navigation.navStatus.ready ? navigation.navStatus.statusSummary : 'waiting nav2 actions'} />
                <PrepRow
                  title="最近路径报告"
                  value={!navigation.path ? '路径状态未知：当前服务未提供路径数据'
                    : `${navigation.path.statusMessage} · ${navigation.path.lastUpdate ?? '未报告时间'} · ${navigation.path.frameId && navigation.path.frameId !== 'map'
                      ? `${navigation.path.frameId} 坐标系，未绘制`
                      : `${navigation.path.poseCount} 个位姿 / ${navigation.path.points.length} 个显示点`}`}
                />
              </div>
            </Card>
          </div>

          <div className="order-1 grid min-w-0 gap-5 xl:order-2">
            <Card>
              <div className="panel-header"><div><CardTitle>地图操作</CardTitle><CardDescription>先选模式，再选位置和方向，最后点击发送。</CardDescription></div></div>
              <div className="grid grid-cols-3 gap-2" role="group" aria-label="地图操作模式">
                {([['observe', '观察'], ['goal', '导航目标'], ['initial-pose', '重定位']] as const).map(([mode, label]) => (
                  <Button key={mode} className="px-2 tracking-normal" variant={mapMode === mode ? 'default' : 'outline'}
                    aria-pressed={mapMode === mode} disabled={sending} onClick={() => changeMapMode(mode)}>{label}</Button>
                ))}
              </div>
              <p className="mt-3 text-sm leading-6 text-muted-foreground">
                {mapMode === 'observe' ? '观察模式只看地图。选择导航目标或重定位后，地图点击才会选择草稿。'
                  : '点地图选位置；拖动或再点一次确定方向。也可以在下方调整角度，选点不会立即发布。'}
              </p>
              {mapMode !== 'observe' && <div className="mt-3 grid gap-3">
                <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
                  <span>{draftPose ? `待发送位置 (${draftPose.x.toFixed(2)}, ${draftPose.y.toFixed(2)}) 米` : '等待在地图上选择位置'}</span>
                  <Button variant="ghost" size="sm" disabled={!draftPose || sending} onClick={() => { setDraftPose(null); setRequestFeedback(null) }}>重新选点</Button>
                </div>
                <label className="flex items-center gap-3 text-sm">
                  <span>方向（度）</span>
                  <input aria-label="方向（度）" className="station-well min-h-11 w-24 rounded-xl px-3" type="number" min={-180} max={180} step="1"
                    disabled={!draftPose || draftBlocked} value={draftPose ? Number((draftPose.yaw * 180 / Math.PI).toFixed(1)) : 0}
                    onChange={(event) => { const value = event.currentTarget.valueAsNumber; if (draftPose && Number.isFinite(value)) setDraftPose({ ...draftPose, yaw: Math.max(-180, Math.min(180, value)) * Math.PI / 180 }) }} />
                  <span className="text-xs text-muted-foreground">0° 向右，90° 向上</span>
                </label>
                <Button disabled={!canSend} onClick={() => void sendMapPose()}><Send className="mr-2 h-4 w-4" />
                  {sending ? '正在发布…' : mapMode === 'initial-pose' ? '发布重定位位姿' : '发送导航目标'}</Button>
                {!mapInteractive && <p className="text-sm text-muted-foreground">切换到实时 scan+map 图层并等待地图后才能发送。</p>}
                {!controlReady && <p className="text-sm text-muted-foreground">控制桥未连接或当前为示例数据，发送暂不可用。</p>}
              </div>}
              {requestFeedback && <p className="mt-3 text-sm leading-6" role="status" aria-live="polite">
                {requestFeedback.status === 'sending' ? '正在等待发布回执…'
                  : requestFeedback.status === 'error' ? `请求未获确认：${requestFeedback.error}。请先核对当前反馈。`
                    : requestFeedback.status === 'unconfirmed' ? '未收到发布回执，结果未知。同一草稿禁止再次发送；请先核对导航或定位反馈，再重新选点。'
                    : requestFeedback.mode === 'initial-pose'
                      ? localizationUpdated ? '重定位位姿已发布；收到新的定位消息，请核对车身位置与方向。' : '重定位位姿已发布，等待定位反馈。'
                      : '导航目标已发布，等待 Nav2 反馈。发布回执不代表已到达。'}
              </p>}
              <p className="mt-3 text-xs leading-5 text-muted-foreground">多航点巡逻、返航和取消请进入“仿真巡逻”。该页使用隔离 MuJoCo 环境，不向本页控制桥派发任务。</p>
            </Card>
            <RadarViewport
              config={config}
              mapMode={mapMode}
              draftPose={draftPose}
              selectionDisabled={draftBlocked || config.freeze}
              pathTelemetryLive={!usingFallbackData && connection.mode === 'live'}
              history={history}
              navigation={navigation}
              onPoseSelect={setDraftPose}
              onPointSelect={setSelectedPoint}
              robotState={robotState}
              scan={perception.scan}
              selectedPoint={selectedPoint}
            />
            <RadarWorkbenchControls config={config} onClearHistory={() => setHistory([])} onConfigChange={setConfig} />
          </div>

          <div className="order-3 grid gap-5">
            <Card>
              <div className="panel-header">
                <div>
                  <div className="station-kicker mb-2">point inspector / field pick</div>
                  <CardTitle>Point Inspector</CardTitle>
                  <CardDescription>鼠标停在雷达点上时，这里显示当前射线的极坐标和直角坐标。</CardDescription>
                </div>
                <BadgeLike active={!!selectedPoint}>{selectedPoint ? 'locked' : 'idle'}</BadgeLike>
              </div>

              {selectedPoint ? (
                <div className="grid gap-3">
                  <InspectorRow label="Range" value={`${selectedPoint.rangeMeters.toFixed(3)} m`} />
                  <InspectorRow label="Angle" value={`${(selectedPoint.angleRad * 180 / Math.PI).toFixed(2)}°`} />
                  <InspectorRow label="X" value={selectedPoint.x.toFixed(3)} />
                  <InspectorRow label="Y" value={selectedPoint.y.toFixed(3)} />
                </div>
              ) : (
                <div className="station-well flex min-h-[240px] flex-col items-center justify-center rounded-[24px] text-center">
                  <Box className="mb-3 h-8 w-8 text-muted-foreground/45" />
                  <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">hover a point to inspect</div>
                </div>
              )}
            </Card>

            <Card>
              <div className="panel-header">
                <div>
                  <div className="station-kicker mb-2">operator note / source of truth</div>
                  <CardTitle>Sensor Note</CardTitle>
                  <CardDescription>当前页面显示的是 LaserScan 采样点，不是完整点云地图。</CardDescription>
                </div>
                <Map className="h-5 w-5 text-[hsl(var(--accent))]" />
              </div>

              <div className="grid gap-3 text-sm leading-6 text-muted-foreground">
                <div className="station-well rounded-[22px] px-4 py-4">
                  scan+map 图层叠加 /map、扫描、定位和后端路径报告；示例数据不绘制为实时路径。导航目标发布到 /goal_pose，重定位发布到 /initialpose；两者都需要显式发送。
                </div>
                <div className="station-well rounded-[22px] px-4 py-4">
                  当前边界：地图是后端采样的栅格（≤6000 格）；TF 只报存在性，扫描先按基座原点对齐，真实 laser→base 偏移待 TF 数值接入后修正。
                </div>
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  )
}

function PrepRow({
  title,
  value,
}: {
  title: string
  value: string
}) {
  return (
    <div className="station-well rounded-[22px] px-4 py-4">
      <div className="mb-2 text-xs uppercase tracking-[0.18em] text-muted-foreground">{title}</div>
      <div className="text-sm font-semibold text-foreground/92">{value}</div>
    </div>
  )
}

function InspectorRow({
  label,
  value,
}: {
  label: string
  value: string
}) {
  return (
    <div className="station-well flex items-center justify-between gap-3 rounded-[20px] px-4 py-4">
      <div className="text-xs uppercase tracking-[0.18em] text-muted-foreground">{label}</div>
      <div className="station-readout text-base font-semibold text-foreground/96">{value}</div>
    </div>
  )
}

function BadgeLike({
  active,
  children,
}: {
  active: boolean
  children: string
}) {
  return (
    <div
      className={
        active
          ? 'rounded-full border border-[hsl(var(--accent))] bg-[hsl(var(--accent))] px-3 py-1 text-xs uppercase tracking-[0.18em] text-[hsl(var(--accent-foreground))]'
          : 'rounded-full border border-border bg-secondary px-3 py-1 text-xs uppercase tracking-[0.18em] text-secondary-foreground'
      }
    >
      {children}
    </div>
  )
}
