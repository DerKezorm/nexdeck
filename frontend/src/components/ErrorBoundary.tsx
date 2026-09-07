/**
 * The last thing between a mistake and a white page.
 *
 * ⚠️ There was none. A render error anywhere, or a lazy chunk that is no
 * longer on the server because a new version was deployed while a tab sat
 * open, unmounted the whole tree and left a blank white page with nothing on
 * it: no message, no button, no hint that reloading would help. On a wall
 * display nobody is standing there to work that out.
 *
 * A stale chunk is the common case and it has an obvious cure, so it is named
 * separately and offers the reload.
 */
import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** Shown instead of the standard page, for a boundary around one card. */
  fallback?: (error: Error, retry: () => void) => ReactNode
}

interface State {
  error: Error | null
}

/** A chunk that 404s reaches us as one of these, depending on the browser. */
function looksLikeAStaleChunk(error: Error): boolean {
  const text = `${error.name} ${error.message}`
  return /dynamically imported module|Importing a module script failed|ChunkLoadError|Failed to fetch/i.test(text)
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // The console is the only place this can go: sending it anywhere would be
    // an outbound call nobody asked for.
    console.error('nexdeck could not draw this:', error, info.componentStack)
  }

  private retry = (): void => {
    this.setState({ error: null })
  }

  render(): ReactNode {
    const { error } = this.state
    if (!error) return this.props.children
    if (this.props.fallback) return this.props.fallback(error, this.retry)

    const stale = looksLikeAStaleChunk(error)
    return (
      <div className="min-h-screen grid place-items-center p-6" role="alert">
        <div className="glass rounded-2xl p-8 text-center max-w-md">
          <h1 className="font-semibold text-lg">
            {stale ? 'A newer version is on the server' : 'Something in the interface went wrong'}
          </h1>
          <p className="text-sm text-muted mt-2">
            {stale
              ? 'This tab has been open across an update, and a piece of the old version is gone. Reloading picks up the new one.'
              : 'The page could not be drawn. Reloading usually helps; the details are in the browser console.'}
          </p>
          <p className="num text-[11px] text-faint mt-3 break-all">{error.message}</p>
          <div className="mt-5 flex gap-2 justify-center">
            <button className="btn btn-accent" onClick={() => window.location.reload()}>
              Reload
            </button>
            {!stale && (
              <button className="btn" onClick={this.retry}>
                Try again
              </button>
            )}
          </div>
        </div>
      </div>
    )
  }
}
