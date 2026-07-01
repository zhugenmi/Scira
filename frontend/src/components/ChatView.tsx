import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Send, Sparkles, Bot, User, Loader2, Plus, Trash2, MessageSquare, Clock, Check, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'
import PaperSelectionModal from './PaperSelectionModal'
import { OutlineCard } from './cards/OutlineCard'
import { WritingCard } from './cards/WritingCard'
import { ReviewCard } from './cards/ReviewCard'

interface RetrievalConditions {
  task_id?: string
  normalized_topic?: string
  key_concepts?: string[]
  research_direction?: string
  background_context?: string
  boolean_query?: string
  keywords?: string[]
  categories?: string[]
  date_range?: string[]
  max_results?: number
  rationale?: string
  [k: string]: any
}

interface Approval {
  taskId: string
  conditions: RetrievalConditions
  status: 'pending' | 'submitting' | 'approved'
  error?: string
}

export interface PendingPaper {
  paper_id: string
  title: string
  authors: string[] | string
  published_date: string
  abstract: string
  pdf_url: string
  source: string
  has_pdf_link: boolean
}

export type PaperDownloadStatus = 'pending' | 'downloading' | 'success' | 'failed'

export interface PaperStatusEntry {
  status: PaperDownloadStatus
  error?: string
}

export interface DownloadApproval {
  taskId: string
  papers: PendingPaper[]
  status: 'pending' | 'submitting' | 'approved' | 'rejected'
  selectedIds: string[]
  matchedCategory: string
  existingCategories: string[]
  submitted: boolean
  paperStatus: Record<string, PaperStatusEntry>
  error?: string
}

interface OutlineCardData {
  title?: string
  sections?: { section_id?: string; title?: string; key_points?: string[] }[]
  expanded?: boolean
}
interface WritingCardData {
  content: string
  done: boolean
  expanded?: boolean
}
interface ReviewCardData {
  revision_feedback?: string
  final_review?: string
  expanded?: boolean
}

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  workflowStatus?: string
  approval?: Approval
  downloadApproval?: DownloadApproval
  outlineCard?: OutlineCardData
  writingCard?: WritingCardData
  reviewCard?: ReviewCardData
}

interface Session {
  session_id: string
  created_at: string
  updated_at: string
  message_count: number
  context_tokens: number
  research_topics: string[]
}

type WorkflowStatus = 'idle' | 'running' | 'completed' | 'failed' | 'thinking'

interface ChatViewProps {
  sessionId?: string | null
  pendingMessage?: string | null
  onPendingConsumed?: () => void
}

export default function ChatView({ sessionId: initialSessionId, pendingMessage, onPendingConsumed }: ChatViewProps) {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'welcome',
      role: 'system',
      content: '欢迎使用 Scira 科研助手！请输入您感兴趣的研究主题，我将为您检索相关论文并生成综述报告。您也可以询问之前研究过的主题，或进行简单的对话。',
      timestamp: new Date()
    }
  ])
  const [input, setInput] = useState('')
  const [status, setStatus] = useState<WorkflowStatus>('idle')
  const [sessionId, setSessionId] = useState<string | null>(initialSessionId || null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [showSessions, setShowSessions] = useState(false)
  const [modalOpen, setModalOpen] = useState<{ msgId: string } | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)
  // 保存 messages 的最新引用，供 SSE 回调内读取（回调闭包会捕获旧 state）
  const messagesRef = useRef<Message[]>(messages)
  useEffect(() => { messagesRef.current = messages }, [messages])

  // 加载会话列表
  const loadSessions = async () => {
    try {
      const response = await fetch('/api/chat/sessions')
      const data = await response.json()
      if (data.sessions) {
        setSessions(data.sessions)
      }
    } catch (error) {
      console.error('Failed to load sessions:', error)
    }
  }

  // 删除会话
  const deleteSession = async (e: React.MouseEvent, sessionIdToDelete: string) => {
    e.stopPropagation()
    if (!confirm('确定要删除这个会话吗？')) return

    try {
      const response = await fetch(`/api/chat/session/${sessionIdToDelete}`, {
        method: 'DELETE'
      })
      if (response.ok) {
        // 如果删除的是当前会话，重置聊天
        if (sessionId === sessionIdToDelete) {
          setSessionId(null)
          setMessages([{
            id: 'welcome',
            role: 'system',
            content: '欢迎使用 Scira 科研助手！请输入您感兴趣的研究主题，我将为您检索相关论文并生成综述报告。您也可以询问之前研究过的主题，或进行简单的对话。',
            timestamp: new Date()
          }])
        }
        // 重新加载会话列表
        loadSessions()
      }
    } catch (error) {
      console.error('Failed to delete session:', error)
    }
  }

  // 创建新会话
  const createNewSession = () => {
    setSessionId(null)
    setMessages([{
      id: 'welcome',
      role: 'system',
      content: '欢迎使用 Scira 科研助手！请输入您感兴趣的研究主题，我将为您检索相关论文并生成综述报告。您也可以询问之前研究过的主题，或进行简单的对话。',
      timestamp: new Date()
    }])
    setShowSessions(false)
  }

  // 加载指定会话的历史
  const loadSessionHistory = async (sid: string) => {
    try {
      setSessionId(sid)
      const response = await fetch(`/api/chat/history/${sid}`)
      if (response.ok) {
        const data = await response.json()
        if (data.messages && data.messages.length > 0) {
          const historyMessages: Message[] = data.messages.map((msg: any, index: number) => {
            const m: Message = {
              id: `${sid}-${index}`,
              role: msg.role === 'user' ? 'user' : 'assistant',
              content: msg.content,
              timestamp: new Date(msg.timestamp || Date.now())
            }
            // 从 metadata 还原检索条件卡片（只读"已确认"态）
            const meta = msg.metadata || {}
            if (m.role === 'assistant' && meta.retrieval_conditions && meta.conditions_approved) {
              m.approval = {
                taskId: `${sid}-${index}`,
                conditions: meta.retrieval_conditions,
                status: 'approved',
              }
            }
            // 还原大纲/写作/审查卡片（折叠态）
            if (m.role === 'assistant') {
              if (meta.outline_card) m.outlineCard = { ...meta.outline_card, expanded: false }
              if (meta.writing_card) m.writingCard = { ...meta.writing_card, expanded: false }
              if (meta.review_card) m.reviewCard = { ...meta.review_card, expanded: false }
            }
            return m
          })
          setMessages([{
            id: 'welcome',
            role: 'system',
            content: '欢迎使用 Scira 科研助手！请输入您感兴趣的研究主题，我将为您检索相关论文并生成综述报告。您也可以询问之前研究过的主题，或进行简单的对话。',
            timestamp: new Date()
          }, ...historyMessages])
        }
      }
      setShowSessions(false)
    } catch (error) {
      console.error('Failed to load session history:', error)
    }
  }

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Cleanup polling/SSE on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
      }
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
      }
    }
  }, [])

  // SSE 事件处理
  const startWorkflowSSE = (taskId: string, assistantMessageId: string) => {
    // 关闭之前的连接
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }

    setStatus('running')

    // 建立 SSE 连接
    const eventSource = new EventSource(`/api/workflow/stream/${taskId}`)
    eventSourceRef.current = eventSource

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        console.log('SSE event:', data)

        switch (data.type) {
          case 'workflow_started':
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? { ...msg, workflowStatus: '已启动研究工作流，正在准备...' }
                : msg
            ))
            break

          case 'thinking':
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? { ...msg, workflowStatus: data.data?.message || 'thinking...' }
                : msg
            ))
            break

          case 'phase':
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? { ...msg, workflowStatus: data.data?.message || '' }
                : msg
            ))
            break

          case 'download': {
            // per-paper 事件：data.data.paper_id 存在时更新 paperStatus
            const pid = data.data?.paper_id
            const pstatus = data.data?.paper_status
            if (pid && pstatus) {
              setMessages(prev => prev.map(msg => {
                if (!msg.downloadApproval) return msg
                const ps = { ...msg.downloadApproval.paperStatus }
                ps[pid] = {
                  status: pstatus as PaperDownloadStatus,
                  error: data.data?.error || undefined,
                }
                return { ...msg, downloadApproval: { ...msg.downloadApproval, paperStatus: ps } }
              }))
            }
            // 同时更新顶层 workflowStatus 文本（计数事件）
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? { ...msg, workflowStatus: data.data?.message || '下载论文中...' }
                : msg
            ))
            break
          }

          case 'reading':
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? { ...msg, workflowStatus: data.data?.message || '阅读论文中...' }
                : msg
            ))
            break

          case 'generation':
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? { ...msg, workflowStatus: data.data?.message || '生成报告中...' }
                : msg
            ))
            break

          case 'outline_result':
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? { ...msg, outlineCard: { ...(data.data || {}), expanded: true } }
                : msg
            ))
            fetch(`/api/chat/session/${sessionId}/card`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ card_type: 'outline', payload: data.data || {} }),
            }).catch(() => {})
            break

          case 'writing_token':
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? {
                    ...msg,
                    writingCard: {
                      content: (msg.writingCard?.content || '') + (data.data?.token || ''),
                      done: false,
                      expanded: true,
                    },
                  }
                : msg
            ))
            break

          case 'writing_done':
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? {
                    ...msg,
                    writingCard: {
                      content: data.data?.paper_content || msg.writingCard?.content || '',
                      done: true,
                      expanded: true,
                    },
                  }
                : msg
            ))
            fetch(`/api/chat/session/${sessionId}/card`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ card_type: 'writing', payload: { content: data.data?.paper_content || '', done: true } }),
            }).catch(() => {})
            break

          case 'review_result':
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? { ...msg, reviewCard: { ...(data.data || {}), expanded: true } }
                : msg
            ))
            fetch(`/api/chat/session/${sessionId}/card`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ card_type: 'review', payload: data.data || {} }),
            }).catch(() => {})
            break

          case 'paper_download_approval_request': {
            const papers: PendingPaper[] = (data.data?.papers || []).map((p: any) => ({
              ...p,
              source: p.source || 'unknown',
              has_pdf_link: !!p.has_pdf_link,
            }))
            const matchedCategory: string = data.data?.matched_category || ''
            const existingCategories: string[] = data.data?.existing_categories || []
            const initialStatus: Record<string, PaperStatusEntry> = {}
            papers.forEach(p => { initialStatus[p.paper_id] = { status: 'pending' } })
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? {
                    ...msg,
                    workflowStatus: `检索完成，请确认要下载的论文（共 ${papers.length} 篇候选）`,
                    downloadApproval: {
                      taskId: data.data?.task_id || taskId,
                      papers,
                      status: 'pending',
                      selectedIds: papers.map(p => p.paper_id),
                      matchedCategory,
                      existingCategories,
                      submitted: false,
                      paperStatus: initialStatus,
                    },
                  }
                : msg
            ))
            break
          }

          case 'complete':
            setStatus('completed')
            eventSource.close()
            eventSourceRef.current = null

            const topic = data.data?.topic || ''
            const mode = data.data?.workflow_mode || 'full'
            const papersFound = data.data?.papers_found ?? 0
            const papersDownloaded = data.data?.papers_downloaded ?? 0
            const summary = data.data?.summary || ''
            let completeText: string
            if (mode === 'search') {
              // search 模式优先展示后端生成的检索结果简介（含论文清单）
              if (summary) {
                completeText = summary
              } else {
                completeText = topic
                  ? `已完成对「${topic}」的检索并下载 ${papersDownloaded} 篇论文，您可以在"知识库"页面查看。`
                  : `已完成检索并下载 ${papersDownloaded} 篇论文，您可以在"知识库"页面查看。`
              }
            } else {
              if (data.data?.final_report) {
                completeText = data.data.final_report
              } else {
                completeText = topic
                  ? `已完成对「${topic}」的研究！您可以在"生成论文"页面查看生成的报告。`
                  : '研究任务已完成！您可以在"生成论文"页面查看生成的报告。'
              }
            }
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? { ...msg, content: completeText, workflowStatus: undefined }
                : msg
            ))
            break

          case 'error':
            setStatus('failed')
            eventSource.close()
            eventSourceRef.current = null

            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? { ...msg, content: `抱歉，运行过程中出现错误：${data.data?.message || '未知错误'}`, workflowStatus: undefined }
                : msg
            ))
            break
        }
      } catch (error) {
        console.error('SSE parse error:', error)
      }
    }

    eventSource.onerror = (error) => {
      console.error('SSE error:', error)
      eventSource.close()
      eventSourceRef.current = null

      // 如果连接错误，尝试回退到轮询
      if (status === 'running') {
        console.log('SSE connection failed, falling back to polling')
        startWorkflowPolling(taskId, assistantMessageId)
      }
    }
  }

  // 保留轮询作为后备
  const startWorkflowPolling = (taskId: string, assistantMessageId: string) => {
    // 后端 phase 字符串 → 前端展示文案（与 SSE 推送保持一致）
    const phaseLabels: Record<string, string> = {
      init: '已启动研究工作流，正在准备...',
      retrieval: '论文检索中...',
      retrieval_download: '论文下载中...',
      reading: '论文阅读中...',
      analysis: '文献分析中...',
      outline: '生成论文大纲中...',
      writing: '生成论文中...',
      revision: '论文审查中...',
    }

    pollIntervalRef.current = setInterval(async () => {
      try {
        const response = await fetch(`/api/workflow/status/${taskId}`)
        if (!response.ok) return

        const data = await response.json()

        if (data.status === 'completed') {
          clearInterval(pollIntervalRef.current!)
          pollIntervalRef.current = null
          setStatus('completed')

          const researchTopic = data.result?.topic || ''
          const pollMode = data.result?.workflow_mode || 'full'
          const pollFound = data.result?.papers_found ?? 0
          const pollDownloaded = data.result?.papers_downloaded ?? 0
          const pollSummary = data.result?.summary || ''
          let pollCompleteText: string
          if (pollMode === 'search') {
            if (pollSummary) {
              pollCompleteText = pollSummary
            } else {
              pollCompleteText = researchTopic
                ? `已完成对「${researchTopic}」的检索并下载 ${pollDownloaded} 篇论文，您可以在"知识库"页面查看。`
                : `已完成检索并下载 ${pollDownloaded} 篇论文，您可以在"知识库"页面查看。`
            }
          } else {
            pollCompleteText = researchTopic
              ? `已完成对「${researchTopic}」的研究！您可以在"生成论文"页面查看生成的报告。`
              : '研究任务已完成！您可以在"生成论文"页面查看生成的报告。'
          }
          setMessages(prev => prev.map(msg =>
            msg.id === assistantMessageId
              ? {
                  ...msg,
                  content: pollCompleteText,
                  workflowStatus: undefined
                }
              : msg
          ))
        } else if (data.status === 'failed') {
          clearInterval(pollIntervalRef.current!)
          pollIntervalRef.current = null
          setStatus('failed')
          setMessages(prev => prev.map(msg =>
            msg.id === assistantMessageId
              ? { ...msg, content: `抱歉，运行过程中出现错误：${data.error || '未知错误'}`, workflowStatus: undefined }
              : msg
          ))
        } else {
          const phaseProgress = data.progress || 0
          // 优先用 details.message（后端进度回调写入），其次按 phase 映射
          const statusText = data.details?.message
            || phaseLabels[data.phase]
            || `工作中... (${Math.round(phaseProgress * 100)}%)`
          setMessages(prev => prev.map(msg =>
            msg.id === assistantMessageId
              ? { ...msg, workflowStatus: statusText }
              : msg
          ))
        }
      } catch (error) {
        console.error('Poll error:', error)
      }
    }, 2000)
  }

  const sendMessage = async (text: string) => {
    if (!text.trim() || status === 'running') return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: text.trim(),
      timestamp: new Date()
    }
    setMessages(prev => [...prev, userMessage])
    setInput('')

    const msgText = text.trim()

    // 添加助手消息占位
    const assistantMessageId = (Date.now() + 1).toString()
    let currentContent = ''
    setMessages(prev => [...prev, {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      workflowStatus: 'thinking...'
    }])

    setStatus('thinking')

    try {
      // 使用流式端点
      const requestBody: { message: string; session_id?: string } = {
        message: msgText
      }
      if (sessionId) {
        requestBody.session_id = sessionId
      }

      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody)
      })

      if (!response.ok) {
        throw new Error('请求失败')
      }

      // 保存 session_id（从第一个事件获取）
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      if (!reader) {
        throw new Error('无法读取响应')
      }

      let taskId: string | null = null

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const text = decoder.decode(value)
        // 解析多个 SSE 事件
        const events = text.split('data: ').filter(e => e.trim())

        for (const eventData of events) {
          try {
            const data = JSON.parse(eventData.trim())
            console.log('SSE event:', data.type, data.data)

            switch (data.type) {
              case 'thinking':
                setMessages(prev => prev.map(msg =>
                  msg.id === assistantMessageId
                    ? { ...msg, workflowStatus: data.data?.message || 'thinking...' }
                    : msg
                ))
                break

              case 'response_start':
                currentContent = data.data?.content || ''
                setMessages(prev => prev.map(msg =>
                  msg.id === assistantMessageId
                    ? { ...msg, content: currentContent, workflowStatus: currentContent ? undefined : (msg.workflowStatus || 'thinking...') }
                    : msg
                ))
                break

              case 'token':
                currentContent += data.data?.token || ''
                // 保留 workflowStatus：响应期间持续显示状态（如「thinking...」+ 旋转图标），
                // 避免长耗时阶段（如论文精读的 analyze_paper）页面看起来静止。
                // 仅在尚无具体状态时设一个通用的「正在思考...」。
                setMessages(prev => prev.map(msg =>
                  msg.id === assistantMessageId
                    ? { ...msg, content: currentContent, workflowStatus: msg.workflowStatus || '正在思考...' }
                    : msg
                ))
                break

              case 'workflow_started':
                taskId = data.data?.task_id
                setStatus('running')
                setMessages(prev => prev.map(msg =>
                  msg.id === assistantMessageId
                    ? { ...msg, workflowStatus: data.data?.message || '工作流已启动' }
                    : msg
                ))
                if (data.data?.session_id && !sessionId) {
                  setSessionId(data.data.session_id)
                }
                break

              case 'retrieval_approval_request':
                // 检索条件待确认：记录 task_id 与条件，等待用户接受/拒绝，
                // 此时不应启动工作流 SSE（工作流尚未真正运行）
                taskId = data.data?.task_id
                setStatus('completed')
                setMessages(prev => prev.map(msg =>
                  msg.id === assistantMessageId
                    ? {
                        ...msg,
                        workflowStatus: undefined,
                        approval: {
                          taskId: data.data?.task_id,
                          conditions: data.data?.conditions || {},
                          status: 'pending',
                        },
                      }
                    : msg
                ))
                break

              case 'response_done':
                if (taskId) {
                  // 仅当不存在待确认的审批时才订阅工作流状态；
                  // 审批流里 response_done 紧跟 retrieval_approval_request，此时不应启动 SSE
                  const hasApproval = messagesRef.current.find(m => m.id === assistantMessageId)?.approval
                  if (!hasApproval) {
                    startWorkflowSSE(taskId, assistantMessageId)
                  }
                } else {
                  setStatus('completed')
                  setMessages(prev => prev.map(msg =>
                    msg.id === assistantMessageId
                      ? { ...msg, workflowStatus: undefined }
                      : msg
                  ))
                }
                break

              case 'complete':
                setStatus('completed')
                setMessages(prev => prev.map(msg =>
                  msg.id === assistantMessageId
                    ? { ...msg, workflowStatus: undefined }
                    : msg
                ))
                break
            }
          } catch (err) {
            // 忽略解析错误
          }
        }
      }

    } catch (error) {
      setStatus('failed')
      setMessages(prev => prev.map(msg =>
        msg.id === assistantMessageId
          ? { ...msg, content: `抱歉，请求过程中出现错误：${error instanceof Error ? error.message : '未知错误'}`, workflowStatus: undefined }
          : msg
      ))
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    sendMessage(input)
  }

  // 接受检索条件：后台启动完整工作流，订阅工作流状态
  const handleApproveRetrieval = async (assistantMessageId: string, taskId: string) => {
    setMessages(prev => prev.map(m =>
      m.id === assistantMessageId && m.approval
        ? { ...m, approval: { ...m.approval, status: 'submitting', error: undefined } }
        : m
    ))
    try {
      const res = await fetch('/api/workflow/approve-retrieval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, decision: 'approve', session_id: sessionId || undefined }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data.status === 'running') {
        setMessages(prev => prev.map(m =>
          m.id === assistantMessageId && m.approval
            ? { ...m, approval: { ...m.approval!, status: 'approved' }, workflowStatus: '已确认检索条件，开始检索论文...' }
            : m
        ))
        setStatus('running')
        startWorkflowSSE(taskId, assistantMessageId)
      } else {
        setMessages(prev => prev.map(m =>
          m.id === assistantMessageId && m.approval
            ? { ...m, approval: { ...m.approval!, status: 'pending', error: data.detail || '启动失败' } }
            : m
        ))
      }
    } catch (e) {
      setMessages(prev => prev.map(m =>
        m.id === assistantMessageId && m.approval
          ? { ...m, approval: { ...m.approval!, status: 'pending', error: '网络错误' } }
          : m
      ))
    }
  }

  // 拒绝检索条件并提交修改建议：后端据此重新生成条件，刷新审批卡片
  const handleRejectRetrieval = async (assistantMessageId: string, taskId: string, modification: string) => {
    setMessages(prev => prev.map(m =>
      m.id === assistantMessageId && m.approval
        ? { ...m, approval: { ...m.approval, status: 'submitting', error: undefined } }
        : m
    ))
    try {
      const res = await fetch('/api/workflow/approve-retrieval', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, decision: 'reject', modification, session_id: sessionId || undefined }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data.status === 'awaiting_approval' && data.conditions) {
        setMessages(prev => prev.map(m =>
          m.id === assistantMessageId && m.approval
            ? { ...m, approval: { taskId, conditions: data.conditions, status: 'pending' } }
            : m
        ))
      } else {
        setMessages(prev => prev.map(m =>
          m.id === assistantMessageId && m.approval
            ? { ...m, approval: { ...m.approval!, status: 'pending', error: data.detail || '重新生成失败' } }
            : m
        ))
      }
    } catch (e) {
      setMessages(prev => prev.map(m =>
        m.id === assistantMessageId && m.approval
          ? { ...m, approval: { ...m.approval!, status: 'pending', error: '网络错误' } }
          : m
      ))
    }
  }

  // 确认下载：提交勾选的 paper_id，后端执行下载 + 后续节点
  const handleApproveDownload = async (
    assistantMessageId: string,
    taskId: string,
    selectedIds: string[],
    targetCategory?: string,
    newCategoryName?: string,
  ) => {
    setMessages(prev => prev.map(m =>
      m.id === assistantMessageId && m.downloadApproval
        ? { ...m, downloadApproval: { ...m.downloadApproval!, status: 'submitting', error: undefined, submitted: true }, workflowStatus: `开始下载 ${selectedIds.length} 篇论文...` }
        : m
    ))
    try {
      const res = await fetch('/api/workflow/approve-download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task_id: taskId,
          decision: 'approve',
          selected_paper_ids: selectedIds,
          target_category: targetCategory,
          new_category_name: newCategoryName,
          session_id: sessionId || undefined,
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok && (data.status === 'running' || data.status === 'completed')) {
        setMessages(prev => prev.map(m =>
          m.id === assistantMessageId && m.downloadApproval
            ? { ...m, downloadApproval: { ...m.downloadApproval!, status: 'approved' } }
            : m
        ))
        setStatus('running')
        startWorkflowSSE(taskId, assistantMessageId)
      } else {
        setMessages(prev => prev.map(m =>
          m.id === assistantMessageId && m.downloadApproval
            ? { ...m, downloadApproval: { ...m.downloadApproval!, status: 'pending', submitted: false, error: data.detail || '提交失败' } }
            : m
        ))
      }
    } catch (e) {
      setMessages(prev => prev.map(m =>
        m.id === assistantMessageId && m.downloadApproval
          ? { ...m, downloadApproval: { ...m.downloadApproval!, status: 'pending', submitted: false, error: '网络错误' } }
          : m
      ))
    }
  }

  // 跳过下载：不下载 PDF，任务标记完成
  const handleRejectDownload = async (assistantMessageId: string, taskId: string) => {
    setMessages(prev => prev.map(m =>
      m.id === assistantMessageId && m.downloadApproval
        ? { ...m, downloadApproval: { ...m.downloadApproval!, status: 'submitting', error: undefined } }
        : m
    ))
    try {
      const res = await fetch('/api/workflow/approve-download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId, decision: 'reject', session_id: sessionId || undefined }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.ok && data.status === 'completed') {
        setMessages(prev => prev.map(m =>
          m.id === assistantMessageId && m.downloadApproval
            ? { ...m, downloadApproval: { ...m.downloadApproval!, status: 'rejected' }, workflowStatus: undefined, content: '已跳过下载。论文已入库知识库（未下载 PDF）。' }
            : m
        ))
        setStatus('completed')
      } else {
        setMessages(prev => prev.map(m =>
          m.id === assistantMessageId && m.downloadApproval
            ? { ...m, downloadApproval: { ...m.downloadApproval!, status: 'pending', error: data.detail || '提交失败' } }
            : m
        ))
      }
    } catch (e) {
      setMessages(prev => prev.map(m =>
        m.id === assistantMessageId && m.downloadApproval
          ? { ...m, downloadApproval: { ...m.downloadApproval!, status: 'pending', error: '网络错误' } }
          : m
      ))
    }
  }

  // Load session on mount
  useEffect(() => {
    const initSession = async () => {
      await loadSessions()

      // 如果有外部传入的 sessionId，加载该会话
      if (initialSessionId) {
        setSessionId(initialSessionId)
        try {
          const historyResponse = await fetch(`/api/chat/history/${initialSessionId}`)
          if (historyResponse.ok) {
            const historyData = await historyResponse.json()
            if (historyData.messages && historyData.messages.length > 0) {
              const historyMessages: Message[] = historyData.messages.map((msg: any, index: number) => ({
                id: `${initialSessionId}-${index}`,
                role: msg.role === 'user' ? 'user' : 'assistant',
                content: msg.content,
                timestamp: new Date(msg.timestamp || Date.now())
              }))
              setMessages([
                {
                  id: 'welcome',
                  role: 'system',
                  content: '欢迎使用 Scira 科研助手！请输入您感兴趣的研究主题，我将为您检索相关论文并生成综述报告。您也可以询问之前研究过的主题，或进行简单的对话。',
                  timestamp: new Date()
                },
                ...historyMessages
              ])
            }
          }
        } catch (error) {
          console.error('Failed to load session history:', error)
        }
        return
      }

      // 如果没有 sessionId，创建新会话（只显示欢迎消息）
      if (!initialSessionId) {
        setSessionId(null)
        // 若有 pendingMessage（从知识库「阅读该论文」跳转来），自动发送 effect 已在挂载时
        // 触发 sendMessage 并写入用户消息，这里不能再覆写 messages，否则会把待发送消息冲掉
        if (!pendingMessage) {
          setMessages([{
            id: 'welcome',
            role: 'system',
            content: '欢迎使用 Scira 科研助手！请输入您感兴趣的研究主题，我将为您检索相关论文并生成综述报告。您也可以询问之前研究过的主题，或进行简单的对话。',
            timestamp: new Date()
          }])
        }
        return
      }

      // 否则加载最近的会话
      try {
        const response = await fetch('/api/chat/sessions')
        const data = await response.json()
        if (data.sessions && data.sessions.length > 0) {
          // Use the most recent session
          const latestSession = data.sessions[0]
          setSessionId(latestSession.session_id)

          // Load history for this session
          const historyResponse = await fetch(`/api/chat/history/${latestSession.session_id}`)
          if (historyResponse.ok) {
            const historyData = await historyResponse.json()
            if (historyData.messages && historyData.messages.length > 0) {
              // Convert history messages to UI format
              const historyMessages: Message[] = historyData.messages.map((msg: any, index: number) => ({
                id: `${latestSession.session_id}-${index}`,
                role: msg.role === 'user' ? 'user' : 'assistant',
                content: msg.content,
                timestamp: new Date(msg.timestamp || Date.now())
              }))
              // Prepend to existing messages (keep welcome message)
              setMessages(prev => [...prev.slice(0, 1), ...historyMessages])
            }
          }
        }
      } catch (error) {
        console.error('Failed to load session:', error)
      }
    }

    initSession()
  }, [])

  // 从知识库「阅读该论文」跳转过来时，自动发送预填消息
  // 用 ref 去重，避免 React.StrictMode 在开发模式下双触发 effect 导致重复发送
  const pendingFiredRef = useRef<string | null>(null)
  useEffect(() => {
    if (!pendingMessage) return
    if (pendingFiredRef.current === pendingMessage) return
    pendingFiredRef.current = pendingMessage
    onPendingConsumed?.()
    sendMessage(pendingMessage)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingMessage])

  return (
    <div className="h-full flex flex-col">
      {/* 顶部会话管理栏 */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-dark-border bg-dark-surface/50">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowSessions(!showSessions)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-dark-border/50 hover:bg-dark-border
                     text-dark-muted hover:text-dark-text rounded-lg transition-colors"
          >
            <MessageSquare className="w-4 h-4" />
            会话
          </button>
          {sessionId && (
            <span className="text-xs text-dark-muted">
              {sessions.find(s => s.session_id === sessionId)?.message_count || 0} 条消息
            </span>
          )}
        </div>
        <button
          onClick={createNewSession}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary-500/20 hover:bg-primary-500/30
                   text-primary-400 rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" />
          新会话
        </button>
      </div>

      {/* 会话列表弹窗 */}
      <AnimatePresence>
        {showSessions && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-b border-dark-border bg-dark-surface overflow-hidden"
          >
            <div className="p-3 max-h-48 overflow-auto">
              {sessions.length === 0 ? (
                <div className="text-center text-dark-muted text-sm py-4">
                  暂无会话记录
                </div>
              ) : (
                <div className="space-y-2">
                  {sessions.map((s) => (
                    <div
                      key={s.session_id}
                      onClick={() => loadSessionHistory(s.session_id)}
                      className={`flex items-center justify-between p-2 rounded-lg cursor-pointer transition-colors
                        ${sessionId === s.session_id
                          ? 'bg-primary-500/20 border border-primary-500/30'
                          : 'hover:bg-dark-border/50'
                        }`}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="text-sm text-dark-text truncate">
                          {s.research_topics?.length > 0
                            ? s.research_topics.join(', ')
                            : '新会话'}
                        </div>
                        <div className="flex items-center gap-2 text-xs text-dark-muted">
                          <Clock className="w-3 h-3" />
                          {new Date(s.updated_at).toLocaleString('zh-CN', {
                            month: 'numeric',
                            day: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit'
                          })}
                          <span>· {s.message_count} 条消息</span>
                        </div>
                      </div>
                      <button
                        onClick={(e) => deleteSession(e, s.session_id)}
                        className="p-1.5 text-dark-muted hover:text-red-400 hover:bg-red-400/10
                                 rounded-lg transition-colors"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 消息区域 */}
      <div className="flex-1 overflow-auto p-4 space-y-4">
        {messages.map((message) => (
          <motion.div
            key={message.id}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className={`flex gap-3 ${message.role === 'user' ? 'flex-row-reverse' : ''}`}
          >
            {/* 头像 */}
            <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0
              ${message.role === 'system'
                ? 'bg-gradient-to-br from-primary-400 to-primary-600'
                : message.role === 'user'
                  ? 'bg-dark-border'
                  : 'bg-primary-500/30'
              }`}>
              {message.role === 'system' && <Sparkles className="w-4 h-4 text-white" />}
              {message.role === 'user' && <User className="w-4 h-4 text-dark-muted" />}
              {message.role === 'assistant' && <Bot className="w-4 h-4 text-primary-400" />}
            </div>

            {/* 消息内容 */}
            <div className={`max-w-[70%] ${message.approval ? 'md:max-w-[85%] max-w-[90%]' : ''}`}>
              <div className={`rounded-2xl px-4 py-3 text-sm leading-relaxed
                ${message.role === 'system'
                  ? 'bg-dark-surface border border-dark-border text-dark-text/80 whitespace-pre-wrap'
                  : message.role === 'user'
                    ? 'bg-primary-500 text-white whitespace-pre-wrap'
                    : 'bg-dark-surface border border-dark-border text-dark-text'
                }`}>
                {message.role === 'assistant' ? (
                  <div className="prose-chat">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm, remarkMath]}
                      rehypePlugins={[rehypeKatex]}
                      components={{
                        h1: ({ children }) => <h1 className="text-lg font-bold text-dark-text border-b border-dark-border pb-2 mb-3 mt-2">{children}</h1>,
                        h2: ({ children }) => <h2 className="text-base font-bold text-primary-400 mt-4 mb-2">{children}</h2>,
                        h3: ({ children }) => <h3 className="text-sm font-semibold text-dark-text mt-3 mb-1.5">{children}</h3>,
                        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                        ul: ({ children }) => <ul className="list-disc list-inside space-y-1 mb-2">{children}</ul>,
                        ol: ({ children }) => <ol className="list-decimal list-inside space-y-1 mb-2">{children}</ol>,
                        li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                        strong: ({ children }) => <strong className="font-semibold text-dark-text">{children}</strong>,
                        em: ({ children }) => <em className="italic">{children}</em>,
                        code: ({ children }) => <code className="bg-dark-border/50 px-1 py-0.5 rounded text-xs">{children}</code>,
                        pre: ({ children }) => <pre className="bg-dark-border/30 p-2 rounded text-xs overflow-x-auto mb-2">{children}</pre>,
                        blockquote: ({ children }) => <blockquote className="border-l-2 border-primary-400 pl-3 text-dark-muted mb-2">{children}</blockquote>,
                        table: ({ children }) => <table className="border-collapse mb-2 text-xs">{children}</table>,
                        th: ({ children }) => <th className="border border-dark-border px-2 py-1 bg-dark-border/30">{children}</th>,
                        td: ({ children }) => <td className="border border-dark-border px-2 py-1">{children}</td>,
                      }}
                    >
                      {message.content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <span className="whitespace-pre-wrap">{message.content}</span>
                )}
              </div>

              {/* 检索条件审批卡片 */}
              {message.role === 'assistant' && message.approval && (
                <ApprovalCard
                  approval={message.approval}
                  onApprove={() => handleApproveRetrieval(message.id, message.approval!.taskId)}
                  onReject={(mod) => handleRejectRetrieval(message.id, message.approval!.taskId, mod)}
                />
              )}

              {message.role === 'assistant' && message.downloadApproval && (
                <PaperDownloadCard
                  approval={message.downloadApproval}
                  onOpenModal={() => setModalOpen({ msgId: message.id })}
                  onReject={() => handleRejectDownload(message.id, message.downloadApproval!.taskId)}
                />
              )}

              {modalOpen && modalOpen.msgId === message.id && message.downloadApproval && (
                <PaperSelectionModal
                  open
                  approval={message.downloadApproval}
                  workflowMode={'full'}
                  onClose={() => setModalOpen(null)}
                  onSubmit={(ids, targetCat, newName) => {
                    handleApproveDownload(message.id, message.downloadApproval!.taskId, ids, targetCat, newName)
                  }}
                />
              )}

              {message.role === 'assistant' && message.outlineCard && (
                <OutlineCard
                  data={message.outlineCard}
                  onToggle={() => setMessages(prev => prev.map(m =>
                    m.id === message.id ? { ...m, outlineCard: { ...m.outlineCard!, expanded: !m.outlineCard!.expanded } } : m
                  ))}
                />
              )}
              {message.role === 'assistant' && message.writingCard && (
                <WritingCard
                  data={message.writingCard}
                  onToggle={() => setMessages(prev => prev.map(m =>
                    m.id === message.id ? { ...m, writingCard: { ...m.writingCard!, expanded: !m.writingCard!.expanded } } : m
                  ))}
                />
              )}
              {message.role === 'assistant' && message.reviewCard && (
                <ReviewCard
                  data={message.reviewCard}
                  onToggle={() => setMessages(prev => prev.map(m =>
                    m.id === message.id ? { ...m, reviewCard: { ...m.reviewCard!, expanded: !m.reviewCard!.expanded } } : m
                  ))}
                />
              )}

              {message.role === 'assistant' && message.workflowStatus && (
                <div className="flex items-center gap-1.5 mt-1 text-xs text-dark-muted">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  {message.workflowStatus}
                </div>
              )}
              <div className="text-xs text-dark-muted mt-1">
                {message.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
              </div>
            </div>
          </motion.div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区域 */}
      <div className="p-4 border-t border-dark-border">
        <form onSubmit={handleSubmit} className="flex gap-3">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSubmit(e)
                }
              }}
              placeholder="输入研究主题，例如：深度强化学习、Transformer架构..."
              className="w-full bg-dark-surface border border-dark-border rounded-xl px-4 py-3 pr-12
                       text-dark-text placeholder-dark-muted resize-none
                       focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500/20
                       transition-all"
              rows={1}
              style={{ minHeight: '48px', maxHeight: '120px' }}
              disabled={status === 'running'}
            />
          </div>
          <button
            type="submit"
            disabled={!input.trim() || status === 'running'}
            className="w-12 h-12 rounded-xl bg-primary-500 hover:bg-primary-600
                     disabled:bg-dark-border disabled:text-dark-muted
                     text-white flex items-center justify-center
                     transition-all duration-200 hover:shadow-lg hover:shadow-primary-500/20
                     active:scale-95 disabled:active:scale-100"
          >
            {status === 'running' ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <Send className="w-5 h-5" />
            )}
          </button>
        </form>

        {/* 快捷输入 */}
        <div className="flex gap-2 mt-3 flex-wrap">
          <span className="text-xs text-dark-muted">快捷输入：</span>
          {['深度学习', '强化学习', 'Transformer', 'GPT'].map((topic) => (
            <button
              key={topic}
              onClick={() => setInput(topic)}
              disabled={status === 'running'}
              className="px-2 py-1 text-xs bg-dark-border/50 hover:bg-dark-border
                       text-dark-muted hover:text-dark-text rounded-md
                       transition-colors disabled:opacity-50"
            >
              {topic}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}


// 检索条件审批卡片：展示规范化主题/关键词/布尔查询/时间范围等，提供 接受 / 拒绝+修改建议 两个入口
function ApprovalCard({
  approval,
  onApprove,
  onReject,
}: {
  approval: Approval
  onApprove: () => void
  onReject: (modification: string) => void
}) {
  const [showReject, setShowReject] = useState(false)
  const [mod, setMod] = useState('')
  const c = approval.conditions || {}
  const submitting = approval.status === 'submitting'
  const approved = approval.status === 'approved'

  return (
    <div className="mt-2 rounded-xl border border-primary-500/30 bg-primary-500/5 p-3 text-left">
      <div className="flex items-center gap-2 text-primary-400 text-xs font-medium mb-2">
        <Sparkles className="w-3.5 h-3.5" />
        请确认检索条件
      </div>

      <div className="space-y-1.5 text-xs text-dark-text/90">
        {c.normalized_topic && (
          <div><span className="text-dark-muted">规范化主题：</span>{c.normalized_topic}</div>
        )}
        {(c.key_concepts || []).length > 0 && (
          <div><span className="text-dark-muted">关键概念：</span>{(c.key_concepts || []).join('、')}</div>
        )}
        {c.boolean_query && (
          <div className="flex gap-1"><span className="text-dark-muted shrink-0">布尔查询：</span><code className="bg-dark-bg px-1.5 py-0.5 rounded text-primary-300 break-all">{c.boolean_query}</code></div>
        )}
        {(c.keywords || []).length > 0 && (
          <div><span className="text-dark-muted">关键词：</span>{(c.keywords || []).join('、')}</div>
        )}
        {(c.categories || []).length > 0 && (
          <div><span className="text-dark-muted">分类：</span>{(c.categories || []).join('、')}</div>
        )}
        {c.date_range && c.date_range.length === 2 && (c.date_range[0] || c.date_range[1]) && (
          <div><span className="text-dark-muted">时间范围：</span>{c.date_range[0] || '…'} ~ {c.date_range[1] || '…'}</div>
        )}
        {c.max_results != null && (
          <div><span className="text-dark-muted">最大结果数：</span>{c.max_results}</div>
        )}
        {c.rationale && (
          <div className="text-dark-muted"><span>理由：</span>{c.rationale}</div>
        )}
      </div>

      {approval.error && (
        <div className="mt-2 text-xs text-red-400">{approval.error}</div>
      )}

      {!approved && (
        <div className="mt-3 space-y-2">
          {!showReject ? (
            <div className="flex gap-2">
              <button
                onClick={onApprove}
                disabled={submitting}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-500 hover:bg-primary-600 disabled:opacity-50 text-white rounded-lg text-xs transition-colors"
              >
                {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                接受并检索
              </button>
              <button
                onClick={() => setShowReject(true)}
                disabled={submitting}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-dark-bg hover:bg-dark-border disabled:opacity-50 text-dark-text rounded-lg text-xs border border-dark-border transition-colors"
              >
                <X className="w-3.5 h-3.5" />
                拒绝并修改
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              <textarea
                value={mod}
                onChange={(e) => setMod(e.target.value)}
                placeholder="请输入修改建议，例如：增加近5年的论文、补充XXX方向的关键词…"
                className="w-full bg-dark-bg border border-dark-border rounded-lg px-2.5 py-1.5 text-xs text-dark-text resize-none focus:outline-none focus:border-primary-500 placeholder:text-dark-muted"
                rows={2}
              />
              <div className="flex gap-2">
                <button
                  onClick={() => { onReject(mod); setMod(''); setShowReject(false) }}
                  disabled={submitting || !mod.trim()}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-500 hover:bg-primary-600 disabled:opacity-50 text-white rounded-lg text-xs transition-colors"
                >
                  {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                  提交修改并重新生成
                </button>
                <button
                  onClick={() => setShowReject(false)}
                  disabled={submitting}
                  className="px-3 py-1.5 bg-dark-bg hover:bg-dark-border text-dark-muted rounded-lg text-xs border border-dark-border transition-colors"
                >
                  取消
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {approved && (
        <div className="mt-3 flex items-center gap-1.5 text-xs text-green-400">
          <Check className="w-3.5 h-3.5" />
          已确认检索条件，正在检索…
        </div>
      )}
    </div>
  )
}

function PaperDownloadCard({
  approval,
  onOpenModal,
  onReject,
}: {
  approval: DownloadApproval
  onOpenModal: () => void
  onReject: () => void
}) {
  const { papers, status, submitted, paperStatus } = approval
  const readonly = status === 'approved' || status === 'rejected' || status === 'submitting'

  const successCount = papers.filter(p => paperStatus[p.paper_id]?.status === 'success').length
  const failedCount = papers.filter(p => paperStatus[p.paper_id]?.status === 'failed').length
  const total = papers.length
  const downloading = submitted && successCount + failedCount < total

  return (
    <div className="mt-3 rounded-xl border border-primary-500/30 bg-primary-500/5 p-3 text-left">
      <div className="flex items-center justify-between mb-2">
        <div className="text-sm font-medium text-dark-text">
          {submitted
            ? `下载中 ${successCount + failedCount}/${total}`
            : `论文下载确认（共 ${total} 篇候选）`}
        </div>
      </div>
      {!readonly && (
        <div className="flex gap-2">
          <button
            onClick={onOpenModal}
            className="flex-1 px-3 py-1.5 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium transition-colors"
          >
            {submitted ? '查看下载进度' : '查看 / 选择详情'}
          </button>
          <button
            onClick={onReject}
            className="px-3 py-1.5 rounded-lg border border-dark-border hover:bg-dark-surface text-dark-muted text-sm transition-colors"
          >
            跳过下载
          </button>
        </div>
      )}
      {readonly && status === 'approved' && (
        <div className="text-xs text-green-400 flex items-center gap-1">
          <Check className="w-3 h-3" />
          {downloading ? `下载中 ${successCount + failedCount}/${total}` : `下载完成（成功 ${successCount}，失败 ${failedCount}）`}
        </div>
      )}
    </div>
  )
}
