import { Bot, Layers3, Map, Radar } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { getMapDataSections, getMapShellPresentation, getNavigationSlots } from '@/lib/station-runtime'
import { useStationStore } from '@/store/station-store'
import type { LaserScanPointSnapshot, MapSnapshot } from '@/types/station'

type ProjectedPoint = { id: string; left: number; top: number }

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

export function MapNavShell({ onOpen }: { onOpen?: () => void }) {
  const { connection, perception, robotState, navigation, usingFallbackData } = useStationStore()
  const map = getMapShellPresentation(connection, robotState, navigation, usingFallbackData)
  const mapSections = getMapDataSections(connection, navigation, usingFallbackData)
  const slots = getNavigationSlots(connection, navigation, usingFallbackData)
  const pose = getDisplayPose(connection.mode, robotState.odom, navigation.localization)
  const hasGrid = navigation.map.ready && navigation.map.sampledCells.length > 0
  const scanOverlay = hasGrid
    ? projectScanToMap(perception.scan.samplePoints, pose, navigation.map)
    : projectScanToCanvas(perception.scan.samplePoints, perception.scan.observedRange || perception.scan.rangeMax || 4)
  const cellWidth = hasGrid ? Math.max((navigation.map.sampleStride / navigation.map.width) * 100, 0.24) : 0
  const cellHeight = hasGrid ? Math.max((navigation.map.sampleStride / navigation.map.height) * 100, 0.24) : 0
  const sensors = [
    { title: '激光雷达', value: perception.scan.ready ? `${scanOverlay.length} / ${perception.scan.beamCount} 点` : '等待数据', detail: perception.scan.ready ? `坐标系 ${perception.scan.frameId} · 最远 ${perception.scan.observedRange.toFixed(2)} m` : perception.scan.statusMessage },
    { title: '超声测距', value: perception.ultrasonic.ready ? `${perception.ultrasonic.distanceMeters.toFixed(2)} m` : '等待数据', detail: perception.ultrasonic.statusMessage },
    { title: '红外测距', value: perception.infrared.ready ? `${perception.infrared.distanceMeters.toFixed(2)} m` : '等待数据', detail: perception.infrared.statusMessage },
  ]

  return (
    <section className="station-section" aria-label="地图观测">
      <div className="station-section-heading"><div><h2><Map size={17} />地图观测</h2><p>{hasGrid ? '占用栅格与激光叠层' : '等待地图 · 当前显示雷达坐标预览'}</p></div>{onOpen ? <Button size="sm" variant="outline" onClick={onOpen} className="gap-1.5"><Radar size={14} />打开工作台</Button> : <Badge variant={map.tone}>{map.label}</Badge>}</div>
      <div className="station-map-content">
        <div>
          <div className="station-map-stage station-canvas">
            <div className="station-map-axis-x" /><div className="station-map-axis-y" />
            {hasGrid && navigation.map.sampledCells.map((cell, index) => (
              <div key={`${cell.x}-${cell.y}-${cell.occupancy}-${index}`} className="absolute" style={{
                backgroundColor: occupancyColor(cell.occupancy), height: `${cellHeight}%`, width: `${cellWidth}%`,
                left: `${(cell.x / navigation.map.width) * 100}%`, top: `${100 - (((cell.y + navigation.map.sampleStride) / navigation.map.height) * 100)}%`,
              }} />
            ))}
            {scanOverlay.map((point) => <div key={point.id} className="absolute z-[3] h-1 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-emerald-600" style={{ left: `${point.left}%`, top: `${point.top}%` }} />)}
            <div className="station-map-robot" style={{ left: `${map.robotPercentX}%`, top: `${map.robotPercentY}%` }}><div style={{ transform: `rotate(${pose.yaw}rad)` }}><Bot size={17} color="white" /></div><span>x {pose.x.toFixed(2)} / y {pose.y.toFixed(2)}</span></div>
            <div className="station-map-note">{hasGrid ? `${navigation.map.width} × ${navigation.map.height} · ${navigation.map.resolution.toFixed(2)} m / 格` : '暂无占用地图'}<br /><span>{map.label}</span></div>
          </div>
          <div className="station-map-legend"><span><i style={{ background: '#2563eb' }} />机器人位置参考</span><span><i style={{ background: '#059669' }} />激光点</span><span><i style={{ background: '#253e5c' }} />占用栅格</span></div>
        </div>
        <div className="station-map-sensors">{sensors.map((sensor) => <div className="station-metric" key={sensor.title}><span>{sensor.title}</span><strong className="station-value">{sensor.value}</strong><p>{sensor.detail}</p></div>)}</div>
      </div>
      <p className="station-map-caption">{map.caption}</p>
      <details className="station-details"><summary><Layers3 size={12} className="mr-1 inline" />地图来源与导航状态</summary><p>绿色点与占用墙体明显错位时，请先核对定位。当前位置来源、坐标变换与动作状态见下方报告。</p><div className="metric-grid">{mapSections.map((section) => <div className="station-metric" key={section.title}><div className="flex items-center justify-between gap-2"><strong>{section.title}</strong><Badge variant={section.tone}>{section.status}</Badge></div><p>{section.summary}</p><p>{section.detail}</p>{section.hooks.map((hook) => <p key={hook}>{hook}</p>)}</div>)}</div><div className="mt-3 metric-grid">{slots.slice(0, 3).map((slot) => <div className="station-metric" key={slot.title}><div className="flex items-center justify-between gap-2"><strong>{slot.title}</strong><Badge variant={slot.tone}>{slot.status}</Badge></div><p>{slot.description}</p></div>)}</div></details>
    </section>
  )
}

function getDisplayPose(
  mode: string,
  odom: { x: number; y: number; yaw: number },
  localization: { ready: boolean; x: number; y: number; yaw: number },
) {
  if (mode === 'live' && localization.ready) {
    return {
      x: localization.x,
      y: localization.y,
      yaw: localization.yaw,
    }
  }

  return odom
}

function projectScanToMap(
  points: LaserScanPointSnapshot[],
  pose: { x: number; y: number; yaw: number },
  map: MapSnapshot,
): ProjectedPoint[] {
  const cos = Math.cos(pose.yaw)
  const sin = Math.sin(pose.yaw)

  return points.flatMap((point, index) => {
    const worldX = pose.x + (point.x * cos) - (point.y * sin)
    const worldY = pose.y + (point.x * sin) + (point.y * cos)
    const projected = projectWorldToMap(worldX, worldY, map)
    return projected ? [{ id: `${point.angleRad}-${index}`, ...projected }] : []
  })
}

function projectScanToCanvas(points: LaserScanPointSnapshot[], extent: number): ProjectedPoint[] {
  const safeExtent = Math.max(extent, 1)
  return points.map((point, index) => ({
    id: `${point.angleRad}-${index}`,
    left: clamp(50 + (point.y / safeExtent) * 38, 2, 98),
    top: clamp(50 - (point.x / safeExtent) * 38, 2, 98),
  }))
}

function projectWorldToMap(worldX: number, worldY: number, map: MapSnapshot) {
  if (map.width <= 0 || map.height <= 0 || map.resolution <= 0) {
    return null
  }

  const left = ((worldX - map.originX) / (map.width * map.resolution)) * 100
  const top = 100 - (((worldY - map.originY) / (map.height * map.resolution)) * 100)

  if (!Number.isFinite(left) || !Number.isFinite(top) || left < -4 || left > 104 || top < -4 || top > 104) {
    return null
  }

  return {
    left: clamp(left, 0, 100),
    top: clamp(top, 0, 100),
  }
}

function occupancyColor(occupancy: number) {
  if (occupancy >= 65) {
    return '#253e5c'
  }
  if (occupancy >= 20) {
    return '#9ab1ce'
  }
  return '#ffffffb8'
}
