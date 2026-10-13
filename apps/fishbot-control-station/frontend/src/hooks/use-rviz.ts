import { useEffect, useRef, useState } from 'react'

import { requestSimulation, SIMULATION_DOMAIN, SimulationRejectedRequest } from '@/lib/simulation'

type RvizStatus = { available: boolean; running: boolean; domain: number; message: string }
class RvizDomainMismatchError extends Error {}

function validateStatus(value: RvizStatus): RvizStatus {
  if (!value || typeof value.available !== 'boolean' || typeof value.running !== 'boolean'
    || typeof value.message !== 'string') {
    throw new Error('RViz 服务没有返回有效状态。')
  }
  if (!Number.isInteger(value.domain) || value.domain < 1 || value.domain > 232 || value.domain !== SIMULATION_DOMAIN) {
    throw new RvizDomainMismatchError(`RViz 未连接当前 MuJoCo 仿真（ROS 域 ${SIMULATION_DOMAIN}），请确认服务配置。`)
  }
  return value
}

export function useRviz() {
  const [status, setStatus] = useState<RvizStatus | null>(null)
  const [pending, setPending] = useState(true)
  const [message, setMessage] = useState('正在检查控制站 RViz…')
  const [unknown, setUnknown] = useState(false)
  const mounted = useRef(false)
  const busy = useRef(false)
  const sequence = useRef(0)
  const unknownReceipt = useRef(false)
  const wrongDomain = useRef(false)
  const controllers = useRef(new Set<AbortController>())

  async function request(launch: boolean) {
    if (busy.current) return
    busy.current = true
    setPending(true)
    setMessage(launch ? '正在控制站电脑打开 RViz…' : '正在读取 RViz 状态…')
    const current = ++sequence.current
    const isCurrent = () => mounted.current && current === sequence.current

    async function readOrLaunch(post: boolean) {
      const controller = new AbortController()
      controllers.current.add(controller)
      const timeout = setTimeout(() => controller.abort(), post ? 5000 : 3000)
      try {
        return validateStatus(await requestSimulation<RvizStatus>('rviz', post ? {} : undefined, controller.signal))
      } finally {
        clearTimeout(timeout)
        controllers.current.delete(controller)
      }
    }

    try {
      let result: RvizStatus
      try {
        result = await readOrLaunch(launch)
      } catch (error) {
        if (!isCurrent()) return
        if (!launch || error instanceof RvizDomainMismatchError
          || (error instanceof SimulationRejectedRequest && (error.status < 500 || error.status === 503))) throw error
        unknownReceipt.current = true
        setUnknown(true)
        setMessage('打开回执未知，正在读取 RViz 状态；不会重复启动。')
        result = await readOrLaunch(false)
      }
      if (!isCurrent()) return
      const wasUnknown = unknownReceipt.current
      unknownReceipt.current = false
      wrongDomain.current = false
      setUnknown(false)
      setStatus(result)
      setMessage(result.running
        ? `RViz 已在控制站电脑打开（ROS 域 ${result.domain}）。`
        : wasUnknown && result.available ? '未检测到 RViz 进程；可再次点击打开。' : result.message)
    } catch (error) {
      if (!isCurrent()) return
      if (error instanceof RvizDomainMismatchError) {
        wrongDomain.current = true
        setStatus(null)
        setUnknown(true)
        setMessage(error.message)
        return
      }
      if (error instanceof SimulationRejectedRequest && error.status === 503) {
        setStatus(null)
      }
      setMessage(unknownReceipt.current ? 'RViz 启动状态未知；请点击“确认 RViz 状态”，不会重复启动。'
        : error instanceof Error && error.name !== 'AbortError' ? error.message : 'RViz 请求超时，请稍后重试。')
    } finally {
      if (isCurrent()) {
        busy.current = false
        setPending(false)
      }
    }
  }

  useEffect(() => {
    mounted.current = true
    void request(false)
    const activeControllers = controllers.current
    return () => {
      mounted.current = false
      sequence.current += 1
      busy.current = false
      activeControllers.forEach((controller) => controller.abort())
      activeControllers.clear()
    }
    // RViz has an independent lifecycle; navigation state changes do not launch it.
  }, [])

  return { status, pending, message, unknown, open: () => request(!unknownReceipt.current && !wrongDomain.current) }
}
