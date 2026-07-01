import ReactMarkdown from 'react-markdown'
import { CardTimer } from './CardTimer'

interface WritingCardData {
  content: string
  done: boolean
  expanded?: boolean
  generating?: boolean
  timerStart?: number | null
  timerEnd?: number | null
}

export function WritingCard({ data, onToggle }: { data: WritingCardData; onToggle: () => void }) {
  return (
    <div className="border border-dark-border rounded-lg bg-dark-surface p-3 my-2">
      <button onClick={onToggle} className="w-full flex items-center justify-between text-left">
        <span className="text-sm font-semibold text-dark-text">论文写作</span>
        <span className="text-xs text-dark-text-secondary">
          {data.done ? '已完成' : (data.generating ? '写作中...' : '写作中...')} {data.expanded ? '收起' : '展开'}
        </span>
      </button>
      {data.expanded && (
        <div className="mt-2 prose prose-invert prose-sm max-w-none">
          {data.content ? <ReactMarkdown>{data.content}</ReactMarkdown> : (
            <div className="text-xs text-dark-muted">正在生成正文，请稍候...</div>
          )}
        </div>
      )}
      <CardTimer start={data.timerStart} end={data.timerEnd} />
    </div>
  )
}
