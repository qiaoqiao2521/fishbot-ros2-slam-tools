import { useEffect, useState, useSyncExternalStore } from 'react'
import { observeEventSequence } from '@/lib/command-evidence'
import type { CooperationEvent } from '@/lib/cooperation'
import { runtimeRegistry } from '@/lib/runtime-context'

export function EventContinuity({ events, episodeId, taskId }: {
  events: CooperationEvent[]; episodeId: string | null; taskId: string | null
}) {
  const runtime = useSyncExternalStore(runtimeRegistry.subscribe, runtimeRegistry.getSnapshot, runtimeRegistry.getSnapshot).cooperation
  const instanceId = runtime.descriptor?.instance_id ?? 'legacy-unverified'
  const [evidence, setEvidence] = useState(() => observeEventSequence(null, { instanceId, episodeId, taskId }, events))
  useEffect(() => {
    setEvidence((previous) => observeEventSequence(previous.cursor, { instanceId, episodeId, taskId }, events))
  }, [instanceId, episodeId, taskId, events])
  return <p className="cooperation-action-help" data-event-continuity={evidence.hasGaps === null ? 'unknown' : evidence.hasGaps ? 'gap' : 'observed'}>
    {evidence.label}{!runtime.descriptor && '；旧接口未提供进程身份'}
    {evidence.gaps.length > 0 && `（缺少序号 ${evidence.gaps.map((gap) => gap.from === gap.to ? gap.from : `${gap.from}–${gap.to}`).join('、')}）`}
  </p>
}
