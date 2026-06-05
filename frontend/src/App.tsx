import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Sidebar from './components/Sidebar'
import ChatView from './components/ChatView'
import GeneratedPapers from './components/GeneratedPapers'
import DownloadedPapers from './components/DownloadedPapers'
import KnowledgeBase from './components/KnowledgeBase'
import Header from './components/Header'

type View = 'chat' | 'generated' | 'downloaded' | 'knowledge'

export default function App() {
  const [currentView, setCurrentView] = useState<View>('chat')
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)

  const renderView = () => {
    switch (currentView) {
      case 'chat':
        return <ChatView />
      case 'generated':
        return <GeneratedPapers />
      case 'downloaded':
        return <DownloadedPapers />
      case 'knowledge':
        return <KnowledgeBase />
      default:
        return <ChatView />
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
