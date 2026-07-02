import { useState, useEffect, useCallback, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BookOpen, Search, ChevronRight, FileText, Calendar, User, Users,
  Tag, ExternalLink, File, PanelLeftClose, PanelLeft, Maximize2,
  ArrowLeft, FolderOpen, FolderClosed, Copy, Check,
  Trash2, Plus, Upload, Type, Download, Sparkles, Microscope, Globe, BookOpenCheck, ChevronDown
} from 'lucide-react'

// 把后端返回的相对路径（如 data/papers/具体表征/pdfs/xxx.pdf）转成可访问的 URL。
// 路径里可能含中文/空格等字符，直接放进 iframe src 会导致请求失败
// （Failed to load PDF document）。这里对每一段单独 encodeURIComponent，
// 保留 '/' 作为路径分隔符。
function toPdfUrl(pdfPath: string): string {
  if (!pdfPath) return ''
  const normalized = pdfPath.replace(/^data\//, '/data/')
  const isAbsolute = normalized.startsWith('/data/')
  const root = isAbsolute ? '/data/' : ''
  const rest = isAbsolute ? normalized.slice('/data/'.length) : normalized
  const encoded = rest.split('/').map(encodeURIComponent).join('/')
  return root + encoded
}

interface Paper {
  paper_id: string
  title: string
  authors: string[] | string
  abstract: string
  published_date: string
  pdf_url: string
  keywords: string[]
  citations?: number
  pdf_path?: string
  journal?: string
  conference?: string
  doi?: string
  arxiv_id?: string
  source?: string
}

interface TopicGroup {
  name: string
  displayName: string
  count: number
  papers: Paper[]
}

interface KnowledgeBaseProps {
  onReadPaper?: (paperTitle: string, mode: 'snap' | 'lens' | 'sphere') => void
}

export default function KnowledgeBase({ onReadPaper }: KnowledgeBaseProps) {
  const [topics, setTopics] = useState<TopicGroup[]>([])
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null)
  const [activeTab, setActiveTab] = useState<'detail' | 'pdf'>('detail')
  const [sidebarExpanded, setSidebarExpanded] = useState(true)
  const [pdfFullscreen, setPdfFullscreen] = useState(false)
  const [showCitation, setShowCitation] = useState(false)
  const [copiedFormat, setCopiedFormat] = useState<string | null>(null)
  // 新增状态
  const [showNewTopic, setShowNewTopic] = useState(false)
  const [newTopicName, setNewTopicName] = useState('')
  const [showAddPaper, setShowAddPaper] = useState(false)
  const [addMode, setAddMode] = useState<'pdf' | 'citation'>('pdf')
  const [citationText, setCitationText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // 获取论文 / 阅读论文 下拉与状态
  const [fetchMenuOpen, setFetchMenuOpen] = useState(false)
  const [readMenuOpen, setReadMenuOpen] = useState(false)
  const [fetching, setFetching] = useState(false)
  const [fetchMessage, setFetchMessage] = useState<{ ok: boolean; text: string } | null>(null)
  const uploadPdfRef = useRef<HTMLInputElement>(null)

  // 加载知识库数据
  const loadKnowledgeBase = useCallback(async () => {
    try {
      const topicGroups: TopicGroup[] = []
      try {
        const topicsResponse = await fetch('/api/papers/topics')
        if (topicsResponse.ok) {
          const topicsData = await topicsResponse.json()
          for (const topic of topicsData.topics || []) {
            try {
              // 加 cache 查询参数避免浏览器缓存 FileResponse，
              // 否则删除/新增论文后端已变更，前端仍读到旧 JSON
              const topicResponse = await fetch(`/${topic.file}?_t=${Date.now()}`)
              if (topicResponse.ok) {
                const topicData = await topicResponse.json()
                topicGroups.push({
                  name: topic.name,
                  displayName: topic.displayName,
                  count: topicData.papers?.length || 0,
                  papers: topicData.papers || []
                })
              }
            } catch (e) {
              console.warn(`Failed to load topic: ${topic.name}`, e)
            }
          }
        }
      } catch (e) {
        console.warn('Failed to fetch topics from API', e)
      }
      topicGroups.sort((a, b) => b.count - a.count)
      setTopics(topicGroups)
      if (topicGroups.length > 0 && !selectedTopic) {
        setSelectedTopic(topicGroups[0].name)
      }
      // 刷新后用「函数式更新」同步当前选中论文的最新字段（如 pdf_path），
      // 仅当 paper_id 仍匹配当前选中项时才替换，避免覆盖用户在此期间切换到的别的论文
      setSelectedPaper(prev => {
        if (!prev) return prev
        for (const t of topicGroups) {
          const p = t.papers.find(pp => pp.paper_id === prev.paper_id)
          if (p) return p
        }
        return prev
      })
    } catch (error) {
      console.error('加载知识库失败:', error)
    }
  }, [selectedTopic])

  useEffect(() => {
    loadKnowledgeBase()
  }, [])

  const currentTopic = topics.find(t => t.name === selectedTopic)
  const currentPapers = currentTopic?.papers || []

  const filteredPapers = currentPapers.filter(paper => {
    const authorStr = typeof paper.authors === 'string'
      ? paper.authors.toLowerCase()
      : paper.authors?.join(' ').toLowerCase() || ''
    return (
      paper.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      paper.abstract?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      authorStr.includes(searchQuery.toLowerCase())
    )
  })

  const formatAuthors = (authors: string[] | string) => {
    if (typeof authors === 'string') {
      if (!authors || authors.length === 0) return '未知作者'
      const authorList = authors.split(';').map(a => a.trim()).filter(a => a)
      if (authorList.length <= 3) return authorList.join(', ')
      return `${authorList.slice(0, 3).join(', ')} 等`
    }
    if (!authors || authors.length === 0) return '未知作者'
    if (authors.length <= 3) return authors.join(', ')
    return `${authors.slice(0, 3).join(', ')} 等`
  }

  const extractYear = (dateStr: string) => {
    if (!dateStr) return ''
    const match = dateStr.match(/\d{4}/)
    return match ? match[0] : ''
  }

  const getSourceType = (paper: Paper): 'arxiv' | 'journal' | 'conference' | 'unknown' => {
    if (paper.source === 'arxiv' || paper.arxiv_id || paper.paper_id?.match(/^\d{4}\.\d{4,5}v?\d*$/)) {
      return 'arxiv'
    }
    if (paper.journal) return 'journal'
    if (paper.conference) return 'conference'
    return 'unknown'
  }

  const formatAuthorsForCitation = (authors: string[] | string, format: 'APA' | 'MLA' | 'Chicago' | 'GB') => {
    const list = typeof authors === 'string'
      ? authors.split(';').map(a => a.trim()).filter(a => a)
      : authors || []
    if (list.length === 0) return ''

    if (format === 'APA') {
      if (list.length <= 7) {
        return list.map(a => {
          const parts = a.split(',').map(p => p.trim())
          if (parts.length >= 2) return `${parts[0]}, ${parts[1]?.[0] || ''}.`
          return a
        }).join(', ')
      }
      return list.slice(0, 7).map(a => {
        const parts = a.split(',').map(p => p.trim())
        if (parts.length >= 2) return `${parts[0]}, ${parts[1]?.[0] || ''}.`
        return a
      }).join(', ') + ', ... ' + list[list.length - 1]
    }
    if (format === 'MLA') {
      const formatted = list.map(a => {
        const parts = a.split(',').map(p => p.trim())
        if (parts.length >= 2) return `${parts[0]}, ${parts[1]}`
        return a
      })
      if (formatted.length === 1) return formatted[0]
      if (formatted.length === 2) return `${formatted[0]}, and ${formatted[1]}`
      return `${formatted[0]}, et al.`
    }
    if (format === 'Chicago') {
      return list.map(a => {
        const parts = a.split(',').map(p => p.trim())
        if (parts.length >= 2) return `${parts[0]} ${parts[1]}`
        return a
      }).join(', ')
    }
    return list.map(a => {
      const parts = a.split(',').map(p => p.trim())
      if (parts.length >= 2) return `${parts[0].toUpperCase()} ${parts[1].toUpperCase()}`
      return a.toUpperCase()
    }).join(', ')
  }

  const generateCitation = useCallback((paper: Paper, format: string) => {
    const title = paper.title || ''
    const year = extractYear(paper.published_date)
    const sourceType = getSourceType(paper)
    let doiUrl = ''
    if (paper.doi) {
      const cleanDoi = paper.doi.replace(/v\d+$/, '')
      doiUrl = cleanDoi.startsWith('http') ? cleanDoi : `https://doi.org/${cleanDoi}`
    } else if (sourceType === 'arxiv' && paper.paper_id) {
      const arxivId = paper.paper_id.match(/^(\d{4}\.\d{4,5})v?\d*$/)?.[1] || paper.paper_id.replace(/v\d+$/, '')
      doiUrl = `https://doi.org/10.48550/arXiv.${arxivId}`
    }

    if (sourceType === 'arxiv') {
      const authors = formatAuthorsForCitation(paper.authors, format as 'APA' | 'MLA' | 'Chicago' | 'GB')
      switch (format) {
        case 'APA': return `${authors}${year ? ` (${year})` : ''}. ${title ? title + '.' : ''} arXiv. ${doiUrl}`
        case 'MLA': return `${authors}. "${title}." arXiv${year ? `, ${year}` : ''}${doiUrl ? `, ${doiUrl}` : ''}.`
        case 'Chicago': return `${authors}${year ? ` ${year}` : ''}. "${title}." arXiv. ${doiUrl}.`
        case 'GB/T 7714-2015': return `${formatAuthorsForCitation(paper.authors, 'GB')}. ${title ? title + '[EB/OL].' : ''} arXiv${year ? `, ${year}` : ''}. ${doiUrl}`
        default: return ''
      }
    }

    const venue = paper.journal || paper.conference || ''
    const authors = formatAuthorsForCitation(paper.authors, format as 'APA' | 'MLA' | 'Chicago' | 'GB')
    switch (format) {
      case 'APA': return `${authors}${year ? ` (${year})` : ''}. ${title ? title + '.' : ''} ${venue ? venue + '.' : ''} ${doiUrl}`
      case 'MLA': return `${authors}. "${title}." ${venue}${year ? `, ${year}` : ''}${doiUrl ? `, ${doiUrl}` : ''}.`
      case 'Chicago': return `${authors}${year ? ` ${year}` : ''}. "${title}." ${venue}. ${doiUrl}.`
      case 'GB/T 7714-2015': return `${formatAuthorsForCitation(paper.authors, 'GB')}. ${title ? title + '[J].' : ''} ${venue ? venue + ',' : ''}${year ? ` ${year}.` : ''} ${doiUrl}`
      default: return ''
    }
  }, [])

  const copyToClipboard = async (text: string, format: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedFormat(format)
      setTimeout(() => setCopiedFormat(null), 2000)
    } catch (err) {
      console.error('复制失败:', err)
    }
  }

  // ========== CRUD 操作 ==========

  const handleDeletePaper = async () => {
    if (!selectedPaper || !selectedTopic) return
    if (!confirm(`确定要删除论文「${selectedPaper.title}」吗？此操作不可恢复。`)) return
    try {
      const res = await fetch(`/api/papers/${selectedTopic}/${selectedPaper.paper_id}`, { method: 'DELETE' })
      if (res.ok) {
        setSelectedPaper(null)
        loadKnowledgeBase()
      } else {
        alert('删除失败')
      }
    } catch {
      alert('删除失败')
    }
  }

  const handleCreateTopic = async () => {
    if (!newTopicName.trim()) return
    setSubmitting(true)
    try {
      const res = await fetch('/api/papers/topics', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newTopicName.trim() }),
      })
      if (res.ok) {
        setNewTopicName('')
        setShowNewTopic(false)
        loadKnowledgeBase()
      } else {
        const data = await res.json()
        alert(data.detail || '创建失败')
      }
    } catch {
      alert('创建失败')
    }
    setSubmitting(false)
  }

  const handleDeleteTopic = async (topicName: string, e: React.MouseEvent) => {
    e.stopPropagation()
    const topic = topics.find(t => t.name === topicName)
    if (!confirm(`确定要删除分类「${topic?.displayName || topicName}」及其所有论文吗？`)) return
    try {
      const res = await fetch(`/api/papers/topics/${topicName}`, { method: 'DELETE' })
      if (res.ok) {
        if (selectedTopic === topicName) {
          setSelectedPaper(null)
          setSelectedTopic(null)
        }
        loadKnowledgeBase()
      } else {
        alert('删除失败')
      }
    } catch {
      alert('删除失败')
    }
  }

  const handleUploadPdf = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!selectedTopic || !e.target.files?.length) return
    setSubmitting(true)
    try {
      const formData = new FormData()
      formData.append('file', e.target.files[0])
      const res = await fetch(`/api/papers/${selectedTopic}/import-pdf`, {
        method: 'POST',
        body: formData,
      })
      if (res.ok) {
        setShowAddPaper(false)
        loadKnowledgeBase()
      } else {
        const data = await res.json()
        alert(data.detail || '导入失败')
      }
    } catch {
      alert('导入失败')
    }
    setSubmitting(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleImportCitation = async () => {
    if (!selectedTopic || !citationText.trim()) return
    setSubmitting(true)
    try {
      const res = await fetch(`/api/papers/${selectedTopic}/import-citation`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: citationText.trim() }),
      })
      if (res.ok) {
        setCitationText('')
        setShowAddPaper(false)
        loadKnowledgeBase()
      } else {
        const data = await res.json()
        alert(data.detail || '导入失败')
      }
    } catch {
      alert('导入失败')
    }
    setSubmitting(false)
  }

  // 在线获取论文 PDF：调用 MCP 检索 + 多级回退下载，挂到当前条目
  const handleFetchOnline = async () => {
    if (!selectedTopic || !selectedPaper) return
    setFetchMenuOpen(false)
    setFetching(true)
    setFetchMessage(null)
    try {
      const res = await fetch(`/api/papers/${selectedTopic}/${selectedPaper.paper_id}/fetch-online`, { method: 'POST' })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data.success) {
        setFetchMessage({ ok: true, text: data.message || '已获取并关联 PDF' })
        // 刷新后由 loadKnowledgeBase 内部按 paper_id 同步选中论文的最新 pdf_path
        await loadKnowledgeBase()
      } else {
        setFetchMessage({ ok: false, text: data.message || data.detail || '获取失败' })
      }
    } catch (e) {
      setFetchMessage({ ok: false, text: '获取失败，请稍后重试' })
    }
    setFetching(false)
  }

  // 导入本地 PDF：用户自己下载好后上传，挂到当前条目
  const handleUploadPdfAttach = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!selectedTopic || !selectedPaper || !e.target.files?.length) return
    setFetchMenuOpen(false)
    setFetching(true)
    setFetchMessage(null)
    try {
      const formData = new FormData()
      formData.append('file', e.target.files[0])
      const res = await fetch(`/api/papers/${selectedTopic}/${selectedPaper.paper_id}/upload-pdf`, {
        method: 'POST',
        body: formData,
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data.success) {
        setFetchMessage({ ok: true, text: data.message || 'PDF 已上传并关联' })
        await loadKnowledgeBase()
      } else {
        setFetchMessage({ ok: false, text: data.detail || '上传失败' })
      }
    } catch {
      setFetchMessage({ ok: false, text: '上传失败' })
    }
    setFetching(false)
    if (uploadPdfRef.current) uploadPdfRef.current.value = ''
  }

  const handleReadPaper = (mode: 'snap' | 'lens' | 'sphere') => {
    if (!selectedPaper) return
    setReadMenuOpen(false)
    onReadPaper?.(selectedPaper.title, mode)
  }

  // ========== 渲染 ==========

  if (pdfFullscreen && selectedPaper?.pdf_path) {
    return (
      <div className="h-full bg-black flex flex-col">
        <div className="h-14 bg-dark-surface border-b border-dark-border flex items-center justify-between px-4 shrink-0">
          <div className="flex items-center gap-3">
            <button onClick={() => setPdfFullscreen(false)} className="flex items-center gap-2 px-3 py-1.5 bg-dark-bg rounded-lg text-dark-text hover:bg-dark-border transition-colors">
              <ArrowLeft className="w-4 h-4" />返回
            </button>
            <span className="text-dark-text font-medium truncate max-w-md">{selectedPaper.title}</span>
          </div>
          <div className="flex items-center gap-2">
            {selectedPaper.pdf_url && (
              <a href={selectedPaper.pdf_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 px-3 py-1.5 bg-dark-bg rounded-lg text-dark-text hover:bg-dark-border transition-colors">
                <ExternalLink className="w-4 h-4" />查看原文
              </a>
            )}
          </div>
        </div>
        <iframe src={toPdfUrl(selectedPaper.pdf_path)} className="w-full h-full" title="PDF Preview" />
      </div>
    )
  }

  return (
    <div className="h-full flex">
      {/* 左侧可折叠侧边栏 */}
      <AnimatePresence mode="wait">
        {sidebarExpanded ? (
          <motion.div
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 320, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="h-full flex flex-col border-r border-dark-border bg-dark-surface shrink-0"
          >
            {/* 标题栏 */}
            <div className="p-3 border-b border-dark-border flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2 text-dark-text">
                <BookOpen className="w-4 h-4 text-primary-500" />
                <span className="font-display font-semibold text-sm">知识库</span>
              </div>
              <button onClick={() => setSidebarExpanded(false)} className="p-1.5 hover:bg-dark-border/50 rounded text-dark-muted hover:text-dark-text" title="收起侧边栏">
                <PanelLeftClose className="w-4 h-4" />
              </button>
            </div>

            {/* 分类列表 */}
            <div className="p-2 border-b border-dark-border max-h-48 overflow-auto shrink-0">
              <div className="flex items-center justify-between mb-2 px-2">
                <span className="text-xs text-dark-muted">分类</span>
                <button onClick={() => setShowNewTopic(!showNewTopic)} className="p-1 hover:bg-dark-border/50 rounded text-primary-400 hover:text-primary-300" title="新建分类">
                  <Plus className="w-3.5 h-3.5" />
                </button>
              </div>

              {/* 新建分类输入框 */}
              <AnimatePresence>
                {showNewTopic && (
                  <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="mb-2 overflow-hidden">
                    <div className="flex gap-1">
                      <input
                        type="text" value={newTopicName} onChange={(e) => setNewTopicName(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleCreateTopic()}
                        placeholder="输入分类名称..."
                        className="flex-1 bg-dark-bg border border-dark-border rounded px-2 py-1 text-xs text-dark-text focus:outline-none focus:border-primary-500 placeholder:text-dark-muted"
                      />
                      <button onClick={handleCreateTopic} disabled={submitting || !newTopicName.trim()} className="px-2 py-1 bg-primary-500 text-white rounded text-xs hover:bg-primary-600 disabled:opacity-50">
                        创建
                      </button>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              <div className="space-y-0.5">
                {topics.map((topic) => (
                  <div key={topic.name} className="group relative">
                    <motion.button
                      onClick={() => { setSelectedTopic(topic.name); setSelectedPaper(null) }}
                      className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg transition-all duration-200 text-left
                        ${selectedTopic === topic.name ? 'bg-primary-500/20 text-primary-400' : 'text-dark-muted hover:bg-dark-border/30 hover:text-dark-text'}`}
                    >
                      {selectedTopic === topic.name ? <FolderOpen className="w-4 h-4 shrink-0" /> : <FolderClosed className="w-4 h-4 shrink-0" />}
                      <span className="text-xs font-medium truncate flex-1">{topic.displayName}</span>
                      <span className="text-xs px-1.5 py-0.5 rounded-full bg-dark-border/50 shrink-0">{topic.count}</span>
                    </motion.button>
                    <button
                      onClick={(e) => handleDeleteTopic(topic.name, e)}
                      className="absolute right-1 top-1/2 -translate-y-1/2 p-0.5 rounded text-dark-muted/0 hover:text-red-400 hover:bg-red-400/10 opacity-0 group-hover:opacity-100 transition-all"
                      title="删除分类"
                    >
                      <Trash2 className="w-3 h-3" />
                    </button>
                  </div>
                ))}
              </div>
            </div>

            {/* 搜索栏 */}
            <div className="p-3 border-b border-dark-border shrink-0">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-dark-muted" />
                <input
                  type="text" placeholder="搜索论文..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full bg-dark-bg border border-dark-border rounded-lg pl-8 pr-3 py-1.5 text-xs focus:outline-none focus:border-primary-500 placeholder:text-dark-muted"
                />
              </div>
              <div className="mt-1.5 flex items-center justify-between">
                <span className="text-xs text-dark-muted">
                  {currentTopic?.displayName} · {filteredPapers.length} 篇
                </span>
                {selectedTopic && (
                  <button onClick={() => setShowAddPaper(!showAddPaper)} className="flex items-center gap-1 text-xs text-primary-400 hover:text-primary-300">
                    <Plus className="w-3 h-3" />添加论文
                  </button>
                )}
              </div>
            </div>

            {/* 添加论文面板 */}
            <AnimatePresence>
              {showAddPaper && selectedTopic && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="border-b border-dark-border overflow-hidden shrink-0">
                  <div className="p-3 space-y-2">
                    <div className="flex bg-dark-bg rounded-lg p-0.5">
                      <button onClick={() => setAddMode('pdf')} className={`flex-1 px-2 py-1 rounded-md text-xs font-medium transition-colors ${addMode === 'pdf' ? 'bg-dark-surface text-dark-text shadow-sm' : 'text-dark-muted hover:text-dark-text'}`}>
                        <Upload className="w-3 h-3 inline mr-1" />上传文件
                      </button>
                      <button onClick={() => setAddMode('citation')} className={`flex-1 px-2 py-1 rounded-md text-xs font-medium transition-colors ${addMode === 'citation' ? 'bg-dark-surface text-dark-text shadow-sm' : 'text-dark-muted hover:text-dark-text'}`}>
                        <Type className="w-3 h-3 inline mr-1" />导入引用
                      </button>
                    </div>
                    {addMode === 'pdf' ? (
                      <div>
                        <input ref={fileInputRef} type="file" accept=".pdf,.caj" onChange={handleUploadPdf} className="hidden" />
                        <button onClick={() => fileInputRef.current?.click()} disabled={submitting} className="w-full py-2 border-2 border-dashed border-dark-border rounded-lg text-xs text-dark-muted hover:border-primary-500/50 hover:text-primary-400 transition-colors disabled:opacity-50">
                          {submitting ? '导入中...' : '点击选择 PDF / CAJ 文件'}
                        </button>
                      </div>
                    ) : (
                      <div className="space-y-2">
                        <textarea
                          value={citationText} onChange={(e) => setCitationText(e.target.value)}
                          placeholder="粘贴 BibTeX / APA / 其他引用格式..."
                          className="w-full bg-dark-bg border border-dark-border rounded-lg px-2 py-1.5 text-xs text-dark-text resize-none focus:outline-none focus:border-primary-500 placeholder:text-dark-muted"
                          rows={4}
                        />
                        <button onClick={handleImportCitation} disabled={submitting || !citationText.trim()} className="w-full py-1.5 bg-primary-500 text-white rounded-lg text-xs hover:bg-primary-600 disabled:opacity-50">
                          {submitting ? '解析中...' : '解析并导入'}
                        </button>
                      </div>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* 论文列表 */}
            <div className="flex-1 overflow-auto p-2 space-y-1.5">
              {filteredPapers.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-24 text-dark-muted">
                  <FileText className="w-6 h-6 mb-1 opacity-50" />
                  <span className="text-xs">暂无论文</span>
                </div>
              ) : (
                filteredPapers.map((paper) => (
                  <motion.div
                    key={paper.paper_id}
                    onClick={() => { setSelectedPaper(paper); setActiveTab('detail') }}
                    className={`p-2.5 rounded-lg border cursor-pointer transition-all duration-200
                      ${selectedPaper?.paper_id === paper.paper_id ? 'bg-primary-500/15 border-primary-500/50' : 'bg-dark-bg border-dark-border hover:border-primary-500/30'}`}
                  >
                    <h3 className="font-medium text-dark-text text-xs line-clamp-2 mb-1.5 leading-snug">{paper.title}</h3>
                    <div className="flex items-center justify-between text-[10px] text-dark-muted">
                      <span className="truncate flex-1">{formatAuthors(paper.authors)}</span>
                      <span className="shrink-0 ml-2">{paper.published_date || '未知'}</span>
                    </div>
                  </motion.div>
                ))
              )}
            </div>
          </motion.div>
        ) : (
          <motion.div
            initial={{ width: 0, opacity: 0 }}
            animate={{ width: 48, opacity: 1 }}
            exit={{ width: 0, opacity: 0 }}
            className="h-full flex flex-col items-center py-3 border-r border-dark-border bg-dark-surface shrink-0"
          >
            <button onClick={() => setSidebarExpanded(true)} className="p-2 hover:bg-dark-border/50 rounded-lg text-dark-muted hover:text-dark-text" title="展开侧边栏">
              <PanelLeft className="w-5 h-5" />
            </button>
            <div className="mt-4 flex flex-col gap-2">
              {topics.map((topic) => (
                <button key={topic.name} onClick={() => { setSelectedTopic(topic.name); setSidebarExpanded(true) }}
                  className={`p-2 rounded-lg transition-colors ${selectedTopic === topic.name ? 'bg-primary-500/20 text-primary-400' : 'text-dark-muted hover:bg-dark-border/30 hover:text-dark-text'}`}
                  title={topic.displayName}
                >
                  <Tag className="w-4 h-4" />
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 右侧主区域 */}
      <div className="flex-1 flex flex-col min-w-0">
        {selectedPaper ? (
          <>
            {/* 顶部操作栏 */}
            <div className="h-14 border-b border-dark-border flex items-center justify-between px-4 shrink-0 bg-dark-surface">
              <div className="flex items-center gap-4 min-w-0">
                {!sidebarExpanded && (
                  <button onClick={() => setSidebarExpanded(true)} className="p-1.5 hover:bg-dark-border/50 rounded text-dark-muted hover:text-dark-text shrink-0">
                    <PanelLeft className="w-4 h-4" />
                  </button>
                )}
                <h2 className="font-display font-semibold text-dark-text text-sm truncate">{selectedPaper.title}</h2>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {/* 标签页切换 */}
                <div className="flex bg-dark-bg rounded-lg p-0.5 mr-2">
                  <button onClick={() => setActiveTab('detail')} className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${activeTab === 'detail' ? 'bg-dark-surface text-dark-text shadow-sm' : 'text-dark-muted hover:text-dark-text'}`}>
                    详情
                  </button>
                  {selectedPaper.pdf_path && (
                    <button onClick={() => setActiveTab('pdf')} className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${activeTab === 'pdf' ? 'bg-dark-surface text-dark-text shadow-sm' : 'text-dark-muted hover:text-dark-text'}`}>
                      PDF阅读
                    </button>
                  )}
                </div>
                {activeTab === 'pdf' && selectedPaper.pdf_path && (
                  <button onClick={() => setPdfFullscreen(true)} className="p-2 hover:bg-dark-border/50 rounded-lg text-dark-muted hover:text-dark-text" title="全屏阅读">
                    <Maximize2 className="w-4 h-4" />
                  </button>
                )}

                {/* 无 PDF 时：获取论文下拉（在线搜索 / 导入） */}
                {!selectedPaper.pdf_path && (
                  <div className="relative">
                    <button
                      onClick={() => { setFetchMenuOpen(v => !v); setReadMenuOpen(false) }}
                      disabled={fetching}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-500/10 border border-primary-500/30 rounded-lg text-xs text-primary-400 hover:bg-primary-500/20 hover:border-primary-500/50 transition-colors disabled:opacity-50"
                    >
                      <Download className="w-3.5 h-3.5" />
                      {fetching ? '获取中...' : '获取论文'}
                      <ChevronDown className="w-3 h-3" />
                    </button>
                    <input ref={uploadPdfRef} type="file" accept=".pdf,.caj" onChange={handleUploadPdfAttach} className="hidden" />
                    {fetchMenuOpen && (
                      <div className="absolute right-0 top-full mt-1 w-40 bg-dark-surface border border-dark-border rounded-lg shadow-lg z-20 overflow-hidden">
                        <button onClick={handleFetchOnline} className="w-full flex items-center gap-2 px-3 py-2 text-xs text-dark-text hover:bg-dark-border/30 transition-colors">
                          <Search className="w-3.5 h-3.5 text-primary-400" />在线搜索
                        </button>
                        <button onClick={() => { setFetchMenuOpen(false); uploadPdfRef.current?.click() }} className="w-full flex items-center gap-2 px-3 py-2 text-xs text-dark-text hover:bg-dark-border/30 transition-colors">
                          <Upload className="w-3.5 h-3.5 text-primary-400" />导入
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {/* 阅读该论文：三种精读模式，跳转到新会话 */}
                {selectedPaper.pdf_path && (
                  <div className="relative">
                    <button
                      onClick={() => { setReadMenuOpen(v => !v); setFetchMenuOpen(false) }}
                      className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-500/10 border border-primary-500/30 rounded-lg text-xs text-primary-400 hover:bg-primary-500/20 hover:border-primary-500/50 transition-colors"
                    >
                      <BookOpenCheck className="w-3.5 h-3.5" />AI读论文
                      <ChevronDown className="w-3 h-3" />
                    </button>
                    {readMenuOpen && (
                      <div className="absolute right-0 top-full mt-1 w-48 bg-dark-surface border border-dark-border rounded-lg shadow-lg z-20 overflow-hidden">
                        {([
                          { mode: 'snap' as const, icon: Sparkles, label: '速览模式', desc: '30秒核心贡献' },
                          { mode: 'lens' as const, icon: Microscope, label: '深度精读', desc: '公式/算法/实验' },
                          { mode: 'sphere' as const, icon: Globe, label: '研究全景', desc: '参考文献与聚类' },
                        ]).map(opt => {
                          const Icon = opt.icon
                          return (
                            <button
                              key={opt.mode}
                              onClick={() => handleReadPaper(opt.mode)}
                              className="w-full flex items-start gap-2 px-3 py-2 text-left hover:bg-dark-border/30 transition-colors"
                            >
                              <Icon className="w-3.5 h-3.5 text-primary-400 mt-0.5 shrink-0" />
                              <div className="min-w-0">
                                <div className="text-xs text-dark-text">{opt.label}</div>
                                <div className="text-[10px] text-dark-muted">{opt.desc}</div>
                              </div>
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )}

                {selectedPaper.pdf_url && (
                  <a href={selectedPaper.pdf_url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1.5 px-3 py-1.5 bg-dark-bg border border-dark-border rounded-lg text-xs text-dark-text hover:border-primary-500/50 transition-colors">
                    <ExternalLink className="w-3.5 h-3.5" />原文
                  </a>
                )}
                {/* 删除按钮 */}
                <button onClick={handleDeletePaper} className="flex items-center gap-1.5 px-3 py-1.5 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400 hover:bg-red-500/20 hover:border-red-500/50 transition-colors">
                  <Trash2 className="w-3.5 h-3.5" />删除
                </button>
              </div>
            </div>

            {/* 获取论文反馈消息 */}
            {fetchMessage && (
              <div className={`px-4 py-1.5 text-xs border-b ${fetchMessage.ok ? 'bg-green-500/10 text-green-400 border-green-500/20' : 'bg-red-500/10 text-red-400 border-red-500/20'}`}>
                {fetchMessage.text}
              </div>
            )}

            {/* 内容区域 */}
            <div className="flex-1 overflow-hidden">
              {activeTab === 'detail' ? (
                <div className="h-full overflow-auto p-6">
                  <div className="max-w-3xl mx-auto space-y-5">
                    <h1 className="text-lg font-display font-bold text-dark-text leading-snug">{selectedPaper.title}</h1>
                    <div className="flex flex-wrap gap-y-2 text-sm">
                      <div className="flex items-center gap-1.5 mr-4">
                        <User className="w-3.5 h-3.5 text-dark-muted" />
                        <span className="text-dark-muted">作者：</span>
                        <span className="text-dark-text">{formatAuthors(selectedPaper.authors)}</span>
                      </div>
                      <div className="flex items-center gap-1.5 mr-4">
                        <Calendar className="w-3.5 h-3.5 text-dark-muted" />
                        <span className="text-dark-muted">日期：</span>
                        <span className="text-dark-text">{selectedPaper.published_date || '未知'}</span>
                      </div>
                      {selectedPaper.citations !== undefined && (
                        <div className="flex items-center gap-1.5">
                          <Users className="w-3.5 h-3.5 text-dark-muted" />
                          <span className="text-dark-muted">引用：</span>
                          <span className="text-dark-text">{selectedPaper.citations}</span>
                        </div>
                      )}
                    </div>
                    {selectedPaper.keywords && selectedPaper.keywords.length > 0 && (
                      <div className="flex items-start gap-2 flex-wrap">
                        <Tag className="w-3.5 h-3.5 text-dark-muted mt-0.5" />
                        <div className="flex flex-wrap gap-1">
                          {selectedPaper.keywords.map((kw, i) => (
                            <span key={i} className="px-2 py-0.5 bg-primary-500/15 text-primary-400 rounded text-xs">{kw}</span>
                          ))}
                        </div>
                      </div>
                    )}
                    <div className="pt-4 border-t border-dark-border">
                      <h3 className="text-dark-text font-medium mb-2 flex items-center gap-2">
                        <FileText className="w-4 h-4 text-primary-500" />摘要
                      </h3>
                      <p className="text-dark-text/80 text-sm leading-relaxed whitespace-pre-wrap">{selectedPaper.abstract || '暂无摘要'}</p>
                    </div>
                    <div className="pt-3 border-t border-dark-border">
                      <span className="text-dark-muted text-xs">论文 ID：</span>
                      <code className="text-primary-400 text-xs ml-1.5 bg-dark-bg px-2 py-1 rounded">{selectedPaper.paper_id}</code>
                    </div>
                    {/* 学术引用 */}
                    <div className="pt-3 border-t border-dark-border">
                      <button onClick={() => setShowCitation(!showCitation)} className="flex items-center justify-between w-full text-left">
                        <span className="text-dark-text font-medium text-sm flex items-center gap-2">
                          <FileText className="w-4 h-4 text-primary-500" />学术引用
                        </span>
                        <ChevronRight className={`w-4 h-4 text-dark-muted transition-transform ${showCitation ? 'rotate-90' : ''}`} />
                      </button>
                      <AnimatePresence>
                        {showCitation && (
                          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }} className="overflow-hidden">
                            <div className="pt-3 space-y-2.5">
                              {['APA', 'MLA', 'Chicago', 'GB/T 7714-2015'].map((format) => (
                                <div key={format} className="bg-dark-bg rounded-lg p-2.5">
                                  <div className="flex items-center justify-between mb-1.5">
                                    <span className="text-xs font-medium text-primary-400">{format}</span>
                                    <button onClick={() => copyToClipboard(generateCitation(selectedPaper, format), format)} className="flex items-center gap-1 text-xs text-dark-muted hover:text-primary-400 transition-colors">
                                      {copiedFormat === format ? <><Check className="w-3 h-3" />已复制</> : <><Copy className="w-3 h-3" />复制</>}
                                    </button>
                                  </div>
                                  <p className="text-xs text-dark-text/80 leading-relaxed break-words">{generateCitation(selectedPaper, format)}</p>
                                </div>
                              ))}
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="h-full">
                  {selectedPaper.pdf_path ? (
                    <iframe src={toPdfUrl(selectedPaper.pdf_path)} className="w-full h-full" title="PDF Preview" />
                  ) : (
                    <div className="h-full flex flex-col items-center justify-center text-dark-muted">
                      <File className="w-12 h-12 mb-3 opacity-30" />
                      <p className="text-sm">该论文暂无本地PDF</p>
                      {selectedPaper.pdf_url && (
                        <a href={selectedPaper.pdf_url} target="_blank" rel="noopener noreferrer" className="mt-3 px-4 py-2 bg-primary-500 rounded-lg text-white text-sm hover:bg-primary-600 transition-colors">
                          在原文网站查看
                        </a>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-dark-muted bg-dark-bg">
            <BookOpen className="w-16 h-16 mb-4 opacity-20" />
            <p className="text-sm">从左侧选择论文查看详情</p>
            {topics.length > 0 && (
              <p className="text-xs mt-2 opacity-60">共 {topics.reduce((sum, t) => sum + t.count, 0)} 篇论文 · {topics.length} 个分类</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
