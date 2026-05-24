'use client'

import { useCallback, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import type { EditorState, SfxEventType } from '@/types/editor'

interface TimelineProps {
  state: EditorState
  onSelectElement: (element: EditorState['selected_element']) => void
  onSetPlayhead: (time: number) => void
}

const PX_PER_SECOND = 8
const TRACK_HEIGHT = 48
const SFX_TRACK_HEIGHT = 32
const TRANSITION_HEIGHT = 8

const SFX_COLORS: Record<string, string> = {
  dark_riser: '#6b8cff',
  magic_whoosh: '#ffd700',
  deep_boom: '#ff6b35',
  tension_riser: '#ff3333',
  pre_silence: '#888',
  post_silence: '#888',
  pattern_interrupt: '#aaa',
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export function Timeline({ state, onSelectElement, onSetPlayhead }: TimelineProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [isDraggingPlayhead, setIsDraggingPlayhead] = useState(false)

  const totalWidth = Math.max(state.total_duration * PX_PER_SECOND, 600)

  const handleTimelineClick = useCallback(
    (e: React.MouseEvent) => {
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      const x = e.clientX - rect.left + (containerRef.current?.scrollLeft || 0)
      const time = x / PX_PER_SECOND
      onSetPlayhead(Math.max(0, Math.min(time, state.total_duration)))
    },
    [state.total_duration, onSetPlayhead],
  )

  const handlePlayheadDrag = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      setIsDraggingPlayhead(true)

      const handleMouseMove = (ev: MouseEvent) => {
        const rect = containerRef.current?.getBoundingClientRect()
        if (!rect) return
        const x = ev.clientX - rect.left + (containerRef.current?.scrollLeft || 0)
        const time = x / PX_PER_SECOND
        onSetPlayhead(Math.max(0, Math.min(time, state.total_duration)))
      }

      const handleMouseUp = () => {
        setIsDraggingPlayhead(false)
        document.removeEventListener('mousemove', handleMouseMove)
        document.removeEventListener('mouseup', handleMouseUp)
      }

      document.addEventListener('mousemove', handleMouseMove)
      document.addEventListener('mouseup', handleMouseUp)
    },
    [state.total_duration, onSetPlayhead],
  )

  // Generate time ruler marks
  const rulerMarks: { time: number; isMajor: boolean }[] = []
  for (let t = 0; t <= state.total_duration; t += 0.5) {
    rulerMarks.push({ time: t, isMajor: t % 1 === 0 })
  }

  return (
    <div className="h-full flex flex-col bg-[var(--ae-bg)]">
      {/* Time ruler */}
      <div
        ref={containerRef}
        className="overflow-x-auto overflow-y-hidden flex-1"
        onMouseDown={handleTimelineClick}
      >
        <div style={{ width: totalWidth, minWidth: '100%', position: 'relative' }}>
          {/* Ruler */}
          <div className="h-6 border-b border-[var(--ae-border)] relative" style={{ width: totalWidth }}>
            {rulerMarks.map((mark) => (
              <div
                key={mark.time}
                className="absolute top-0"
                style={{ left: mark.time * PX_PER_SECOND }}
              >
                <div
                  className={cn(
                    'bg-[var(--ae-border)]',
                    mark.isMajor ? 'w-px h-3' : 'w-px h-1.5',
                  )}
                />
                {mark.isMajor && (
                  <span className="absolute top-3 left-1 text-[9px] text-[var(--ae-text-muted)] whitespace-nowrap">
                    {formatTime(mark.time)}
                  </span>
                )}
              </div>
            ))}
          </div>

          {/* Video track */}
          <div
            className="relative border-b border-[var(--ae-border)]"
            style={{ height: TRACK_HEIGHT, width: totalWidth }}
          >
            {state.clips.map((clip) => {
              const left = clip.start_time * PX_PER_SECOND
              const width = clip.duration * PX_PER_SECOND
              const isSelected = state.selected_clip_id === clip.id

              return (
                <div key={clip.id} className="absolute top-1" style={{ left, width, height: TRACK_HEIGHT - 8 }}>
                  {/* Clip block */}
                  <div
                    onClick={() => onSelectElement({ type: 'clip', clip_id: clip.id })}
                    className={cn(
                      'absolute inset-0 rounded cursor-pointer flex items-center justify-center text-[10px] font-medium transition-colors',
                      isSelected
                        ? 'ring-1 ring-[var(--ae-accent)]'
                        : 'hover:brightness-110',
                    )}
                    style={{ backgroundColor: 'var(--ae-clip)' }}
                  >
                    <span className="text-white/90 truncate px-1">
                      Clip {clip.index + 1}
                    </span>
                    <span className="text-white/60 ml-1">{clip.duration.toFixed(1)}s</span>
                  </div>

                  {/* Transition block (after clip, before next) */}
                  {clip.transition_after && clip.index < state.clips.length - 1 && (
                    <div
                      onClick={(e) => {
                        e.stopPropagation()
                        onSelectElement({ type: 'transition', clip_id: clip.id })
                      }}
                      className="absolute cursor-pointer rounded-sm hover:brightness-110 transition-colors"
                      style={{
                        left: width - 4,
                        top: TRACK_HEIGHT / 2 - TRANSITION_HEIGHT / 2 - 4,
                        width: 8,
                        height: TRANSITION_HEIGHT,
                        backgroundColor: 'var(--ae-transition)',
                      }}
                      title={clip.transition_after.type.replace(/_/g, ' ')}
                    />
                  )}
                </div>
              )
            })}
          </div>

          {/* SFX track */}
          <div
            className="relative border-b border-[var(--ae-border)]"
            style={{ height: SFX_TRACK_HEIGHT, width: totalWidth }}
          >
            {state.clips.map((clip) =>
              clip.sfx_events.map((sfx) => {
                const left = (clip.start_time + sfx.time) * PX_PER_SECOND
                const color = SFX_COLORS[sfx.type] || '#888'
                const isSelected =
                  state.selected_element?.type === 'sfx' &&
                  state.selected_element.clip_id === clip.id &&
                  state.selected_element.sfx_id === sfx.id

                return (
                  <div
                    key={sfx.id}
                    onClick={() => onSelectElement({ type: 'sfx', clip_id: clip.id, sfx_id: sfx.id })}
                    className={cn(
                      'absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full cursor-pointer transition-transform hover:scale-125',
                      isSelected && 'ring-1 ring-white',
                    )}
                    style={{
                      left: left - 6,
                      backgroundColor: color,
                    }}
                    title={`${sfx.type} @ ${sfx.time.toFixed(1)}s`}
                  />
                )
              }),
            )}
          </div>

          {/* Playhead */}
          <div
            className="absolute top-0 bottom-0 w-0.5 cursor-ew-resize z-10"
            style={{
              left: state.playhead_time * PX_PER_SECOND,
              backgroundColor: 'var(--ae-playhead)',
            }}
            onMouseDown={handlePlayheadDrag}
          >
            <div
              className="w-3 h-3 rounded-full mx-auto"
              style={{
                marginLeft: -5.5,
                backgroundColor: 'var(--ae-playhead)',
              }}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
