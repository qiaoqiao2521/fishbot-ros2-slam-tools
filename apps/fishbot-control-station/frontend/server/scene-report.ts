import { readFile } from 'node:fs/promises'
import type { IncomingMessage, ServerResponse } from 'node:http'

/** Serve one operator-selected report. The browser cannot choose a filesystem path. */
export function sceneReportMiddleware(file: string, route = '/scene-validation/report') {
  return async (request: IncomingMessage, response: ServerResponse, next: () => void) => {
    if (request.url?.split('?')[0] !== route) return next()
    response.setHeader('Content-Type', 'application/json; charset=utf-8')
    response.setHeader('Cache-Control', 'no-store')
    if (request.method !== 'GET') {
      response.statusCode = 405
      response.setHeader('Allow', 'GET')
      response.end(JSON.stringify({ message: '报告入口只提供读取。' }))
      return
    }
    try {
      const text = await readFile(file, 'utf8')
      JSON.parse(text) // Validate syntax only; editable metadata is handled by the panel.
      response.end(text)
    } catch (error) {
      response.statusCode = (error as NodeJS.ErrnoException).code === 'ENOENT' ? 404 : 422
      response.end(JSON.stringify({ message: response.statusCode === 404
        ? '尚无场景验证报告。运行验证后重读，或导入本地JSON。'
        : '报告暂不可读取。修正JSON后可直接重读，无需重跑仿真。' }))
    }
  }
}
