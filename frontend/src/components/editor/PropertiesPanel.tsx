'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import type { EditorState, TransitionType, GlitchStyle, SweepShape, MorphQuality, SfxEventType } from '@/types/editor'
import { Button } from '@/components/ui/button'
import { Slider } from '@/components/ui/slider'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { Plus, Trash2 } from 'lucide-react'

interface PropertiesPanelProps {
  state: EditorState
  onUpdateTransition: (clipId: string, config: Record<string, unknown>) => void
  onUpdateSfx: (clipId: string, sfxId: string, params: Record<string, unknown>) => void
  onAddSfx: (clipId: string, event: { time: number; type: SfxEventType; params: Record<string, unknown>; source: 'auto' | 'manual' }) => void
  onRemoveSfx: (clipId: string, sfxId: string) => void
}

const TRANSITION_OPTIONS: { value: TransitionType; label: string }[] = [
  { value: 'none', label: 'None' },
  { value: 'match_cut', label: 'Match Cut' },
  { value: 'glitch', label: 'Glitch' },
  { value: 'sweep_mask', label: 'Sweep Mask' },
  { value: 'mask_reveal', label: 'Mask Reveal' },
  { value: 'shape_morph', label: 'Shape Morph' },
]

const GLITCH_STYLES: { value: GlitchStyle; label: string }[] = [
  { value: 'rgb', label: 'RGB Split' },
  { value: 'scan', label: 'Scan Lines' },
  { value: 'freeze', label: 'Freeze Frame' },
]

const SWEEP_SHAPES: { value: SweepShape; label: string }[] = [
  { value: 'circle', label: 'Circle' },
  { value: 'diagonal', label: 'Diagonal' },
  { value: 'wipe', label: 'Wipe' },
]

const MORPH_QUALITIES: { value: MorphQuality; label: string }[] = [
  { value: 'fast', label: 'Fast' },
  { value: 'high', label: 'High Quality' },
  { value: 'ultra', label: 'Ultra' },
]

const SFX_TYPES: { value: SfxEventType; label: string }[] = [
  { value: 'dark_riser', label: 'Dark Riser' },
  { value: 'magic_whoosh', label: 'Magic Whoosh' },
  { value: 'deep_boom', label: 'Deep Boom' },
  { value: 'tension_riser', label: 'Tension Riser' },
  { value: 'pre_silence', label: 'Pre Silence' },
  { value: 'post_silence', label: 'Post Silence' },
  { value: 'pattern_interrupt', label: 'Pattern Interrupt' },
]

const WHOOSH_VARIANTS = [
  { value: 0, label: '0.3s (Short)' },
  { value: 1, label: '0.45s (Medium)' },
  { value: 2, label: '0.6s (Long)' },
]

const BOOM_VARIANTS = [
  { value: 0, label: 'Profundo (45Hz)' },
  { value: 1, label: 'Seco (60Hz)' },
  { value: 2, label: 'Largo (35Hz)' },
  { value: 3, label: 'Climático (45+75Hz)' },
]

function ClipProperties({ state }: { state: EditorState }) {
  const clip = state.clips.find((c) => c.id === state.selected_clip_id)
  if (!clip) return null

  return (
    <div className="space-y-4">
      {/* Info del clip */}
      <div>
        <h4 className="text-xs font-semibold text-[var(--ae-text-muted)] uppercase tracking-wider mb-2">
          Clip Info
        </h4>
        <div className="space-y-1 text-xs text-[var(--ae-text)]">
          <div className="flex justify-between">
            <span className="text-[var(--ae-text-muted)]">Index</span>
            <span>#{clip.index + 1}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[var(--ae-text-muted)]">Duration</span>
            <span>{clip.duration.toFixed(1)}s</span>
          </div>
          <div className="flex justify-between">
            <span className="text-[var(--ae-text-muted)]">Start</span>
            <span>{clip.start_time.toFixed(1)}s</span>
          </div>
          {clip.transcript && (
            <div className="pt-1">
              <span className="text-[var(--ae-text-muted)] block mb-1">Transcript</span>
              <p className="text-[10px] text-[var(--ae-text)]/70 leading-relaxed">
                {clip.transcript.slice(0, 100)}
                {clip.transcript.length > 100 ? '...' : ''}
              </p>
            </div>
          )}
        </div>
      </div>

      <Separator className="bg-[var(--ae-border)]" />

      {/* Transición siguiente */}
      {clip.transition_after !== undefined && (
        <TransitionProperties
          clipId={clip.id}
          transition={clip.transition_after}
          isLastClip={clip.index === state.clips.length - 1}
        />
      )}
    </div>
  )
}

function TransitionProperties({
  clipId,
  transition,
  isLastClip,
}: {
  clipId: string
  transition?: { type: TransitionType; duration?: number; glitch_style?: GlitchStyle; sweep_shape?: SweepShape; morph_quality?: MorphQuality; motion_blur?: boolean; auto_score?: { match_cut: number; glitch: number; semantic_category: string } }
  isLastClip: boolean
}) {
  // This is a placeholder — the actual component will be rendered inside PropertiesPanel
  // where we have access to onUpdateTransition
  return null
}

export function PropertiesPanel({
  state,
  onUpdateTransition,
  onUpdateSfx,
  onAddSfx,
  onRemoveSfx,
}: PropertiesPanelProps) {
  const selectedClip = state.clips.find((c) => c.id === state.selected_clip_id)
  const sfxElement =
    state.selected_element?.type === 'sfx' ? state.selected_element : null
  const selectedSfx =
    sfxElement && selectedClip
      ? selectedClip.sfx_events.find((s) => s.id === sfxElement.sfx_id)
      : null

  const [addSfxOpen, setAddSfxOpen] = useState(false)

  return (
    <div className="h-full flex flex-col">
      <div className="px-3 py-2 text-xs font-semibold text-[var(--ae-text-muted)] uppercase tracking-wider border-b border-[var(--ae-border)]">
        Properties
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-4">
        {!state.selected_element && (
          <p className="text-xs text-[var(--ae-text-muted)] text-center py-8">
            Select an element to edit its properties
          </p>
        )}

        {/* Clip selected */}
        {state.selected_element?.type === 'clip' && selectedClip && (
          <div className="space-y-4">
            <div>
              <h4 className="text-xs font-semibold text-[var(--ae-text-muted)] uppercase tracking-wider mb-2">
                Clip Info
              </h4>
              <div className="space-y-1 text-xs text-[var(--ae-text)]">
                <div className="flex justify-between">
                  <span className="text-[var(--ae-text-muted)]">Index</span>
                  <span>#{selectedClip.index + 1}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--ae-text-muted)]">Duration</span>
                  <span>{selectedClip.duration.toFixed(1)}s</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--ae-text-muted)]">Start</span>
                  <span>{selectedClip.start_time.toFixed(1)}s</span>
                </div>
                {selectedClip.transcript && (
                  <div className="pt-1">
                    <span className="text-[var(--ae-text-muted)] block mb-1">Transcript</span>
                    <p className="text-[10px] text-[var(--ae-text)]/70 leading-relaxed">
                      {selectedClip.transcript.slice(0, 100)}
                      {selectedClip.transcript.length > 100 ? '...' : ''}
                    </p>
                  </div>
                )}
              </div>
            </div>

            <Separator className="bg-[var(--ae-border)]" />

            {/* Transition config */}
            {selectedClip.index < state.clips.length - 1 && (
              <div className="space-y-3">
                <h4 className="text-xs font-semibold text-[var(--ae-text-muted)] uppercase tracking-wider">
                  Next Transition
                </h4>

                <div className="space-y-1">
                  <label className="text-[10px] text-[var(--ae-text-muted)]">Type</label>
                  <Select
                    value={selectedClip.transition_after?.type || 'none'}
                    onValueChange={(val: string) =>
                      onUpdateTransition(selectedClip.id, { type: val as TransitionType })
                    }
                  >
                    <SelectTrigger className="h-7 text-xs bg-[var(--ae-panel)] border-[var(--ae-border)] text-[var(--ae-text)]">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent className="bg-[var(--ae-panel)] border-[var(--ae-border)] text-[var(--ae-text)]">
                      {TRANSITION_OPTIONS.map((opt) => (
                        <SelectItem key={opt.value} value={opt.value} className="text-xs">
                          {opt.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {selectedClip.transition_after?.type === 'glitch' && (
                  <div className="space-y-1">
                    <label className="text-[10px] text-[var(--ae-text-muted)]">Glitch Style</label>
                    <Select
                      value={selectedClip.transition_after.glitch_style || 'rgb'}
                      onValueChange={(val: string) =>
                        onUpdateTransition(selectedClip.id, { glitch_style: val as GlitchStyle })
                      }
                    >
                      <SelectTrigger className="h-7 text-xs bg-[var(--ae-panel)] border-[var(--ae-border)] text-[var(--ae-text)]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-[var(--ae-panel)] border-[var(--ae-border)] text-[var(--ae-text)]">
                        {GLITCH_STYLES.map((opt) => (
                          <SelectItem key={opt.value} value={opt.value} className="text-xs">
                            {opt.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}

                {selectedClip.transition_after?.type === 'sweep_mask' && (
                  <div className="space-y-1">
                    <label className="text-[10px] text-[var(--ae-text-muted)]">Sweep Shape</label>
                    <Select
                      value={selectedClip.transition_after.sweep_shape || 'circle'}
                      onValueChange={(val: string) =>
                        onUpdateTransition(selectedClip.id, { sweep_shape: val as SweepShape })
                      }
                    >
                      <SelectTrigger className="h-7 text-xs bg-[var(--ae-panel)] border-[var(--ae-border)] text-[var(--ae-text)]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-[var(--ae-panel)] border-[var(--ae-border)] text-[var(--ae-text)]">
                        {SWEEP_SHAPES.map((opt) => (
                          <SelectItem key={opt.value} value={opt.value} className="text-xs">
                            {opt.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}

                {selectedClip.transition_after?.type === 'shape_morph' && (
                  <div className="space-y-1">
                    <label className="text-[10px] text-[var(--ae-text-muted)]">Quality</label>
                    <Select
                      value={selectedClip.transition_after.morph_quality || 'high'}
                      onValueChange={(val: string) =>
                        onUpdateTransition(selectedClip.id, { morph_quality: val as MorphQuality })
                      }
                    >
                      <SelectTrigger className="h-7 text-xs bg-[var(--ae-panel)] border-[var(--ae-border)] text-[var(--ae-text)]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent className="bg-[var(--ae-panel)] border-[var(--ae-border)] text-[var(--ae-text)]">
                        {MORPH_QUALITIES.map((opt) => (
                          <SelectItem key={opt.value} value={opt.value} className="text-xs">
                            {opt.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}

                <div className="space-y-1">
                  <div className="flex justify-between text-[10px]">
                    <span className="text-[var(--ae-text-muted)]">Duration</span>
                    <span className="text-[var(--ae-text)]">
                      {(selectedClip.transition_after?.duration || 0.5).toFixed(2)}s
                    </span>
                  </div>
                  <Slider
                    min={0.2}
                    max={1.5}
                    step={0.05}
                    value={[selectedClip.transition_after?.duration || 0.5]}
                    onValueChange={([v]) => onUpdateTransition(selectedClip.id, { duration: v })}
                    className="[&_[role=slider]]:bg-[var(--ae-accent)]"
                  />
                </div>

                {/* Auto-score info */}
                {selectedClip.transition_after?.auto_score && (
                  <div className="p-2 rounded bg-[var(--ae-panel)] border border-[var(--ae-border)]">
                    <p className="text-[10px] text-[var(--ae-text-muted)] mb-1">Auto Selector Scores</p>
                    <div className="space-y-0.5 text-[10px]">
                      <div className="flex justify-between">
                        <span>Match Cut</span>
                        <span>{selectedClip.transition_after.auto_score.match_cut.toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Glitch</span>
                        <span>{selectedClip.transition_after.auto_score.glitch.toFixed(2)}</span>
                      </div>
                      <div className="flex justify-between">
                        <span>Category</span>
                        <span className="text-[var(--ae-accent)]">{selectedClip.transition_after.auto_score.semantic_category}</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* SFX selected */}
        {state.selected_element?.type === 'sfx' && selectedSfx && selectedClip && (
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <Badge
                variant="outline"
                className="text-[10px] border-[var(--ae-border)] text-[var(--ae-text)]"
              >
                {selectedSfx.type.replace(/_/g, ' ')}
              </Badge>
              <Badge
                className={cn(
                  'text-[10px]',
                  selectedSfx.source === 'auto'
                    ? 'bg-blue-500/20 text-blue-400'
                    : 'bg-amber-500/20 text-amber-400',
                )}
              >
                {selectedSfx.source === 'auto' ? 'AUTO' : 'MANUAL'}
              </Badge>
            </div>

            <div className="space-y-1">
              <div className="flex justify-between text-[10px]">
                <span className="text-[var(--ae-text-muted)]">Time</span>
                <span className="text-[var(--ae-text)]">{selectedSfx.time.toFixed(2)}s</span>
              </div>
              <Slider
                min={0}
                max={selectedClip.duration}
                step={0.05}
                value={[selectedSfx.time]}
                onValueChange={([v]) => onUpdateSfx(selectedClip.id, selectedSfx.id, { time: v })}
                className="[&_[role=slider]]:bg-[var(--ae-accent)]"
              />
            </div>

            {/* Type-specific params */}
            {(selectedSfx.type === 'dark_riser' || selectedSfx.type === 'tension_riser') && (
              <div className="space-y-1">
                <div className="flex justify-between text-[10px]">
                  <span className="text-[var(--ae-text-muted)]">Duration</span>
                  <span className="text-[var(--ae-text)]">{selectedSfx.params.duration || 2.0}s</span>
                </div>
                <Slider
                  min={0.3}
                  max={5.0}
                  step={0.1}
                  value={[selectedSfx.params.duration || 2.0]}
                  onValueChange={([v]) =>
                    onUpdateSfx(selectedClip.id, selectedSfx.id, {
                      params: { ...selectedSfx.params, duration: v },
                    })
                  }
                  className="[&_[role=slider]]:bg-[var(--ae-accent)]"
                />
              </div>
            )}

            {selectedSfx.type === 'magic_whoosh' && (
              <div className="space-y-1">
                <label className="text-[10px] text-[var(--ae-text-muted)]">Variant</label>
                <Select
                  value={String(selectedSfx.params.variant ?? 0)}
                  onValueChange={(val: string) =>
                    onUpdateSfx(selectedClip.id, selectedSfx.id, {
                      params: { ...selectedSfx.params, variant: parseInt(val) },
                    })
                  }
                >
                  <SelectTrigger className="h-7 text-xs bg-[var(--ae-panel)] border-[var(--ae-border)] text-[var(--ae-text)]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-[var(--ae-panel)] border-[var(--ae-border)] text-[var(--ae-text)]">
                    {WHOOSH_VARIANTS.map((opt) => (
                      <SelectItem key={opt.value} value={String(opt.value)} className="text-xs">
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {selectedSfx.type === 'deep_boom' && (
              <div className="space-y-1">
                <label className="text-[10px] text-[var(--ae-text-muted)]">Variant</label>
                <Select
                  value={String(selectedSfx.params.variant ?? 0)}
                  onValueChange={(val: string) =>
                    onUpdateSfx(selectedClip.id, selectedSfx.id, {
                      params: { ...selectedSfx.params, variant: parseInt(val) },
                    })
                  }
                >
                  <SelectTrigger className="h-7 text-xs bg-[var(--ae-panel)] border-[var(--ae-border)] text-[var(--ae-text)]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent className="bg-[var(--ae-panel)] border-[var(--ae-border)] text-[var(--ae-text)]">
                    {BOOM_VARIANTS.map((opt) => (
                      <SelectItem key={opt.value} value={String(opt.value)} className="text-xs">
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {(selectedSfx.type === 'pre_silence' || selectedSfx.type === 'post_silence') && (
              <div className="space-y-1">
                <div className="flex justify-between text-[10px]">
                  <span className="text-[var(--ae-text-muted)]">Duration (ms)</span>
                  <span className="text-[var(--ae-text)]">{selectedSfx.params.duration_ms || 100}ms</span>
                </div>
                <Slider
                  min={40}
                  max={300}
                  step={10}
                  value={[selectedSfx.params.duration_ms || 100]}
                  onValueChange={([v]) =>
                    onUpdateSfx(selectedClip.id, selectedSfx.id, {
                      params: { ...selectedSfx.params, duration_ms: v },
                    })
                  }
                  className="[&_[role=slider]]:bg-[var(--ae-accent)]"
                />
              </div>
            )}

            <Separator className="bg-[var(--ae-border)]" />

            <Button
              variant="outline"
              size="sm"
              onClick={() => onRemoveSfx(selectedClip.id, selectedSfx.id)}
              className="w-full text-xs border-red-500/30 text-red-400 hover:bg-red-500/10 h-7"
            >
              <Trash2 className="w-3 h-3 mr-1" />
              Delete this event
            </Button>
          </div>
        )}

        {/* Add SFX button */}
        {state.selected_element?.type === 'clip' && selectedClip && (
          <div className="pt-2">
            <Separator className="bg-[var(--ae-border)] mb-3" />
            {addSfxOpen ? (
              <div className="space-y-2">
                <label className="text-[10px] text-[var(--ae-text-muted)]">Add SFX</label>
                <div className="grid grid-cols-1 gap-1 max-h-40 overflow-y-auto">
                  {SFX_TYPES.map((sfx) => (
                    <button
                      key={sfx.value}
                      onClick={() => {
                        onAddSfx(selectedClip.id, {
                          time: state.playhead_time,
                          type: sfx.value,
                          params: {},
                          source: 'manual',
                        })
                        setAddSfxOpen(false)
                      }}
                      className="text-left px-2 py-1 rounded text-[10px] hover:bg-white/5 text-[var(--ae-text)] transition-colors"
                    >
                      {sfx.label}
                    </button>
                  ))}
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setAddSfxOpen(false)}
                  className="text-[10px] text-[var(--ae-text-muted)] h-6 w-full"
                >
                  Cancel
                </Button>
              </div>
            ) : (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setAddSfxOpen(true)}
                className="w-full text-xs border-[var(--ae-border)] text-[var(--ae-text)] hover:bg-white/5 h-7"
              >
                <Plus className="w-3 h-3 mr-1" />
                Add SFX
              </Button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
