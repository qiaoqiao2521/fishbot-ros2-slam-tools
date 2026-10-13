import { Activity, Radio, Radar, Waves } from 'lucide-react'

import { useStationStore } from '@/store/station-store'

export function HeaderStatusBar() {
  const { connection, usingFallbackData } = useStationStore()
  const fallback = usingFallbackData || connection.mode === 'fallback'
  const offline = connection.mode === 'offline'
  const source = fallback ? '本地兜底快照' : offline ? '离线开发模式' : 'ROS 话题链路'
  const detail = fallback ? '等待后端数据接管' : offline ? '模拟遥测' : '最近桥接报告 · 不判定实体在线'
  const bridge = (connected: boolean) => fallback ? '示例' : offline ? '绕过' : connected ? '已连接' : '未连接'
  const feed = (online: boolean) => fallback ? '示例' : offline ? '模拟' : online ? '有数据' : '暂无数据'
  const tone = (ready: boolean, telemetry = false) => fallback ? 'warning' : offline ? 'neutral' : ready ? 'success' : telemetry ? 'warning' : 'danger'
  const items = [
    { label: '控制连接', icon: Radio, value: bridge(connection.controlBridge.connected), tone: tone(connection.controlBridge.connected) },
    { label: '控制数据', icon: Activity, value: feed(connection.controlBridge.telemetryOnline), tone: tone(connection.controlBridge.telemetryOnline, true) },
    { label: '雷达连接', icon: Radar, value: bridge(connection.laserBridge.connected), tone: tone(connection.laserBridge.connected) },
    { label: '雷达数据', icon: Waves, value: feed(connection.laserBridge.telemetryOnline), tone: tone(connection.laserBridge.telemetryOnline, true) },
  ]
  return (
    <section className="station-link-strip" aria-label="数据来源与连接状态">
      <div className="station-source"><span className={`station-tone-${fallback ? 'warning' : 'neutral'}`}>{source}</span><small>{detail}</small></div>
      {items.map(({ label, icon: Icon, value, tone: statusTone }) => (
        <div className="station-link-item" key={label}><Icon size={14} /><span>{label}</span><strong className={`station-link-value station-tone-${statusTone}`}><i className="station-dot" />{value}</strong></div>
      ))}
    </section>
  )
}
