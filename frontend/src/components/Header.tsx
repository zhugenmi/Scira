import { Search, Settings, User, Bell } from 'lucide-react'

interface HeaderProps {
  // 可以添加 props 如 onSearch 等
}

export default function Header({}: HeaderProps) {
  return (
    <header className="h-14 bg-dark-surface/80 backdrop-blur-sm border-b border-dark-border flex items-center justify-between px-4 shrink-0">
      {/* 左侧 Logo */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary-500 to-primary-700 flex items-center justify-center">
          <span className="text-white font-bold text-sm">S</span>
        </div>
        <h1 className="text-lg font-display font-semibold text-dark-text">
          Scira
        </h1>
        <span className="text-xs text-dark-muted px-2 py-0.5 bg-dark-border/50 rounded-full">
          科研助手
        </span>
      </div>

      {/* 中间搜索框 */}
      <div className="flex-1 max-w-xl mx-8">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-dark-muted" />
          <input
            type="text"
            placeholder="搜索论文、主题或会话..."
            className="w-full bg-dark-bg border border-dark-border rounded-lg pl-10 pr-4 py-2 text-sm
                     focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500/20
                     placeholder:text-dark-muted transition-all"
          />
          <kbd className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-dark-muted bg-dark-border/50 px-1.5 py-0.5 rounded">
            ⌘K
          </kbd>
        </div>
      </div>

      {/* 右侧操作区 */}
      <div className="flex items-center gap-2">
        <button className="p-2 rounded-lg hover:bg-dark-border/50 transition-colors text-dark-muted hover:text-dark-text">
          <Bell className="w-5 h-5" />
        </button>
        <button className="p-2 rounded-lg hover:bg-dark-border/50 transition-colors text-dark-muted hover:text-dark-text">
          <Settings className="w-5 h-5" />
        </button>
        <div className="w-px h-6 bg-dark-border mx-1" />
        <button className="flex items-center gap-2 p-1.5 rounded-lg hover:bg-dark-border/50 transition-colors">
          <div className="w-7 h-7 rounded-full bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center">
            <User className="w-4 h-4 text-white" />
          </div>
        </button>
      </div>
    </header>
  )
}
