import { useMemo, useRef, useState } from 'react'

import {
  cellWorldCenter,
  createMapProjection,
  mapHeadingDegrees,
  mapPointerToWorld,
  mapWorldCorners,
  occupancyColor,
  renderableNavigationPath,
  resolveMapWorldBounds,
  scanPointInMapFrame,
  selectMapPose,
  type RadarMapMode,
  type RadarMapPose,
  type WorldPoint,
} from '@/lib/radar-workbench'
import type { LaserScanSnapshot, NavigationSnapshot, RobotStateSnapshot } from '@/types/station'
import type { RadarSelectedPoint, RadarWorkbenchConfig } from '@/lib/radar-workbench'

type Point = RadarSelectedPoint & {
  left: number
  top: number
}

function mapPoint(point: RadarSelectedPoint, extent: number): Point {
  const safeExtent = Math.max(extent, 1)
  return {
    ...point,
    left: 50 + (point.y / safeExtent) * 42,
    top: 50 - (point.x / safeExtent) * 42,
  }
}

export function RadarViewport({
  config,
  mapMode,
  draftPose,
  selectionDisabled,
  pathTelemetryLive,
  history,
  navigation,
  onPoseSelect,
  onPointSelect,
  robotState,
  scan,
  selectedPoint,
}: {
  scan: LaserScanSnapshot
  history: LaserScanSnapshot[]
  config: RadarWorkbenchConfig
  selectedPoint: RadarSelectedPoint | null
  onPointSelect: (point: RadarSelectedPoint | null) => void
  robotState: RobotStateSnapshot
  navigation: NavigationSnapshot
  mapMode: RadarMapMode
  draftPose: RadarMapPose | null
  selectionDisabled: boolean
  pathTelemetryLive: boolean
  onPoseSelect: (pose: RadarMapPose) => void
}) {
  const gesture = useRef<{ pointerId: number; start: WorldPoint; current: RadarMapPose | null; clientX: number; clientY: number } | null>(null)
  const [gesturePreview, setGesturePreview] = useState<RadarMapPose | null>(null)
  const mapLayerActive = config.layerMode === 'scan+map' && navigation.map.ready
  const selectionEnabled = mapLayerActive && mapMode !== 'observe' && !selectionDisabled
  const poseX = navigation.localization.ready ? navigation.localization.x : robotState.odom.x
  const poseY = navigation.localization.ready ? navigation.localization.y : robotState.odom.y
  const poseYaw = navigation.localization.ready ? navigation.localization.yaw : robotState.odom.yaw

  const projection = useMemo(
    () => (mapLayerActive ? createMapProjection(resolveMapWorldBounds(navigation.map), config.zoom) : null),
    [mapLayerActive, navigation.map, config.zoom],
  )

  const mapCells = useMemo(() => {
    if (!projection || !navigation.map.ready) return []
    const size = projection.cellViewportSize(navigation.map)
    return navigation.map.sampledCells.map((cell) => {
      const center = projection.toViewport(cellWorldCenter(cell, navigation.map))
      return { key: `${cell.x}-${cell.y}`, left: center.left, top: center.top, size, fill: occupancyColor(cell.occupancy) }
    })
  }, [projection, navigation.map])

  const worldGridLines = useMemo(() => {
    if (!projection || !config.showGrid) return []
    const bounds = resolveMapWorldBounds(navigation.map)
    const lines: Array<{ x1: number; y1: number; x2: number; y2: number }> = []
    for (let gx = Math.ceil(bounds.minX); gx <= Math.floor(bounds.maxX); gx += 1) {
      const start = projection.toViewport({ x: gx, y: bounds.minY })
      const end = projection.toViewport({ x: gx, y: bounds.maxY })
      lines.push({ x1: start.left, y1: start.top, x2: end.left, y2: end.top })
    }
    for (let gy = Math.ceil(bounds.minY); gy <= Math.floor(bounds.maxY); gy += 1) {
      const start = projection.toViewport({ x: bounds.minX, y: gy })
      const end = projection.toViewport({ x: bounds.maxX, y: gy })
      lines.push({ x1: start.left, y1: start.top, x2: end.left, y2: end.top })
    }
    return lines
  }, [projection, config.showGrid, navigation.map])

  const extent = Math.max(scan.rangeMax || 1, scan.observedRange || 1, 4)
  const currentPoints = scan.samplePoints.map((point) => mapPoint(point, extent / config.zoom))
  const ghostFrames = config.showGhost && !mapLayerActive ? history.slice(-5) : []
  const mapScanPoints = useMemo(() => {
    if (!projection || mapLayerActive !== true) return []
    return scan.samplePoints.map((point) => {
      const placed = projection.toViewport(scanPointInMapFrame(point, { x: poseX, y: poseY, yaw: poseYaw }))
      return { ...point, left: placed.left, top: placed.top }
    })
  }, [projection, mapLayerActive, scan.samplePoints, poseX, poseY, poseYaw])

  const poseViewport = projection ? projection.toViewport({ x: poseX, y: poseY }) : null
  const displayedDraft = gesturePreview ?? draftPose
  const draftViewport = projection && displayedDraft ? projection.toViewport(displayedDraft) : null
  const boundaryPoints = projection ? mapWorldCorners(navigation.map).map((point) => projection.toViewport(point)) : []
  const pathPoints = projection && pathTelemetryLive ? renderableNavigationPath(navigation.path).map((point) => projection.toViewport(point)) : []

  function handlePointerDown(event: React.PointerEvent<SVGSVGElement>) {
    if (!projection || !selectionEnabled || !event.isPrimary || event.button !== 0) return
    const start = mapPointerToWorld(event, event.currentTarget.getBoundingClientRect(), projection, navigation.map)
    if (!start) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    gesture.current = { pointerId: event.pointerId, start, current: draftPose, clientX: event.clientX, clientY: event.clientY }
  }

  function handlePointerMove(event: React.PointerEvent<SVGSVGElement>) {
    if (!projection || !selectionEnabled || gesture.current?.pointerId !== event.pointerId) return
    const end = mapPointerToWorld(event, event.currentTarget.getBoundingClientRect(), projection, navigation.map)
    if (!end) return
    const dragged = Math.hypot(event.clientX - gesture.current.clientX, event.clientY - gesture.current.clientY) >= 6
    setGesturePreview(selectMapPose(mapMode, gesture.current.current, gesture.current.start, end, dragged))
  }

  function clearGesture(event: React.PointerEvent<SVGSVGElement>) {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
    gesture.current = null
    setGesturePreview(null)
  }

  function handlePointerUp(event: React.PointerEvent<SVGSVGElement>) {
    const current = gesture.current
    if (!current || current.pointerId !== event.pointerId) return
    if (projection && selectionEnabled) {
      const end = mapPointerToWorld(event, event.currentTarget.getBoundingClientRect(), projection, navigation.map)
      if (end) {
        const dragged = Math.hypot(event.clientX - current.clientX, event.clientY - current.clientY) >= 6
        const pose = selectMapPose(mapMode, current.current, current.start, end, dragged)
        if (pose) onPoseSelect(pose)
      }
    }
    clearGesture(event)
  }

  return (
    <div className="glass-panel flex min-h-[520px] flex-col overflow-hidden rounded-[34px] md:min-h-[720px]">
      <div className="flex items-center justify-between gap-3 border-b border-border/70 px-6 py-4">
        <div>
          <div className="station-kicker mb-2">laser scan protagonist / inspection-ready viewport</div>
          <div className="station-readout text-xl font-semibold uppercase tracking-[0.12em] text-foreground/95">Radar Workbench</div>
        </div>
        <div className="text-right text-xs uppercase tracking-[0.18em] text-muted-foreground">
          <div>{mapLayerActive ? `${navigation.map.sampledCells.length} map cells` : `${scan.samplePoints.length} rendered points`}</div>
          <div>{config.layerMode}</div>
        </div>
      </div>

      <div className="relative flex-1 overflow-hidden station-canvas">
        <svg
          className="absolute inset-0 h-full w-full"
          viewBox="0 0 100 100"
          preserveAspectRatio={mapLayerActive ? 'xMidYMid meet' : 'none'}
          aria-label={mapLayerActive ? '地图：正 x 向右，正 y 向上' : '雷达扫描'}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={clearGesture}
          style={{ cursor: selectionEnabled ? 'crosshair' : 'default', touchAction: selectionEnabled ? 'none' : 'pan-y' }}
        >
          {mapLayerActive && projection ? (
            <>
              {worldGridLines.map((line, index) => (
                <line key={`grid-${index}`} x1={line.x1} y1={line.y1} x2={line.x2} y2={line.y2} stroke="rgba(96,74,38,0.14)" strokeWidth="0.15" />
              ))}

              {mapCells.map((cell) => (
                <rect key={cell.key} x={cell.left - cell.size / 2} y={cell.top - cell.size / 2} width={cell.size} height={cell.size} fill={cell.fill}
                  transform={`rotate(${mapHeadingDegrees(navigation.map.originYaw)} ${cell.left} ${cell.top})`} />
              ))}

              <polygon points={boundaryPoints.map((point) => `${point.left},${point.top}`).join(' ')} fill="none" stroke="rgba(96,74,38,0.35)" strokeWidth="0.2" />
              {pathPoints.length > 1 && <polyline data-testid="navigation-path" aria-label="后端路径报告"
                points={pathPoints.map((point) => `${point.left},${point.top}`).join(' ')} fill="none" stroke="rgba(58,124,102,0.95)" strokeWidth="0.65" strokeLinejoin="round" />}

              {navigation.localization.ready ? null : (
                <text x="50" y="8" textAnchor="middle" fontSize="2.6" fill="rgba(120,94,52,0.85)">
                  waiting /amcl_pose - scan anchored to odom pose
                </text>
              )}

              {mapScanPoints.map((point, index) => {
                const danger = point.rangeMeters <= 0.8
                return (
                  <circle
                    key={`mapscan-${point.angleRad}-${index}`}
                    cx={point.left}
                    cy={point.top}
                    r="0.34"
                    fill={danger ? 'rgba(173,48,35,0.9)' : 'rgba(196,132,34,0.92)'}
                    onMouseEnter={() => onPointSelect(point)}
                    onMouseLeave={() => onPointSelect(null)}
                  />
                )
              })}

              {poseViewport ? (
                <g data-testid="map-robot-pose" transform={`translate(${poseViewport.left} ${poseViewport.top}) rotate(${mapHeadingDegrees(poseYaw)})`}>
                  <circle r="1.5" fill="rgba(67,50,24,0.92)" stroke="rgba(196,132,34,0.9)" strokeWidth="0.25" />
                  <polygon points="2.4,0 -1.5,-1.1 -1.5,1.1" fill="rgba(196,132,34,0.95)" />
                </g>
              ) : null}

              {draftViewport && displayedDraft ? (
                <g data-testid="map-pose-draft" transform={`translate(${draftViewport.left} ${draftViewport.top}) rotate(${mapHeadingDegrees(displayedDraft.yaw)})`}>
                  <circle r="2" fill="none" stroke={mapMode === 'initial-pose' ? 'rgba(63,98,145,0.95)' : 'rgba(58,124,102,0.95)'} strokeWidth="0.35" strokeDasharray="0.8 0.5" />
                  <path d="M-1 0 H4 M2 -1.4 L4 0 L2 1.4" fill="none" stroke={mapMode === 'initial-pose' ? 'rgba(63,98,145,0.95)' : 'rgba(58,124,102,0.95)'} strokeWidth="0.45" />
                </g>
              ) : (
                <text x="50" y="95" textAnchor="middle" fontSize="2.4" fill="rgba(120,94,52,0.7)">
                  {mapMode === 'observe' ? '观察模式 · 仅查看地图' : '点选位置和方向 · 点击发送后才发布'}
                </text>
              )}
            </>
          ) : (
            <>
              {config.showGrid ? (
                <>
                  {[14, 24, 34, 44].map((radius) => (
                    <circle
                      key={radius}
                      cx="50"
                      cy="50"
                      r={radius}
                      fill="none"
                      stroke="rgba(96,74,38,0.18)"
                      strokeDasharray={radius === 44 ? '0' : '0.8 1.2'}
                      strokeWidth="0.25"
                    />
                  ))}
                  <line x1="50" y1="4" x2="50" y2="96" stroke="rgba(96,74,38,0.14)" strokeWidth="0.2" />
                  <line x1="4" y1="50" x2="96" y2="50" stroke="rgba(96,74,38,0.14)" strokeWidth="0.2" />
                </>
              ) : null}

              {config.showSweep ? (
                <g style={{ transformOrigin: '50% 50%', animation: 'station-scan 9s linear infinite' }}>
                  <path d="M50 50 L92 50 A42 42 0 0 1 80 20 Z" fill="rgba(197,142,53,0.14)" />
                  <line x1="50" y1="50" x2="92" y2="50" stroke="rgba(197,142,53,0.42)" strokeWidth="0.4" />
                </g>
              ) : null}

              {ghostFrames.map((frame, index) =>
                frame.samplePoints.map((point, pointIndex) => {
                  const ghost = mapPoint(point, extent / config.zoom)
                  return (
                    <circle
                      key={`${frame.lastUpdate}-${pointIndex}`}
                      cx={ghost.left}
                      cy={ghost.top}
                      r="0.38"
                      fill="rgba(189,137,55,0.16)"
                      opacity={Math.max(0.12, 0.42 - index * 0.08)}
                    />
                  )
                }),
              )}

              {config.layerMode !== 'scan' ? (
                <g opacity="0.6">
                  <rect x="19" y="18" width="62" height="64" rx="5" fill="none" stroke="rgba(74,58,34,0.16)" strokeDasharray="1.4 1.4" />
                  <path d="M22 70 C 35 64, 43 57, 54 51 S 70 38, 78 28" fill="none" stroke="rgba(75,122,102,0.28)" strokeWidth="0.7" />
                </g>
              ) : null}

              {currentPoints.map((point, index) => {
                const highlighted = selectedPoint?.angleRad === point.angleRad && selectedPoint?.rangeMeters === point.rangeMeters
                const danger = point.rangeMeters <= 0.8
                return (
                  <g key={`${point.angleRad}-${index}`}>
                    {danger ? <circle cx={point.left} cy={point.top} r="1.3" fill="rgba(173,48,35,0.16)" /> : null}
                    <circle
                      cx={point.left}
                      cy={point.top}
                      r={highlighted ? '0.92' : '0.56'}
                      fill={danger ? 'rgba(173,48,35,0.96)' : 'rgba(196,132,34,0.96)'}
                      onMouseEnter={() => onPointSelect(point)}
                      onMouseLeave={() => onPointSelect(null)}
                      style={{ cursor: 'crosshair' }}
                    />
                  </g>
                )
              })}
            </>
          )}
        </svg>

        <div className="pointer-events-none absolute inset-x-0 top-4 flex flex-wrap items-start justify-between gap-2 px-3 md:px-5">
          <div className="station-chip rounded-[18px] px-4 py-3 text-xs uppercase tracking-[0.18em] text-foreground/88">
            pose x {poseX.toFixed(2)} / y {poseY.toFixed(2)}
          </div>
          <div className="station-chip rounded-[18px] px-4 py-3 text-xs uppercase tracking-[0.18em] text-foreground/88">
            {mapLayerActive && projection
              ? `view ${projection.visibleExtent.toFixed(1)}m / res ${navigation.map.resolution.toFixed(2)}m`
              : `range ${scan.observedRange.toFixed(2)}m / max ${scan.rangeMax.toFixed(2)}m`}
          </div>
        </div>

        {mapLayerActive ? null : (
          <div className="absolute left-1/2 top-1/2 z-10 flex h-14 w-14 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-[rgba(66,50,24,0.25)] bg-[linear-gradient(180deg,rgba(67,50,24,0.94),rgba(38,28,14,0.98))] shadow-[0_10px_24px_rgba(74,55,22,0.22)]">
            <div
              className="h-0 w-0 border-b-[10px] border-l-[7px] border-r-[7px] border-b-[hsl(var(--accent-foreground))] border-l-transparent border-r-transparent"
              style={{ transform: `rotate(${robotState.odom.yaw}rad)` }}
            />
          </div>
        )}

        <div className="pointer-events-none absolute bottom-5 left-3 right-3 grid grid-cols-3 gap-2 md:left-5 md:right-5 md:gap-3">
          <Overlay title="Pure Scan" value="laser samples only" active={config.layerMode === 'scan'} />
          <Overlay title="Scan + Pose" value="footprint and heading" active={config.layerMode === 'scan+pose'} />
          <Overlay
            title="Scan + Map"
            value={mapLayerActive ? pathTelemetryLive ? 'live /map + operator draft' : 'map preview + operator draft' : navigation.map.ready ? 'switch layer to scan+map' : 'waiting /map'}
            active={config.layerMode === 'scan+map'}
          />
        </div>
      </div>
    </div>
  )
}

function Overlay({
  active,
  title,
  value,
}: {
  active: boolean
  title: string
  value: string
}) {
  return (
    <div className="station-chip min-w-0 rounded-[18px] px-2 py-3 md:px-4">
      <div className="mb-1 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">{title}</div>
      <div className={active ? 'text-sm font-semibold text-foreground/96' : 'text-sm text-muted-foreground'}>{value}</div>
    </div>
  )
}
