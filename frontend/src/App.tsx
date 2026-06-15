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

  const handleNewSession = useCallback(() => {
    setSelectedSessionId(null)
    setChatKey(prev => prev + 1)
  }, [])

  const handleSelectSession = useCallback((sessionId: string) => {
    setSelectedSessionId(sessionId)
    setChatKey(prev => prev + 1)
  }, [])

  const renderView = () => {
    switch (currentView) {
      case 'chat':
        return <ChatView key={chatKey} sessionId={selectedSessionId} />
      case 'generated':
        return <GeneratedPapers />
      case 'downloaded':
        return <DownloadedPapers />
      case 'knowledge':
        return <KnowledgeBase />
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
