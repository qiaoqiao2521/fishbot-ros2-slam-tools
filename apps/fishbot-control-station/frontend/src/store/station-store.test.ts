import { beforeEach, describe, expect, it } from 'vitest'
import { useStationStore } from './station-store'
import { mockConnection, mockRobotState } from '@/lib/mock-station'

beforeEach(() => useStationStore.setState(useStationStore.getInitialState(), true))
describe('resource-specific data provenance', () => {
  it('never marks untouched example resources live when only connection arrives', () => {
    useStationStore.getState().setConnection({ ...mockConnection, mode: 'live' })
    expect(useStationStore.getState().resourceProvenance.connection.status).toBe('received')
    expect(useStationStore.getState().resourceProvenance.robotState.status).toBe('example')
    expect(useStationStore.getState().usingFallbackData).toBe(true)
  })
  it('retains last data on disconnect and restores only the resource actually received', () => {
    const store = useStationStore.getState()
    store.setConnection({ ...mockConnection, mode: 'live' }); store.setRobotState(mockRobotState)
    store.markResourceError('connection', 'lost'); store.markResourceError('robotState', 'lost')
    expect(useStationStore.getState().robotState).toEqual(mockRobotState)
    expect(useStationStore.getState().resourceProvenance.robotState.status).toBe('stale')
    store.setConnection({ ...mockConnection, mode: 'live' })
    expect(useStationStore.getState().resourceProvenance.connection.status).toBe('received')
    expect(useStationStore.getState().resourceProvenance.robotState.status).toBe('stale')
  })
  it('records malformed resource failures without erasing the last sample or claiming freshness', () => {
    const store = useStationStore.getState()
    store.setRobotState(mockRobotState); store.markResourceError('robotState', 'invalid pose', true)
    expect(useStationStore.getState().robotState).toBe(mockRobotState)
    expect(useStationStore.getState().resourceProvenance.robotState).toMatchObject({ status: 'invalid', error: 'invalid pose' })
  })
})
