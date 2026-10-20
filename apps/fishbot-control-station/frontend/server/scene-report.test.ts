// @vitest-environment node
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { createServer, type Server } from 'node:http'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { sceneReportMiddleware } from './scene-report'

const cleanup: (() => Promise<void>)[] = []
afterEach(async () => { for (const close of cleanup.splice(0).reverse()) await close() })

async function fixture(route?: string) {
  const directory = await mkdtemp(path.join(tmpdir(), 'fishbot-scene-report-'))
  cleanup.push(() => rm(directory, { recursive: true, force: true }))
  const file = path.join(directory, 'report.json')
  const handler = sceneReportMiddleware(file, route)
  const server: Server = createServer((request, response) => {
    void handler(request, response, () => { response.statusCode = 404; response.end('not found') })
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  cleanup.push(() => new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve())))
  const address = server.address()
  if (!address || typeof address === 'string') throw new Error('Test server has no TCP address')
  return { file, url: `http://127.0.0.1:${address.port}` }
}

describe('editable scene report endpoint', () => {
  it('reuses the fixed-file reader for hardware results without accepting browser paths', async () => {
    const { file, url } = await fixture('/hardware-lab/report')
    await writeFile(file, '{"sections":[]}')
    expect((await fetch(`${url}/hardware-lab/report`)).status).toBe(200)
    expect((await fetch(`${url}/scene-validation/report`)).status).toBe(404)
    expect((await fetch(`${url}/hardware-lab/report`, { method: 'POST' })).status).toBe(405)
  })
  it('reads the selected file again after a local edit without rerunning a task', async () => {
    const { file, url } = await fixture()
    await writeFile(file, JSON.stringify({ schema_version: 9, cases: [{ id: 'clear' }] }))
    expect(await (await fetch(`${url}/scene-validation/report`)).json()).toEqual({ schema_version: 9, cases: [{ id: 'clear' }] })
    await writeFile(file, JSON.stringify({ cases: [{ id: 'blocked', business_result: 'undelivered' }] }))
    const response = await fetch(`${url}/scene-validation/report?refresh=1`)
    expect(response.headers.get('cache-control')).toBe('no-store')
    expect(await response.json()).toEqual({ cases: [{ id: 'blocked', business_result: 'undelivered' }] })
  })

  it('reports missing or temporarily invalid JSON, then recovers from the same file', async () => {
    const { file, url } = await fixture()
    expect((await fetch(`${url}/scene-validation/report`)).status).toBe(404)
    await writeFile(file, '{')
    expect((await fetch(`${url}/scene-validation/report`)).status).toBe(422)
    await writeFile(file, '{}')
    expect((await fetch(`${url}/scene-validation/report`)).status).toBe(200)
  })

  it('rejects writes and does not expose arbitrary paths', async () => {
    const { file, url } = await fixture()
    await writeFile(file, '{"scope":"simulation"}')
    expect((await fetch(`${url}/scene-validation/report`, { method: 'POST' })).status).toBe(405)
    expect((await fetch(`${url}/scene-validation/report/other.json`)).status).toBe(404)
  })
})
