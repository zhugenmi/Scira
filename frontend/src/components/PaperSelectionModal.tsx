import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Check, X, Loader2, Download, FileText, ChevronDown } from 'lucide-react'
import type { DownloadApproval } from './ChatView'

interface Props {
  open: boolean
  approval: DownloadApproval
  workflowMode: 'full' | 'search' | 'none'
  onClose: () => void
  onSubmit: (selectedIds: string[], targetCategory?: string, newCategoryName?: string) => void
}

type ViewState = 'select' | 'downloading' | 'done'

function deriveView(approval: DownloadApproval): ViewState {
  if (!approval.submitted) return 'select'
  const total = approval.papers.length
  const finished = approval.papers.filter(p => {
    const s = approval.paperStatus[p.paper_id]?.status
    return s === 'success' || s === 'failed'
  }).length
  if (finished >= total && total > 0) return 'done'
  return 'downloading'
}

export default function PaperSelectionModal({ open, approval, workflowMode, onClose, onSubmit }: Props) {
  const { papers, selectedIds, matchedCategory, existingCategories, paperStatus } = approval
  const [selected, setSelected] = useState<Set<string>>(new Set(selectedIds))
  const [category, setCategory] = useState<string>(matchedCategory || '')
  const [isAuto, setIsAuto] = useState<boolean>(!!matchedCategory)
  const [showNewInput, setShowNewInput] = useState<boolean>(false)
  const [newName, setNewName] = useState<string>('')
  const [newNameError, setNewNameError] = useState<string>('')

  const view = deriveView(approval)

  const toggle = (pid: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(pid)) next.delete(pid)
      else next.add(pid)
      return next
    })
  }
  const toggleAll = () => {
    if (selected.size === papers.length) setSelected(new Set())
    else setSelected(new Set(papers.map(p => p.paper_id)))
  }

  const fmtYear = (d: string) => {
    const m = String(d || '').match(/\d{4}/)
    return m ? m[0] : ''
  }

  const submit = () => {
    if (showNewInput && newName.trim()) {
      const norm = newName.trim().toLowerCase().replace(/[^\w一-鿿\-]/g, '_').replace(/^_+|_+$/g, '')
      if (!norm) { setNewNameError('请输入有效名称'); return }
      onSubmit(Array.from(selected), undefined, newName)
    } else if (category && !isAuto) {
      onSubmit(Array.from(selected), category, undefined)
    } else {
      onSubmit(Array.from(selected), undefined, undefined)
    }
  }

  const submitLabel = '添加到知识库'

  const successCount = papers.filter(p => paperStatus[p.paper_id]?.status === 'success').length
  const failedCount = papers.filter(p => paperStatus[p.paper_id]?.status === 'failed').length
  const progressPct = papers.length ? Math.round((successCount + failedCount) / papers.length * 100) : 0

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className="w-full max-w-2xl rounded-2xl border border-dark-border bg-dark-surface p-5 max-h-[85vh] overflow-y-auto"
            initial={{ scale: 0.95 }}
            animate={{ scale: 1 }}
            exit={{ scale: 0.95 }}
            onClick={e => e.stopPropagation()}
          >
            {view === 'select' && (
              <>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-base font-semibold text-dark-text">
                    检索到 {papers.length} 篇论文
                  </h3>
                  <button onClick={toggleAll} className="text-xs px-2 py-1 rounded border border-dark-border hover:bg-dark-card text-dark-muted">
                    {selected.size === papers.length ? '全不选' : '全选'}
                  </button>
                </div>

                {/* 知识库选择 */}
                <div className="mb-3">
                  <label className="text-xs text-dark-muted block mb-1">知识库</label>
                  <div className="relative">
                    <select
                      value={showNewInput ? '__new__' : category}
                      onChange={e => {
                        if (e.target.value === '__new__') {
                          setShowNewInput(true)
                          setIsAuto(false)
                        } else {
                          setShowNewInput(false)
                          setCategory(e.target.value)
                          setIsAuto(e.target.value === matchedCategory)
                        }
                      }}
                      className="w-full appearance-none rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-dark-text pr-8"
                    >
                      {matchedCategory && (
                        <option value={matchedCategory}>{matchedCategory}（自动匹配）</option>
                      )}
                      {existingCategories.filter(c => c !== matchedCategory).map(c => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                      <option value="__new__">+ 新建知识库…</option>
                    </select>
                    <ChevronDown className="w-4 h-4 absolute right-2 top-1/2 -translate-y-1/2 text-dark-muted pointer-events-none" />
                  </div>
                  {showNewInput && (
                    <div className="mt-2">
                      <input
                        type="text"
                        value={newName}
                        onChange={e => { setNewName(e.target.value); setNewNameError('') }}
                        placeholder="输入知识库名称"
                        className="w-full rounded-lg border border-dark-border bg-dark-card px-3 py-2 text-sm text-dark-text"
                      />
                      {newNameError && <div className="text-xs text-red-400 mt-1">{newNameError}</div>}
                    </div>
                  )}
                </div>

                {/* 论文列表 */}
                <div className="space-y-1.5 max-h-80 overflow-y-auto pr-1">
                  {papers.map(p => {
                    const checked = selected.has(p.paper_id)
                    return (
                      <label
                        key={p.paper_id}
                        className={`flex gap-2 items-start p-2 rounded-lg border transition-colors cursor-pointer ${
                          checked ? 'border-primary-500/50 bg-primary-500/10' : 'border-dark-border bg-dark-card/40 hover:bg-dark-card'
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggle(p.paper_id)}
                          className="mt-0.5 accent-primary-500"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-dark-border/50 text-dark-muted">{p.source || 'unknown'}</span>
                            {p.has_pdf_link && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-300 flex items-center gap-0.5">
                                <FileText className="w-2.5 h-2.5" /> PDF
                              </span>
                            )}
                            {fmtYear(p.published_date) && (
                              <span className="text-[10px] text-dark-muted">{fmtYear(p.published_date)}</span>
                            )}
                          </div>
                          <div className="text-sm text-dark-text font-medium truncate mt-0.5">{p.title || 'Untitled'}</div>
                          {p.abstract && <div className="text-xs text-dark-muted/80 mt-0.5 line-clamp-2">{p.abstract}</div>}
                        </div>
                      </label>
                    )
                  })}
                </div>

                {approval.error && <div className="text-xs text-red-400 mt-2">{approval.error}</div>}

                <div className="flex gap-2 mt-4">
                  <button
                    onClick={submit}
                    disabled={selected.size === 0 || approval.status === 'submitting'}
                    className="flex-1 px-3 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium transition-colors flex items-center justify-center gap-1.5"
                  >
                    {approval.status === 'submitting' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
                    {submitLabel}（{selected.size}）
                  </button>
                  <button
                    onClick={onClose}
                    className="px-3 py-2 rounded-lg border border-dark-border hover:bg-dark-card text-dark-muted text-sm transition-colors"
                  >
                    取消
                  </button>
                </div>
              </>
            )}

            {view === 'downloading' && (
              <>
                {(() => {
                  const downloadingPaper = papers.find(p => paperStatus[p.paper_id]?.status === 'downloading')
                  if (downloadingPaper) {
                    return (
                      <h3 className="text-base font-semibold text-dark-text mb-2 truncate">
                        正在下载：{downloadingPaper.title}...
                      </h3>
                    )
                  }
                  return (
                    <h3 className="text-base font-semibold text-dark-text mb-2">
                      已下载 {successCount + failedCount}/{papers.length} 篇
                    </h3>
                  )
                })()}
                <div className="w-full h-2 rounded-full bg-dark-border/30 mb-3 overflow-hidden">
                  <div className="h-full bg-primary-500 transition-all" style={{ width: `${progressPct}%` }} />
                </div>
                <div className="space-y-1.5 max-h-80 overflow-y-auto pr-1">
                  {papers.map(p => {
                    const st = paperStatus[p.paper_id]?.status || 'pending'
                    const err = paperStatus[p.paper_id]?.error
                    return (
                      <div key={p.paper_id} className="flex items-center gap-2 p-2 rounded-lg border border-dark-border bg-dark-card/40">
                        {st === 'downloading' && <Loader2 className="w-4 h-4 animate-spin text-primary-400" />}
                        {st === 'success' && <Check className="w-4 h-4 text-green-400" />}
                        {st === 'failed' && <X className="w-4 h-4 text-red-400" />}
                        {st === 'pending' && <div className="w-4 h-4 rounded-full border border-dark-muted" />}
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-dark-border/50 text-dark-muted">{p.source || 'unknown'}</span>
                        <span className="text-sm text-dark-text truncate flex-1">{p.title}</span>
                        {st === 'failed' && <span className="text-xs text-red-400 truncate max-w-[40%]">失败: {err}</span>}
                        {st === 'success' && <span className="text-xs text-green-400">成功</span>}
                      </div>
                    )
                  })}
                </div>
                <div className="flex justify-end mt-4">
                  <button
                    onClick={onClose}
                    className="px-3 py-2 rounded-lg border border-dark-border hover:bg-dark-card text-dark-muted text-sm transition-colors"
                  >
                    隐藏到后台
                  </button>
                </div>
              </>
            )}

            {view === 'done' && (
              <>
                <h3 className="text-base font-semibold text-dark-text mb-2">完成</h3>
                <p className="text-sm text-dark-muted mb-1">
                  成功下载 {successCount} 篇{failedCount > 0 ? `，失败 ${failedCount} 篇` : ''}
                </p>
                {failedCount > 0 && <p className="text-xs text-dark-muted/80">失败论文已跳过，可稍后重试</p>}
                {workflowMode === 'full' && <p className="text-xs text-dark-muted/80 mt-2">论文已添加到知识库，后续将生成综述。</p>}
                <div className="flex justify-end mt-4">
                  <button
                    onClick={onClose}
                    className="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium transition-colors"
                  >
                    关闭
                  </button>
                </div>
              </>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
