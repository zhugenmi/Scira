import { CardTimer } from './CardTimer'

interface OutlineSection {
  section_id?: string
  title?: string
  key_points?: string[]
}
interface OutlineCardData {
  title?: string
  sections?: OutlineSection[]
  expanded?: boolean
  generating?: boolean
  timerStart?: number | null
  timerEnd?: number | null
}

export function OutlineCard({ data, onToggle }: { data: OutlineCardData; onToggle: () => void }) {
  return (
    <div className="border border-dark-border rounded-lg bg-dark-surface p-3 my-2">
      <button onClick={onToggle} className="w-full flex items-center justify-between text-left">
        <span className="text-sm font-semibold text-dark-text">论文大纲</span>
        <span className="text-xs text-dark-text-secondary">
          {data.generating ? '生成中...' : (data.expanded ? '收起' : '展开')}
        </span>
      </button>
      {data.expanded && (
        <div className="mt-2 space-y-2">
          {data.generating && !data.title && (
            <div className="text-xs text-dark-muted">正在生成大纲，请稍候...</div>
          )}
          {data.title && <div className="text-sm font-medium text-dark-text">{data.title}</div>}
          {(data.sections || []).map((s, i) => (
            <div key={s.section_id || i} className="text-xs text-dark-text-secondary">
              <div className="font-medium text-dark-text">{s.title}</div>
              {s.key_points && s.key_points.length > 0 && (
                <ul className="list-disc list-inside ml-2">
                  {s.key_points.map((p, j) => <li key={j}>{p}</li>)}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
      <CardTimer start={data.timerStart} end={data.timerEnd} />
    </div>
  )
}
