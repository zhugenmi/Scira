import { useState, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Sidebar from './components/Sidebar'
import ChatView from './components/ChatView'
import GeneratedPapers from './components/GeneratedPapers'
import DownloadedPapers from './components/DownloadedPapers'
import KnowledgeBase from './components/KnowledgeBase'
import PaperReading from './components/PaperReading'
import Header from './components/Header'

type View = 'chat' | 'generated' | 'downloaded' | 'knowledge' | 'paper-reading'

export default function App() {
  const [currentView, setCurrentView] = useState<View>('chat')
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [chatKey, setChatKey] = useState(0)  // 用于刷新 ChatView
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)
  const [pendingChatMessage, setPendingChatMessage] = useState<string | null>(null)

  const handleNewSession = useCallback(() => {
    setSelectedSessionId(null)
    setCurrentView('chat')
    setChatKey(prev => prev + 1)
  }, [])

  const handleSelectSession = useCallback((sessionId: string) => {
    setSelectedSessionId(sessionId)
    setCurrentView('chat')
    setChatKey(prev => prev + 1)
  }, [])

  // 侧边栏删除会话后：若删除的正是当前会话，重置聊天视图
  const handleSessionDeleted = useCallback((sessionId: string) => {
    if (selectedSessionId === sessionId) {
      setSelectedSessionId(null)
      setChatKey(prev => prev + 1)
    }
  }, [selectedSessionId])

  // 从知识库「阅读该论文」入口跳转：新建一个会话，并预填一条消息自动发送
  const handleReadPaper = useCallback((_title: string, mode: 'snap' | 'lens' | 'sphere') => {
    const modeLabel = mode === 'snap' ? '速览' : mode === 'lens' ? '深度精读' : '研究全景'
    const message = `用${modeLabel}模式阅读这篇论文《${_title}》`
    setSelectedSessionId(null)
    setPendingChatMessage(message)
    setCurrentView('chat')
    setChatKey(prev => prev + 1)
  }, [])

  // 从报告页「AI 编辑」入口跳转：预填一条含 <report> 全文的消息发给助手，
  // 后端在 chat/stream 中检测到该标签即自动初始化编辑会话（加载工作副本、注入编辑系统提示）。
  const handleEditWithAI = useCallback((paper: { filename: string; title: string }, content: string) => {
    const message = `请帮我编辑以下报告（文件：${paper.filename}）。读完后请先问我需要怎么修改，不要直接改：\n\n<report>\n${content}\n</report>`
    setSelectedSessionId(null)
    setPendingChatMessage(message)
    setCurrentView('chat')
    setChatKey(prev => prev + 1)
  }, [])

  const renderView = () => {
    switch (currentView) {
      case 'chat':
        return <ChatView key={chatKey} sessionId={selectedSessionId} pendingMessage={pendingChatMessage} onPendingConsumed={() => setPendingChatMessage(null)} />
      case 'generated':
        return <GeneratedPapers onEditWithAI={(paper, content) => handleEditWithAI({ filename: paper.filename, title: paper.title }, content)} />
      case 'downloaded':
        return <DownloadedPapers />
      case 'knowledge':
        return <KnowledgeBase onReadPaper={handleReadPaper} />
      case 'paper-reading':
        return <PaperReading />
      default:
        return <ChatView key={chatKey} />
    }
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-dark-bg grid-gradient">
      {/* 顶部导航栏 */}
      <Header />

      <div className="flex flex-1 overflow-hidden">
        {/* 侧边栏 */}
        <Sidebar
          currentView={currentView}
          onViewChange={setCurrentView}
          isCollapsed={isSidebarCollapsed}
          onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
          onNewSession={handleNewSession}
          onSelectSession={handleSelectSession}
          onSessionDeleted={handleSessionDeleted}
        />

        {/* 主内容区域 */}
        <main className="flex-1 overflow-hidden">
          <AnimatePresence mode="wait">
            <motion.div
              key={currentView}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.2 }}
              className="h-full overflow-auto"
            >
              {renderView()}
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  )
}
