'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useSession } from '@/lib/auth-client'
import { useEditorState } from '@/hooks/useEditorState'
import { LayersPanel } from '@/components/editor/LayersPanel'
import { PreviewPanel } from '@/components/editor/PreviewPanel'
import { PropertiesPanel } from '@/components/editor/PropertiesPanel'
import { Timeline } from '@/components/editor/Timeline'
import { Button } from '@/components/ui/button'
import { ArrowLeft, Monitor, Smartphone, Loader2 } from 'lucide-react'
import '@/styles/editor.css'

export default function StudioPage() {
  const params = useParams()
  const router = useRouter()
  const taskId = params.id as string
  const { data: session } = useSession()

  const {
    state,
    updateTransition,
    updateSfxEvent,
    addSfxEvent,
    removeSfxEvent,
    selectElement,
    setPlayhead,
    triggerRerender,
    isLoading,
    isSaving,
    saveError,
  } = useEditorState(taskId)

  const [showMobileWarning, setShowMobileWarning] = useState(false)
  const [previewMode, setPreviewMode] = useState<'desktop' | 'mobile'>('desktop')

  // Force dark mode for the editor
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', 'dark')
    return () => {
      document.documentElement.removeAttribute('data-theme')
    }
  }, [])

  // Detect mobile
  useEffect(() => {
    const checkMobile = () => {
      if (window.innerWidth < 768) {
        setShowMobileWarning(true)
      }
    }
    checkMobile()
    window.addEventListener('resize', checkMobile)
    return () => window.removeEventListener('resize', checkMobile)
  }, [])

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Space → play/pause
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.code === 'Space') {
        e.preventDefault()
        setPlayhead(state.playhead_time + 0.1) // just trigger a re-render
      }
      // Cmd+S → save
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault()
        // Auto-save will trigger via debounce
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [state.playhead_time, setPlayhead])

  // Confirm before leaving with unsaved changes
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (state.has_unsaved_changes) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [state.has_unsaved_changes])

  const handleBack = useCallback(() => {
    if (state.has_unsaved_changes) {
      const confirmed = window.confirm('You have unsaved changes. Are you sure you want to leave?')
      if (!confirmed) return
    }
    router.push(`/tasks/${taskId}`)
  }, [state.has_unsaved_changes, taskId, router])

  // ── Skeleton loader ──────────────────────────────────────────────────────
  // Mínimo 400ms para evitar flash de contenido instantáneo
  const [minLoadTimeElapsed, setMinLoadTimeElapsed] = useState(false)
  useEffect(() => {
    const timer = setTimeout(() => setMinLoadTimeElapsed(true), 400)
    return () => clearTimeout(timer)
  }, [])

  const showSkeleton = isLoading || !minLoadTimeElapsed

  if (!session?.user) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-violet-500 animate-spin" />
      </div>
    )
  }

  if (showSkeleton) {
    return (
      <div className="h-screen editor-studio flex flex-col overflow-hidden">
        {/* Header skeleton */}
        <header className="flex items-center justify-between px-4 py-2 border-b border-[var(--ae-border)] bg-[var(--ae-panel)] flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="ae-skeleton w-8 h-8" />
            <div className="ae-skeleton w-32 h-4" />
          </div>
          <div className="flex items-center gap-2">
            <div className="ae-skeleton w-20 h-6" />
            <div className="ae-skeleton w-16 h-6" />
          </div>
        </header>

        {/* Main layout skeleton */}
        <div className="flex-1 flex overflow-hidden">
          {/* LayersPanel skeleton */}
          <aside className="flex-shrink-0 border-r border-[var(--ae-border)] bg-[var(--ae-panel)]" style={{ width: 280 }}>
            <div className="px-3 py-2 border-b border-[var(--ae-border)]">
              <div className="ae-skeleton w-12 h-3" />
            </div>
            <div className="p-2 space-y-2">
              {[1, 2, 3].map((i) => (
                <div key={i} className="flex items-center gap-2 px-2 py-1.5">
                  <div className="ae-skeleton w-8 h-8 rounded flex-shrink-0" />
                  <div className="ae-skeleton flex-1 h-4" />
                  <div className="ae-skeleton w-10 h-3" />
                </div>
              ))}
            </div>
          </aside>

          {/* PreviewPanel skeleton */}
          <main className="flex-1 flex flex-col min-w-0">
            <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--ae-border)]">
              <div className="ae-skeleton w-12 h-3" />
              <div className="ae-skeleton w-24 h-6" />
            </div>
            <div className="flex-1 flex items-center justify-center p-4 bg-black/40">
              <div className="w-full max-w-[360px] aspect-[9/16] ae-skeleton rounded-lg flex items-center justify-center">
                <svg className="w-12 h-12 text-[var(--ae-text-muted)] opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
              </div>
            </div>
          </main>

          {/* PropertiesPanel skeleton */}
          <aside className="flex-shrink-0 border-l border-[var(--ae-border)] bg-[var(--ae-panel)]" style={{ width: 320 }}>
            <div className="px-3 py-2 border-b border-[var(--ae-border)]">
              <div className="ae-skeleton w-16 h-3" />
            </div>
            <div className="p-3 space-y-4">
              <div className="ae-skeleton w-20 h-3" />
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="flex items-center justify-between">
                  <div className="ae-skeleton w-16 h-3" />
                  <div className="ae-skeleton w-20 h-5" />
                </div>
              ))}
            </div>
          </aside>
        </div>

        {/* Timeline skeleton */}
        <div className="flex-shrink-0 border-t border-[var(--ae-border)] bg-[var(--ae-panel)]" style={{ height: 180 }}>
          <div className="p-2">
            <div className="ae-skeleton w-full h-6 mb-1" />
            <div className="ae-skeleton w-3/4 h-12 mb-1" />
            <div className="ae-skeleton w-1/2 h-8" />
          </div>
        </div>
      </div>
    )
  }

  if (showMobileWarning) {
    return (
      <div className="min-h-screen editor-studio flex items-center justify-center p-8">
        <div className="text-center max-w-md">
          <Smartphone className="w-16 h-16 mx-auto mb-4 text-[var(--ae-text-muted)]" />
          <h2 className="text-lg font-semibold text-[var(--ae-text)] mb-2">Desktop Editor</h2>
          <p className="text-sm text-[var(--ae-text-muted)] mb-6">
            The Studio Editor is designed for desktop use. Please open it on a larger screen for the best experience.
          </p>
          <Link href={`/tasks/${taskId}`}>
            <Button variant="outline" className="border-[var(--ae-border)] text-[var(--ae-text)]">
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Task
            </Button>
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="h-screen editor-studio flex flex-col overflow-hidden">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-2 border-b border-[var(--ae-border)] bg-[var(--ae-panel)] flex-shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={handleBack}
            className="p-1.5 rounded hover:bg-white/5 text-[var(--ae-text-muted)] hover:text-[var(--ae-text)] transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="flex items-center gap-2 text-sm">
            <Link
              href={`/tasks/${taskId}`}
              className="text-[var(--ae-text-muted)] hover:text-[var(--ae-text)] transition-colors"
            >
              Project
            </Link>
            <span className="text-[var(--ae-text-muted)]">/</span>
            <span className="text-[var(--ae-text)]">Studio</span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Preview mode toggle */}
          <button
            onClick={() => setPreviewMode('desktop')}
            className={`p-1.5 rounded transition-colors ${
              previewMode === 'desktop'
                ? 'bg-[var(--ae-accent)]/20 text-[var(--ae-accent)]'
                : 'text-[var(--ae-text-muted)] hover:text-[var(--ae-text)]'
            }`}
            title="Desktop preview"
          >
            <Monitor className="w-4 h-4" />
          </button>
          <button
            onClick={() => setPreviewMode('mobile')}
            className={`p-1.5 rounded transition-colors ${
              previewMode === 'mobile'
                ? 'bg-[var(--ae-accent)]/20 text-[var(--ae-accent)]'
                : 'text-[var(--ae-text-muted)] hover:text-[var(--ae-text)]'
            }`}
            title="Mobile preview"
          >
            <Smartphone className="w-4 h-4" />
          </button>

          {isSaving && (
            <span className="text-[10px] text-[var(--ae-text-muted)] flex items-center gap-1">
              <Loader2 className="w-3 h-3 animate-spin" />
              Saving...
            </span>
          )}
          {saveError && (
            <span className="text-[10px] text-red-400">{saveError}</span>
          )}
        </div>
      </header>

      {/* Main layout: 3 panels */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left panel: Layers */}
        <aside
          className="flex-shrink-0 border-r border-[var(--ae-border)] bg-[var(--ae-panel)]"
          style={{ width: 280 }}
        >
          <LayersPanel
            state={state}
            onSelectElement={selectElement}
            onRemoveSfx={removeSfxEvent}
          />
        </aside>

        {/* Center: Preview */}
        <main className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 overflow-hidden">
            <PreviewPanel
              state={state}
              onSetPlayhead={setPlayhead}
              onTriggerRerender={triggerRerender}
            />
          </div>
        </main>

        {/* Right panel: Properties */}
        <aside
          className="flex-shrink-0 border-l border-[var(--ae-border)] bg-[var(--ae-panel)]"
          style={{ width: 320 }}
        >
          <PropertiesPanel
            state={state}
            onUpdateTransition={(clipId, config) =>
              updateTransition(clipId, config as Parameters<typeof updateTransition>[1])
            }
            onUpdateSfx={(clipId, sfxId, params) =>
              updateSfxEvent(clipId, sfxId, params as Parameters<typeof updateSfxEvent>[2])
            }
            onAddSfx={(clipId, event) =>
              addSfxEvent(clipId, event as Parameters<typeof addSfxEvent>[1])
            }
            onRemoveSfx={removeSfxEvent}
          />
        </aside>
      </div>

      {/* Timeline at bottom */}
      <div
        className="flex-shrink-0 border-t border-[var(--ae-border)] bg-[var(--ae-panel)]"
        style={{ height: 180 }}
      >
        <Timeline
          state={state}
          onSelectElement={selectElement}
          onSetPlayhead={setPlayhead}
        />
      </div>
    </div>
  )
}
