import ReactMarkdown from 'react-markdown'

interface WritingCardData {
  content: string
  done: boolean
  expanded?: boolean
}

export function WritingCard({ data, onToggle }: { data: WritingCardData; onToggle: () => void }) {
  return (
    <div className="border border-dark-border rounded-lg bg-dark-surface p-3 my-2">
      <button onClick={onToggle} className="w-full flex items-center justify-between text-left">
        <span className="text-sm font-semibold text-dark-text">论文写作</span>
        <span className="text-xs text-dark-text-secondary">
          {data.done ? '已完成' : '写作中...'} {data.expanded ? '收起' : '展开'}
        </span>
      </button>
      {data.expanded && (
        <div className="mt-2 prose prose-invert prose-sm max-w-none">
          <ReactMarkdown>{data.content || ''}</ReactMarkdown>
        </div>
      )}
    </div>
  )
}
