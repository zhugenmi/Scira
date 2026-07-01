import ReactMarkdown from 'react-markdown'

interface ReviewCardData {
  revision_feedback?: string
  final_review?: string
  expanded?: boolean
}

export function ReviewCard({ data, onToggle }: { data: ReviewCardData; onToggle: () => void }) {
  return (
    <div className="border border-dark-border rounded-lg bg-dark-surface p-3 my-2">
      <button onClick={onToggle} className="w-full flex items-center justify-between text-left">
        <span className="text-sm font-semibold text-dark-text">审查意见</span>
        <span className="text-xs text-dark-text-secondary">{data.expanded ? '收起' : '展开'}</span>
      </button>
      {data.expanded && (
        <div className="mt-2 space-y-3 prose prose-invert prose-sm max-w-none">
          {data.revision_feedback && (
            <div>
              <div className="text-xs font-medium text-dark-text-secondary mb-1">修订建议</div>
              <ReactMarkdown>{data.revision_feedback}</ReactMarkdown>
            </div>
          )}
          {data.final_review && (
            <div>
              <div className="text-xs font-medium text-dark-text-secondary mb-1">终稿</div>
              <ReactMarkdown>{data.final_review}</ReactMarkdown>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
