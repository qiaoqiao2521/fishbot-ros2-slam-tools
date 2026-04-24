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
  history,
  navigation,
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
}) {
  const extent = Math.max(scan.rangeMax || 1, scan.observedRange || 1, 4)
  const currentPoints = scan.samplePoints.map((point) => mapPoint(point, extent / config.zoom))
  const ghostFrames = config.showGhost ? history.slice(-5) : []
  const poseX = navigation.localization.ready ? navigation.localization.x : robotState.odom.x
  const poseY = navigation.localization.ready ? navigation.localization.y : robotState.odom.y

  return (
    <div className="glass-panel flex min-h-[720px] flex-col overflow-hidden rounded-[34px]">
      <div className="flex items-center justify-between gap-3 border-b border-border/70 px-6 py-4">
        <div>
          <div className="station-kicker mb-2">laser scan protagonist / inspection-ready viewport</div>
          <div className="station-readout text-xl font-semibold uppercase tracking-[0.12em] text-foreground/95">Radar Workbench</div>
        </div>
        <div className="text-right text-xs uppercase tracking-[0.18em] text-muted-foreground">
          <div>{scan.samplePoints.length} rendered points</div>
          <div>{config.layerMode}</div>
        </div>
      </div>

      <div className="relative flex-1 overflow-hidden station-canvas">
        <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
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
        </svg>

        <div className="absolute inset-x-0 top-4 flex items-start justify-between px-5">
          <div className="station-chip rounded-[18px] px-4 py-3 text-xs uppercase tracking-[0.18em] text-foreground/88">
            pose x {poseX.toFixed(2)} / y {poseY.toFixed(2)}
          </div>
          <div className="station-chip rounded-[18px] px-4 py-3 text-xs uppercase tracking-[0.18em] text-foreground/88">
            range {scan.observedRange.toFixed(2)}m / max {scan.rangeMax.toFixed(2)}m
          </div>
        </div>

        <div className="absolute left-1/2 top-1/2 z-10 flex h-14 w-14 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-[rgba(66,50,24,0.25)] bg-[linear-gradient(180deg,rgba(67,50,24,0.94),rgba(38,28,14,0.98))] shadow-[0_10px_24px_rgba(74,55,22,0.22)]">
          <div
            className="h-0 w-0 border-b-[10px] border-l-[7px] border-r-[7px] border-b-[hsl(var(--accent-foreground))] border-l-transparent border-r-transparent"
            style={{ transform: `rotate(${robotState.odom.yaw}rad)` }}
          />
        </div>

        <div className="absolute bottom-5 left-5 right-5 grid gap-3 md:grid-cols-3">
          <Overlay title="Pure Scan" value="laser samples only" active={config.layerMode === 'scan'} />
          <Overlay title="Scan + Pose" value="footprint and heading" active={config.layerMode === 'scan+pose'} />
          <Overlay title="Scan + Map" value="reserved map overlay" active={config.layerMode === 'scan+map'} />
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
  title: string
  value: string
  active: boolean
}) {
  return (
    <div className="station-chip rounded-[18px] px-4 py-3">
      <div className="mb-1 text-[11px] uppercase tracking-[0.18em] text-muted-foreground">{title}</div>
      <div className={active ? 'text-sm font-semibold text-foreground/96' : 'text-sm text-muted-foreground'}>{value}</div>
    </div>
  )
}
