import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Bot, Crosshair, Keyboard, Layers3, Map, Radar, Sparkles } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardTitle } from '@/components/ui/card'
import { getMapDataSections, getMapShellPresentation, getNavigationSlots } from '@/lib/station-runtime'
import { useStationStore } from '@/store/station-store'
import type { LaserScanPointSnapshot, MapSnapshot } from '@/types/station'

type ProjectedPoint = {
  id: string
  left: number
  top: number
}

export function MapNavShell() {
  const { activeDirection, connection, perception, robotState, navigation, usingFallbackData } = useStationStore()
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

  return (
    <Card>
      <div className="panel-header">
        <div>
          <div className="station-kicker mb-2">real map / scan overlay / keyboard drive</div>
          <CardTitle>Mapping Workbench</CardTitle>
          <CardDescription>
            这里优先显示真实 `/map` 栅格和 `/scan` 点云叠加，用来判断新图到底贴不贴实际环境。
          </CardDescription>
        </div>
        <Badge variant={map.tone}>{map.label}</Badge>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.18fr_0.82fr]">
        <div className="station-well rounded-[28px] p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-foreground/90">
              <Map className="h-4 w-4 text-accent" />
              {hasGrid ? 'live occupancy grid' : 'scan-only map preview'}
            </div>
            <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">
              {navigation.map.ready
                ? `${navigation.map.width}x${navigation.map.height} / ${navigation.map.resolution.toFixed(2)}m`
                : map.headingLabel}
            </div>
          </div>

          <div className="station-canvas relative min-h-[360px] overflow-hidden rounded-[24px] border border-border/80 bg-[hsl(42_28%_92%)]">
            <div className="absolute inset-0 bg-[linear-gradient(rgba(74,55,25,0.055)_1px,transparent_1px),linear-gradient(90deg,rgba(74,55,25,0.055)_1px,transparent_1px)] bg-[size:24px_24px]" />
            <div className="absolute inset-3 rounded-[20px] border border-dashed border-[rgba(74,55,25,0.18)]" />

            {hasGrid ? (
              <div className="absolute inset-0">
                {navigation.map.sampledCells.map((cell, index) => (
                  <div
                    key={`${cell.x}-${cell.y}-${cell.occupancy}-${index}`}
                    className="absolute"
                    style={{
                      backgroundColor: occupancyColor(cell.occupancy),
                      height: `${cellHeight}%`,
                      left: `${(cell.x / navigation.map.width) * 100}%`,
                      top: `${100 - (((cell.y + navigation.map.sampleStride) / navigation.map.height) * 100)}%`,
                      width: `${cellWidth}%`,
                    }}
                  />
                ))}
              </div>
            ) : (
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgba(196,142,53,0.14),transparent_32%)]" />
            )}

            <div className="absolute left-1/2 top-1/2 h-px w-full -translate-y-1/2 bg-[rgba(98,73,37,0.15)]" />
            <div className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-[rgba(98,73,37,0.15)]" />

            {scanOverlay.map((point) => (
              <div
                key={point.id}
                className="absolute z-[3] h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[rgba(15,105,87,0.82)] shadow-[0_0_0_3px_rgba(15,105,87,0.1)]"
                style={{ left: `${point.left}%`, top: `${point.top}%` }}
              />
            ))}

            <div
              className="absolute z-10 flex -translate-x-1/2 -translate-y-1/2 items-center gap-2"
              style={{ left: `${map.robotPercentX}%`, top: `${map.robotPercentY}%` }}
            >
              <div
                className="flex h-12 w-12 items-center justify-center rounded-full border border-[rgba(66,50,24,0.2)] bg-[linear-gradient(180deg,rgba(67,50,24,0.92),rgba(38,28,14,0.96))] shadow-[0_10px_22px_rgba(74,55,22,0.22)]"
                style={{ transform: `rotate(${pose.yaw}rad)` }}
              >
                <Bot className="h-5 w-5 text-[hsl(var(--accent-foreground))]" />
              </div>
              <div className="station-chip station-readout rounded-2xl px-3 py-2 text-xs uppercase tracking-[0.18em] text-foreground/82">
                x {pose.x.toFixed(2)} / y {pose.y.toFixed(2)}
              </div>
            </div>

            <div className="absolute bottom-4 left-4 right-4 grid gap-3 md:grid-cols-3">
              <OverlayChip icon={Crosshair} label="pose source" value={map.label} />
              <OverlayChip icon={Radar} label="scan overlay" value={perception.scan.ready ? `${scanOverlay.length}/${perception.scan.beamCount}` : 'waiting /scan'} />
              <OverlayChip icon={Keyboard} label="keyboard drive" value={activeDirection ? activeDirection : 'arrow keys armed'} />
            </div>

            <div className="absolute right-4 top-4 max-w-[260px] rounded-[20px] border border-border/70 bg-[rgba(255,249,238,0.9)] px-3 py-3 shadow-[0_10px_24px_rgba(89,67,31,0.1)]">
              <div className="station-kicker mb-2">map honesty check</div>
              <div className="station-readout text-sm font-semibold text-foreground/90">
                {hasGrid ? `${navigation.map.sampledCells.length} sampled map cells` : 'no occupancy cells yet'}
              </div>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                绿色点是当前 `/scan`，深色块是占用墙体。如果绿色点和深色墙体明显错位，这张图就不适合导航。
              </p>
            </div>
          </div>

          <p className="mt-4 text-sm leading-6 text-muted-foreground">{map.caption}</p>

          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <Keycap icon={ArrowUp} label="Forward" value="↑ / W" active={activeDirection === 'forward'} />
            <Keycap icon={ArrowLeft} label="Left" value="← / A" active={activeDirection === 'left'} />
            <Keycap icon={ArrowRight} label="Right" value="→ / D" active={activeDirection === 'right'} />
            <Keycap icon={ArrowDown} label="Backward" value="↓ / S" active={activeDirection === 'backward'} />
          </div>

          <div className="station-chip mt-4 rounded-[24px] p-4">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-foreground/90">
                <Layers3 className="h-4 w-4 text-accent" />
                map state matrix
              </div>
              <div className="text-xs uppercase tracking-[0.16em] text-muted-foreground">source / tf / localization / overlays</div>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              {mapSections.map((section) => (
                <div key={section.title} className="station-well rounded-[20px] p-4">
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <div className="text-sm font-semibold uppercase tracking-[0.16em] text-foreground/90">{section.title}</div>
                    <Badge variant={section.tone}>{section.status}</Badge>
                  </div>
                  <p className="text-sm leading-6 text-muted-foreground">{section.summary}</p>
                  <p className="mt-3 text-sm leading-6 text-foreground/78">{section.detail}</p>
                  <div className="mt-4 grid gap-1 text-[11px] uppercase tracking-[0.16em] text-muted-foreground">
                    {section.hooks.map((hook) => (
                      <div key={hook}>{hook}</div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <SensorStatusCard
              title="Laser scan"
              value={
                perception.scan.ready
                  ? `${perception.scan.samplePoints.length} / ${perception.scan.beamCount} beams`
                  : 'waiting /scan'
              }
              detail={
                perception.scan.ready
                  ? `frame ${perception.scan.frameId} / max ${perception.scan.observedRange.toFixed(2)}m`
                  : perception.scan.statusMessage
              }
              tone={perception.scan.ready ? 'success' : 'warning'}
            />
            <SensorStatusCard
              title="Ultrasonic"
              value={
                perception.ultrasonic.ready
                  ? `${perception.ultrasonic.distanceMeters.toFixed(2)} m`
                  : 'waiting range'
              }
              detail={perception.ultrasonic.statusMessage}
              tone={perception.ultrasonic.blocked ? 'danger' : perception.ultrasonic.ready ? 'success' : 'warning'}
            />
            <SensorStatusCard
              title="Infrared"
              value={
                perception.infrared.ready
                  ? `${perception.infrared.distanceMeters.toFixed(2)} m`
                  : 'waiting range'
              }
              detail={perception.infrared.statusMessage}
              tone={perception.infrared.blocked ? 'danger' : perception.infrared.ready ? 'success' : 'warning'}
            />
          </div>
        </div>

        <div className="grid gap-4">
          {slots.slice(0, 3).map((slot) => (
            <div key={slot.title} className="station-well rounded-[24px] p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div className="text-sm font-semibold uppercase tracking-[0.16em] text-foreground/90">{slot.title}</div>
                <Badge variant={slot.tone}>{slot.status}</Badge>
              </div>
              <p className="text-sm leading-6 text-muted-foreground">{slot.description}</p>
            </div>
          ))}

          <div className="station-dashed rounded-[24px] p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-foreground/90">
              <Sparkles className="h-4 w-4 text-accent" />
              next data hooks
            </div>
            <div className="grid gap-3 text-sm leading-6 text-muted-foreground">
              <div>`/map`, `/tf`, `/tf_static`</div>
              <div>`/scan` overlaid in map frame</div>
              <div>`/amcl_pose`, costmap footprint, recovery state</div>
            </div>
          </div>
        </div>
      </div>
    </Card>
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
    return 'rgba(50, 39, 24, 0.88)'
  }
  if (occupancy >= 20) {
    return 'rgba(156, 119, 59, 0.32)'
  }
  return 'rgba(255, 251, 241, 0.72)'
}

function OverlayChip({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Crosshair
  label: string
  value: string
}) {
  return (
    <div className="station-chip rounded-2xl px-3 py-3">
      <div className="mb-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        <Icon className="h-4 w-4" />
        {label}
      </div>
      <div className="text-sm font-semibold text-foreground/90">{value}</div>
    </div>
  )
}

function Keycap({
  active,
  icon: Icon,
  label,
  value,
}: {
  icon: typeof ArrowUp
  label: string
  value: string
  active: boolean
}) {
  return (
    <div className={`station-chip rounded-[20px] p-3 ${active ? 'station-console-button-active' : ''}`}>
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.16em] text-foreground/90">
        <Icon className="h-4 w-4 text-accent" />
        {label}
      </div>
      <div className="station-readout text-sm font-semibold text-foreground/80">{value}</div>
    </div>
  )
}

function SensorStatusCard({
  detail,
  title,
  tone,
  value,
}: {
  title: string
  value: string
  detail: string
  tone: 'neutral' | 'success' | 'warning' | 'danger'
}) {
  return (
    <div className="station-chip rounded-[22px] p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="station-kicker">{title}</div>
        <Badge variant={tone}>{tone}</Badge>
      </div>
      <div className="station-readout text-base font-semibold text-foreground/92">{value}</div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">{detail}</p>
    </div>
  )
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}
