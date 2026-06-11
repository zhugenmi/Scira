import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Send, Sparkles, Bot, User, Loader2, Plus, Trash2, MessageSquare, Clock } from 'lucide-react'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
}

interface Session {
  session_id: string
  created_at: string
  updated_at: string
  message_count: number
  context_tokens: number
  research_topics: string[]
}

type WorkflowStatus = 'idle' | 'running' | 'completed' | 'failed'

type ChatAction = 'direct_response' | 'knowledge_query' | 'start_workflow' | 'clarification' | 'help'

export default function ChatView() {
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
  const [progress, setProgress] = useState(0)
  const [currentPhase, setCurrentPhase] = useState('')
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [showSessions, setShowSessions] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)

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

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
      }
    }
  }, [])

  // Poll workflow status
  const startWorkflowPolling = (taskId: string, assistantMessageId: string) => {
    const phases = ['论文检索', '论文阅读', '文献分析', '大纲生成', '论文写作', '论文修订']
    let currentProgress = 0

    pollIntervalRef.current = setInterval(async () => {
      try {
        const response = await fetch(`/api/workflow/status/${taskId}`)
        if (!response.ok) return

        const data = await response.json()

        if (data.status === 'completed') {
          // Workflow completed
          clearInterval(pollIntervalRef.current!)
          pollIntervalRef.current = null
          setProgress(100)
          setCurrentPhase('完成！')
          setStatus('completed')

          const researchTopic = data.result?.topic || ''
          setMessages(prev => prev.map(msg =>
            msg.id === assistantMessageId
              ? {
                  ...msg,
                  content: researchTopic
                    ? `已完成对「${researchTopic}」的研究！您可以在"生成论文"页面查看生成的报告。`
                    : '研究任务已完成！您可以在"生成论文"页面查看生成的报告。'
                }
              : msg
          ))
        } else if (data.status === 'failed') {
          // Workflow failed
          clearInterval(pollIntervalRef.current!)
          pollIntervalRef.current = null
          setStatus('failed')
          setCurrentPhase('运行失败')
          setMessages(prev => prev.map(msg =>
            msg.id === assistantMessageId
              ? { ...msg, content: `抱歉，运行过程中出现错误：${data.error || '未知错误'}` }
              : msg
          ))
        } else {
          // Still running - update progress
          const phaseProgress = data.progress || 0
          setProgress(Math.min(phaseProgress * 100, 95))
          if (data.phase) {
            const phaseIndex = phases.findIndex(p => data.phase.toLowerCase().includes(p.replace('论文', '')))
            if (phaseIndex >= 0) {
              setCurrentPhase(`正在${phases[phaseIndex]}...`)
            } else {
              setCurrentPhase(`工作中... (${Math.round(phaseProgress * 100)}%)`)
            }
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
    setMessages(prev => [...prev, {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date()
    }])

    try {
      // 调用新的 Chat API
      const requestBody: { message: string; session_id?: string } = {
        message: userMessage.content
      }
      if (sessionId) {
        requestBody.session_id = sessionId
      }

      const response = await fetch('/api/chat/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody)
      })

      if (!response.ok) {
        throw new Error('请求失败')
      }

      const data = await response.json()

      // 保存 session_id
      if (data.session_id && !sessionId) {
        setSessionId(data.session_id)
      }

      const action = data.action as ChatAction

      if (action === 'start_workflow') {
        // 需要触发工作流
        setStatus('running')
        setProgress(0)
        setCurrentPhase('正在启动工作流...')

        if (data.task_id) {
          // 开始轮询工作流状态
          startWorkflowPolling(data.task_id, assistantMessageId)
        } else {
          // 没有 task_id，直接完成
          setStatus('completed')
          setProgress(100)
          setCurrentPhase('完成！')
          setMessages(prev => prev.map(msg =>
            msg.id === assistantMessageId
              ? { ...msg, content: data.response || '任务已完成。' }
              : msg
          ))
        }
      } else {
        // 直接回复或知识查询
        setStatus('completed')
        setMessages(prev => prev.map(msg =>
          msg.id === assistantMessageId
            ? { ...msg, content: data.response }
            : msg
        ))
      }

    } catch (error) {
      setStatus('failed')
      setCurrentPhase('运行失败')
      setMessages(prev => prev.map(msg =>
        msg.id === assistantMessageId
          ? { ...msg, content: `抱歉，请求过程中出现错误：${error instanceof Error ? error.message : '未知错误'}` }
          : msg
      ))
    }
  }

  // Load session on mount
  useEffect(() => {
    const initSession = async () => {
      await loadSessions()
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
              <div className={`text-xs text-dark-muted mt-1 ${message.role === 'user' ? 'text-right' : ''}`}>
                {message.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
              </div>
            </div>
          </motion.div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* 运行状态 */}
      <AnimatePresence>
        {status === 'running' && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="border-t border-dark-border bg-dark-surface/50"
          >
            <div className="p-4 space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="text-dark-muted">{currentPhase}</span>
                <span className="text-primary-400 font-medium">{progress}%</span>
              </div>
              <div className="h-1.5 bg-dark-border rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-gradient-to-r from-primary-500 to-primary-400"
                  initial={{ width: 0 }}
                  animate={{ width: `${progress}%` }}
                  transition={{ duration: 0.3 }}
                />
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

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
