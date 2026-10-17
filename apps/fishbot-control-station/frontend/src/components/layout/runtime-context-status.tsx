import { useSyncExternalStore } from 'react'

import { runtimeContextLabel, runtimeRegistry, type RuntimeService } from '@/lib/runtime-context'
import type { AppRoute } from '@/lib/app-route'
import './runtime-context-status.css'

const labels: Record<RuntimeService, string> = {
  station: '控制与雷达', mission: '地图巡逻', cooperation: '车臂协同', voice: '语音入口',
}
const routeService: Record<AppRoute, RuntimeService | null> = {
  dashboard: 'station', radar: 'station', simulation: 'mission', cooperation: 'cooperation', workbench: null,
}

export function RuntimeContextStatus({ route }: { route: AppRoute }) {
  const snapshot = useSyncExternalStore(runtimeRegistry.subscribe, runtimeRegistry.getSnapshot, runtimeRegistry.getSnapshot)
  const service = routeService[route]
  return <details className="runtime-context" data-runtime-service={service ?? 'overview'}>
    <summary>{service ? runtimeContextLabel(snapshot[service]) : '运行环境'}<span aria-hidden="true">⌄</span></summary>
    <div className="runtime-context-popover">
      <strong>各服务的运行身份</strong>
      <p>身份来自服务自身；连接可用不表示任务已完成。各环境分别核对。</p>
      {(Object.keys(labels) as RuntimeService[]).map((key) => {
        const entry = snapshot[key]
        return <section key={key} data-runtime-status={entry.status}>
          <div><b>{labels[key]}</b><span>{runtimeContextLabel(entry)}</span></div>
          {entry.error && <p>{entry.error}</p>}
          {entry.descriptor && <>
            <small>实例 {entry.descriptor.instance_id}</small>
            {entry.descriptor.episode_id && <small>回合 {entry.descriptor.episode_id}</small>}
            <small>{entry.descriptor.capabilities.map((cap) => `${cap.id} · ${{ native_action: '原生动作', topic_publish: '话题发布', delegated: '委托任务', read_only: '只读' }[cap.submission]}`).join('；')}</small>
          </>}
        </section>
      })}
    </div>
  </details>
}
