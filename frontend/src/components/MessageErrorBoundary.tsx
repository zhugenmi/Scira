import { Component, ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: (error: Error, reset: () => void) => ReactNode
  /** 用于在降级文案里标识是哪条消息渲染失败 */
  label?: string
}

interface State {
  error: Error | null
}

/**
 * 单条消息粒度的错误边界。
 *
 * 用途：final_report 等大段 markdown 含格式异常的 $...$ 公式时，
 * rehypeKatex 会在渲染期抛 ParseError；React 没有 ErrorBoundary 会卸载整棵树
 * → 整页白屏。包在这里后，单条消息渲染失败只降级这一条（显示纯文本 + 重试按钮），
 * 不影响其他消息和整个 App。
 */
export default class MessageErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: any) {
    console.error('Message render failed:', error, info)
  }

  reset = () => this.setState({ error: null })

  render() {
    if (this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.reset)
      }
      return (
        <div className="text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg px-3 py-2">
          <div className="mb-1">{this.props.label || '该消息'}渲染失败：{this.state.error.message}</div>
          <button
            onClick={this.reset}
            className="px-2 py-0.5 rounded bg-red-400/20 hover:bg-red-400/30 text-red-300"
          >
            重试
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
