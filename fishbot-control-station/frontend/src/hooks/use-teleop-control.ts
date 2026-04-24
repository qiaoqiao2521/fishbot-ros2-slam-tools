import { useEffect, useEffectEvent, useRef } from 'react'

import { postCommand, postStop } from '@/lib/api'
import { useStationStore } from '@/store/station-store'
import type { ControlDirection } from '@/types/station'

type Vector = {
  linearX: number
  angularZ: number
}

const repeatMs = 140

export function useTeleopControl() {
  const intervalRef = useRef<number | null>(null)
  const lastPublishAtRef = useRef(0)
  const sequenceRef = useRef(0)
  const {
    activeDirection,
    angularSpeed,
    appendCommand,
    appendError,
    linearSpeed,
    patchControlFeedback,
    setActiveDirection,
  } = useStationStore()

  const makeVector = (direction: ControlDirection): Vector => {
    switch (direction) {
      case 'forward':
        return { linearX: linearSpeed, angularZ: 0 }
      case 'backward':
        return { linearX: -linearSpeed, angularZ: 0 }
      case 'left':
        return { linearX: 0, angularZ: angularSpeed }
      case 'right':
        return { linearX: 0, angularZ: -angularSpeed }
      case 'stop':
      default:
        return { linearX: 0, angularZ: 0 }
    }
  }

  const publish = async (direction: ControlDirection) => {
    const nowPerf = performance.now()
    if (direction !== 'stop' && nowPerf - lastPublishAtRef.current < repeatMs - 8) {
      patchControlFeedback({
        throttleActive: true,
        holdCadenceMs: repeatMs,
        lastAckMessage: `cadence gate ${repeatMs}ms`,
        releaseToZeroArmed: true,
      })
      return
    }

    const vector = makeVector(direction)
    sequenceRef.current += 1
    lastPublishAtRef.current = nowPerf

    try {
      await postCommand({
        ...vector,
        source: 'web-console',
        sequence: sequenceRef.current,
      })
      appendCommand({
        id: crypto.randomUUID(),
        level: 'info',
        message: `${direction} linear=${vector.linearX.toFixed(2)} angular=${vector.angularZ.toFixed(2)}`,
        timestamp: new Date().toISOString(),
      })
      patchControlFeedback({
        holdCadenceMs: repeatMs,
        lastCommandAt: new Date().toISOString(),
        lastAckAt: new Date().toISOString(),
        lastAckMessage: `ack ${direction} linear=${vector.linearX.toFixed(2)} angular=${vector.angularZ.toFixed(2)}`,
        lastSequence: sequenceRef.current,
        throttleActive: false,
        releaseToZeroArmed: true,
      })
    } catch {
      appendError({
        id: crypto.randomUUID(),
        level: 'error',
        message: `Failed to send ${direction} command`,
        timestamp: new Date().toISOString(),
      })
      patchControlFeedback({
        lastAckAt: new Date().toISOString(),
        lastAckMessage: `failed ${direction} dispatch`,
        throttleActive: false,
      })
    }
  }

  const clearLoop = () => {
    if (intervalRef.current !== null) {
      window.clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }

  const begin = async (direction: Exclude<ControlDirection, 'stop'>) => {
    clearLoop()
    setActiveDirection(direction)
    await publish(direction)
    intervalRef.current = window.setInterval(() => {
      void publish(direction)
    }, repeatMs)
  }

  const stop = async () => {
    clearLoop()
    setActiveDirection(null)
    try {
      await postStop('/api/v1/control/stop')
      appendCommand({
        id: crypto.randomUUID(),
        level: 'info',
        message: 'stop command published',
        timestamp: new Date().toISOString(),
      })
      patchControlFeedback({
        lastStopAt: new Date().toISOString(),
        lastAckAt: new Date().toISOString(),
        lastAckMessage: 'release -> zero velocity sent',
        throttleActive: false,
        releaseToZeroArmed: false,
      })
    } catch {
      appendError({
        id: crypto.randomUUID(),
        level: 'error',
        message: 'Failed to publish stop command',
        timestamp: new Date().toISOString(),
      })
      patchControlFeedback({
        lastAckAt: new Date().toISOString(),
        lastAckMessage: 'release -> zero failed',
        throttleActive: false,
      })
    }
  }

  const emergencyStop = async () => {
    clearLoop()
    setActiveDirection(null)
    try {
      await postStop('/api/v1/control/emergency-stop')
      appendCommand({
        id: crypto.randomUUID(),
        level: 'warning',
        message: 'emergency stop issued',
        timestamp: new Date().toISOString(),
      })
      patchControlFeedback({
        lastStopAt: new Date().toISOString(),
        lastAckAt: new Date().toISOString(),
        lastAckMessage: 'emergency stop acknowledged',
        throttleActive: false,
        releaseToZeroArmed: false,
      })
    } catch {
      appendError({
        id: crypto.randomUUID(),
        level: 'error',
        message: 'Failed to publish emergency stop',
        timestamp: new Date().toISOString(),
      })
      patchControlFeedback({
        lastAckAt: new Date().toISOString(),
        lastAckMessage: 'emergency stop failed',
        throttleActive: false,
      })
    }
  }

  const handleBegin = useEffectEvent((direction: Exclude<ControlDirection, 'stop'>) => {
    void begin(direction)
  })

  const handleStop = useEffectEvent(() => {
    void stop()
  })

  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.repeat) {
        return
      }

      if (event.code === 'Space') {
        event.preventDefault()
        handleStop()
        return
      }

      const mapping: Record<string, Exclude<ControlDirection, 'stop'>> = {
        ArrowUp: 'forward',
        KeyW: 'forward',
        ArrowDown: 'backward',
        KeyS: 'backward',
        ArrowLeft: 'left',
        KeyA: 'left',
        ArrowRight: 'right',
        KeyD: 'right',
      }

      const mapped = mapping[event.code]
      if (mapped) {
        event.preventDefault()
        handleBegin(mapped)
      }
    }

    const keyup = (event: KeyboardEvent) => {
      if (
        ['ArrowUp', 'KeyW', 'ArrowDown', 'KeyS', 'ArrowLeft', 'KeyA', 'ArrowRight', 'KeyD'].includes(
          event.code,
        )
      ) {
        handleStop()
      }
    }

    const blur = () => {
      handleStop()
    }

    const visibility = () => {
      if (document.visibilityState !== 'visible') {
        handleStop()
      }
    }

    window.addEventListener('keydown', keydown)
    window.addEventListener('keyup', keyup)
    window.addEventListener('blur', blur)
    document.addEventListener('visibilitychange', visibility)

    return () => {
      window.removeEventListener('keydown', keydown)
      window.removeEventListener('keyup', keyup)
      window.removeEventListener('blur', blur)
      document.removeEventListener('visibilitychange', visibility)
      clearLoop()
    }
  }, [handleBegin, handleStop])

  return {
    activeDirection,
    begin,
    emergencyStop,
    stop,
  }
}
