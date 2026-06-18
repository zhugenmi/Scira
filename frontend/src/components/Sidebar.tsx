import { motion } from 'framer-motion'
import {
  MessageSquare,
  FileText,
  BookOpen,
  ChevronLeft,
  Plus,
  History,
  GraduationCap,
  Trash2
} from 'lucide-react'
import { useState, useEffect, useCallback } from 'react'

type View = 'chat' | 'generated' | 'knowledge' | 'paper-reading'

interface SidebarProps {
  currentView: View
  onViewChange: (view: View) => void
  isCollapsed: boolean
  onToggleCollapse: () => void
  onNewSession?: () => void
  onSelectSession?: (sessionId: string) => void
  onSessionDeleted?: (sessionId: string) => void
}

interface MenuItem {
  id: View
  label: string
  icon: React.ReactNode
  badge?: number
}

interface Session {
  session_id: string
  created_at: string
  updated_at: string
  message_count: number
  context_tokens: number
  research_topics: string[]
}

function formatTimeAgo(dateString: string): string {
  const date = new Date(dateString)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMs / 3600000)
  const diffDays = Math.floor(diffMs / 86400000)

  if (diffMins < 1) return '刚刚'
  if (diffMins < 60) return `${diffMins}分钟前`
  if (diffHours < 24) return `${diffHours}小时前`
  if (diffDays === 1) return '昨天'
  if (diffDays < 7) return `${diffDays}天前`
  return `${Math.floor(diffDays / 7)}周前`
}

export default function Sidebar({
  currentView,
  onViewChange,
  isCollapsed,
  onToggleCollapse,
  onNewSession,
  onSelectSession,
  onSessionDeleted
}: SidebarProps) {
  const [generatedCount, setGeneratedCount] = useState(0)
  const [knowledgeCount, setKnowledgeCount] = useState(0)
  const [recentSessions, setRecentSessions] = useState<Session[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)

  // 拉取最近会话列表（删除后复用同一逻辑刷新）
  const loadRecentSessions = useCallback(async () => {
    try {
      const sessionsRes = await fetch('/api/chat/sessions')
      if (sessionsRes.ok) {
        const sessionsData = await sessionsRes.json()
        const sorted = (sessionsData.sessions || [])
          .sort((a: Session, b: Session) =>
            new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
          )
          .slice(0, 5)
        setRecentSessions(sorted)
      }
    } catch (e) {
      console.error('Failed to fetch sessions:', e)
    }
  }, [])

  // 删除会话：复用后端已有的 /api/chat/session/{id} DELETE 接口
  const handleDeleteSession = async (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation()
    if (!confirm('确定要删除这个会话吗？')) return
    try {
      const res = await fetch(`/api/chat/session/${sessionId}`, { method: 'DELETE' })
      if (res.ok) {
        if (currentSessionId === sessionId) {
          setCurrentSessionId(null)
        }
        await loadRecentSessions()
        onSessionDeleted?.(sessionId)
      }
    } catch (e) {
      console.error('Failed to delete session:', e)
    }
  }

  // 从API获取真实数量和会话列表
  useEffect(() => {
    const fetchCounts = async () => {
      try {
        // 获取报告数量
        const outputsRes = await fetch('/api/outputs/list')
        if (outputsRes.ok) {
          const outputsData = await outputsRes.json()
          const reportCount = outputsData.files?.filter((f: any) => f.name.endsWith('.md')).length || 0
          setGeneratedCount(reportCount)
        }
      } catch (e) {
        console.error('Failed to fetch outputs count:', e)
      }

      try {
        // 获取知识库论文数量
        const topicsRes = await fetch('/api/papers/topics')
        if (topicsRes.ok) {
          const topicsData = await topicsRes.json()
          const totalPapers = topicsData.topics?.reduce((sum: number, t: any) => sum + t.count, 0) || 0
          setKnowledgeCount(totalPapers)
        }
      } catch (e) {
        console.error('Failed to fetch papers count:', e)
      }

      loadRecentSessions()
    }

    fetchCounts()
  }, [loadRecentSessions])

  const menuItems: MenuItem[] = [
    {
      id: 'chat',
      label: '会话',
      icon: <MessageSquare className="w-5 h-5" />
    },
    {
      id: 'generated',
      label: '报告生成',
      icon: <FileText className="w-5 h-5" />,
      badge: generatedCount
    },
    {
      id: 'knowledge',
      label: '知识库',
      icon: <BookOpen className="w-5 h-5" />,
      badge: knowledgeCount
    },
    {
      id: 'paper-reading',
      label: '论文精读',
      icon: <GraduationCap className="w-5 h-5" />
    }
  ]

  // 模拟历史会话数据
  // const recentSessions = [
  //   { id: '1', title: '深度强化学习研究', time: '2小时前' },
  //   { id: '2', title: 'Transformer 架构分析', time: '昨天' },
  //   { id: '3', title: '机器学习综述', time: '3天前' },
  // ]

  return (
    <motion.aside
      initial={false}
      animate={{ width: isCollapsed ? 64 : 240 }}
      transition={{ duration: 0.2, ease: 'easeInOut' }}
      className="h-full bg-dark-surface/50 border-r border-dark-border flex flex-col shrink-0"
    >
      {/* 新建会话按钮 */}
      <div className="p-3">
        <button
          onClick={() => onNewSession?.()}
          className={`w-full flex items-center justify-center gap-2 bg-primary-500 hover:bg-primary-600
                     text-white rounded-lg py-2.5 font-medium transition-all duration-200
                     hover:shadow-lg hover:shadow-primary-500/20 active:scale-95
                     ${isCollapsed ? 'px-0' : 'px-4'}`}
        >
          <Plus className="w-5 h-5" />
          {!isCollapsed && <span>新建会话</span>}
        </button>
      </div>

      {/* 主菜单 */}
      <nav className="flex-1 px-2 py-2">
        <div className={`space-y-1 ${isCollapsed ? 'px-0' : ''}`}>
          {menuItems.map((item) => (
            <motion.button
              key={item.id}
              onClick={() => onViewChange(item.id)}
              className={`w-full flex items-center gap-3 rounded-lg transition-all duration-200
                        ${currentView === item.id
                          ? 'bg-primary-500/20 text-primary-400'
                          : 'text-dark-muted hover:bg-dark-border/30 hover:text-dark-text'
                        }
                        ${isCollapsed ? 'justify-center p-2' : 'px-3 py-2.5'}
                        `}
              whileHover={{ x: 2 }}
              whileTap={{ scale: 0.98 }}
            >
              {item.icon}
              {!isCollapsed && (
                <>
                  <span className="flex-1 text-left text-sm font-medium">{item.label}</span>
                  {item.badge && (
                    <span className="px-2 py-0.5 text-xs bg-primary-500/30 text-primary-400 rounded-full">
                      {item.badge}
                    </span>
                  )}
                </>
              )}
              {isCollapsed && item.badge && (
                <span className="absolute top-1 right-1 w-2 h-2 bg-primary-500 rounded-full" />
              )}
            </motion.button>
          ))}
        </div>
      </nav>

      {/* 历史会话 */}
      {!isCollapsed && (
        <div className="px-3 py-2 border-t border-dark-border">
          <div className="flex items-center gap-2 text-xs text-dark-muted mb-2 px-2">
            <History className="w-3.5 h-3.5" />
            <span>最近会话</span>
          </div>
          <div className="space-y-1">
            {recentSessions.length === 0 ? (
              <div className="text-xs text-dark-muted px-2 py-2">
                暂无会话记录
              </div>
            ) : (
              recentSessions.map((session) => (
                <div
                  key={session.session_id}
                  className={`group relative w-full flex flex-col items-start gap-0.5 px-2 py-1.5 rounded-md
                           transition-colors text-left cursor-pointer
                           ${currentSessionId === session.session_id
                             ? 'bg-primary-500/20 text-primary-400'
                             : 'text-dark-muted hover:bg-dark-border/30 hover:text-dark-text'
                           }`}
                  onClick={() => {
                    setCurrentSessionId(session.session_id)
                    onSelectSession?.(session.session_id)
                  }}
                >
                  <span className="text-sm truncate w-full pr-6">
                    {session.research_topics?.length > 0
                      ? session.research_topics[0]
                      : '新会话'}
                  </span>
                  <span className="text-xs text-dark-muted/60">
                    {formatTimeAgo(session.updated_at)}
                  </span>
                  <button
                    onClick={(e) => handleDeleteSession(e, session.session_id)}
                    className="absolute right-1 top-1/2 -translate-y-1/2 p-1 rounded text-dark-muted/0 hover:text-red-400 hover:bg-red-400/10 opacity-0 group-hover:opacity-100 transition-all"
                    title="删除会话"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* 折叠按钮 */}
      <div className="p-2 border-t border-dark-border">
        <button
          onClick={onToggleCollapse}
          className="w-full flex items-center justify-center gap-2 text-dark-muted
                   hover:text-dark-text hover:bg-dark-border/30 rounded-lg py-2
                   transition-all duration-200"
        >
          <motion.div
            animate={{ rotate: isCollapsed ? 180 : 0 }}
            transition={{ duration: 0.2 }}
          >
            <ChevronLeft className="w-5 h-5" />
          </motion.div>
          {!isCollapsed && <span className="text-sm">收起</span>}
        </button>
      </div>
    </motion.aside>
  )
}
