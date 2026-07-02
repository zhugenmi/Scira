import { useState, useEffect, useRef, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { FileText, Download, Calendar, Search, Trash2, Edit3, ChevronDown, Sparkles, PenLine, Eye, Check, Loader2, AlertCircle, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

interface GeneratedPaper {
  id: string
  title: string
  topic: string
  createdAt: string
  createdAtMs: number
  wordCount: number
  filename: string
}

type ViewMode = 'render' | 'manual-edit'
type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

interface EditMenuChoice {
  kind: 'ai' | 'manual'
}

interface GeneratedPapersProps {
  onEditWithAI?: (paper: GeneratedPaper, content: string) => void
}

const markdownComponents = {
  h1: ({ children }: any) => <h1 className="text-3xl font-bold text-dark-text border-b border-dark-border pb-3 mb-6 mt-2">{children}</h1>,
  h2: ({ children }: any) => <h2 className="text-2xl font-bold text-primary-400 mt-8 mb-4 flex items-center gap-2"><span className="w-1 h-6 bg-primary-500 rounded"></span>{children}</h2>,
  h3: ({ children }: any) => <h3 className="text-xl font-semibold text-dark-text mt-6 mb-3">{children}</h3>,
  h4: ({ children }: any) => <h4 className="text-lg font-semibold text-dark-text mt-4 mb-2">{children}</h4>,
  p: ({ children }: any) => <p className="text-dark-text leading-relaxed mb-4 text-base">{children}</p>,
  ul: ({ children }: any) => <ul className="list-disc list-inside space-y-2 mb-4 text-dark-text ml-2">{children}</ul>,
  ol: ({ children }: any) => <ol className="list-decimal list-inside space-y-2 mb-4 text-dark-text ml-2">{children}</ol>,
  li: ({ children }: any) => <li className="text-dark-text leading-relaxed">{children}</li>,
  strong: ({ children }: any) => <strong className="text-primary-400 font-semibold">{children}</strong>,
  em: ({ children }: any) => <em className="text-primary-300 italic">{children}</em>,
  code: ({ children, className }: any) => {
    const isInline = !className
    return isInline
      ? <code className="text-primary-400 bg-dark-surface px-1.5 py-0.5 rounded text-sm font-mono">{children}</code>
      : <code className={`${className} block`}>{children}</code>
  },
  pre: ({ children }: any) => <pre className="bg-dark-surface border border-dark-border rounded-lg p-4 overflow-x-auto mb-4 text-sm">{children}</pre>,
  blockquote: ({ children }: any) => <blockquote className="border-l-4 border-primary-500 pl-4 py-2 my-4 bg-primary-500/5 text-dark-muted italic">{children}</blockquote>,
  table: ({ children }: any) => <div className="overflow-x-auto mb-4 rounded-lg border border-dark-border"><table className="min-w-full divide-y divide-dark-border">{children}</table></div>,
  thead: ({ children }: any) => <thead className="bg-dark-surface">{children}</thead>,
  th: ({ children }: any) => <th className="px-4 py-2 text-left text-sm font-semibold text-primary-400 border-r border-dark-border last:border-r-0">{children}</th>,
  td: ({ children }: any) => <td className="px-4 py-2 text-sm text-dark-text border-r border-dark-border last:border-r-0">{children}</td>,
  tr: ({ children }: any) => <tr className="border-b border-dark-border hover:bg-dark-surface/50 transition-colors">{children}</tr>,
  a: ({ children, href }: any) => <a href={href} className="text-primary-400 hover:text-primary-300 underline" target="_blank" rel="noopener noreferrer">{children}</a>,
  hr: () => <hr className="my-6 border-dark-border" />,
}

const HISTORY_LIMIT = 50
const SAVE_DEBOUNCE_MS = 1500

export default function GeneratedPapers({ onEditWithAI }: GeneratedPapersProps) {
  const [papers, setPapers] = useState<GeneratedPaper[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedPaper, setSelectedPaper] = useState<GeneratedPaper | null>(null)
  const [renderContent, setRenderContent] = useState('')

  const [viewMode, setViewMode] = useState<ViewMode>('render')
  const [editingContent, setEditingContent] = useState('')
  const [historyStack, setHistoryStack] = useState<string[]>([])
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')
  const [dirty, setDirty] = useState(false)

  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  const [editMenuOpen, setEditMenuOpen] = useState(false)

  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const editingContentRef = useRef('')
  const selectedFilenameRef = useRef<string | null>(null)
  useEffect(() => { editingContentRef.current = editingContent }, [editingContent])
  useEffect(() => { selectedFilenameRef.current = selectedPaper?.filename ?? null }, [selectedPaper])

  const flushSave = useCallback(async () => {
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
      debounceTimerRef.current = null
    }
    const filename = selectedFilenameRef.current
    const content = editingContentRef.current
    if (!filename) return
    if (!dirty) return
    setSaveStatus('saving')
    try {
      const res = await fetch('/api/outputs/write', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, content }),
      })
      if (res.ok) {
        setSaveStatus('saved')
        setDirty(false)
        setRenderContent(content)
        setTimeout(() => setSaveStatus('idle'), 1500)
      } else {
        setSaveStatus('error')
      }
    } catch {
      setSaveStatus('error')
    }
  }, [dirty])

  const scheduleSave = useCallback((content: string) => {
    setDirty(true)
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    debounceTimerRef.current = setTimeout(() => {
      debounceTimerRef.current = null
      const filename = selectedFilenameRef.current
      if (!filename) return
      setSaveStatus('saving')
      fetch('/api/outputs/write', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, content }),
      }).then(res => {
        if (res.ok) {
          setSaveStatus('saved')
          setDirty(false)
          setRenderContent(content)
          setTimeout(() => setSaveStatus('idle'), 1500)
        } else {
          setSaveStatus('error')
        }
      }).catch(() => setSaveStatus('error'))
    }, SAVE_DEBOUNCE_MS)
  }, [])

  const loadPaper = useCallback(async (paper: GeneratedPaper) => {
    // 切换前若有未保存改动，先 flush
    if (dirty) await flushSave()
    setSelectedPaper(paper)
    setViewMode('render')
    setEditingContent('')
    setHistoryStack([])
    setSaveStatus('idle')
    setDirty(false)
    try {
      const res = await fetch(`/data/outputs/${paper.filename}`)
      const text = res.ok ? await res.text() : `# ${paper.title}\n\n（内容加载失败）`
      setRenderContent(text)
    } catch {
      setRenderContent(`# ${paper.title}\n\n（内容加载失败）`)
    }
  }, [dirty, flushSave])

  useEffect(() => {
    const loadPapers = async () => {
      try {
        const res = await fetch('/api/outputs/list')
        if (res.ok) {
          const data = await res.json()
          const list: GeneratedPaper[] = (data.files || [])
            .filter((f: any) => f.name.endsWith('.md'))
            .map((f: any, index: number) => {
              const nameWithoutExt = f.name.replace(/\.md$/, '')
              const match = nameWithoutExt.match(/^(.+)_(\d{8}_\d{6})$/)
              const title = match ? match[1] : nameWithoutExt
              const createdMs = f.modified * 1000
              return {
                id: String(index + 1),
                title,
                topic: '研究论文',
                createdAt: new Date(createdMs).toLocaleString('zh-CN'),
                createdAtMs: createdMs,
                wordCount: Math.round(f.size / 5),
                filename: f.name,
              }
            })
          list.sort((a, b) => b.createdAtMs - a.createdAtMs)
          setPapers(list)
          if (list.length > 0) {
            await loadPaper(list[0])
          }
        }
      } catch (e) {
        console.error('加载文件列表失败:', e)
      }
      setLoading(false)
    }
    loadPapers()
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    }
  }, [])

  const handleDownload = (paper: GeneratedPaper) => {
    window.open(`/data/outputs/${paper.filename}`, '_blank')
  }

  const handleDelete = async (paper: GeneratedPaper) => {
    if (!confirm('确定要删除这篇论文吗？此操作不可恢复。')) return
    try {
      const res = await fetch(`/api/outputs/${paper.filename}`, { method: 'DELETE' })
      if (res.ok) {
        const next = papers.filter(p => p.filename !== paper.filename)
        setPapers(next)
        if (selectedPaper?.filename === paper.filename) {
          if (next.length > 0) await loadPaper(next[0])
          else { setSelectedPaper(null); setRenderContent('') }
        }
      } else {
        alert('删除失败')
      }
    } catch {
      alert('删除失败')
    }
  }

  const filteredPapers = papers.filter(p =>
    p.title.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const enterManualEdit = () => {
    setViewMode('manual-edit')
    setEditingContent(renderContent)
    setHistoryStack([])
    setSaveStatus('idle')
    setDirty(false)
    setEditMenuOpen(false)
  }

  const handleEditClick = (choice: EditMenuChoice) => {
    if (choice.kind === 'manual') {
      enterManualEdit()
      return
    }
    // AI 编辑
    setEditMenuOpen(false)
    if (onEditWithAI && selectedPaper) {
      onEditWithAI(selectedPaper, renderContent)
    }
  }

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const next = e.target.value
    // 推入历史栈（限制大小）
    setHistoryStack(prev => {
      const updated = [...prev, editingContentRef.current]
      if (updated.length > HISTORY_LIMIT) updated.shift()
      return updated
    })
    setEditingContent(next)
    scheduleSave(next)
  }

  const handleUndo = () => {
    setHistoryStack(prev => {
      if (prev.length === 0) return prev
      const last = prev[prev.length - 1]
      const rest = prev.slice(0, -1)
      setEditingContent(last)
      editingContentRef.current = last
      scheduleSave(last)
      return rest
    })
  }

  const handleExitManualEdit = async () => {
    await flushSave()
    setViewMode('render')
    setHistoryStack([])
  }

  // Ctrl+Z 撤销（仅 manual-edit 态生效）
  useEffect(() => {
    if (viewMode !== 'manual-edit') return
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey) {
        e.preventDefault()
        handleUndo()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [viewMode])

  const saveBadge = () => {
    switch (saveStatus) {
      case 'saving': return <span className="flex items-center gap-1 text-xs text-dark-muted"><Loader2 className="w-3 h-3 animate-spin" />保存中…</span>
      case 'saved': return <span className="flex items-center gap-1 text-xs text-green-400"><Check className="w-3 h-3" />已保存</span>
      case 'error': return <span className="flex items-center gap-1 text-xs text-red-400"><AlertCircle className="w-3 h-3" />保存失败</span>
      default: return dirty ? <span className="text-xs text-dark-muted">未保存</span> : null
    }
  }

  return (
    <div className="h-full flex flex-col">
      {/* 顶部工具栏：下拉选择 + 编辑按钮 */}
      <div className="border-b border-dark-border px-4 py-3 flex items-center gap-3 bg-dark-bg/50">
        {/* 下拉选择器 */}
        <div className="relative flex-1 max-w-md">
          <button
            onClick={() => setDropdownOpen(o => !o)}
            className="w-full flex items-center justify-between gap-2 px-3 py-2 bg-dark-surface border border-dark-border rounded-lg text-sm hover:border-primary-500/50 transition-colors"
          >
            <div className="flex items-center gap-2 min-w-0">
              <FileText className="w-4 h-4 text-primary-500 shrink-0" />
              <span className="truncate text-dark-text">
                {selectedPaper ? selectedPaper.title : (loading ? '加载中…' : '暂无报告')}
              </span>
            </div>
            <ChevronDown className={`w-4 h-4 text-dark-muted shrink-0 transition-transform ${dropdownOpen ? 'rotate-180' : ''}`} />
          </button>
          <AnimatePresence>
            {dropdownOpen && (
              <motion.div
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.15 }}
                className="absolute z-20 mt-1 w-full bg-dark-surface border border-dark-border rounded-lg shadow-xl overflow-hidden"
              >
                <div className="p-2 border-b border-dark-border">
                  <div className="relative">
                    <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-dark-muted" />
                    <input
                      autoFocus
                      type="text"
                      placeholder="搜索报告..."
                      value={searchQuery}
                      onChange={e => setSearchQuery(e.target.value)}
                      className="w-full bg-dark-bg border border-dark-border rounded pl-7 pr-2 py-1.5 text-xs focus:outline-none focus:border-primary-500"
                    />
                  </div>
                </div>
                <div className="max-h-80 overflow-auto">
                  {filteredPapers.length === 0 ? (
                    <div className="px-3 py-4 text-center text-xs text-dark-muted">无匹配报告</div>
                  ) : filteredPapers.map(paper => (
                    <div
                      key={paper.id}
                      onClick={() => { setDropdownOpen(false); setSearchQuery(''); loadPaper(paper) }}
                      className={`px-3 py-2 cursor-pointer hover:bg-primary-500/10 flex items-start justify-between gap-2 ${selectedPaper?.id === paper.id ? 'bg-primary-500/10' : ''}`}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="text-sm text-dark-text truncate">{paper.title}</div>
                        <div className="flex items-center gap-1 text-[10px] text-dark-muted mt-0.5">
                          <Calendar className="w-2.5 h-2.5" />
                          {paper.createdAt}
                          <span className="mx-1">·</span>
                          {paper.wordCount.toLocaleString()} 字
                        </div>
                      </div>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDelete(paper) }}
                        className="p-1 hover:bg-dark-border/50 rounded text-dark-muted hover:text-red-400 shrink-0"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* 右侧操作区 */}
        <div className="flex items-center gap-2 shrink-0">
          {viewMode === 'manual-edit' && (
            <>
              {saveBadge()}
              <button
                onClick={handleUndo}
                disabled={historyStack.length === 0}
                className="flex items-center gap-1.5 px-3 py-2 bg-dark-surface border border-dark-border rounded-lg text-xs text-dark-text hover:border-primary-500/50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                title="撤销（Ctrl+Z，仅本次会话）"
              >
                <X className="w-3.5 h-3.5" />
                撤销
              </button>
              <button
                onClick={handleExitManualEdit}
                className="flex items-center gap-1.5 px-3 py-2 bg-primary-500 rounded-lg text-xs text-white hover:bg-primary-600 transition-colors"
              >
                <Eye className="w-3.5 h-3.5" />
                完成编辑
              </button>
            </>
          )}
          {viewMode === 'render' && (
            <>
              <div className="relative">
                <button
                  onClick={() => setEditMenuOpen(o => !o)}
                  disabled={!selectedPaper}
                  className="flex items-center gap-1.5 px-4 py-2 bg-primary-500 rounded-lg text-sm text-white hover:bg-primary-600 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <Edit3 className="w-4 h-4" />
                  编辑
                  <ChevronDown className={`w-3.5 h-3.5 transition-transform ${editMenuOpen ? 'rotate-180' : ''}`} />
                </button>
                <AnimatePresence>
                  {editMenuOpen && (
                    <motion.div
                      initial={{ opacity: 0, y: -4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -4 }}
                      transition={{ duration: 0.15 }}
                      className="absolute right-0 z-20 mt-1 w-44 bg-dark-surface border border-dark-border rounded-lg shadow-xl overflow-hidden"
                    >
                      <button
                        onClick={() => handleEditClick({ kind: 'ai' })}
                        className="w-full px-3 py-2.5 flex items-center gap-2 hover:bg-primary-500/10 text-sm text-dark-text text-left"
                      >
                        <Sparkles className="w-4 h-4 text-primary-400" />
                        <div>
                          <div>AI 编辑</div>
                          <div className="text-[10px] text-dark-muted">跳转助手对话修改</div>
                        </div>
                      </button>
                      <button
                        onClick={() => handleEditClick({ kind: 'manual' })}
                        className="w-full px-3 py-2.5 flex items-center gap-2 hover:bg-primary-500/10 text-sm text-dark-text text-left border-t border-dark-border"
                      >
                        <PenLine className="w-4 h-4 text-primary-400" />
                        <div>
                          <div>手动编辑</div>
                          <div className="text-[10px] text-dark-muted">直接编辑，自动保存</div>
                        </div>
                      </button>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
              <button
                onClick={() => selectedPaper && handleDownload(selectedPaper)}
                disabled={!selectedPaper}
                className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-dark-border rounded-lg text-sm text-dark-text hover:border-primary-500/50 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <Download className="w-4 h-4" />
                下载
              </button>
            </>
          )}
        </div>
      </div>

      {/* 内容区 */}
      <div className="flex-1 overflow-hidden">
        {!selectedPaper ? (
          <div className="h-full flex flex-col items-center justify-center text-dark-muted">
            <FileText className="w-12 h-12 mb-4 opacity-30" />
            <p className="text-sm">{loading ? '加载中…' : '暂无报告，请先在工作流中生成'}</p>
          </div>
        ) : viewMode === 'render' ? (
          <div className="h-full overflow-auto p-6">
            <div className="max-w-3xl mx-auto">
              <article className="paper-reading-result">
                {renderContent ? (
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm, remarkMath]}
                    rehypePlugins={[rehypeKatex]}
                    components={markdownComponents}
                  >
                    {renderContent}
                  </ReactMarkdown>
                ) : (
                  <p className="text-dark-muted text-sm">正在加载…</p>
                )}
              </article>
            </div>
          </div>
        ) : (
          <div className="h-full flex flex-col">
            <div className="px-4 py-1.5 bg-dark-surface/30 border-b border-dark-border text-[11px] text-dark-muted flex items-center gap-2">
              <PenLine className="w-3 h-3" />
              手动编辑模式 · 自动保存（1.5s 防抖）· Ctrl+Z 撤销（仅本次会话）
            </div>
            <textarea
              value={editingContent}
              onChange={handleTextareaChange}
              className="flex-1 w-full bg-dark-bg text-dark-text p-6 font-mono text-sm leading-relaxed resize-none focus:outline-none"
              spellCheck={false}
              placeholder="编辑 markdown 内容..."
            />
          </div>
        )}
      </div>
    </div>
  )
}
