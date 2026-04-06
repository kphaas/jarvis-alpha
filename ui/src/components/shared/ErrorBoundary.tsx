import { Component, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback
      return (
        <div className="rounded-3xl border border-rose-500/30 bg-rose-500/10 p-8 text-center">
          <p className="text-sm font-medium text-rose-400 mb-2">Something went wrong</p>
          <p className="text-xs text-rose-400/70 mb-4 font-mono">{this.state.error?.message}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 rounded-xl border border-rose-500/30 text-xs font-medium text-rose-400 hover:bg-rose-500/10"
          >
            Reload page
          </button>
        </div>
      )
    }
    return this.props.children
  }
}
