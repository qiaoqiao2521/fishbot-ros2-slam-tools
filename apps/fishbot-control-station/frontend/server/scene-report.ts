import { readFile } from 'node:fs/promises'
import type { IncomingMessage, ServerResponse } from 'node:http'
import path from 'node:path'
import send from 'send'

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

/** Serve only the selected transition recording, never its containing directory. */
export function transitionVideoMiddleware(file: string, route = '/hardware-lab/transition.mp4') {
  return (request: IncomingMessage, response: ServerResponse, next: () => void) => {
    if (request.url?.split('?')[0] !== route) return next()
    response.setHeader('Cache-Control', 'no-store')
    if (request.method !== 'GET') {
      response.statusCode = 405
      response.setHeader('Allow', 'GET')
      response.end('视频入口只提供读取。')
      return
    }
    response.setHeader('Content-Type', 'video/mp4')
    // The mature sender handles streaming and Range; its path never comes from the browser.
    send(request, encodeURIComponent(path.basename(file)), {
      root: path.dirname(file), index: false, extensions: false,
      etag: false, lastModified: false, cacheControl: false,
    }).on('directory', () => {
      response.statusCode = 404
      response.end()
    }).on('error', (error: Error & { statusCode?: number }) => {
      if (response.headersSent) { response.destroy(error); return }
      response.statusCode = error.statusCode || 500
      response.removeHeader('Content-Length')
      response.setHeader('Content-Type', 'text/plain; charset=utf-8')
      response.end(response.statusCode === 404 ? '整车转墙录像尚未生成。' : '录像暂不可读取，请稍后重试。')
    }).pipe(response)
  }
}
