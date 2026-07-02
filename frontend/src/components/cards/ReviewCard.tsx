import ReactMarkdown from 'react-markdown'
import { CardTimer } from './CardTimer'

interface RevisionFeedback {
  logic_issues?: string[]
  language_issues?: string[]
  structure_issues?: string[]
  overall_assessment?: string
  revision_priority?: string
}

interface ReviewCardData {
  // 后端 src/agents/reviewer.py 把 revision_feedback 构造成 Dict
  // （logic_issues / language_issues / structure_issues / overall_assessment / revision_priority）。
  // 历史会话里可能持久化成 string，故两种都兼容。
  revision_feedback?: string | RevisionFeedback
  final_review?: string
  expanded?: boolean
  generating?: boolean
  timerStart?: number | null
  timerEnd?: number | null
}

const PRIORITY_LABEL: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
}

function IssueList({ title, items }: { title: string; items?: string[] }) {
  if (!items || items.length === 0) return null
  return (
    <div>
      <div className="text-xs font-medium text-dark-text-secondary mb-1">{title}</div>
      <ul className="list-disc list-inside text-xs text-dark-text/90 space-y-0.5">
        {items.map((it, i) => <li key={i}>{it}</li>)}
      </ul>
    </div>
  )
}

function RevisionFeedbackView({ fb }: { fb: RevisionFeedback }) {
  const priority = fb.revision_priority ? PRIORITY_LABEL[fb.revision_priority] || fb.revision_priority : null
  return (
    <div className="space-y-2">
      {priority && (
        <div className="text-xs">
          <span className="text-dark-muted">修订优先级：</span>
          <span className="text-dark-text">{priority}</span>
        </div>
      )}
      {fb.overall_assessment && (
        <div>
          <div className="text-xs font-medium text-dark-text-secondary mb-1">总体评估</div>
          <div className="prose prose-invert prose-sm max-w-none">
            <ReactMarkdown>{String(fb.overall_assessment)}</ReactMarkdown>
          </div>
        </div>
      )}
      <IssueList title="逻辑问题" items={fb.logic_issues} />
      <IssueList title="语言问题" items={fb.language_issues} />
      <IssueList title="结构问题" items={fb.structure_issues} />
    </div>
  )
}

export function ReviewCard({ data, onToggle }: { data: ReviewCardData; onToggle: () => void }) {
  const rf = data.revision_feedback
  const rfIsString = typeof rf === 'string'
  const rfIsObject = rf && typeof rf === 'object'
  // final_review 理论上是 string，但保险起见强转，避免再被 react-markdown 拒收。
  const finalReview = data.final_review != null ? String(data.final_review) : ''

  return (
    <div className="border border-dark-border rounded-lg bg-dark-surface p-3 my-2">
      <button onClick={onToggle} className="w-full flex items-center justify-between text-left">
        <span className="text-sm font-semibold text-dark-text">审查意见</span>
        <span className="text-xs text-dark-text-secondary">
          {data.generating ? '审查中...' : (data.expanded ? '收起' : '展开')}
        </span>
      </button>
      {data.expanded && (
        <div className="mt-2 space-y-3 prose prose-invert prose-sm max-w-none">
          {data.generating && !finalReview && !rf && (
            <div className="text-xs text-dark-muted">正在审查论文，请稍候...</div>
          )}
          {rfIsString && rf && (
            <div>
              <div className="text-xs font-medium text-dark-text-secondary mb-1">修订建议</div>
              <ReactMarkdown>{rf}</ReactMarkdown>
            </div>
          )}
          {rfIsObject && (
            <div>
              <div className="text-xs font-medium text-dark-text-secondary mb-1">修订建议</div>
              <RevisionFeedbackView fb={rf as RevisionFeedback} />
            </div>
          )}
          {finalReview && (
            <div>
              <div className="text-xs font-medium text-dark-text-secondary mb-1">终稿</div>
              <ReactMarkdown>{finalReview}</ReactMarkdown>
            </div>
          )}
        </div>
      )}
      <CardTimer start={data.timerStart} end={data.timerEnd} />
    </div>
  )
}
