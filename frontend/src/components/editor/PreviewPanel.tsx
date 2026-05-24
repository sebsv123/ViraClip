'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import type { EditorState } from '@/types/editor'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Play, Pause, Loader2, Film } from 'lucide-react'

interface PreviewPanelProps {
  state: EditorState
  onSetPlayhead: (time: number) => void
  onTriggerRerender: () => Promise<{ job_id: string }>
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'

const STAGE_LABELS: Record<string, string> = {
  extracting_keywords: 'Extrayendo keywords para iconos...',
  applying_transitions: 'Aplicando transiciones...',
  adding_audio: 'Añadiendo efectos de audio...',
  encoding: 'Codificando vídeo final...',
  done: '¡Completado!',
  error: 'Error en el renderizado',
}

export function PreviewPanel({ state, onSetPlayhead, onTriggerRerender }: PreviewPanelProps) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [renderJobId, setRenderJobId] = useState<string | null>(null)
  const [renderProgress, setRenderProgress] = useState(0)
  const [renderStage, setRenderStage] = useState<string>('')
  const [renderError, setRenderError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const selectedClip = state.clips.find((c) => c.id === state.selected_clip_id)

  // Sync playhead with video
  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    const onTimeUpdate = () => {
      setCurrentTime(video.currentTime)
      onSetPlayhead(video.currentTime)
    }
    const onPlay = () => setIsPlaying(true)
    const onPause = () => setIsPlaying(false)

    video.addEventListener('timeupdate', onTimeUpdate)
    video.addEventListener('play', onPlay)
    video.addEventListener('pause', onPause)

    return () => {
      video.removeEventListener('timeupdate', onTimeUpdate)
      video.removeEventListener('play', onPlay)
      video.removeEventListener('pause', onPause)
    }
  }, [onSetPlayhead, selectedClip?.id])

  // Seek video when playhead changes externally (timeline click)
  useEffect(() => {
    const video = videoRef.current
    if (!video || !selectedClip) return
    if (Math.abs(video.currentTime - state.playhead_time) > 0.3) {
      video.currentTime = state.playhead_time
    }
  }, [state.playhead_time, selectedClip?.id])

  const togglePlay = () => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) {
      video.play().catch(() => {})
    } else {
      video.pause()
    }
  }

  const handleProgressClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!selectedClip) return
    const rect = e.currentTarget.getBoundingClientRect()
    const ratio = (e.clientX - rect.left) / rect.width
    const time = ratio * selectedClip.duration
    onSetPlayhead(time)
    if (videoRef.current) {
      videoRef.current.currentTime = time
    }
  }

  const reloadPreview = useCallback(() => {
    setRenderJobId(null)
    setRenderProgress(0)
    setRenderStage('')
    if (videoRef.current) {
      videoRef.current.load()
    }
  }, [])

  const connectWebSocket = useCallback((taskId: string) => {
    // Close existing WS
    if (wsRef.current) {
      wsRef.current.close()
    }

    try {
      const ws = new WebSocket(`${WS_BASE}/ws/tasks/${taskId}/progress`)
      wsRef.current = ws

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          setRenderProgress(data.percent || 0)
          setRenderStage(data.stage || '')
          if (data.stage === 'done') {
            ws.close()
            reloadPreview()
          } else if (data.stage === 'error') {
            setRenderError(data.detail || 'Render failed')
            ws.close()
          }
        } catch {
          // Ignore parse errors
        }
      }

      ws.onerror = () => {
        // WebSocket failed — fall back to polling
        console.warn('[Preview] WebSocket failed, falling back to polling')
        startPolling(taskId)
      }

      ws.onclose = () => {
        wsRef.current = null
      }
    } catch {
      startPolling(taskId)
    }
  }, [reloadPreview])

  const startPolling = useCallback((taskId: string) => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/tasks/${taskId}/re-render/${renderJobId}/status`)
        if (!res.ok) throw new Error('Poll failed')
        const data = await res.json()
        if (data.status === 'done' || data.status === 'completed') {
          setRenderJobId(null)
          if (pollRef.current) clearInterval(pollRef.current)
          reloadPreview()
        } else if (data.status === 'error') {
          setRenderError(data.error || 'Render failed')
          setRenderJobId(null)
          if (pollRef.current) clearInterval(pollRef.current)
        }
      } catch {
        // Silently retry
      }
    }, 2000)
  }, [renderJobId, reloadPreview])

  const handleRerender = async () => {
    setRenderError(null)
    setRenderProgress(0)
    setRenderStage('')
    try {
      const { job_id } = await onTriggerRerender()
      setRenderJobId(job_id)
      // Try WebSocket first, fall back to polling
      connectWebSocket(state.task_id)
    } catch (err) {
      setRenderError(err instanceof Error ? err.message : 'Render failed')
    }
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close()
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const videoUrl = selectedClip
    ? `/api/clips/${selectedClip.id}/stream`
    : null

  const stageLabel = STAGE_LABELS[renderStage] || ''

  return (
    <div className="h-full flex flex-col">
      {/* Header with render button */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--ae-border)]">
        <span className="text-xs font-semibold text-[var(--ae-text-muted)] uppercase tracking-wider">
          Preview
        </span>
        <Button
          size="sm"
          disabled={!state.has_unsaved_changes && !renderJobId}
          onClick={handleRerender}
          className={cn(
            'h-7 text-xs px-3',
            state.has_unsaved_changes
              ? 'bg-[var(--ae-accent)] text-white hover:brightness-110'
              : 'bg-[var(--ae-panel)] text-[var(--ae-text-muted)] border border-[var(--ae-border)]',
          )}
        >
          {renderJobId ? (
            <>
              <Loader2 className="w-3 h-3 mr-1 animate-spin" />
              {renderProgress}%
            </>
          ) : state.has_unsaved_changes ? (
            'Apply Changes'
          ) : (
            'No pending changes'
          )}
        </Button>
      </div>

      {/* Video preview */}
      <div className="flex-1 flex items-center justify-center p-4 bg-black/40">
        {videoUrl ? (
          <div className="relative w-full max-w-[360px] aspect-[9/16] bg-black rounded-lg overflow-hidden">
            <video
              ref={videoRef}
              src={videoUrl}
              className="w-full h-full object-contain"
              preload="auto"
              playsInline
            />
            {/* Click to play/pause overlay */}
            <div
              className="absolute inset-0 cursor-pointer"
              onClick={togglePlay}
            />
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2 text-[var(--ae-text-muted)]">
            <Film className="w-12 h-12" />
            <p className="text-xs">No clip selected</p>
          </div>
        )}
      </div>

      {/* Controls */}
      {selectedClip && (
        <div className="px-3 py-2 border-t border-[var(--ae-border)] space-y-2">
          <div className="flex items-center gap-2">
            <button
              onClick={togglePlay}
              className="p-1 rounded hover:bg-white/5 text-[var(--ae-text)] transition-colors"
            >
              {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
            </button>
            <span className="text-[10px] text-[var(--ae-text-muted)] tabular-nums">
              {formatTime(currentTime)} / {formatTime(selectedClip.duration)}
            </span>
          </div>

          {/* Progress bar */}
          <div
            className="h-1 bg-[var(--ae-border)] rounded-full cursor-pointer relative overflow-hidden"
            onClick={handleProgressClick}
          >
            <div
              className="h-full bg-[var(--ae-accent)] rounded-full transition-all duration-100"
              style={{ width: `${(currentTime / selectedClip.duration) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Render progress */}
      {renderJobId && (
        <div className="px-3 py-2 border-t border-[var(--ae-border)] space-y-1">
          <div className="h-1.5 bg-[var(--ae-border)] rounded-full overflow-hidden">
            <div
              className="h-full bg-[var(--ae-accent)] rounded-full transition-all duration-300"
              style={{ width: `${renderProgress}%` }}
            />
          </div>
          {stageLabel && (
            <p className="text-[10px] text-[var(--ae-text-muted)] text-center">
              {stageLabel}
            </p>
          )}
        </div>
      )}

      {/* Render error */}
      {renderError && (
        <div className="px-3 py-1.5 bg-red-500/10 border-t border-red-500/30">
          <p className="text-[10px] text-red-400">{renderError}</p>
        </div>
      )}
    </div>
  )
}
