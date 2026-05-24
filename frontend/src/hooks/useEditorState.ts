'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type { EditorState, TransitionConfig, SfxEvent } from '@/types/editor'

const API_BASE = '/api/tasks'

function generateId(): string {
  return `sfx_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

export function useEditorState(taskId: string) {
  const [state, setState] = useState<EditorState>({
    task_id: taskId,
    clips: [],
    total_duration: 0,
    selected_clip_id: null,
    selected_element: null,
    playhead_time: 0,
    is_playing: false,
    is_rendering: false,
    render_progress: 0,
    has_unsaved_changes: false,
  })
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const stateRef = useRef(state)
  stateRef.current = state

  // Carga inicial desde GET /editor-state
  useEffect(() => {
    if (!taskId) return
    setIsLoading(true)
    fetch(`${API_BASE}/${taskId}/editor-state`)
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load editor state: ${res.status}`)
        return res.json()
      })
      .then((data: EditorState) => {
        setState((prev) => ({
          ...prev,
          ...data,
          has_unsaved_changes: false,
        }))
      })
      .catch((err) => {
        console.warn('[EditorState] Load failed, using defaults:', err)
        // Si el backend está caído, usar estado local vacío
      })
      .finally(() => setIsLoading(false))
  }, [taskId])

  // Auto-save con debounce de 1500ms
  const save = useCallback(async (currentState: EditorState) => {
    setIsSaving(true)
    setSaveError(null)
    try {
      const res = await fetch(`${API_BASE}/${currentState.task_id}/editor-state`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          clips: currentState.clips,
          total_duration: currentState.total_duration,
        }),
      })
      if (!res.ok) throw new Error(`Save failed: ${res.status}`)
      setState((prev) => ({ ...prev, has_unsaved_changes: false }))
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown save error'
      setSaveError(msg)
      console.warn('[EditorState] Auto-save failed:', msg)
    } finally {
      setIsSaving(false)
    }
  }, [])

  const scheduleSave = useCallback(
    (updatedState: EditorState) => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => save(updatedState), 1500)
    },
    [save],
  )

  const updateState = useCallback(
    (updater: (prev: EditorState) => EditorState) => {
      setState((prev) => {
        const next = updater(prev)
        scheduleSave(next)
        return next
      })
    },
    [scheduleSave],
  )

  const updateTransition = useCallback(
    (clipId: string, config: Partial<TransitionConfig>) => {
      updateState((prev) => ({
        ...prev,
        has_unsaved_changes: true,
        clips: prev.clips.map((clip) =>
          clip.id === clipId
            ? {
                ...clip,
                transition_after: {
                  ...(clip.transition_after || { type: 'none' }),
                  ...config,
                } as TransitionConfig,
              }
            : clip,
        ),
      }))
    },
    [updateState],
  )

  const updateSfxEvent = useCallback(
    (clipId: string, sfxId: string, params: Partial<SfxEvent>) => {
      updateState((prev) => ({
        ...prev,
        has_unsaved_changes: true,
        clips: prev.clips.map((clip) =>
          clip.id === clipId
            ? {
                ...clip,
                sfx_events: clip.sfx_events.map((sfx) =>
                  sfx.id === sfxId ? { ...sfx, ...params, params: { ...sfx.params, ...params.params } } : sfx,
                ),
              }
            : clip,
        ),
      }))
    },
    [updateState],
  )

  const addSfxEvent = useCallback(
    (clipId: string, event: Omit<SfxEvent, 'id'>) => {
      const newEvent: SfxEvent = { ...event, id: generateId() }
      updateState((prev) => ({
        ...prev,
        has_unsaved_changes: true,
        clips: prev.clips.map((clip) =>
          clip.id === clipId
            ? { ...clip, sfx_events: [...clip.sfx_events, newEvent].sort((a, b) => a.time - b.time) }
            : clip,
        ),
      }))
    },
    [updateState],
  )

  const removeSfxEvent = useCallback(
    (clipId: string, sfxId: string) => {
      updateState((prev) => ({
        ...prev,
        has_unsaved_changes: true,
        selected_element:
          prev.selected_element?.type === 'sfx' && prev.selected_element.sfx_id === sfxId
            ? null
            : prev.selected_element,
        clips: prev.clips.map((clip) =>
          clip.id === clipId
            ? { ...clip, sfx_events: clip.sfx_events.filter((sfx) => sfx.id !== sfxId) }
            : clip,
        ),
      }))
    },
    [updateState],
  )

  const selectElement = useCallback(
    (element: EditorState['selected_element']) => {
      updateState((prev) => ({
        ...prev,
        selected_element: element,
        selected_clip_id: element?.type === 'clip' ? element.clip_id : element?.clip_id ?? prev.selected_clip_id,
      }))
    },
    [updateState],
  )

  const setPlayhead = useCallback((time: number) => {
    setState((prev) => ({ ...prev, playhead_time: Math.max(0, time) }))
  }, [])

  const triggerRerender = useCallback(async (): Promise<{ job_id: string }> => {
    // Primero guardar
    await save(stateRef.current)
    // Luego lanzar re-render
    const res = await fetch(`${API_BASE}/${taskId}/re-render`, {
      method: 'POST',
    })
    if (!res.ok) throw new Error(`Re-render failed: ${res.status}`)
    const data = await res.json()
    setState((prev) => ({ ...prev, is_rendering: true, render_progress: 0, has_unsaved_changes: false }))
    return data
  }, [taskId, save])

  // Cleanup debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  return {
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
  }
}
