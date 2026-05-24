'use client'

import { cn } from '@/lib/utils'
import type { EditorState, EditorClip, SfxEvent, TransitionType } from '@/types/editor'
import {
  Scissors,
  Zap,
  ChevronRight,
  Eye,
  Shapes,
  Minus,
  TrendingUp,
  Wind,
  Volume2,
  AlertTriangle,
  VolumeX,
  Pause,
  Trash2,
  Film,
} from 'lucide-react'

interface LayersPanelProps {
  state: EditorState
  onSelectElement: (element: EditorState['selected_element']) => void
  onRemoveSfx: (clipId: string, sfxId: string) => void
}

const TRANSITION_ICONS: Record<TransitionType, typeof Scissors> = {
  match_cut: Scissors,
  glitch: Zap,
  sweep_mask: ChevronRight,
  mask_reveal: Eye,
  shape_morph: Shapes,
  none: Minus,
}

const SFX_ICONS: Record<string, { icon: typeof Volume2; color: string }> = {
  dark_riser: { icon: TrendingUp, color: '#6b8cff' },
  magic_whoosh: { icon: Wind, color: '#ffd700' },
  deep_boom: { icon: Volume2, color: '#ff6b35' },
  tension_riser: { icon: AlertTriangle, color: '#ff3333' },
  pre_silence: { icon: VolumeX, color: '#888' },
  post_silence: { icon: VolumeX, color: '#888' },
  pattern_interrupt: { icon: Pause, color: '#aaa' },
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function ClipLayer({
  clip,
  isSelected,
  onSelect,
  onSelectTransition,
  onSelectSfx,
  onRemoveSfx,
}: {
  clip: EditorClip
  isSelected: boolean
  onSelect: () => void
  onSelectTransition: () => void
  onSelectSfx: (sfxId: string) => void
  onRemoveSfx: (sfxId: string) => void
}) {
  const TransitionIcon = clip.transition_after
    ? TRANSITION_ICONS[clip.transition_after.type]
    : Minus

  return (
    <div className="space-y-0.5">
      {/* Clip row */}
      <button
        onClick={onSelect}
        className={cn(
          'w-full flex items-center gap-2 px-2 py-1.5 rounded text-xs transition-colors text-left',
          isSelected
            ? 'bg-[var(--ae-accent)]/20 border border-[var(--ae-accent)]/40'
            : 'hover:bg-white/5 border border-transparent',
        )}
      >
        <div
          className="w-6 h-6 rounded flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor: 'var(--ae-clip)' }}
        >
          <Film className="w-3 h-3 text-white/80" />
        </div>
        <span className="flex-1 truncate text-[var(--ae-text)]">
          Clip {clip.index + 1}
        </span>
        <span className="text-[var(--ae-text-muted)] text-[10px]">
          {formatDuration(clip.duration)}
        </span>
      </button>

      {/* Transition badge (not for last clip) */}
      {clip.transition_after && (
        <button
          onClick={onSelectTransition}
          className="ml-5 flex items-center gap-1.5 px-2 py-1 rounded text-[10px] text-[var(--ae-text-muted)] hover:bg-white/5 transition-colors w-full text-left"
        >
          <TransitionIcon className="w-3 h-3" style={{ color: 'var(--ae-accent-2)' }} />
          <span className="truncate">{clip.transition_after.type.replace('_', ' ')}</span>
          {clip.transition_after.source !== 'manual' && (
            <span className="text-[8px] px-1 rounded bg-blue-500/20 text-blue-400 ml-auto">AUTO</span>
          )}
        </button>
      )}

      {/* SFX events */}
      {clip.sfx_events.length > 0 && (
        <div className="ml-5 space-y-0.5">
          {clip.sfx_events.map((sfx) => {
            const sfxIcon = SFX_ICONS[sfx.type] || SFX_ICONS.deep_boom
            const Icon = sfxIcon.icon
            return (
              <button
                key={sfx.id}
                onClick={() => onSelectSfx(sfx.id)}
                className="flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] hover:bg-white/5 transition-colors w-full text-left group"
              >
                <Icon className="w-3 h-3 flex-shrink-0" style={{ color: sfxIcon.color }} />
                <span className="truncate text-[var(--ae-text-muted)]">{sfx.type.replace(/_/g, ' ')}</span>
                <span className="text-[var(--ae-text-muted)] ml-auto">{sfx.time.toFixed(1)}s</span>
                {sfx.source === 'manual' && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      onRemoveSfx(sfx.id)
                    }}
                    className="opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    <Trash2 className="w-2.5 h-2.5 text-red-400" />
                  </button>
                )}
                <span
                  className={cn(
                    'text-[8px] px-1 rounded',
                    sfx.source === 'auto'
                      ? 'bg-blue-500/20 text-blue-400'
                      : 'bg-amber-500/20 text-amber-400',
                  )}
                >
                  {sfx.source === 'auto' ? 'AUTO' : 'MAN'}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

export function LayersPanel({
  state,
  onSelectElement,
  onRemoveSfx,
}: LayersPanelProps) {
  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-2 text-xs font-semibold text-[var(--ae-text-muted)] uppercase tracking-wider border-b border-[var(--ae-border)]">
        Layers
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {state.clips.length === 0 && (
          <p className="text-xs text-[var(--ae-text-muted)] text-center py-8">
            No clips loaded
          </p>
        )}
        {state.clips.map((clip) => (
          <ClipLayer
            key={clip.id}
            clip={clip}
            isSelected={state.selected_clip_id === clip.id}
            onSelect={() => onSelectElement({ type: 'clip', clip_id: clip.id })}
            onSelectTransition={() => onSelectElement({ type: 'transition', clip_id: clip.id })}
            onSelectSfx={(sfxId) => onSelectElement({ type: 'sfx', clip_id: clip.id, sfx_id: sfxId })}
            onRemoveSfx={(sfxId) => onRemoveSfx(clip.id, sfxId)}
          />
        ))}
      </div>
    </div>
  )
}
