import { motion } from 'framer-motion'
import {
  MessageSquare,
  FileText,
  BookOpen,
  ChevronLeft,
  Plus,
  History
} from 'lucide-react'
import { useState, useEffect } from 'react'

type View = 'chat' | 'generated' | 'knowledge'

interface SidebarProps {
  currentView: View
  onViewChange: (view: View) => void
  isCollapsed: boolean
  onToggleCollapse: () => void
}

interface MenuItem {
  id: View
  label: string
  icon: React.ReactNode
  badge?: number
}

export default function Sidebar({
  currentView,
  onViewChange,
  isCollapsed,
  onToggleCollapse
}: SidebarProps) {
  const [generatedCount, setGeneratedCount] = useState(0)
  const [knowledgeCount, setKnowledgeCount] = useState(0)

  // 从API获取真实数量
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
    }

    fetchCounts()
  }, [])

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
    }
  ]

  // 模拟历史会话数据
  const recentSessions = [
    { id: '1', title: '深度强化学习研究', time: '2小时前' },
    { id: '2', title: 'Transformer 架构分析', time: '昨天' },
    { id: '3', title: '机器学习综述', time: '3天前' },
  ]

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
            {recentSessions.map((session) => (
              <button
                key={session.id}
                className="w-full flex flex-col items-start gap-0.5 px-2 py-1.5 rounded-md
                         text-dark-muted hover:bg-dark-border/30 hover:text-dark-text
                         transition-colors text-left"
              >
                <span className="text-sm truncate w-full">{session.title}</span>
                <span className="text-xs text-dark-muted/60">{session.time}</span>
              </button>
            ))}
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
