import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent, MouseEvent } from 'react'

import {
  mapToWorld, worldToMap,
  type Point, type Pose, type SimulationMap, type SimulationState,
} from '@/lib/simulation'

export function SimulationMapView({ map, state, points, editable, onSelect }: {
  map: SimulationMap
  state: SimulationState | null
  points: Pose[]
  editable: boolean
  onSelect: (point: Point) => void
}) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const svg = useRef<SVGSVGElement>(null)
  const [cursor, setCursor] = useState<Point>({ x: 0, y: 0 })
  const [focused, setFocused] = useState(false)
  const [trace, setTrace] = useState<Point[]>([])
  const robot = state?.truth ?? state?.pose

  useEffect(() => {
    const context = canvas.current?.getContext('2d')
    if (!context) return
    const image = context.createImageData(map.width, map.height)
    for (let y = 0; y < map.height; y += 1) {
      for (let x = 0; x < map.width; x += 1) {
        const value = map.data[y * map.width + x]
        const color = value < 0 ? [201, 201, 194] : value >= 50 ? [69, 72, 69] : [248, 248, 241]
        const offset = ((map.height - 1 - y) * map.width + x) * 4
        image.data.set([...color, 255], offset)
      }
    }
    context.putImageData(image, 0, 0)
  }, [map])

  useEffect(() => {
    if (!state?.truth) return
    const { x, y } = state.truth
    setTrace((current) => {
      const last = current.at(-1)
      if (last && Math.hypot(last.x - x, last.y - y) < 0.025) return current
      return [...current.slice(-1200), { x, y }]
    })
  }, [state?.truth])

  function select(event: MouseEvent<SVGSVGElement>) {
    if (!editable) return
    const rect = event.currentTarget.getBoundingClientRect()
    const position = mapToWorld({
      x: (event.clientX - rect.left) / rect.width * map.width,
      y: (event.clientY - rect.top) / rect.height * map.height,
    }, map)
    setCursor(position)
    onSelect(position)
  }

  function keySelect(event: KeyboardEvent<SVGSVGElement>) {
    if (!editable) return
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      onSelect(cursor)
    } else if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) {
      event.preventDefault()
      const pixel = worldToMap(cursor, map)
      const delta = 0.1 / map.resolution
      const next = {
        x: Math.max(0, Math.min(map.width, pixel.x + (event.key === 'ArrowRight' ? delta : event.key === 'ArrowLeft' ? -delta : 0))),
        y: Math.max(0, Math.min(map.height, pixel.y + (event.key === 'ArrowDown' ? delta : event.key === 'ArrowUp' ? -delta : 0))),
      }
      setCursor(mapToWorld(next, map))
    }
  }

  function polyline(values: Point[]) {
    return values.map((value) => { const p = worldToMap(value, map); return `${p.x},${p.y}` }).join(' ')
  }

  const unit = 1 / map.resolution
  const home = state?.home ? worldToMap(state.home, map) : null
  const obstacle = state?.obstacle
  const obstaclePosition = obstacle && typeof obstacle.x === 'number' && Number.isFinite(obstacle.x)
    && typeof obstacle.y === 'number' && Number.isFinite(obstacle.y)
    ? worldToMap({ x: obstacle.x, y: obstacle.y }, map) : null
  const cursorPixel = worldToMap(cursor, map)

  return (
    <div className="simulation-map-frame" style={{ aspectRatio: `${map.width} / ${map.height}` }}>
      <canvas ref={canvas} width={map.width} height={map.height} aria-hidden="true" />
      <svg
        ref={svg}
        viewBox={`0 0 ${map.width} ${map.height}`}
        aria-label="巡逻地图，使用方向键移动选点十字，按回车添加巡逻点"
        role="application"
        tabIndex={editable ? 0 : -1}
        className={editable ? 'simulation-map-editable' : ''}
        onClick={select}
        onKeyDown={keySelect}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
      >
        <defs>
          <pattern id="simulation-grid" width={unit} height={unit} patternUnits="userSpaceOnUse">
            <path d={`M ${unit} 0 L 0 0 0 ${unit}`} fill="none" stroke="#b5b9b0" strokeOpacity=".28" strokeWidth=".15" />
          </pattern>
        </defs>
        <rect width={map.width} height={map.height} fill="url(#simulation-grid)" pointerEvents="none" />
        {trace.length > 1 && <polyline points={polyline(trace)} fill="none" stroke="#297fb1" strokeOpacity=".42" strokeWidth=".7" strokeDasharray="1.5 1.5" />}
        {state && state.path.length > 1 && <polyline points={polyline(state.path)} fill="none" stroke="#577636" strokeWidth="1.1" strokeLinecap="round" strokeLinejoin="round" />}
        {points.length > 1 && <polyline points={polyline(points)} fill="none" stroke="#a77637" strokeOpacity=".6" strokeDasharray="2 2" strokeWidth=".5" />}
        {home && <g transform={`translate(${home.x} ${home.y})`}>
          <path d="M-2 1V-1L0-3L2-1V1Z" fill="#faf8eb" stroke="#77694d" strokeWidth=".45" />
          <title>本轮仿真起点</title>
        </g>}
        {obstacle && obstaclePosition && <g transform={`translate(${obstaclePosition.x} ${obstaclePosition.y})`}>
          <rect x={-obstacle.size * unit / 2} y={-obstacle.size * unit / 2} width={obstacle.size * unit} height={obstacle.size * unit}
            rx=".5" fill={obstacle.state === 'parked' ? '#a6aaa2' : '#ce731d'} stroke="#794518" strokeWidth=".5" />
          <title>{obstacle.state === 'parked' ? '已退回的障碍箱' : '真实移动障碍箱'}</title>
        </g>}
        {points.map((point, index) => {
          const pixel = worldToMap(point, map)
          const active = state?.mission.status === 'running' && index === state.mission.current_index
          return <g key={`${index}-${point.x}-${point.y}`} transform={`translate(${pixel.x} ${pixel.y})`}>
            <circle r={active ? 3.4 : 2.8} fill={active ? '#986423' : '#fffaf0'} stroke="#95662a" strokeWidth=".7" />
            <text textAnchor="middle" dominantBaseline="central" fontSize="3.5" fontWeight="700" fill={active ? '#ffffff' : '#684e2b'}>{index + 1}</text>
            <title>{`巡逻点 ${index + 1}：${point.x.toFixed(2)}，${point.y.toFixed(2)} 米`}</title>
          </g>
        })}
        {state?.pose && state?.truth && <g transform={poseTransform(state.pose, map)}>
          <circle r={0.16 * unit} fill="none" stroke="#527635" strokeWidth=".4" strokeDasharray="1 1" />
          <title>导航定位</title>
        </g>}
        {robot && <g transform={poseTransform(robot, map)}>
          <circle r={0.13 * unit + 1.2} fill="#ffffff" opacity=".82" />
          <rect x={-0.08 * unit} y={-0.14 * unit} width={0.16 * unit} height={0.28 * unit} rx=".5" fill="#1d5d83" />
          <circle r={0.13 * unit} fill="#2780b2" stroke="#154d70" strokeWidth=".45" />
          <path d={`M${0.20 * unit} 0 L${0.04 * unit} ${-0.065 * unit} L${0.04 * unit} ${0.065 * unit}Z`} fill="#f5fbff" stroke="#154d70" strokeWidth=".25" />
          <title>小鱼位置，尖端为车头方向</title>
        </g>}
        {focused && editable && <g transform={`translate(${cursorPixel.x} ${cursorPixel.y})`} stroke="#713f9f" strokeWidth=".6">
          <path d="M-4 0H4M0-4V4" />
          <circle r="2.4" fill="none" />
        </g>}
      </svg>
    </div>
  )
}

function poseTransform(pose: Pose, map: SimulationMap) {
  const pixel = worldToMap(pose, map)
  return `translate(${pixel.x} ${pixel.y}) rotate(${-(pose.yaw - map.origin[2]) * 180 / Math.PI})`
}
