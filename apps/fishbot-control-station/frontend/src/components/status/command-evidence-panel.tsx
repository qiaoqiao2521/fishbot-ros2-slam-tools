import type { CommandEvidence } from '@/lib/command-evidence'
import './command-evidence-panel.css'

export function CommandEvidencePanel({ evidence }: { evidence: CommandEvidence }) {
  return <details className="command-evidence" data-command-owner={evidence.owner}>
    <summary>回执与验收明细</summary>
    <dl>{([
      ['提交回执', evidence.submission], ['原生执行', evidence.execution],
      ['清理与停稳', evidence.cleanup], ['独立物理评分', evidence.physical],
    ] as const).map(([name, layer]) => <div key={name} data-evidence-state={layer.state}>
      <dt>{name}</dt><dd><strong>{layer.label}</strong><span>{layer.detail}</span></dd>
    </div>)}</dl>
  </details>
}
