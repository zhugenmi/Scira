import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Send, Sparkles, Bot, User, Loader2, Plus, Trash2, MessageSquare, Clock } from 'lucide-react'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  workflowStatus?: string
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
}

export default function ChatView({ sessionId: initialSessionId }: ChatViewProps) {
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
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

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
          const historyMessages: Message[] = data.messages.map((msg: any, index: number) => ({
            id: `${sid}-${index}`,
            role: msg.role === 'user' ? 'user' : 'assistant',
            content: msg.content,
            timestamp: new Date(msg.timestamp || Date.now())
          }))
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
                ? { ...msg, workflowStatus: data.data?.message || 'AI 正在思考...' }
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

          case 'download':
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? { ...msg, workflowStatus: data.data?.message || '下载论文中...' }
                : msg
            ))
            break

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

          case 'complete':
            setStatus('completed')
            eventSource.close()
            eventSourceRef.current = null

            const topic = data.data?.topic || ''
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? {
                    ...msg,
                    content: topic
                      ? `已完成对「${topic}」的研究！您可以在"生成论文"页面查看生成的报告。`
                      : '研究任务已完成！您可以在"生成论文"页面查看生成的报告。',
                    workflowStatus: undefined
                  }
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
    const phases = ['论文检索', '论文阅读', '文献分析', '大纲生成', '论文写作', '论文修订']

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
          setMessages(prev => prev.map(msg =>
            msg.id === assistantMessageId
              ? {
                  ...msg,
                  content: researchTopic
                    ? `已完成对「${researchTopic}」的研究！您可以在"生成论文"页面查看生成的报告。`
                    : '研究任务已完成！您可以在"生成论文"页面查看生成的报告。',
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
          if (data.phase) {
            const phaseIndex = phases.findIndex(p => data.phase.toLowerCase().includes(p.replace('论文', '')))
            const statusText = phaseIndex >= 0
              ? `正在${phases[phaseIndex]}...`
              : `工作中... (${Math.round(phaseProgress * 100)}%)`
            setMessages(prev => prev.map(msg =>
              msg.id === assistantMessageId
                ? { ...msg, workflowStatus: statusText }
                : msg
            ))
          }
        }
      } catch (error) {
        console.error('Poll error:', error)
      }
    }, 2000)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || status === 'running') return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date()
    }
    setMessages(prev => [...prev, userMessage])
    setInput('')

    // 添加助手消息占位
    const assistantMessageId = (Date.now() + 1).toString()
    let currentContent = ''
    setMessages(prev => [...prev, {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      workflowStatus: 'AI 正在思考...'
    }])

    setStatus('thinking')

    try {
      // 使用流式端点
      const requestBody: { message: string; session_id?: string } = {
        message: userMessage.content
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
                    ? { ...msg, workflowStatus: data.data?.message || 'AI 正在思考...' }
                    : msg
                ))
                break

              case 'response_start':
                currentContent = data.data?.content || ''
                setMessages(prev => prev.map(msg =>
                  msg.id === assistantMessageId
                    ? { ...msg, content: currentContent, workflowStatus: undefined }
                    : msg
                ))
                break

              case 'token':
                currentContent += data.data?.token || ''
                setMessages(prev => prev.map(msg =>
                  msg.id === assistantMessageId
                    ? { ...msg, content: currentContent, workflowStatus: undefined }
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

              case 'response_done':
                if (taskId) {
                  startWorkflowSSE(taskId, assistantMessageId)
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
        setMessages([{
          id: 'welcome',
          role: 'system',
          content: '欢迎使用 Scira 科研助手！请输入您感兴趣的研究主题，我将为您检索相关论文并生成综述报告。您也可以询问之前研究过的主题，或进行简单的对话。',
          timestamp: new Date()
        }])
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
            <div className={`max-w-[70%] ${message.role === 'user' ? 'text-right' : ''}`}>
              <div className={`rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap
                ${message.role === 'system'
                  ? 'bg-dark-surface border border-dark-border text-dark-text/80'
                  : message.role === 'user'
                    ? 'bg-primary-500 text-white'
                    : 'bg-dark-surface border border-dark-border text-dark-text'
                }`}>
                {message.content}
              </div>
              {message.role === 'assistant' && message.workflowStatus && (
                <div className="flex items-center gap-1.5 mt-1 text-xs text-dark-muted">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  {message.workflowStatus}
                </div>
              )}
              <div className={`text-xs text-dark-muted mt-1 ${message.role === 'user' ? 'text-right' : ''}`}>
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
