import { useEffect, useState } from 'react'
import { Loader2, Check, X, BookOpen } from 'lucide-react'

interface Topic {
  name: string
  topic: string
  count: number
}

interface KbGenerateModalProps {
  open: boolean
  onClose: () => void
  onSubmit: (categories: string[], topic: string) => void
  submitting?: boolean
  error?: string | null
}

export default function KbGenerateModal({ open, onClose, onSubmit, submitting, error }: KbGenerateModalProps) {
  const [topics, setTopics] = useState<Topic[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [topic, setTopic] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!open) return
    setLoading(true)
    fetch('/api/papers/topics')
      .then(r => r.json())
      .then(data => {
        const list: Topic[] = (data.topics || []).map((t: any) => ({
          name: t.name,
          topic: t.topic || t.name,
          count: t.count || 0,
        }))
        setTopics(list)
        setSelected(new Set())
        setTopic('')
      })
      .catch(() => setTopics([]))
      .finally(() => setLoading(false))
  }, [open])

  if (!open) return null

  const toggle = (name: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const canSubmit = selected.size > 0 && topic.trim().length > 0 && !submitting

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-dark-surface border border-dark-border rounded-2xl shadow-2xl w-full max-w-lg max-h-[80vh] flex flex-col">
        {/* 头部 */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-dark-border">
          <div className="flex items-center gap-2 text-primary-400">
            <BookOpen className="w-4 h-4" />
            <span className="text-sm font-semibold text-dark-text">从知识库生成综述</span>
          </div>
          <button
            onClick={onClose}
            disabled={submitting}
            className="p-1.5 rounded-lg text-dark-muted hover:text-dark-text hover:bg-dark-border/50 transition-colors disabled:opacity-50"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* 主体 */}
        <div className="flex-1 overflow-auto p-5 space-y-4">
          <div>
            <div className="text-xs text-dark-muted mb-2">选择一个或多个知识库（{topics.length} 个可用）</div>
            {loading ? (
              <div className="flex items-center gap-2 text-xs text-dark-muted py-4">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> 加载知识库列表...
              </div>
            ) : topics.length === 0 ? (
              <div className="text-xs text-dark-muted py-4">
                暂无知识库。请先通过聊天检索论文建立知识库。
              </div>
            ) : (
              <div className="space-y-1.5 max-h-60 overflow-auto">
                {topics.map(t => {
                  const checked = selected.has(t.name)
                  return (
                    <label
                      key={t.name}
                      className={`flex items-center gap-2.5 px-3 py-2 rounded-lg cursor-pointer transition-colors border
                        ${checked
                          ? 'bg-primary-500/15 border-primary-500/40'
                          : 'bg-dark-bg border-dark-border hover:border-primary-500/30'}`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(t.name)}
                        className="accent-primary-500"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-dark-text truncate">{t.topic || t.name}</div>
                        <div className="text-[11px] text-dark-muted">{t.name} · {t.count} 篇</div>
                      </div>
                    </label>
                  )
                })}
              </div>
            )}
          </div>

          <div>
            <div className="text-xs text-dark-muted mb-2">综述主题 / 聚焦方向</div>
            <input
              type="text"
              value={topic}
              onChange={e => setTopic(e.target.value)}
              placeholder="例如：基于知识图谱的图神经网络方法综述"
              className="w-full bg-dark-bg border border-dark-border rounded-lg px-3 py-2 text-sm text-dark-text
                       placeholder:text-dark-muted focus:outline-none focus:border-primary-500"
              disabled={submitting}
            />
            <div className="text-[11px] text-dark-muted mt-1">
              助手将阅读所选知识库中的精读结果（不重新检索/下载），生成综述并引用这些论文。
            </div>
          </div>

          {error && (
            <div className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
        </div>

        {/* 底部 */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-dark-border">
          <div className="text-xs text-dark-muted">
            已选 {selected.size} 个知识库
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              disabled={submitting}
              className="px-3 py-1.5 rounded-lg text-dark-muted hover:text-dark-text border border-dark-border hover:bg-dark-bg text-xs transition-colors disabled:opacity-50"
            >
              取消
            </button>
            <button
              onClick={() => onSubmit(Array.from(selected), topic.trim())}
              disabled={!canSubmit}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary-500 hover:bg-primary-600 disabled:bg-dark-border disabled:text-dark-muted text-white text-xs transition-colors"
            >
              {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              开始生成
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
