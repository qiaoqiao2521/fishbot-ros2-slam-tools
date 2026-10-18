import { sceneScanPoints } from '@/lib/scene-contract'
import { parseScenePcd } from '@/lib/scene-loaders'
import type { SceneWorkerReply, SceneWorkerRequest } from '@/lib/scene-frame-pipeline'

const worker = self as unknown as { onmessage: ((event: MessageEvent<SceneWorkerRequest>) => void) | null; postMessage: (value: SceneWorkerReply, transfer?: Transferable[]) => void }
worker.onmessage = ({ data }) => {
  const { generation, requestId, input } = data
  try {
    const points = input.kind === 'scan' ? sceneScanPoints(input.scan) : parseScenePcd(input.bytes)
    worker.postMessage({ generation, requestId, points }, [points.positions.buffer as ArrayBuffer, ...(points.colors ? [points.colors.buffer as ArrayBuffer] : [])])
  } catch (error) {
    worker.postMessage({ generation, requestId, error: error instanceof Error ? error.message : '三维数据解析失败。' })
  }
}
