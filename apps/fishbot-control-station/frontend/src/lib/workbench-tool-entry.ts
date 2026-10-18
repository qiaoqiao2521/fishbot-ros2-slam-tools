import type { ServiceId } from './workbench-catalog'

/** Current server configuration, separate from the immutable acceptance catalog. */
export function toolEntry(id: ServiceId, serialized: unknown = import.meta.env.VITE_FISHBOT_TOOL_PORTS): string | null {
  if (typeof serialized !== 'string') return null
  try {
    const ports = JSON.parse(serialized), port = ports[id]
    if (!Number.isInteger(port) || port < 1024 || port > 65535) return null
    return `http://127.0.0.1:${port}/`
  } catch { return null }
}
