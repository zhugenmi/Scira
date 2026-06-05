import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { FileText, Download, Eye, Calendar, Search, MoreVertical, Trash2 } from 'lucide-react'

interface GeneratedPaper {
  id: string
  title: string
  topic: string
  createdAt: string
  wordCount: number
}

export default function GeneratedPapers() {
  const [papers, setPapers] = useState<GeneratedPaper[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedPaper, setSelectedPaper] = useState<GeneratedPaper | null>(null)
  const [previewContent, setPreviewContent] = useState('')

  // 模拟数据 - 实际应该从 API 获取
  useEffect(() => {
    const mockPapers: GeneratedPaper[] = [
      {
        id: '1',
        title: '深度强化学习研究报告',
        topic: '深度强化学习',
        createdAt: '2024-06-05 07:31',
        wordCount: 15820
      },
      {
        id: '2',
        title: '机器学习研究综述',
        topic: '机器学习',
        createdAt: '2024-06-05 07:05',
        wordCount: 12350
      }
    ]
    setPapers(mockPapers)
    setLoading(false)
  }, [])

  // 过滤论文
  const filteredPapers = papers.filter(paper =>
    paper.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    paper.topic.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const handlePreview = async (paper: GeneratedPaper) => {
    setSelectedPaper(paper)
    try {
      const response = await fetch(`/data/outputs/research_${paper.id}.md`)
      if (response.ok) {
        const content = await response.text()
        setPreviewContent(content)
      } else {
        setPreviewContent(`# ${paper.title}\n\n（预览内容加载失败）`)
      }
    } catch {
      setPreviewContent(`# ${paper.title}\n\n（预览内容加载失败）`)
    }
  }

  const handleDownload = (paper: GeneratedPaper) => {
    // 实际应该从 API 获取文件
    window.open(`/data/outputs/research_${paper.id}.md`, '_blank')
  }

  const handleDelete = (id: string) => {
    if (confirm('确定要删除这篇论文吗？')) {
      setPapers(papers.filter(p => p.id !== id))
    }
  }

  return (
    <div className="h-full flex">
      {/* 左侧论文列表 */}
      <div className="w-96 border-r border-dark-border flex flex-col">
        {/* 搜索栏 */}
        <div className="p-4 border-b border-dark-border">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-dark-muted" />
            <input
              type="text"
              placeholder="搜索论文..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full bg-dark-bg border border-dark-border rounded-lg pl-10 pr-4 py-2 text-sm
                       focus:outline-none focus:border-primary-500 placeholder:text-dark-muted"
            />
          </div>
        </div>

        {/* 论文列表 */}
        <div className="flex-1 overflow-auto p-3 space-y-2">
          {loading ? (
            <div className="flex items-center justify-center h-32 text-dark-muted">
              加载中...
            </div>
          ) : filteredPapers.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-32 text-dark-muted">
              <FileText className="w-8 h-8 mb-2 opacity-50" />
              <span className="text-sm">暂无生成的论文</span>
            </div>
          ) : (
            filteredPapers.map((paper, index) => (
              <motion.div
                key={paper.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.05 }}
                className={`p-4 rounded-xl border cursor-pointer transition-all duration-200
                  ${selectedPaper?.id === paper.id
                    ? 'bg-primary-500/10 border-primary-500/50'
                    : 'bg-dark-surface border-dark-border hover:border-primary-500/30'
                  }`}
                onClick={() => setSelectedPaper(paper)}
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <FileText className="w-4 h-4 text-primary-500" />
                    <span className="text-xs px-2 py-0.5 bg-primary-500/20 text-primary-400 rounded-full">
                      {paper.topic}
                    </span>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      handleDelete(paper.id)
                    }}
                    className="p-1 hover:bg-dark-border/50 rounded text-dark-muted hover:text-red-400"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
                <h3 className="font-medium text-dark-text mb-2 line-clamp-2">{paper.title}</h3>
                <div className="flex items-center justify-between text-xs text-dark-muted">
                  <span className="flex items-center gap-1">
                    <Calendar className="w-3 h-3" />
                    {paper.createdAt}
                  </span>
                  <span>{paper.wordCount.toLocaleString()} 字</span>
                </div>
              </motion.div>
            ))
          )}
        </div>
      </div>

      {/* 右侧预览区域 */}
      <div className="flex-1 flex flex-col">
        {selectedPaper ? (
          <>
            {/* 操作栏 */}
            <div className="p-4 border-b border-dark-border flex items-center justify-between">
              <h2 className="font-display font-semibold text-lg text-dark-text">
                {selectedPaper.title}
              </h2>
              <div className="flex gap-2">
                <button
                  onClick={() => handlePreview(selectedPaper)}
                  className="flex items-center gap-2 px-4 py-2 bg-dark-surface border border-dark-border
                           rounded-lg text-sm text-dark-text hover:border-primary-500/50 transition-colors"
                >
                  <Eye className="w-4 h-4" />
                  预览
                </button>
                <button
                  onClick={() => handleDownload(selectedPaper)}
                  className="flex items-center gap-2 px-4 py-2 bg-primary-500 rounded-lg text-sm
                           text-white hover:bg-primary-600 transition-colors"
                >
                  <Download className="w-4 h-4" />
                  下载
                </button>
              </div>
            </div>

            {/* 预览内容 */}
            <div className="flex-1 overflow-auto p-6">
              <div className="max-w-3xl mx-auto">
                <div className="prose prose-invert prose-primary max-w-none">
                  <pre className="whitespace-pre-wrap font-sans text-sm text-dark-text/90 leading-relaxed">
                    {previewContent || '点击"预览"查看论文内容'}
                  </pre>
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-dark-muted">
            <Eye className="w-12 h-12 mb-4 opacity-30" />
            <p className="text-sm">选择一个论文查看预览</p>
          </div>
        )}
      </div>
    </div>
  )
}
