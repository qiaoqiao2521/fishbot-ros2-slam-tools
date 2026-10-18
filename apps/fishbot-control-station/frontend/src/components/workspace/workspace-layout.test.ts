import { describe, expect, it } from 'vitest'
import { decodeWorkspaceLayout, encodeWorkspaceLayout, sanitizeWorkspaceLayout } from './workspace-layout'
const sample = () => ({ grid: { width: 1200, height: 720, orientation: 'HORIZONTAL', root: { type: 'branch', data: [
  { type: 'leaf', size: 800, data: { id: 'g1', views: ['canvas'], activeView: 'canvas' } },
  { type: 'leaf', size: 400, data: { id: 'g2', views: ['task', 'objects'], activeView: 'task' } },
] } }, panels: { canvas: { id: 'canvas', contentComponent: 'slot' }, task: { id: 'task', contentComponent: 'slot' }, objects: { id: 'objects', contentComponent: 'slot' } }, activeGroup: 'g1' })
describe('workspace display cache boundary', () => {
  it('roundtrips a closed properties panel and selected task tab', () => {
    const parsed = decodeWorkspaceLayout(encodeWorkspaceLayout(sample()))
    expect(Object.keys(parsed.panels)).toEqual(['canvas', 'task', 'objects'])
    expect(parsed.activeGroup).toBe('g1')
  })
  it('stores no panel parameters, URLs, commands, credentials or task snapshots', () => {
    const value = sample()
    Object.assign(value.panels.task, { params: { token: 'secret', command: 'start', id: 'task-1' }, title: 'injected' })
    const saved = encodeWorkspaceLayout(value)
    expect(saved).not.toMatch(/secret|injected|task-1|command|token/)
  })
  it.each(['{broken', JSON.stringify({ version: 0, layout: sample() }), 'x'.repeat(32769)])('rejects corrupt, old and oversized caches', (text) => {
    expect(() => decodeWorkspaceLayout(text)).toThrow(/布局/)
  })
  it('rejects duplicate views so one slot cannot be multiplied', () => {
    const value = sample(); value.grid.root.data[1].data.views.push('canvas')
    expect(() => sanitizeWorkspaceLayout(value)).toThrow()
  })
  it('rejects invalid sizes, unknown components, panels and popout URLs', () => {
    const cases = [sample(), sample(), sample(), sample()]
    cases[0].grid.width = NaN
    cases[1].panels.canvas.contentComponent = 'execute'
    Object.assign(cases[2].panels, { unknown: { id: 'unknown', contentComponent: 'slot' } })
    Object.assign(cases[3], { popoutGroups: [{ url: 'http://external/' }] })
    for (const value of cases) expect(() => sanitizeWorkspaceLayout(value)).toThrow()
  })
})
