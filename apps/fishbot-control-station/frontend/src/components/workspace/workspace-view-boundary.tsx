import { Component, type ErrorInfo, type ReactNode } from 'react'

/** The owner lives above this boundary. Retrying a view must not restart its task. */
export class WorkspaceViewBoundary extends Component<{ children: ReactNode }, { error: string | null; revision: number }> {
  state = { error: null as string | null, revision: 0 }
  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error.message : '视图渲染失败' }
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Workspace view failed; task owner retained.', error, info.componentStack)
  }
  render() {
    if (this.state.error) return <div className="workspace-view-error" role="alert">
      <strong>此视图暂时无法显示</strong><p>{this.state.error}</p>
      <p>任务状态仍由原服务管理。恢复视图不会派发、取消或重新开始任务。</p>
      <button type="button" onClick={() => this.setState(({ revision }) => ({ error: null, revision: revision + 1 }))}>恢复此视图</button>
    </div>
    return <div className="workspace-view-content" key={this.state.revision}>{this.props.children}</div>
  }
}
