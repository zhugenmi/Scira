import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  BookOpen, Search, ChevronRight, FileText, Calendar, User, Users,
  Tag, X, ExternalLink, File, PanelLeftClose, PanelLeft, Maximize2,
  Minimize2, ArrowLeft, FolderOpen, FolderClosed, Copy, Check
} from 'lucide-react'

interface Paper {
  paper_id: string
  title: string
  authors: string[]
  abstract: string
  published_date: string
  pdf_url: string
  topics: string[]
  citations?: number
  pdf_path?: string
  journal?: string
  conference?: string
  doi?: string
  arxiv_id?: string
  source?: string  // 'arxiv' | 'journal' | 'conference'
}

interface TopicGroup {
  name: string
  displayName: string
  count: number
  papers: Paper[]
}

export default function KnowledgeBase() {
  const [topics, setTopics] = useState<TopicGroup[]>([])
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null)
  const [activeTab, setActiveTab] = useState<'detail' | 'pdf'>('detail')
  const [sidebarExpanded, setSidebarExpanded] = useState(true)
  const [pdfFullscreen, setPdfFullscreen] = useState(false)
  const [showCitation, setShowCitation] = useState(false)
  const [copiedFormat, setCopiedFormat] = useState<string | null>(null)

  // 加载知识库数据
  useEffect(() => {
    const loadKnowledgeBase = async () => {
      try {
        const response = await fetch('/data/papers/all_papers.json')
        if (!response.ok) throw new Error('加载失败')

        const data = await response.json()
        const topicGroups: TopicGroup[] = []

        // 尝试从 API 获取分类数据
        try {
          const topicsResponse = await fetch('/api/papers/topics')
          if (topicsResponse.ok) {
            const topicsData = await topicsResponse.json()
            for (const topic of topicsData.topics || []) {
              try {
                const topicResponse = await fetch(`/${topic.file}`)
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
          console.warn('Failed to fetch topics from API, using fallback', e)
        }

        // 如果没有获取到分类，按 papers 中的 topics 字段分组
        if (topicGroups.length === 0) {
          const topicMap = new Map<string, Paper[]>()

          for (const paper of data.papers || []) {
            const paperTopics = paper.topics || []
            if (paperTopics.length > 0) {
              for (const topic of paperTopics) {
                if (!topicMap.has(topic)) {
                  topicMap.set(topic, [])
                }
                topicMap.get(topic)!.push(paper)
              }
            } else {
              if (!topicMap.has('general')) {
                topicMap.set('general', [])
              }
              topicMap.get('general')!.push(paper)
            }
          }

          topicMap.forEach((papers, topic) => {
            topicGroups.push({
              name: topic.toLowerCase().replace(/\s+/g, '_'),
              displayName: topic,
              count: papers.length,
              papers
            })
          })
        }

        topicGroups.sort((a, b) => b.count - a.count)
        setTopics(topicGroups)
        if (topicGroups.length > 0) {
          setSelectedTopic(topicGroups[0].name)
        }
      } catch (error) {
        console.error('加载知识库失败:', error)
        setTopics([
          { name: 'deep_reinforcement_learning', displayName: '深度强化学习', count: 20, papers: [] },
          { name: 'machine_learning', displayName: '机器学习', count: 15, papers: [] }
        ])
        setSelectedTopic('deep_reinforcement_learning')
      }
      setLoading(false)
    }

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

  // 提取年份
  const extractYear = (dateStr: string) => {
    if (!dateStr) return ''
    const match = dateStr.match(/\d{4}/)
    return match ? match[0] : ''
  }

  // 判断论文来源类型
  const getSourceType = (paper: Paper): 'arxiv' | 'journal' | 'conference' | 'unknown' => {
    if (paper.source === 'arxiv' || paper.arxiv_id || paper.paper_id?.match(/^\d{4}\.\d{4,5}v?\d*$/)) {
      return 'arxiv'
    }
    if (paper.journal) return 'journal'
    if (paper.conference) return 'conference'
    return 'unknown'
  }

  // 格式化作者为不同引用格式
  const formatAuthorsForCitation = (authors: string[] | string, format: 'APA' | 'MLA' | 'Chicago' | 'GB') => {
    const list = typeof authors === 'string'
      ? authors.split(';').map(a => a.trim()).filter(a => a)
      : authors || []
    if (list.length === 0) return ''

    if (format === 'APA') {
      // APA: 姓, 名缩写.
      if (list.length <= 7) {
        return list.map(a => {
          const parts = a.split(',').map(p => p.trim())
          if (parts.length >= 2) {
            return `${parts[0]}, ${parts[1]?.[0] || ''}.`
          }
          return a
        }).join(', ')
      }
      return list.slice(0, 7).map(a => {
        const parts = a.split(',').map(p => p.trim())
        if (parts.length >= 2) {
          return `${parts[0]}, ${parts[1]?.[0] || ''}.`
        }
        return a
      }).join(', ') + ', ... ' + list[list.length - 1]
    }

    if (format === 'MLA') {
      // MLA: 姓, 名, ...
      const formatted = list.map(a => {
        const parts = a.split(',').map(p => p.trim())
        if (parts.length >= 2) {
          return `${parts[0]}, ${parts[1]}`
        }
        return a
      })
      if (formatted.length === 1) return formatted[0]
      if (formatted.length === 2) return `${formatted[0]}, and ${formatted[1]}`
      return `${formatted[0]}, et al.`
    }

    if (format === 'Chicago') {
      // Chicago: 姓, 名
      return list.map(a => {
        const parts = a.split(',').map(p => p.trim())
        if (parts.length >= 2) {
          return `${parts[0]} ${parts[1]}`
        }
        return a
      }).join(', ')
    }

    // GB/T 7714: 姓, 名
    return list.map(a => {
      const parts = a.split(',').map(p => p.trim())
      if (parts.length >= 2) {
        return `${parts[0].toUpperCase()} ${parts[1].toUpperCase()}`
      }
      return a.toUpperCase()
    }).join(', ')
  }

  // 生成引用格式
  const generateCitation = useCallback((paper: Paper, format: string) => {
    const title = paper.title || ''
    const year = extractYear(paper.published_date)
    const sourceType = getSourceType(paper)

    // 获取DOI/URL
    let doiUrl = ''
    if (paper.doi) {
      // 去掉版本号（如 v1）
      const cleanDoi = paper.doi.replace(/v\d+$/, '')
      doiUrl = cleanDoi.startsWith('http') ? cleanDoi : `https://doi.org/${cleanDoi}`
    } else if (sourceType === 'arxiv' && paper.paper_id) {
      // 提取arXiv ID（去掉版本号）
      const arxivId = paper.paper_id.match(/^(\d{4}\.\d{4,5})v?\d*$/)?.[1] || paper.paper_id.replace(/v\d+$/, '')
      doiUrl = `https://doi.org/10.48550/arXiv.${arxivId}`
    }

    if (sourceType === 'arxiv') {
      // arXiv 预印本引用格式
      const authors = formatAuthorsForCitation(paper.authors, format as 'APA' | 'MLA' | 'Chicago' | 'GB')

      switch (format) {
        case 'APA':
          return `${authors}${year ? ` (${year})` : ''}. ${title ? title + '.' : ''} arXiv. ${doiUrl}`
        case 'MLA':
          return `${authors}. "${title}." arXiv${year ? `, ${year}` : ''}${doiUrl ? `, ${doiUrl}` : ''}.`
        case 'Chicago':
          return `${authors}${year ? ` ${year}` : ''}. "${title}." arXiv. ${doiUrl}.`
        case 'GB/T 7714-2015':
          const gbAuthors = formatAuthorsForCitation(paper.authors, 'GB')
          return `${gbAuthors}. ${title ? title + '[EB/OL].' : ''} arXiv${year ? `, ${year}` : ''}. ${doiUrl}`
        default:
          return ''
      }
    }

    // 期刊/会议论文引用格式
    const venue = paper.journal || paper.conference || ''
    const authors = formatAuthorsForCitation(paper.authors, format as 'APA' | 'MLA' | 'Chicago' | 'GB')

    switch (format) {
      case 'APA':
        return `${authors}${year ? ` (${year})` : ''}. ${title ? title + '.' : ''} ${venue ? venue + '.' : ''} ${doiUrl}`
      case 'MLA':
        return `${authors}. "${title}." ${venue}${year ? `, ${year}` : ''}${doiUrl ? `, ${doiUrl}` : ''}.`
      case 'Chicago':
        return `${authors}${year ? ` ${year}` : ''}. "${title}." ${venue}. ${doiUrl}.`
      case 'GB/T 7714-2015':
        const gbAuthors = formatAuthorsForCitation(paper.authors, 'GB')
        return `${gbAuthors}. ${title ? title + '[J].' : ''} ${venue ? venue + ',' : ''}${year ? ` ${year}.` : ''} ${doiUrl}`
      default:
        return ''
    }
  }, [])

  // 复制到剪贴板
  const copyToClipboard = async (text: string, format: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedFormat(format)
      setTimeout(() => setCopiedFormat(null), 2000)
    } catch (err) {
      console.error('复制失败:', err)
    }
  }

  // 全屏PDF模式
  if (pdfFullscreen && selectedPaper?.pdf_path) {
    return (
      <div className="h-full bg-black flex flex-col">
        {/* 全屏PDF工具栏 */}
        <div className="h-14 bg-dark-surface border-b border-dark-border flex items-center justify-between px-4 shrink-0">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setPdfFullscreen(false)}
              className="flex items-center gap-2 px-3 py-1.5 bg-dark-bg rounded-lg text-dark-text hover:bg-dark-border transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              返回
            </button>
            <span className="text-dark-text font-medium truncate max-w-md">
              {selectedPaper.title}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {selectedPaper.pdf_url && (
              <a
                href={selectedPaper.pdf_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 px-3 py-1.5 bg-dark-bg rounded-lg text-dark-text hover:bg-dark-border transition-colors"
              >
                <ExternalLink className="w-4 h-4" />
                查看原文
              </a>
            )}
          </div>
        </div>

        {/* 全屏PDF */}
        <iframe
          src={selectedPaper.pdf_path.replace('data/', '/data/')}
          className="w-full h-full"
          title="PDF Preview"
        />
      </div>
    )
  }

  return (
    <div className="h-full flex">
      {/* 左侧可折叠侧边栏 - 分类 + 论文列表 */}
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
              <button
                onClick={() => setSidebarExpanded(false)}
                className="p-1.5 hover:bg-dark-border/50 rounded text-dark-muted hover:text-dark-text"
                title="收起侧边栏"
              >
                <PanelLeftClose className="w-4 h-4" />
              </button>
            </div>

            {/* 分类列表 */}
            <div className="p-2 border-b border-dark-border max-h-48 overflow-auto shrink-0">
              <div className="text-xs text-dark-muted mb-2 px-2">分类</div>
              <div className="space-y-1">
                {topics.map((topic, index) => (
                  <motion.button
                    key={topic.name}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: index * 0.03 }}
                    onClick={() => {
                      setSelectedTopic(topic.name)
                      setSelectedPaper(null)
                    }}
                    className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-lg
                             transition-all duration-200 text-left
                             ${selectedTopic === topic.name
                               ? 'bg-primary-500/20 text-primary-400'
                               : 'text-dark-muted hover:bg-dark-border/30 hover:text-dark-text'
                             }`}
                  >
                    {selectedTopic === topic.name ? (
                      <FolderOpen className="w-4 h-4 shrink-0" />
                    ) : (
                      <FolderClosed className="w-4 h-4 shrink-0" />
                    )}
                    <span className="text-xs font-medium truncate flex-1">{topic.displayName}</span>
                    <span className="text-xs px-1.5 py-0.5 rounded-full bg-dark-border/50 shrink-0">
                      {topic.count}
                    </span>
                  </motion.button>
                ))}
              </div>
            </div>

            {/* 搜索栏 */}
            <div className="p-3 border-b border-dark-border shrink-0">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-dark-muted" />
                <input
                  type="text"
                  placeholder="搜索论文..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full bg-dark-bg border border-dark-border rounded-lg pl-8 pr-3 py-1.5 text-xs
                           focus:outline-none focus:border-primary-500 placeholder:text-dark-muted"
                />
              </div>
              <div className="mt-1.5 text-xs text-dark-muted">
                {currentTopic?.displayName} · {filteredPapers.length} 篇
              </div>
            </div>

            {/* 论文列表 */}
            <div className="flex-1 overflow-auto p-2 space-y-1.5">
              {filteredPapers.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-24 text-dark-muted">
                  <FileText className="w-6 h-6 mb-1 opacity-50" />
                  <span className="text-xs">暂无论文</span>
                </div>
              ) : (
                filteredPapers.map((paper, index) => (
                  <motion.div
                    key={paper.paper_id}
                    initial={{ opacity: 0, y: 5 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: index * 0.02 }}
                    onClick={() => {
                      setSelectedPaper(paper)
                      setActiveTab('detail')
                    }}
                    className={`p-2.5 rounded-lg border cursor-pointer transition-all duration-200
                      ${selectedPaper?.paper_id === paper.paper_id
                        ? 'bg-primary-500/15 border-primary-500/50'
                        : 'bg-dark-bg border-dark-border hover:border-primary-500/30'
                      }`}
                  >
                    <h3 className="font-medium text-dark-text text-xs line-clamp-2 mb-1.5 leading-snug">
                      {paper.title}
                    </h3>
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
            <button
              onClick={() => setSidebarExpanded(true)}
              className="p-2 hover:bg-dark-border/50 rounded-lg text-dark-muted hover:text-dark-text"
              title="展开侧边栏"
            >
              <PanelLeft className="w-5 h-5" />
            </button>
            <div className="mt-4 flex flex-col gap-2">
              {topics.map((topic) => (
                <button
                  key={topic.name}
                  onClick={() => {
                    setSelectedTopic(topic.name)
                    setSidebarExpanded(true)
                  }}
                  className={`p-2 rounded-lg transition-colors ${
                    selectedTopic === topic.name
                      ? 'bg-primary-500/20 text-primary-400'
                      : 'text-dark-muted hover:bg-dark-border/30 hover:text-dark-text'
                  }`}
                  title={topic.displayName}
                >
                  <Tag className="w-4 h-4" />
                </button>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 右侧主区域 - 论文详情或PDF阅读 */}
      <div className="flex-1 flex flex-col min-w-0">
        {selectedPaper ? (
          <>
            {/* 顶部操作栏 */}
            <div className="h-14 border-b border-dark-border flex items-center justify-between px-4 shrink-0 bg-dark-surface">
              <div className="flex items-center gap-4 min-w-0">
                {!sidebarExpanded && (
                  <button
                    onClick={() => setSidebarExpanded(true)}
                    className="p-1.5 hover:bg-dark-border/50 rounded text-dark-muted hover:text-dark-text shrink-0"
                  >
                    <PanelLeft className="w-4 h-4" />
                  </button>
                )}
                <h2 className="font-display font-semibold text-dark-text text-sm truncate">
                  {selectedPaper.title}
                </h2>
              </div>

              <div className="flex items-center gap-2 shrink-0">
                {/* 标签页切换 */}
                <div className="flex bg-dark-bg rounded-lg p-0.5 mr-2">
                  <button
                    onClick={() => setActiveTab('detail')}
                    className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors
                      ${activeTab === 'detail'
                        ? 'bg-dark-surface text-dark-text shadow-sm'
                        : 'text-dark-muted hover:text-dark-text'
                      }`}
                  >
                    详情
                  </button>
                  {selectedPaper.pdf_path && (
                    <button
                      onClick={() => setActiveTab('pdf')}
                      className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors
                        ${activeTab === 'pdf'
                          ? 'bg-dark-surface text-dark-text shadow-sm'
                          : 'text-dark-muted hover:text-dark-text'
                        }`}
                    >
                      PDF阅读
                    </button>
                  )}
                </div>

                {activeTab === 'pdf' && selectedPaper.pdf_path && (
                  <button
                    onClick={() => setPdfFullscreen(true)}
                    className="p-2 hover:bg-dark-border/50 rounded-lg text-dark-muted hover:text-dark-text"
                    title="全屏阅读"
                  >
                    <Maximize2 className="w-4 h-4" />
                  </button>
                )}

                {selectedPaper.pdf_url && (
                  <a
                    href={selectedPaper.pdf_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-dark-bg border border-dark-border
                             rounded-lg text-xs text-dark-text hover:border-primary-500/50 transition-colors"
                  >
                    <ExternalLink className="w-3.5 h-3.5" />
                    原文
                  </a>
                )}
              </div>
            </div>

            {/* 内容区域 */}
            <div className="flex-1 overflow-hidden">
              {activeTab === 'detail' ? (
                /* 论文详情 */
                <div className="h-full overflow-auto p-6">
                  <div className="max-w-3xl mx-auto space-y-5">
                    <h1 className="text-lg font-display font-bold text-dark-text leading-snug">
                      {selectedPaper.title}
                    </h1>

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

                    {selectedPaper.topics && selectedPaper.topics.length > 0 && (
                      <div className="flex items-start gap-2 flex-wrap">
                        <Tag className="w-3.5 h-3.5 text-dark-muted mt-0.5" />
                        <div className="flex flex-wrap gap-1">
                          {selectedPaper.topics.map((topic, i) => (
                            <span key={i} className="px-2 py-0.5 bg-primary-500/15 text-primary-400 rounded text-xs">
                              {topic}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="pt-4 border-t border-dark-border">
                      <h3 className="text-dark-text font-medium mb-2 flex items-center gap-2">
                        <FileText className="w-4 h-4 text-primary-500" />
                        摘要
                      </h3>
                      <p className="text-dark-text/80 text-sm leading-relaxed whitespace-pre-wrap">
                        {selectedPaper.abstract || '暂无摘要'}
                      </p>
                    </div>

                    <div className="pt-3 border-t border-dark-border">
                      <span className="text-dark-muted text-xs">论文 ID：</span>
                      <code className="text-primary-400 text-xs ml-1.5 bg-dark-bg px-2 py-1 rounded">
                        {selectedPaper.paper_id}
                      </code>
                    </div>

                    {/* 学术引用 */}
                    <div className="pt-3 border-t border-dark-border">
                      <button
                        onClick={() => setShowCitation(!showCitation)}
                        className="flex items-center justify-between w-full text-left"
                      >
                        <span className="text-dark-text font-medium text-sm flex items-center gap-2">
                          <FileText className="w-4 h-4 text-primary-500" />
                          学术引用
                        </span>
                        <ChevronRight
                          className={`w-4 h-4 text-dark-muted transition-transform ${
                            showCitation ? 'rotate-90' : ''
                          }`}
                        />
                      </button>

                      <AnimatePresence>
                        {showCitation && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: 'auto', opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            transition={{ duration: 0.2 }}
                            className="overflow-hidden"
                          >
                            <div className="pt-3 space-y-2.5">
                              {['APA', 'MLA', 'Chicago', 'GB/T 7714-2015'].map((format) => (
                                <div key={format} className="bg-dark-bg rounded-lg p-2.5">
                                  <div className="flex items-center justify-between mb-1.5">
                                    <span className="text-xs font-medium text-primary-400">{format}</span>
                                    <button
                                      onClick={() => copyToClipboard(generateCitation(selectedPaper, format), format)}
                                      className="flex items-center gap-1 text-xs text-dark-muted hover:text-primary-400 transition-colors"
                                    >
                                      {copiedFormat === format ? (
                                        <>
                                          <Check className="w-3 h-3" />
                                          已复制
                                        </>
                                      ) : (
                                        <>
                                          <Copy className="w-3 h-3" />
                                          复制
                                        </>
                                      )}
                                    </button>
                                  </div>
                                  <p className="text-xs text-dark-text/80 leading-relaxed break-words">
                                    {generateCitation(selectedPaper, format)}
                                  </p>
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
                /* PDF阅读器 - 占据整个右侧区域 */
                <div className="h-full">
                  {selectedPaper.pdf_path ? (
                    <iframe
                      src={selectedPaper.pdf_path.replace('data/', '/data/')}
                      className="w-full h-full"
                      title="PDF Preview"
                    />
                  ) : (
                    <div className="h-full flex flex-col items-center justify-center text-dark-muted">
                      <File className="w-12 h-12 mb-3 opacity-30" />
                      <p className="text-sm">该论文暂无本地PDF</p>
                      {selectedPaper.pdf_url && (
                        <a
                          href={selectedPaper.pdf_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="mt-3 px-4 py-2 bg-primary-500 rounded-lg text-white text-sm hover:bg-primary-600 transition-colors"
                        >
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
              <p className="text-xs mt-2 opacity-60">
                共 {topics.reduce((sum, t) => sum + t.count, 0)} 篇论文 · {topics.length} 个分类
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
