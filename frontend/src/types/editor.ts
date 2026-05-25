export type TransitionType =
  'match_cut' | 'glitch' | 'sweep_mask' | 'mask_reveal' | 'shape_morph' | 'none'

export type GlitchStyle = 'rgb' | 'scan' | 'freeze'
export type SweepShape = 'circle' | 'diagonal' | 'wipe'
export type MorphQuality = 'fast' | 'high' | 'ultra'

export type SfxEventType =
  'dark_riser' | 'magic_whoosh' | 'deep_boom' | 'tension_riser' |
  'pre_silence' | 'post_silence' | 'pattern_interrupt'

export interface TransitionConfig {
  type: TransitionType
  duration?: number           // segundos, default 0.5
  glitch_style?: GlitchStyle
  sweep_shape?: SweepShape
  semantic_category?: string
  morph_quality?: MorphQuality
  motion_blur?: boolean
  // generado automáticamente o editado manualmente
  source?: 'auto' | 'manual'
  // score del selector automático (read-only, informativo)
  auto_score?: {
    match_cut: number
    glitch: number
    semantic_category: string
  }
}

export interface SfxEvent {
  id: string
  time: number               // segundos desde inicio del clip
  type: SfxEventType
  params: {
    duration?: number
    variant?: number
    duration_ms?: number
  }
  // generado automáticamente o editado manualmente
  source: 'auto' | 'manual'
}

export interface EditorClip {
  id: string
  index: number
  thumbnail_url?: string
  duration: number
  start_time: number         // posición en la timeline global
  transcript: string
  sfx_events: SfxEvent[]
  transition_after?: TransitionConfig  // transición hacia el siguiente clip
}

export interface EditorState {
  task_id: string
  clips: EditorClip[]
  total_duration: number
  selected_clip_id: string | null
  selected_element:
    | { type: 'clip'; clip_id: string }
    | { type: 'transition'; clip_id: string }  // transición después del clip
    | { type: 'sfx'; clip_id: string; sfx_id: string }
    | null
  playhead_time: number
  is_playing: boolean
  is_rendering: boolean
  render_progress: number    // 0-100
  has_unsaved_changes: boolean
}
