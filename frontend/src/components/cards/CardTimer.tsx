import { useEffect, useState } from 'react'

function formatDuration(ms: number): string {
  if (ms < 0) ms = 0
  const totalSec = Math.floor(ms / 1000)
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s}s`
  return `${s}s`
}

interface CardTimerProps {
  /** 计时开始时间戳（ms，Date.now()）。未提供则不渲染。 */
  start?: number | null
  /** 计时结束时间戳（ms）。未提供且 start 存在 → 持续计时。 */
  end?: number | null
  /** 是否显示"已完成"前缀文字（默认否，仅显示时长）。 */
  label?: string
}

export function CardTimer({ start, end, label }: CardTimerProps) {
  const [, setTick] = useState(0)

  // 持续计时：start 存在且 end 未定义时，每秒刷新
  const running = !!start && !end
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [running])

  if (!start) return null
  const endTs = end || Date.now()
  const duration = endTs - start
  const text = formatDuration(duration)

  return (
    <div className="text-[10px] text-dark-muted mt-1.5 text-right select-none">
      {label ? `${label} ` : ''}{text}
    </div>
  )
}

/** 行内计时（用于 workflowStatus 行旁的检索计时），返回纯文本节点。 */
export function InlineTimer({ start, end }: { start: number; end?: number | null }) {
  const [, setTick] = useState(0)
  const running = !end
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => setTick(t => t + 1), 1000)
    return () => clearInterval(id)
  }, [running])
  const duration = (end || Date.now()) - start
  return <>{formatDuration(duration)}</>
}
