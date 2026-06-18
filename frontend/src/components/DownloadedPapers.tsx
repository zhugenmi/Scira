import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { FileText, Download, Eye, Calendar, Search, User, ExternalLink } from 'lucide-react'

interface DownloadedPaper {
  id: string
  title: string
  authors: string[]
  publishedDate: string
  pdfUrl: string
  keywords: string[]
}

export default function DownloadedPapers() {
  const [papers, setPapers] = useState<DownloadedPaper[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedPaper, setSelectedPaper] = useState<DownloadedPaper | null>(null)

  // 从本地 JSON 文件加载数据
  useEffect(() => {
    const loadPapers = async () => {
      try {
        const response = await fetch('/data/papers/all_papers.json')
        if (response.ok) {
          const data = await response.json()
          const downloadedPapers: DownloadedPaper[] = data.papers?.map((p: any) => ({
            id: p.paper_id,
            title: p.title,
            authors: p.authors || [],
            publishedDate: p.published_date || p.published || '',
            pdfUrl: p.pdf_url || '',
            keywords: p.keywords || []
          })) || []
          setPapers(downloadedPapers)
        }
      } catch (error) {
        console.error('加载论文失败:', error)
        // 使用模拟数据
        setPapers([])
      }
      setLoading(false)
    }
    loadPapers()
  }, [])

  // 过滤论文
  const filteredPapers = papers.filter(paper =>
    paper.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    paper.authors.some(a => a.toLowerCase().includes(searchQuery.toLowerCase())) ||
    paper.keywords.some(t => t.toLowerCase().includes(searchQuery.toLowerCase()))
  )

  const handlePreview = (paper: DownloadedPaper) => {
    setSelectedPaper(paper)
    // 可以打开 PDF 预览模态框
  }

  const handleDownload = async (paper: DownloadedPaper) => {
    if (!paper.pdfUrl) return

    try {
      // 使用fetch下载PDF并保存到本地
      const response = await fetch(paper.pdfUrl)
      if (!response.ok) throw new Error('下载失败')

      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)

      // 创建下载链接
      const a = document.createElement('a')
      a.href = url
      a.download = `${paper.title.replace(/[^a-zA-Z0-9一-龥]/g, '_')}.pdf`
      document.body.appendChild(a)
      a.click()

      // 清理
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('下载失败:', error)
      // 如果下载失败，回退到打开新标签页
      window.open(paper.pdfUrl, '_blank')
    }
  }

  const formatAuthors = (authors: string[]) => {
    if (!authors || authors.length === 0) return '未知作者'
    if (authors.length <= 3) return authors.join(', ')
    return `${authors.slice(0, 3).join(', ')} 等${authors.length}人`
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
              placeholder="搜索论文标题、作者或主题..."
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
              <span className="text-sm">暂无下载的论文</span>
            </div>
          ) : (
            filteredPapers.map((paper, index) => (
              <motion.div
                key={paper.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.03 }}
                className={`p-4 rounded-xl border cursor-pointer transition-all duration-200
                  ${selectedPaper?.id === paper.id
                    ? 'bg-primary-500/10 border-primary-500/50'
                    : 'bg-dark-surface border-dark-border hover:border-primary-500/30'
                  }`}
                onClick={() => setSelectedPaper(paper)}
              >
                {/* 标签 */}
                <div className="flex flex-wrap gap-1 mb-2">
                  {paper.keywords?.slice(0, 2).map((kw, i) => (
                    <span key={i} className="text-xs px-2 py-0.5 bg-primary-500/20 text-primary-400 rounded-full">
                      {kw}
                    </span>
                  ))}
                </div>

                {/* 标题 */}
                <h3 className="font-medium text-dark-text mb-2 line-clamp-2">{paper.title}</h3>

                {/* 作者 */}
                <div className="flex items-center gap-1 text-xs text-dark-muted mb-2">
                  <User className="w-3 h-3" />
                  <span className="truncate">{formatAuthors(paper.authors)}</span>
                </div>

                {/* 日期 */}
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1 text-xs text-dark-muted">
                    <Calendar className="w-3 h-3" />
                    {paper.publishedDate || '未知日期'}
                  </span>
                  <div className="flex gap-1">
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handlePreview(paper)
                      }}
                      className="p-1.5 hover:bg-dark-border/50 rounded text-dark-muted hover:text-dark-text"
                      title="预览"
                    >
                      <Eye className="w-4 h-4" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        handleDownload(paper)
                      }}
                      className="p-1.5 hover:bg-dark-border/50 rounded text-dark-muted hover:text-primary-400"
                      title="下载"
                    >
                      <Download className="w-4 h-4" />
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        window.open(paper.pdfUrl, '_blank')
                      }}
                      className="p-1.5 hover:bg-dark-border/50 rounded text-dark-muted hover:text-primary-400"
                      title="查看原文"
                    >
                      <ExternalLink className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </motion.div>
            ))
          )}
        </div>

        {/* 统计信息 */}
        <div className="p-3 border-t border-dark-border text-xs text-dark-muted">
          共 {filteredPapers.length} 篇论文
        </div>
      </div>

      {/* 右侧详情区域 */}
      <div className="flex-1 flex flex-col">
        {selectedPaper ? (
          <>
            {/* 操作栏 */}
            <div className="p-4 border-b border-dark-border flex items-center justify-between">
              <h2 className="font-display font-semibold text-lg text-dark-text line-clamp-1">
                {selectedPaper.title}
              </h2>
              <button
                onClick={() => handleDownload(selectedPaper)}
                className="flex items-center gap-2 px-4 py-2 bg-primary-500 rounded-lg text-sm
                         text-white hover:bg-primary-600 transition-colors"
              >
                <Download className="w-4 h-4" />
                下载 PDF
              </button>
            </div>

            {/* 详情内容 */}
            <div className="flex-1 overflow-auto p-6">
              <div className="max-w-3xl mx-auto space-y-6">
                {/* 标题 */}
                <h1 className="text-2xl font-display font-bold text-dark-text">
                  {selectedPaper.title}
                </h1>

                {/* 作者 */}
                <div className="flex items-start gap-2">
                  <span className="text-dark-muted text-sm">作者：</span>
                  <span className="text-dark-text text-sm">{formatAuthors(selectedPaper.authors)}</span>
                </div>

                {/* 日期 */}
                <div className="flex items-center gap-2">
                  <span className="text-dark-muted text-sm">发表日期：</span>
                  <span className="text-dark-text text-sm">{selectedPaper.publishedDate || '未知'}</span>
                </div>

                {/* 标签 */}
                {selectedPaper.keywords && selectedPaper.keywords.length > 0 && (
                  <div className="flex items-start gap-2">
                    <span className="text-dark-muted text-sm">关键词：</span>
                    <div className="flex flex-wrap gap-1">
                      {selectedPaper.keywords.map((kw, i) => (
                        <span key={i} className="px-2 py-0.5 bg-primary-500/20 text-primary-400 rounded-full text-xs">
                          {kw}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* PDF 链接 */}
                <div className="pt-4 border-t border-dark-border">
                  <a
                    href={selectedPaper.pdfUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-2 text-primary-400 hover:text-primary-300"
                  >
                    在原文网站查看
                    <ExternalLink className="w-4 h-4" />
                  </a>
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-dark-muted">
            <FileText className="w-12 h-12 mb-4 opacity-30" />
            <p className="text-sm">选择一个论文查看详情</p>
          </div>
        )}
      </div>
    </div>
  )
}
