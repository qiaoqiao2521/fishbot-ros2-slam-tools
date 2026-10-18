import { describe, expect, it } from 'vitest'
import { toolEntry } from './workbench-tool-entry'
describe('current tool entry', () => {
  it('uses configured ports independently of historical catalog evidence', () => {
    expect(toolEntry('video', '{"video":18123,"spatiallm":8899}')).toBe('http://127.0.0.1:18123/')
    expect(toolEntry('spatiallm', '{"video":18123,"spatiallm":8899}')).toBe('http://127.0.0.1:8899/')
  })
  it('does not invent a destination for absent, disabled or invalid configuration', () => {
    for (const value of [null, '{}', '{"video":null}', '{"video":"https://other/"}', '{"video":80}', 'invalid']) expect(toolEntry('video', value)).toBeNull()
  })
})
