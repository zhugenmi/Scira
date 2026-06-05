import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { BookOpen, Search, ChevronRight, FileText, Calendar, User, Users, Tag, X, ExternalLink } from 'lucide-react'

interface Paper {
  paper_id: string
  title: string
  authors: string[]
  abstract: string
  published_date: string
  pdf_url: string
  topics: string[]
  citations?: number
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

  // 加载知识库数据
  useEffect(() => {
    const loadKnowledgeBase = async () => {
      try {
        // 加载主索引文件
        const response = await fetch('/data/papers/all_papers.json')
        if (!response.ok) throw new Error('加载失败')

        const data = await response.json()
        const topicGroups: TopicGroup[] = []

        // 方法1: 尝试从 API 获取分类数据
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

        // 方法2: 如果没有获取到分类，按 papers 中的 topics 字段分组
        if (topicGroups.length === 0) {
          // 方法2: 按 papers 中的 topics 字段分组
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
              // 没有 topic 的使用 default
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

        // 按论文数量排序
        topicGroups.sort((a, b) => b.count - a.count)

        setTopics(topicGroups)
        if (topicGroups.length > 0) {
          setSelectedTopic(topicGroups[0].name)
        }
      } catch (error) {
        console.error('加载知识库失败:', error)
        // 模拟数据
        setTopics([
          {
            name: 'deep_reinforcement_learning',
            displayName: '深度强化学习',
            count: 20,
            papers: []
          },
          {
            name: 'machine_learning',
            displayName: '机器学习',
            count: 15,
            papers: []
          }
        ])
        setSelectedTopic('deep_reinforcement_learning')
      }
      setLoading(false)
    }

    loadKnowledgeBase()
  }, [])

  // 获取当前选中主题的论文
  const currentTopic = topics.find(t => t.name === selectedTopic)
  const currentPapers = currentTopic?.papers || []

  // 过滤论文
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
    // 处理字符串格式（如 "Hu, B.; Temiz, N. Z.; ..."）
    if (typeof authors === 'string') {
      if (!authors || authors.length === 0) return '未知作者'
      const authorList = authors.split(';').map(a => a.trim()).filter(a => a)
      if (authorList.length <= 3) return authorList.join(', ')
      return `${authorList.slice(0, 3).join(', ')} 等`
    }
    // 处理数组格式
    if (!authors || authors.length === 0) return '未知作者'
    if (authors.length <= 3) return authors.join(', ')
    return `${authors.slice(0, 3).join(', ')} 等`
  }

  return (
    <div className="h-full flex">
      {/* 左侧分类列表 */}
      <div className="w-72 border-r border-dark-border flex flex-col">
        {/* 标题 */}
        <div className="p-4 border-b border-dark-border">
          <div className="flex items-center gap-2 text-dark-text">
            <BookOpen className="w-5 h-5 text-primary-500" />
            <span className="font-display font-semibold">知识库</span>
          </div>
        </div>

        {/* 分类列表 */}
        <div className="flex-1 overflow-auto p-2">
          {loading ? (
            <div className="flex items-center justify-center h-32 text-dark-muted">
              加载中...
            </div>
          ) : (
            <div className="space-y-1">
              {topics.map((topic, index) => (
                <motion.button
                  key={topic.name}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.05 }}
                  onClick={() => setSelectedTopic(topic.name)}
                  className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg
                           transition-all duration-200 text-left
                           ${selectedTopic === topic.name
                             ? 'bg-primary-500/20 text-primary-400'
                             : 'text-dark-muted hover:bg-dark-border/30 hover:text-dark-text'
                           }`}
                >
                  <div className="flex items-center gap-2">
                    <Tag className="w-4 h-4" />
                    <span className="text-sm font-medium">{topic.displayName}</span>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full
                    ${selectedTopic === topic.name
                      ? 'bg-primary-500/30 text-primary-300'
                      : 'bg-dark-border/50 text-dark-muted'
                    }`}>
                    {topic.count}
                  </span>
                </motion.button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 中间论文列表 */}
      <div className="w-96 border-r border-dark-border flex flex-col">
        {/* 搜索栏 */}
        <div className="p-4 border-b border-dark-border">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-dark-muted" />
            <input
              type="text"
              placeholder="搜索论文标题、摘要或作者..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-dark-bg border border-dark-border rounded-lg pl-10 pr-4 py-2 text-sm
                       focus:outline-none focus:border-primary-500 placeholder:text-dark-muted"
            />
          </div>
          <div className="mt-2 text-xs text-dark-muted">
            {currentTopic?.displayName} · {filteredPapers.length} 篇论文
          </div>
        </div>

        {/* 论文卡片列表 */}
        <div className="flex-1 overflow-auto p-3 space-y-3">
          {filteredPapers.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-32 text-dark-muted">
              <FileText className="w-8 h-8 mb-2 opacity-50" />
              <span className="text-sm">暂无论文</span>
            </div>
          ) : (
            filteredPapers.map((paper, index) => (
              <motion.div
                key={paper.paper_id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03 }}
                onClick={() => setSelectedPaper(paper)}
                className={`p-4 rounded-xl border cursor-pointer transition-all duration-200
                  ${selectedPaper?.paper_id === paper.paper_id
                    ? 'bg-primary-500/10 border-primary-500/50'
                    : 'bg-dark-surface border-dark-border hover:border-primary-500/30'
                  }`}
              >
                {/* 标题 */}
                <h3 className="font-medium text-dark-text mb-2 line-clamp-2 text-sm leading-relaxed">
                  {paper.title}
                </h3>

                {/* 作者 */}
                <div className="flex items-center gap-1 text-xs text-dark-muted mb-2">
                  <User className="w-3 h-3 shrink-0" />
                  <span className="truncate">{formatAuthors(paper.authors)}</span>
                </div>

                {/* 摘要 */}
                <p className="text-xs text-dark-muted/80 line-clamp-3 mb-2">
                  {paper.abstract || '暂无摘要'}
                </p>

                {/* 底部信息 */}
                <div className="flex items-center justify-between text-xs text-dark-muted">
                  <span className="flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    {paper.published_date || '未知日期'}
                  </span>
                  {paper.citations !== undefined && (
                    <span className="flex items-center gap-1">
                      <Users className="w-3 h-3" />
                      {paper.citations} 次引用
                    </span>
                  )}
                </div>
              </motion.div>
            ))
          )}
        </div>
      </div>

      {/* 右侧论文详情 */}
      <div className="flex-1 flex flex-col">
        {selectedPaper ? (
          <>
            {/* 操作栏 */}
            <div className="p-4 border-b border-dark-border flex items-center justify-between">
              <h2 className="font-display font-semibold text-lg text-dark-text line-clamp-1 pr-4">
                {selectedPaper.title}
              </h2>
              <div className="flex gap-2 shrink-0">
                {selectedPaper.pdf_url && (
                  <a
                    href={selectedPaper.pdf_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 px-4 py-2 bg-dark-surface border border-dark-border
                             rounded-lg text-sm text-dark-text hover:border-primary-500/50 transition-colors"
                  >
                    <ExternalLink className="w-4 h-4" />
                    查看原文
                  </a>
                )}
              </div>
            </div>

            {/* 详情内容 */}
            <div className="flex-1 overflow-auto p-6">
              <div className="max-w-3xl mx-auto space-y-6">
                {/* 标题 */}
                <h1 className="text-xl font-display font-bold text-dark-text">
                  {selectedPaper.title}
                </h1>

                {/* 作者 */}
                <div className="flex items-start gap-2">
                  <User className="w-4 h-4 text-dark-muted mt-0.5" />
                  <div>
                    <span className="text-dark-muted text-sm">作者：</span>
                    <span className="text-dark-text text-sm ml-1">{formatAuthors(selectedPaper.authors)}</span>
                  </div>
                </div>

                {/* 发表日期 */}
                <div className="flex items-center gap-2">
                  <Calendar className="w-4 h-4 text-dark-muted" />
                  <span className="text-dark-muted text-sm">发表日期：</span>
                  <span className="text-dark-text text-sm">{selectedPaper.published_date || '未知'}</span>
                </div>

                {/* 引用数 */}
                {selectedPaper.citations !== undefined && (
                  <div className="flex items-center gap-2">
                    <Users className="w-4 h-4 text-dark-muted" />
                    <span className="text-dark-muted text-sm">引用数：</span>
                    <span className="text-dark-text text-sm">{selectedPaper.citations}</span>
                  </div>
                )}

                {/* 摘要 */}
                <div className="pt-4 border-t border-dark-border">
                  <h3 className="text-dark-text font-medium mb-3 flex items-center gap-2">
                    <FileText className="w-4 h-4 text-primary-500" />
                    摘要
                  </h3>
                  <p className="text-dark-text/80 text-sm leading-relaxed whitespace-pre-wrap">
                    {selectedPaper.abstract || '暂无摘要'}
                  </p>
                </div>

                {/* Paper ID */}
                <div className="pt-4 border-t border-dark-border">
                  <span className="text-dark-muted text-sm">论文 ID：</span>
                  <code className="text-primary-400 text-sm ml-2 bg-dark-bg px-2 py-1 rounded">
                    {selectedPaper.paper_id}
                  </code>
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-dark-muted">
            <BookOpen className="w-12 h-12 mb-4 opacity-30" />
            <p className="text-sm">选择一个论文查看详情</p>
          </div>
        )}
      </div>
    </div>
  )
}
