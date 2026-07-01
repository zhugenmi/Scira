import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import {
  Upload, FileText, BookOpen, Search, Play, Settings,
  Loader2, AlertCircle, X, ArrowLeft, Copy, Download,
  Sparkles, Microscope, Globe, MessageCircle, Languages, Cpu, FileUp
} from 'lucide-react'

type InputMode = 'upload' | 'library'
type ReadingMode = 'snap' | 'lens' | 'sphere' | 'qa'
type Language = 'zh' | 'en'

interface Paper {
  paper_id: string
  title: string
  authors: string | string[]
  pdf_path?: string
}

interface AnalysisResult {
  markdown: string
  json?: string
  mode: ReadingMode
  title?: string
  fromCache?: boolean
}

export default function PaperReading() {
  const [inputMode, setInputMode] = useState<InputMode>('library')
  const [readingMode, setReadingMode] = useState<ReadingMode>('snap')
  const [language, setLanguage] = useState<Language>('zh')
  const [model, setModel] = useState('default')
  const [file, setFile] = useState<File | null>(null)
  const [selectedPaper, setSelectedPaper] = useState<Paper | null>(null)
  const [libraryQuery, setLibraryQuery] = useState('')
  const [libraryPapers, setLibraryPapers] = useState<Paper[]>([])
  const [loading, setLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [progressMsg, setProgressMsg] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  // 流式累积 buffer：用 ref 避免 SSE 回调里的 stale state
  const streamBufferRef = useRef<string>('')

  // 加载知识库论文列表
  const loadLibraryPapers = async () => {
    try {
      const topicsRes = await fetch('/api/papers/topics')
      if (!topicsRes.ok) {
        const response = await fetch('/data/papers/all_papers.json')
        if (!response.ok) return []
        const data = await response.json()
        return data.papers || []
      }

      const topicsData = await topicsRes.json()
      const allPapers: Paper[] = []

      for (const topic of topicsData.topics || []) {
        try {
          const topicResponse = await fetch(`/${topic.file}`)
          if (topicResponse.ok) {
            const topicData = await topicResponse.json()
            if (topicData.papers) {
              allPapers.push(...topicData.papers)
            }
          }
        } catch (e) {
          console.warn(`Failed to load topic: ${topic.name}`, e)
        }
      }

      return allPapers
    } catch (e) {
      console.error('Failed to load library papers', e)
      return []
    }
  }

  // 搜索知识库论文
  useEffect(() => {
    if (inputMode !== 'library') return

    const searchPapers = async () => {
      const papers = await loadLibraryPapers()

      if (!libraryQuery) {
        setLibraryPapers(papers.slice(0, 20))
        return
      }

      const filtered = papers.filter((p: Paper) =>
        p.title.toLowerCase().includes(libraryQuery.toLowerCase()) ||
        (Array.isArray(p.authors) ? p.authors : (p.authors as string).split(';'))
          .some((a: string) => a.toLowerCase().includes(libraryQuery.toLowerCase()))
      )
      setLibraryPapers(filtered.slice(0, 20))
    }

    const debounce = setTimeout(searchPapers, 300)
    return () => clearTimeout(debounce)
  }, [inputMode, libraryQuery])

  // 处理文件选择
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile && selectedFile.type === 'application/pdf') {
      setFile(selectedFile)
      setSelectedPaper(null)
      setError(null)
    } else {
      setError('请选择PDF文件')
    }
  }

  // 处理拖拽
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const files = e.dataTransfer.files
    const ok = files && files.length > 0 && (
      files[0].type === 'application/pdf' ||
      files[0].name.toLowerCase().endsWith('.pdf') ||
      files[0].name.toLowerCase().endsWith('.caj')
    )
    if (ok) {
      setFile(files[0])
      setSelectedPaper(null)
      setError(null)
    } else {
      setError('请选择 PDF 或 CAJ 文件')
    }
  }

  // 上传PDF
  const handleUpload = async () => {
    if (!file) return

    setLoading(true)
    setError(null)

    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await fetch('/api/paper-reading/upload', {
        method: 'POST',
        body: formData
      })

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.detail || '上传失败')
      }

      const data = await response.json()
      setSelectedPaper({
        paper_id: data.paper_id,
        title: data.title || file.name.replace(/\.(pdf|caj)$/i, ''),
        authors: data.authors || [],
        pdf_path: data.pdf_path
      })
    } catch (e: any) {
      setError(e.message || '上传失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  // 执行分析
  const handleAnalyze = async () => {
    if (!selectedPaper) return

    setAnalyzing(true)
    setError(null)
    setResult(null)

    try {
      // 1. 启动分析任务
      const response = await fetch('/api/paper-reading/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          paper_id: selectedPaper.paper_id,
          mode: readingMode,
          language,
          model,
          pdf_path: selectedPaper.pdf_path || null
        })
      })

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.detail || '分析失败')
      }

      const { run_id } = await response.json()

      // 2. SSE流式获取结果
      const streamResponse = await fetch(`/api/paper-reading/stream/${run_id}`)
      if (!streamResponse.ok) {
        throw new Error('获取分析结果失败')
      }

      const reader = streamResponse.body?.getReader()
      if (!reader) throw new Error('无法读取响应')

      const decoder = new TextDecoder()
      let buffer = ''

      // 流式增量渲染：token 累积到 ref，定时 flush 到 result.markdown
      streamBufferRef.current = ''
      let flushTimer: ReturnType<typeof setInterval> | null = null
      const flush = () => {
        const text = streamBufferRef.current
        if (!text) return
        setResult({
          markdown: text,
          mode: readingMode,
          title: selectedPaper.title,
          fromCache: false,
        })
      }
      flushTimer = setInterval(flush, 80)

      try {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const jsonStr = line.slice(6).trim()
              if (!jsonStr) continue

              try {
                const parsed = JSON.parse(jsonStr)
                const data = parsed.data || parsed

                if (parsed.type === 'token') {
                  // 累积 token，由 flushTimer 定时渲染
                  streamBufferRef.current += data.token || ''
                } else if (parsed.type === 'progress') {
                  setProgressMsg(data.message || null)
                } else if (parsed.type === 'complete') {
                  // 最终结果覆盖（确保完整，避免 flush 漏尾）
                  streamBufferRef.current = ''
                  setResult({
                    markdown: data.markdown,
                    json: data.json,
                    mode: readingMode,
                    title: selectedPaper.title,
                    fromCache: data.from_cache
                  })
                } else if (parsed.type === 'error') {
                  setError(data.message || '分析失败')
                }
              } catch {
                // 忽略解析错误
              }
            }
          }
        }
      } finally {
        if (flushTimer) clearInterval(flushTimer)
        // 兜底 flush：若 complete 未到但流已结束
        if (streamBufferRef.current) {
          setResult({
            markdown: streamBufferRef.current,
            mode: readingMode,
            title: selectedPaper.title,
            fromCache: false,
          })
          streamBufferRef.current = ''
        }
      }
    } catch (e: any) {
      setError(e.message || '分析失败，请重试')
    } finally {
      setAnalyzing(false)
      setProgressMsg(null)
    }
  }

  // 从知识库选择论文
  const handleSelectFromLibrary = (paper: Paper) => {
    const authors = Array.isArray(paper.authors) ? paper.authors :
                    typeof paper.authors === 'string' ? paper.authors.split(';').map(s => s.trim()) : []

    setSelectedPaper({
      paper_id: paper.paper_id,
      title: paper.title,
      authors,
      pdf_path: paper.pdf_path
    })
    setFile(null)
  }

  const readingModeInfo = {
    snap: { icon: Sparkles, label: '速览', desc: '30秒快速了解核心贡献' },
    lens: { icon: Microscope, label: '深度精读', desc: '深入分析公式、算法和实验' },
    sphere: { icon: Globe, label: '研究全景', desc: '参考文献网络、主题聚类' }
  }

  return (
    <div className="h-full flex flex-col p-6">
      {/* 全屏结果展示模式 */}
      {result ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="h-full flex flex-col"
        >
          {/* 顶部工具栏 */}
          <div className="flex items-center justify-between mb-4 pb-4 border-b border-dark-border">
            <div className="flex items-center gap-3">
              <button
                onClick={() => setResult(null)}
                className="p-2 rounded-lg bg-dark-surface hover:bg-dark-border/30 transition-colors flex items-center gap-2"
                title="返回"
              >
                <ArrowLeft className="w-4 h-4 text-dark-muted" />
                <span className="text-sm text-dark-text">返回</span>
              </button>
              <div>
                <h1 className="text-xl font-bold text-dark-text">{selectedPaper?.title || '论文精读结果'}</h1>
                <p className="text-xs text-dark-muted mt-0.5 flex items-center gap-2">
                  <span>模式：{readingModeInfo[readingMode].label}</span>
                  <span>·</span>
                  <span>语言：{language === 'zh' ? '中文' : 'English'}</span>
                  {result.fromCache && (
                    <>
                      <span>·</span>
                      <span className="text-green-400 flex items-center gap-1">
                        <span className="w-1.5 h-1.5 bg-green-400 rounded-full"></span>
                        缓存命中（历史分析）
                      </span>
                    </>
                  )}
                  {analyzing && progressMsg && (
                    <>
                      <span>·</span>
                      <span className="text-primary-400 flex items-center gap-1">
                        <Loader2 className="w-3 h-3 animate-spin" />
                        {progressMsg}
                      </span>
                    </>
                  )}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  navigator.clipboard.writeText(result.markdown)
                }}
                className="p-2 rounded-lg bg-dark-surface hover:bg-dark-border/30 transition-colors"
                title="复制Markdown"
              >
                <Copy className="w-4 h-4 text-dark-muted" />
              </button>
              <button
                onClick={() => {
                  const blob = new Blob([result.markdown], { type: 'text/markdown' })
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url
                  a.download = `${selectedPaper?.title || 'paper'}_${readingMode}.md`
                  a.click()
                  URL.revokeObjectURL(url)
                }}
                className="p-2 rounded-lg bg-dark-surface hover:bg-dark-border/30 transition-colors"
                title="下载Markdown"
              >
                <Download className="w-4 h-4 text-dark-muted" />
              </button>
            </div>
          </div>

          {/* 全屏结果内容 */}
          <div className="flex-1 overflow-auto bg-dark-surface/30 rounded-lg p-8">
            <div className="max-w-4xl mx-auto">
              <article className="paper-reading-result">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm, remarkMath]}
                  rehypePlugins={[rehypeKatex]}
                  components={{
                    h1: ({ children }) => (
                      <h1 className="text-3xl font-bold text-dark-text border-b border-dark-border pb-3 mb-6 mt-2">
                        {children}
                      </h1>
                    ),
                    h2: ({ children }) => (
                      <h2 className="text-2xl font-bold text-primary-400 mt-8 mb-4 flex items-center gap-2">
                        <span className="w-1 h-6 bg-primary-500 rounded"></span>
                        {children}
                      </h2>
                    ),
                    h3: ({ children }) => (
                      <h3 className="text-xl font-semibold text-dark-text mt-6 mb-3">{children}</h3>
                    ),
                    h4: ({ children }) => (
                      <h4 className="text-lg font-semibold text-dark-text mt-4 mb-2">{children}</h4>
                    ),
                    p: ({ children }) => (
                      <p className="text-dark-text leading-relaxed mb-4 text-base">{children}</p>
                    ),
                    ul: ({ children }) => (
                      <ul className="list-disc list-inside space-y-2 mb-4 text-dark-text ml-2">{children}</ul>
                    ),
                    ol: ({ children }) => (
                      <ol className="list-decimal list-inside space-y-2 mb-4 text-dark-text ml-2">{children}</ol>
                    ),
                    li: ({ children }) => (
                      <li className="text-dark-text leading-relaxed">{children}</li>
                    ),
                    strong: ({ children }) => (
                      <strong className="text-primary-400 font-semibold">{children}</strong>
                    ),
                    em: ({ children }) => (
                      <em className="text-primary-300 italic">{children}</em>
                    ),
                    code: ({ children, className }: any) => {
                      const isInline = !className
                      return isInline ? (
                        <code className="text-primary-400 bg-dark-surface px-1.5 py-0.5 rounded text-sm font-mono">
                          {children}
                        </code>
                      ) : (
                        <code className={`${className} block`}>{children}</code>
                      )
                    },
                    pre: ({ children }) => (
                      <pre className="bg-dark-surface border border-dark-border rounded-lg p-4 overflow-x-auto mb-4 text-sm">
                        {children}
                      </pre>
                    ),
                    blockquote: ({ children }) => (
                      <blockquote className="border-l-4 border-primary-500 pl-4 py-2 my-4 bg-primary-500/5 text-dark-muted italic">
                        {children}
                      </blockquote>
                    ),
                    table: ({ children }) => (
                      <div className="overflow-x-auto mb-4 rounded-lg border border-dark-border">
                        <table className="min-w-full divide-y divide-dark-border">{children}</table>
                      </div>
                    ),
                    thead: ({ children }) => (
                      <thead className="bg-dark-surface">{children}</thead>
                    ),
                    th: ({ children }) => (
                      <th className="px-4 py-2 text-left text-sm font-semibold text-primary-400 border-r border-dark-border last:border-r-0">
                        {children}
                      </th>
                    ),
                    td: ({ children }) => (
                      <td className="px-4 py-2 text-sm text-dark-text border-r border-dark-border last:border-r-0">
                        {children}
                      </td>
                    ),
                    tr: ({ children }) => (
                      <tr className="border-b border-dark-border hover:bg-dark-surface/50 transition-colors">
                        {children}
                      </tr>
                    ),
                    a: ({ children, href }) => (
                      <a href={href} className="text-primary-400 hover:text-primary-300 underline" target="_blank" rel="noopener noreferrer">
                        {children}
                      </a>
                    ),
                    hr: () => <hr className="my-6 border-dark-border" />,
                  }}
                >
                  {result.markdown}
                </ReactMarkdown>
              </article>
            </div>
          </div>
        </motion.div>
      ) : (
      <>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-dark-text">论文精读</h1>
        <button
          onClick={() => setShowSettings(!showSettings)}
          className="p-2 rounded-lg bg-dark-surface hover:bg-dark-border/30 transition-colors"
        >
          <Settings className="w-5 h-5 text-dark-muted" />
        </button>
      </div>

      {/* 设置面板 */}
      <AnimatePresence>
        {showSettings && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="mb-4 overflow-hidden"
          >
            <div className="flex gap-4 p-4 bg-dark-surface/50 rounded-lg">
              <div className="flex items-center gap-2">
                <Languages className="w-4 h-4 text-dark-muted" />
                <select
                  value={language}
                  onChange={(e) => setLanguage(e.target.value as Language)}
                  className="bg-dark-surface border border-dark-border rounded px-2 py-1 text-sm text-dark-text"
                >
                  <option value="zh">中文</option>
                  <option value="en">English</option>
                </select>
              </div>
              <div className="flex items-center gap-2">
                <Cpu className="w-4 h-4 text-dark-muted" />
                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="bg-dark-surface border border-dark-border rounded px-2 py-1 text-sm text-dark-text"
                >
                  <option value="default">默认模型</option>
                  <option value="gpt-4">GPT-4</option>
                </select>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 输入模式选择 */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => { setInputMode('library'); setSelectedPaper(null); setResult(null); }}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${
            inputMode === 'library' ? 'bg-primary-500 text-white' : 'bg-dark-surface text-dark-muted hover:text-dark-text'
          }`}
        >
          <BookOpen className="w-4 h-4" />
          知识库选文
        </button>
        <button
          onClick={() => { setInputMode('upload'); setSelectedPaper(null); setResult(null); }}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-all ${
            inputMode === 'upload' ? 'bg-primary-500 text-white' : 'bg-dark-surface text-dark-muted hover:text-dark-text'
          }`}
        >
          <FileUp className="w-4 h-4" />
          上传PDF
        </button>
      </div>

      {/* 输入区域 */}
      <div className="flex-1 min-h-0 mb-4">
        {inputMode === 'upload' ? (
          <div className="h-full flex flex-col">
            {!selectedPaper ? (
              <div
                className="flex-1 flex flex-col items-center justify-center border-2 border-dashed border-dark-border rounded-lg cursor-pointer hover:border-primary-500/50 transition-colors"
                onDragOver={handleDragOver}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
              >
                <input ref={fileInputRef} type="file" accept=".pdf,.caj" onChange={handleFileChange} className="hidden" />
                <Upload className="w-12 h-12 text-dark-muted mb-4" />
                <p className="text-dark-muted mb-2">点击选择 PDF / CAJ 或拖拽文件到此处</p>
                {file && (
                  <>
                    <div className="flex items-center gap-2 mt-2">
                      <FileText className="w-4 h-4 text-primary-400" />
                      <span className="text-dark-text">{file.name}</span>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleUpload(); }}
                      disabled={loading}
                      className="mt-4 px-6 py-2 bg-primary-500 hover:bg-primary-600 text-white rounded-lg disabled:opacity-50"
                    >
                      {loading ? <span className="flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" />上传中...</span> : '上传并解析'}
                    </button>
                  </>
                )}
              </div>
            ) : (
              <div className="h-full flex flex-col">
                <div className="flex items-center gap-3 p-3 bg-dark-surface/50 rounded-lg mb-4">
                  <FileText className="w-5 h-5 text-primary-400" />
                  <div className="flex-1">
                    <p className="text-dark-text font-medium">{selectedPaper.title}</p>
                    {selectedPaper.authors.length > 0 && (
                      <p className="text-dark-muted text-sm">{Array.isArray(selectedPaper.authors) ? selectedPaper.authors.join(', ') : selectedPaper.authors}</p>
                    )}
                  </div>
                  <button onClick={() => { setSelectedPaper(null); setResult(null); }} className="p-1 hover:bg-dark-border/30 rounded">
                    <X className="w-4 h-4 text-dark-muted" />
                  </button>
                </div>
                <button onClick={() => fileInputRef.current?.click()} className="text-primary-400 hover:text-primary-300 text-sm">更换文件</button>
                <input ref={fileInputRef} type="file" accept=".pdf" onChange={handleFileChange} className="hidden" />
              </div>
            )}
          </div>
        ) : (
          <div className="h-full flex flex-col">
            <div className="relative mb-4">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-dark-muted" />
              <input
                type="text"
                value={libraryQuery}
                onChange={(e) => setLibraryQuery(e.target.value)}
                placeholder="搜索知识库中的论文..."
                className="w-full pl-10 pr-4 py-2 bg-dark-surface border border-dark-border rounded-lg text-dark-text placeholder-dark-muted"
              />
            </div>
            <div className="flex-1 overflow-auto">
              {libraryPapers.length === 0 ? (
                <div className="text-center text-dark-muted py-8">未找到相关论文</div>
              ) : (
                <div className="space-y-2">
                  {libraryPapers.map((paper) => (
                    <button
                      key={paper.paper_id}
                      onClick={() => handleSelectFromLibrary(paper)}
                      className={`w-full text-left p-3 rounded-lg transition-all ${
                        selectedPaper?.paper_id === paper.paper_id
                          ? 'bg-primary-500/20 border border-primary-500/50'
                          : 'bg-dark-surface/50 hover:bg-dark-border/30'
                      }`}
                    >
                      <p className="text-dark-text font-medium line-clamp-2">{paper.title}</p>
                      {paper.authors && <p className="text-dark-muted text-sm mt-1 line-clamp-1">{Array.isArray(paper.authors) ? paper.authors.join(', ') : paper.authors}</p>}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="flex items-center gap-2 p-3 mb-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400">
          <AlertCircle className="w-4 h-4" />
          {error}
        </div>
      )}

      {/* 阅读模式选择 */}
      <div className="mb-4">
        <p className="text-dark-muted text-sm mb-2">选择阅读模式</p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {(Object.entries(readingModeInfo) as [ReadingMode, typeof readingModeInfo.snap][]).map(([key, info]) => {
            const Icon = info.icon
            return (
              <button
                key={key}
                onClick={() => setReadingMode(key)}
                className={`p-3 rounded-lg transition-all text-left ${
                  readingMode === key ? 'bg-primary-500/20 border border-primary-500/50' : 'bg-dark-surface hover:bg-dark-border/30'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <Icon className={`w-4 h-4 ${readingMode === key ? 'text-primary-400' : 'text-dark-muted'}`} />
                  <span className={`text-sm font-medium ${readingMode === key ? 'text-primary-400' : 'text-dark-text'}`}>{info.label}</span>
                </div>
                <p className="text-xs text-dark-muted line-clamp-2">{info.desc}</p>
              </button>
            )
          })}
        </div>
      </div>

      {/* 开始分析按钮 */}
      <button
        onClick={handleAnalyze}
        disabled={!selectedPaper || analyzing}
        className="w-full py-3 bg-primary-500 hover:bg-primary-600 disabled:bg-dark-border disabled:cursor-not-allowed text-white rounded-lg transition-colors flex items-center justify-center gap-2"
      >
        {analyzing ? <><Loader2 className="w-5 h-5 animate-spin" />分析中...</> : <><Play className="w-5 h-5" />开始精读</>}
      </button>
      </>
      )}
    </div>
  )
}
