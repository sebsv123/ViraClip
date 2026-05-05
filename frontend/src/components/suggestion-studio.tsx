"use client";

import { useState, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetFooter } from "@/components/ui/sheet";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import { Progress } from "@/components/ui/progress";
import {
  SlidersHorizontal,
  Eye,
  Play,
  RotateCcw,
  Save,
  Check,
  X,
  Loader2,
  AlertCircle,
  Clock,
  Type,
  Image,
  Video,
  Music,
  Sparkles,
  Wand2,
  Zap,
  Layers,
  CheckCircle2,
  XCircle,
  Activity,
  TrendingUp,
  Smile,
  MousePointer,
  Search,
  ExternalLink,
  Target,
  Sun,
  EyeOff,
} from "lucide-react";

export interface Suggestion {
  id: string;
  kind: string;
  category: "timing" | "captions" | "media" | "polish";
  label: string | null;
  status: "pending" | "approved" | "rejected";
  payload: Record<string, unknown> | null;
  score: number | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

interface SuggestionStudioProps {
  isOpen: boolean;
  onClose: () => void;
  clipId: string | null;
  taskId: string;
  apiUrl: string;
  sessionToken?: string;
}

const KIND_ICONS: Record<string, React.ReactNode> = {
  hook_reorder: <Zap className="w-4 h-4" />,
  trim_offsets: <Clock className="w-4 h-4" />,
  timeline_moments: <Activity className="w-4 h-4" />,
  caption_template: <Type className="w-4 h-4" />,
  caption_style: <Type className="w-4 h-4" />,
  virality_prediction: <TrendingUp className="w-4 h-4" />,
  emoji_overlay: <Smile className="w-4 h-4" />,
  cta_overlay: <MousePointer className="w-4 h-4" />,
  text_pops: <Type className="w-4 h-4" />,
  highlight_words: <Layers className="w-4 h-4" />,
  broll_overlays: <Image className="w-4 h-4" />,
  ai_broll_generator: <Video className="w-4 h-4" />,
  contextual_overlay: <Video className="w-4 h-4" />,
  music_track: <Music className="w-4 h-4" />,
  sfx_cues: <Sparkles className="w-4 h-4" />,
  zoom_punch: <Zap className="w-4 h-4" />,
  color_grade: <Wand2 className="w-4 h-4" />,
  sharpen: <Target className="w-4 h-4" />,
  vignette: <Sun className="w-4 h-4" />,
  film_grain: <Layers className="w-4 h-4" />,
  blur: <EyeOff className="w-4 h-4" />,
  speed_control: <Clock className="w-4 h-4" />,
  loudnorm: <Music className="w-4 h-4" />,
  audio_ducking: <Music className="w-4 h-4" />,
  denoise: <Layers className="w-4 h-4" />,
  background_composite: <Image className="w-4 h-4" />,
  qa_retry: <AlertCircle className="w-4 h-4" />,
};

const KIND_LABELS: Record<string, string> = {
  hook_reorder: "Hook Reorder",
  trim_offsets: "Trim In/Out",
  timeline_moments: "Viral Moments",
  caption_template: "Caption Template",
  caption_style: "Caption Style",
  virality_prediction: "Virality Score",
  emoji_overlay: "Emoji Overlays",
  cta_overlay: "CTA Overlay",
  text_pops: "Text Pop Emphasis",
  highlight_words: "Highlight Words",
  broll_overlays: "B-Roll Overlays",
  ai_broll_generator: "AI B-roll Generator",
  contextual_overlay: "Contextual Overlay",
  music_track: "Music Track",
  sfx_cues: "Sound Effects",
  zoom_punch: "Zoom Punch",
  color_grade: "Color Grade",
  sharpen: "Sharpen",
  vignette: "Vignette",
  film_grain: "Film Grain",
  blur: "Blur",
  speed_control: "Speed Control",
  loudnorm: "Audio Normalize",
  audio_ducking: "Audio Ducking",
  denoise: "Denoise",
  background_composite: "Background",
  qa_retry: "QA Retry",
};

const CATEGORY_COLORS: Record<string, string> = {
  timing: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  captions: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  media: "bg-purple-500/15 text-purple-400 border-purple-500/30",
  polish: "bg-rose-500/15 text-rose-400 border-rose-500/30",
};

export function SuggestionStudio({ isOpen, onClose, clipId, taskId, apiUrl, sessionToken }: SuggestionStudioProps) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isFinalizing, setIsFinalizing] = useState(false);
  const [previewReady, setPreviewReady] = useState(false);
  const [jobStatus, setJobStatus] = useState<{ preview?: string; finalize?: string }>({});
  const [expandedId, setExpandedId] = useState<string | null>(null);  // Granular editing mode
  const [editingItems, setEditingItems] = useState<Record<string, any[]>>({});  // Local edits
  
  // Stock video search state
  const [stockQuery, setStockQuery] = useState("");
  const [stockResults, setStockResults] = useState<any[]>([]);
  const [stockLoading, setStockLoading] = useState(false);
  const [showStockSearch, setShowStockSearch] = useState(false);
  const [selectedStockVideo, setSelectedStockVideo] = useState<any>(null);
  
  // AI B-roll generation state
  const [aiGeneratingId, setAiGeneratingId] = useState<string | null>(null);
  const [aiStatus, setAiStatus] = useState<Record<string, string>>({});

  const fetchSuggestions = useCallback(async () => {
    if (!clipId || !taskId) return;
    setLoading(true);
    setError(null);
    try {
      // Use Next.js proxy to properly forward auth headers to backend
      const res = await fetch(`/api/tasks/${taskId}/clips/${clipId}/suggestions`);
      if (!res.ok) throw new Error("Failed to load suggestions");
      const data = await res.json();
      setSuggestions(data.suggestions || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error loading suggestions");
    } finally {
      setLoading(false);
    }
  }, [clipId, taskId, apiUrl, sessionToken]);

  useEffect(() => {
    if (isOpen && clipId) {
      fetchSuggestions();
      setPreviewReady(false);
      setJobStatus({});
    }
  }, [isOpen, clipId, fetchSuggestions]);

  const updateSuggestionStatus = async (suggestionId: string, status: "approved" | "rejected") => {
    if (!clipId || !taskId) return;
    setUpdatingId(suggestionId);
    try {
      const res = await fetch(
        `/api/tasks/${taskId}/clips/${clipId}/suggestions/${suggestionId}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        }
      );
      if (!res.ok) throw new Error("Failed to update suggestion");
      setSuggestions((prev) =>
        prev.map((s) => (s.id === suggestionId ? { ...s, status } : s))
      );
      setPreviewReady(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error updating suggestion");
    } finally {
      setUpdatingId(null);
    }
  };

  // Granular editing: expand/collapse suggestion items
  const toggleExpand = (suggestionId: string) => {
    if (expandedId === suggestionId) {
      setExpandedId(null);
    } else {
      setExpandedId(suggestionId);
      // Load current items into editing state
      const suggestion = suggestions.find(s => s.id === suggestionId);
      if (suggestion?.payload?.items) {
        setEditingItems(prev => ({
          ...prev,
          [suggestionId]: JSON.parse(JSON.stringify(suggestion.payload.items))
        }));
      }
    }
  };

  // Update items via API
  const updateSuggestionItems = async (suggestionId: string, operation: string, items: any[]) => {
    if (!clipId || !taskId) return;
    setUpdatingId(suggestionId);
    try {
      const res = await fetch(
        `${apiUrl}/tasks/${taskId}/clips/${clipId}/suggestions/${suggestionId}/items`,
        {
          method: "PATCH",
          headers: {
            "Content-Type": "application/json",
            ...(sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {}),
          },
          body: JSON.stringify({ operation, items }),
        }
      );
      if (!res.ok) throw new Error("Failed to update items");
      const data = await res.json();
      // Update local state with server response
      setSuggestions((prev) =>
        prev.map((s) => (s.id === suggestionId ? data.suggestion : s))
      );
      setPreviewReady(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error updating items");
    } finally {
      setUpdatingId(null);
    }
  };

  // Local item editing helpers
  const moveItem = (suggestionId: string, itemId: string, newStartTime: number) => {
    setEditingItems(prev => ({
      ...prev,
      [suggestionId]: prev[suggestionId]?.map(item =>
        item.id === itemId ? { ...item, start_time: newStartTime } : item
      ) || []
    }));
  };

  const updateItemField = (suggestionId: string, itemId: string, field: string, value: unknown) => {
    setEditingItems(prev => ({
      ...prev,
      [suggestionId]: prev[suggestionId]?.map(item =>
        item.id === itemId ? { ...item, [field]: value } : item
      ) || []
    }));
  };

  const addItem = (suggestionId: string, template: Record<string, unknown>) => {
    const newItem = {
      id: `manual_${Date.now()}`,
      ...template,
      start_time: 0,
      duration: 3.0,
    };
    setEditingItems(prev => ({
      ...prev,
      [suggestionId]: [...(prev[suggestionId] || []), newItem]
    }));
  };

  const removeItem = (suggestionId: string, itemId: string) => {
    setEditingItems(prev => ({
      ...prev,
      [suggestionId]: prev[suggestionId]?.filter(item => item.id !== itemId) || []
    }));
  };

  // Stock video search (Pexels API via backend proxy)
  const searchStockVideos = async (query: string) => {
    if (!query.trim()) return;
    setStockLoading(true);
    try {
      // Use a free Pexels API endpoint - this would ideally go through your backend
      // For now using direct Pexels API (user needs to add their own key in production)
      const PEXELS_API_KEY = process.env.NEXT_PUBLIC_PEXELS_API_KEY || "";
      if (!PEXELS_API_KEY) {
        // Fallback: show placeholder results for demo
        setStockResults([
          { id: "demo1", video_url: "https://videos.pexels.com/placeholder1.mp4", duration: 15, width: 1920, height: 1080, user: { name: "Demo" } },
          { id: "demo2", video_url: "https://videos.pexels.com/placeholder2.mp4", duration: 10, width: 1920, height: 1080, user: { name: "Demo" } },
          { id: "demo3", video_url: "https://videos.pexels.com/placeholder3.mp4", duration: 12, width: 1920, height: 1080, user: { name: "Demo" } },
        ]);
        setStockLoading(false);
        return;
      }
      
      const res = await fetch(`https://api.pexels.com/videos/search?query=${encodeURIComponent(query)}&per_page=6&orientation=landscape`, {
        headers: { Authorization: PEXELS_API_KEY }
      });
      if (!res.ok) throw new Error("Search failed");
      const data = await res.json();
      setStockResults(data.videos?.map((v: Record<string, unknown>) => (
        id: v.id,
        video_url: v.video_files?.[0]?.link || v.url,
        duration: v.duration,
        width: v.width,
        height: v.height,
        user: v.user,
        image: v.image,
      })) || []);
    } catch (e) {
      console.error("Stock search failed:", e);
      setStockResults([]);
    } finally {
      setStockLoading(false);
    }
  };

  const addStockVideoAsBroll = (suggestionId: string, video: Record<string, unknown>, startTime: number) => {
    const newItem = {
      id: `stock_${video.id}_${Date.now()}`,
      video_url: video.video_url,
      start_time: startTime,
      duration: Math.min(video.duration || 5, 5), // Max 5 seconds
      position: "fullscreen",
      opacity: 1.0,
      scale: 1.0,
      keywords: stockQuery.split(" "),
      source: "pexels",
      source_id: video.id,
    };
    setEditingItems(prev => ({
      ...prev,
      [suggestionId]: [...(prev[suggestionId] || []), newItem]
    }));
    setSelectedStockVideo(null);
    setShowStockSearch(false);
  };

  // Save local edits to server
  const saveItemEdits = async (suggestionId: string) => {
    const items = editingItems[suggestionId];
    if (!items) return;
    await updateSuggestionItems(suggestionId, "replace", items);
  };

  const resetAll = async () => {
    if (!clipId || !taskId) return;
    setLoading(true);
    try {
      const res = await fetch(
        `${apiUrl}/tasks/${taskId}/clips/${clipId}/suggestions/reset`,
        {
          method: "POST",
          headers: sessionToken ? { Authorization: `Bearer ${sessionToken}` } : {},
        }
      );
      if (!res.ok) throw new Error("Failed to reset suggestions");
      await fetchSuggestions();
      setPreviewReady(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error resetting suggestions");
    } finally {
      setLoading(false);
    }
  };

  const approveAll = async () => {
    const pending = suggestions.filter((s) => s.status === "pending");
    for (const s of pending) {
      await updateSuggestionStatus(s.id, "approved");
    }
  };

  // Generate AI B-roll using LTX Video
  const generateAIBroll = async (suggestionId: string, prompt: string, duration: number) => {
    if (!clipId || !taskId) return;
    setAiGeneratingId(suggestionId);
    setAiStatus(prev => ({ ...prev, [suggestionId]: "Iniciando generación..." }));
    
    try {
      // Call backend API to generate B-roll with LTX
      const res = await fetch(`/api/tasks/${taskId}/clips/${clipId}/ai-broll`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          duration,
          model: "ltx-video",
          suggestion_id: suggestionId,
        }),
      });
      
      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: "Unknown error" }));
        throw new Error(err.error || "Failed to start AI generation");
      }
      
      const data = await res.json();
      setAiStatus(prev => ({ ...prev, [suggestionId]: `Generando... Job ID: ${data.job_id?.slice(0, 8)}` }));
      
      // Poll for completion
      if (data.job_id) {
        const maxAttempts = 60; // 2 minutes max
        for (let i = 0; i < maxAttempts; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          
          const pollRes = await fetch(`/api/jobs/${data.job_id}`);
          if (!pollRes.ok) continue;
          
          const pollData = await pollRes.json();
          
          if (pollData.status === "completed" || pollData.status === "ready") {
            setAiStatus(prev => ({ ...prev, [suggestionId]: "✓ Generado! Guardado en B-roll." }));
            // Refresh suggestions to show the new B-roll
            await fetchSuggestions();
            setTimeout(() => {
              setAiStatus(prev => ({ ...prev, [suggestionId]: "" }));
            }, 3000);
            break;
          }
          
          if (pollData.status === "failed") {
            throw new Error(pollData.error || "Generation failed");
          }
          
          // Update progress message every 10 seconds
          if (i % 5 === 0) {
            setAiStatus(prev => ({ ...prev, [suggestionId]: `Generando... ${Math.round((i / maxAttempts) * 100)}%` }));
          }
        }
      }
    } catch (e) {
      setAiStatus(prev => ({ ...prev, [suggestionId]: `Error: ${e instanceof Error ? e.message : "Failed"}` }));
    } finally {
      setAiGeneratingId(null);
    }
  };

  const pollJob = useCallback(async (jobId: string, type: "preview" | "finalize") => {
    const maxAttempts = 30;
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      try {
        const res = await fetch(`/api/jobs/${jobId}`);
        if (!res.ok) continue;
        const data = await res.json();
        if (data.status === "completed" || data.status === "ready") {
          if (type === "preview") {
            setPreviewReady(true);
            setJobStatus((prev) => ({ ...prev, preview: "ready" }));
          } else {
            setJobStatus((prev) => ({ ...prev, finalize: "complete" }));
            setIsFinalizing(false);
            onClose();
          }
          return;
        }
        if (data.status === "failed") {
          setError(data.error || `${type} job failed`);
          if (type === "finalize") setIsFinalizing(false);
          return;
        }
      } catch {
        // Continue polling
      }
    }
    setError(`${type} timed out — check back in a moment`);
    if (type === "finalize") setIsFinalizing(false);
  }, [apiUrl, sessionToken, onClose]);

  const generatePreview = async () => {
    if (!clipId || !taskId) return;
    setIsPreviewing(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/tasks/${taskId}/clips/${clipId}/preview`,
        { method: "POST" }
      );
      const data = await res.json();
      if (data.status === "ready") {
        setPreviewReady(true);
        setJobStatus((prev) => ({ ...prev, preview: "ready" }));
      } else if (data.job_id) {
        setJobStatus((prev) => ({ ...prev, preview: "processing" }));
        pollJob(data.job_id, "preview");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error generating preview");
    } finally {
      setIsPreviewing(false);
    }
  };

  const finalizeClip = async () => {
    if (!clipId || !taskId) return;
    setIsFinalizing(true);
    setError(null);
    try {
      const res = await fetch(
        `/api/tasks/${taskId}/clips/${clipId}/finalize`,
        { method: "POST" }
      );
      const data = await res.json();
      if (data.status === "final") {
        setJobStatus((prev) => ({ ...prev, finalize: "complete" }));
        setIsFinalizing(false);
        onClose();
      } else if (data.job_id) {
        setJobStatus((prev) => ({ ...prev, finalize: "processing" }));
        pollJob(data.job_id, "finalize");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error finalizing clip");
      setIsFinalizing(false);
    }
  };

  const approvedCount = suggestions.filter((s) => s.status === "approved").length;
  const rejectedCount = suggestions.filter((s) => s.status === "rejected").length;
  const pendingCount = suggestions.filter((s) => s.status === "pending").length;

  const groupedSuggestions = suggestions.reduce((acc, s) => {
    if (!acc[s.category]) acc[s.category] = [];
    acc[s.category].push(s);
    return acc;
  }, {} as Record<string, Suggestion[]>);

  return (
    <Sheet open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full sm:max-w-xl md:max-w-2xl bg-gray-900 border-gray-800 overflow-y-auto">
        <SheetHeader className="pb-4 border-b border-gray-800">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <SlidersHorizontal className="w-5 h-5 text-rose-400" />
              <SheetTitle className="text-white">Suggestion Studio</SheetTitle>
            </div>
            <div className="flex gap-2">
              <Badge variant="outline" className="bg-green-500/15 text-green-400 border-green-500/30">
                <CheckCircle2 className="w-3 h-3 mr-1" />
                {approvedCount}
              </Badge>
              <Badge variant="outline" className="bg-amber-500/15 text-amber-400 border-amber-500/30">
                <Clock className="w-3 h-3 mr-1" />
                {pendingCount}
              </Badge>
              <Badge variant="outline" className="bg-red-500/15 text-red-400 border-red-500/30">
                <XCircle className="w-3 h-3 mr-1" />
                {rejectedCount}
              </Badge>
            </div>
          </div>
          <SheetDescription className="text-gray-400">
            Toggle AI suggestions to customize your clip. Preview changes before finalizing.
          </SheetDescription>
        </SheetHeader>

        {error && (
          <Alert variant="destructive" className="mt-4 bg-red-500/15 border-red-500/30">
            <AlertCircle className="h-4 w-4 text-red-400" />
            <AlertDescription className="text-red-300">{error}</AlertDescription>
          </Alert>
        )}

        <div className="py-4 space-y-6">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-8 h-8 animate-spin text-rose-400" />
            </div>
          ) : suggestions.length === 0 ? (
            <div className="text-center py-12 text-gray-400">
              <p>No suggestions available for this clip.</p>
            </div>
          ) : (
            Object.entries(groupedSuggestions).map(([category, items]) => (
              <div key={category} className="space-y-3">
                <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider flex items-center gap-2">
                  <Badge className={CATEGORY_COLORS[category]}>{category}</Badge>
                  <span className="text-xs">{items.length} suggestions</span>
                </h3>
                <div className="space-y-2">
                  <AnimatePresence mode="popLayout">
                    {items.map((suggestion) => (
                      <motion.div
                        key={suggestion.id}
                        layout
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, scale: 0.95 }}
                        className={`p-3 rounded-lg border transition-colors ${
                          suggestion.status === "approved"
                            ? "bg-green-500/10 border-green-500/30"
                            : suggestion.status === "rejected"
                            ? "bg-red-500/10 border-red-500/30 opacity-60"
                            : suggestion.payload?.failed
                            ? "bg-amber-500/10 border-amber-500/50"
                            : "bg-gray-800/50 border-gray-700 hover:border-gray-600"
                        }`}
                      >
                        <div className="flex items-start gap-3">
                          <div className={`flex-shrink-0 mt-0.5 ${suggestion.payload?.failed ? "text-amber-400" : "text-gray-400"}`}>
                            {suggestion.payload?.failed ? <AlertCircle className="w-4 h-4" /> : KIND_ICONS[suggestion.kind] || <Sparkles className="w-4 h-4" />}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between gap-2">
                              <p className={`font-medium text-sm ${suggestion.payload?.failed ? "text-amber-300" : "text-gray-200"}`}>
                                {KIND_LABELS[suggestion.kind] || suggestion.kind}
                                {suggestion.payload?.failed && <span className="ml-1 text-amber-400">⚠️</span>}
                              </p>
                              {suggestion.score !== null && (
                                <Badge variant="outline" className="text-xs bg-white/5">
                                  {(suggestion.score * 100).toFixed(0)}%
                                </Badge>
                              )}
                            </div>
                            {suggestion.label && (
                              <p className={`text-xs mt-1 ${suggestion.payload?.failed ? "text-amber-400/80" : "text-gray-400"}`}>{suggestion.label}</p>
                            )}
                            {typeof suggestion.payload?.qa_reason === "string" && (
                              <p className="text-xs text-amber-500 mt-1">QA: {suggestion.payload.qa_reason}</p>
                            )}
                            {typeof suggestion.payload?.error === "string" && (
                              <p className="text-xs text-red-400 mt-1">Error: {suggestion.payload.error}</p>
                            )}
                            {/* Expandable granular editing for suggestions with items */}
                            {suggestion.payload?.editable && suggestion.payload?.items && (
                              <div className="mt-3">
                                <button
                                  onClick={() => toggleExpand(suggestion.id)}
                                  className="text-xs flex items-center gap-1 text-purple-400 hover:text-purple-300 transition-colors"
                                >
                                  {expandedId === suggestion.id ? "▲" : "▼"} Editar items ({Array.isArray(suggestion.payload.items) ? suggestion.payload.items.length : 0})
                                </button>

                                {expandedId === suggestion.id && (
                                  <motion.div
                                    initial={{ height: 0, opacity: 0 }}
                                    animate={{ height: "auto", opacity: 1 }}
                                    exit={{ height: 0, opacity: 0 }}
                                    className="mt-3 space-y-2 bg-black/20 rounded-lg p-3"
                                  >
                                    {/* Mini timeline visualization */}
                                    <div className="flex items-center gap-1 mb-2 text-[10px] text-gray-500">
                                      <span>0s</span>
                                      <div className="flex-1 h-1 bg-gray-700 rounded-full overflow-hidden">
                                        {editingItems[suggestion.id]?.map((item: Record<string, unknown>) => (
                                          <div
                                            key={item.id}
                                            className="h-full bg-purple-500/60 absolute"
                                            style={{
                                              left: `${(item.start_time / 30) * 100}%`,
                                              width: `${(item.duration / 30) * 100}%`,
                                              minWidth: "4px",
                                            }}
                                            title={`${item.id} @ ${item.start_time}s`}
                                          />
                                        ))}
                                      </div>
                                      <span>30s</span>
                                    </div>

                                    {/* Editable items list */}
                                    <div className="space-y-2 max-h-48 overflow-y-auto">
                                      {editingItems[suggestion.id]?.map((item: Record<string, unknown>) => (
                                        <div key={item.id as string} className="flex items-center gap-2 text-xs bg-gray-800/50 rounded p-2">
                                          <span className="text-gray-500 w-16 truncate">{item.id as string}</span>
                                          <div className="flex items-center gap-1">
                                            <span className="text-gray-500">@</span>
                                            <input
                                              type="number"
                                              value={item.start_time.toFixed(1)}
                                              onChange={(e) => moveItem(suggestion.id, item.id, parseFloat(e.target.value))}
                                              className="w-14 bg-black/30 rounded px-1 py-0.5 text-purple-300"
                                              step="0.5"
                                              min="0"
                                            />
                                            <span className="text-gray-500">s</span>
                                          </div>
                                          <div className="flex items-center gap-1">
                                            <span className="text-gray-500">dur:</span>
                                            <input
                                              type="number"
                                              value={item.duration?.toFixed(1) || "3.0"}
                                              onChange={(e) => updateItemField(suggestion.id, item.id, "duration", parseFloat(e.target.value))}
                                              className="w-12 bg-black/30 rounded px-1 py-0.5 text-purple-300"
                                              step="0.5"
                                              min="0.5"
                                            />
                                          </div>
                                          {item.position && (
                                            <select
                                              value={item.position}
                                              onChange={(e) => updateItemField(suggestion.id, item.id, "position", e.target.value)}
                                              className="bg-black/30 rounded px-1 py-0.5 text-xs text-gray-300"
                                            >
                                              <option value="fullscreen">Full</option>
                                              <option value="corner">Corner</option>
                                              <option value="split">Split</option>
                                            </select>
                                          )}
                                          <button
                                            onClick={() => removeItem(suggestion.id, item.id)}
                                            className="ml-auto text-red-400 hover:text-red-300"
                                            title="Remove item"
                                          >
                                            <X className="w-3 h-3" />
                                          </button>
                                        </div>
                                      ))}
                                    </div>

                                    {/* Add item buttons */}
                                    <div className="flex gap-2 pt-2 border-t border-gray-700">
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        className="text-xs h-7 border-purple-500/30 text-purple-400"
                                        onClick={() => {
                                          setShowStockSearch(true);
                                          const keywords = (suggestion.payload?.keywords as string[]) || [];
                                          setStockQuery(keywords.join(" ") || "");
                                        }}
                                      >
                                        <Search className="w-3 h-3 mr-1" /> Buscar Stock
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="outline"
                                        className="text-xs h-7 border-gray-500/30 text-gray-400"
                                        onClick={() => addItem(suggestion.id, { position: "fullscreen" })}
                                      >
                                        + Manual
                                      </Button>
                                      <Button
                                        size="sm"
                                        variant="default"
                                        className="text-xs h-7 bg-purple-600 hover:bg-purple-700"
                                        onClick={() => saveItemEdits(suggestion.id)}
                                        disabled={updatingId === suggestion.id}
                                      >
                                        {updatingId === suggestion.id ? (
                                          <Loader2 className="w-3 h-3 animate-spin" />
                                        ) : (
                                          "Guardar"
                                        )}
                                      </Button>
                                    </div>
                                    
                                    {/* Stock video search panel */}
                                    {showStockSearch && (
                                      <motion.div
                                        initial={{ height: 0, opacity: 0 }}
                                        animate={{ height: "auto", opacity: 1 }}
                                        exit={{ height: 0, opacity: 0 }}
                                        className="mt-3 p-3 bg-gray-800/50 rounded-lg border border-gray-700"
                                      >
                                        <div className="flex items-center gap-2 mb-3">
                                          <input
                                            type="text"
                                            value={stockQuery}
                                            onChange={(e) => setStockQuery(e.target.value)}
                                            placeholder="Buscar videos (ej: nature, city, abstract)..."
                                            className="flex-1 bg-black/30 rounded px-2 py-1 text-sm text-gray-200"
                                            onKeyDown={(e) => e.key === "Enter" && searchStockVideos(stockQuery)}
                                          />
                                          <Button
                                            size="sm"
                                            variant="outline"
                                            className="h-7 text-xs"
                                            onClick={() => searchStockVideos(stockQuery)}
                                            disabled={stockLoading}
                                          >
                                            {stockLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Search className="w-3 h-3" />}
                                          </Button>
                                          <button
                                            onClick={() => setShowStockSearch(false)}
                                            className="text-gray-400 hover:text-gray-300"
                                          >
                                            <X className="w-4 h-4" />
                                          </button>
                                        </div>
                                        
                                        {/* Stock results grid */}
                                        {stockResults.length > 0 && (
                                          <div className="grid grid-cols-3 gap-2 max-h-48 overflow-y-auto">
                                            {stockResults.map((video) => (
                                              <div
                                                key={video.id}
                                                className={`relative aspect-video bg-gray-900 rounded overflow-hidden cursor-pointer border-2 transition-colors ${
                                                  selectedStockVideo?.id === video.id 
                                                    ? "border-purple-500" 
                                                    : "border-transparent hover:border-purple-500/50"
                                                }`}
                                                onClick={() => setSelectedStockVideo(video)}
                                              >
                                                {video.image ? (
                                                  <img 
                                                    src={video.image} 
                                                    alt="" 
                                                    className="w-full h-full object-cover"
                                                  />
                                                ) : (
                                                  <div className="w-full h-full flex items-center justify-center text-gray-600">
                                                    <Video className="w-6 h-6" />
                                                  </div>
                                                )}
                                                <div className="absolute bottom-0 left-0 right-0 bg-black/60 text-[10px] text-gray-300 px-1 py-0.5 truncate">
                                                  {video.duration}s • {video.user?.name || "Stock"}
                                                </div>
                                                {selectedStockVideo?.id === video.id && (
                                                  <div className="absolute inset-0 flex items-center justify-center bg-purple-500/20">
                                                    <Check className="w-6 h-6 text-purple-400" />
                                                  </div>
                                                )}
                                              </div>
                                            ))}
                                          </div>
                                        )}
                                        
                                        {/* Add selected stock video */}
                                        {selectedStockVideo && (
                                          <div className="mt-3 flex items-center gap-2">
                                            <span className="text-xs text-gray-400">Añadir @</span>
                                            <input
                                              type="number"
                                              defaultValue={0}
                                              step="0.5"
                                              min="0"
                                              id="stock-start-time"
                                              className="w-16 bg-black/30 rounded px-2 py-1 text-sm text-purple-300"
                                            />
                                            <span className="text-xs text-gray-400">s</span>
                                            <Button
                                              size="sm"
                                              variant="default"
                                              className="h-7 text-xs bg-purple-600 hover:bg-purple-700"
                                              onClick={() => {
                                                const startTime = parseFloat((document.getElementById("stock-start-time") as HTMLInputElement)?.value || "0");
                                                addStockVideoAsBroll(suggestion.id, selectedStockVideo, startTime);
                                              }}
                                            >
                                              <Check className="w-3 h-3 mr-1" /> Añadir
                                            </Button>
                                          </div>
                                        )}
                                        
                                        {!process.env.NEXT_PUBLIC_PEXELS_API_KEY && stockResults.length > 0 && (
                                          <p className="mt-2 text-[10px] text-amber-400/80">
                                            ⚠️ Modo demo: Agrega NEXT_PUBLIC_PEXELS_API_KEY en .env para búsqueda real
                                          </p>
                                        )}
                                      </motion.div>
                                    )}
                                  </motion.div>
                                )}
                              </div>
                            )}

                            {suggestion.payload && Object.keys(suggestion.payload).length > 0 && !suggestion.payload?.editable && (
                              <div className="mt-2 text-xs text-gray-500 font-mono">
                                {JSON.stringify(suggestion.payload).slice(0, 100)}
                                {JSON.stringify(suggestion.payload).length > 100 ? "..." : ""}
                              </div>
                            )}

                            {/* AI B-roll Generator UI */}
                            {suggestion.kind === "ai_broll_generator" && (
                              <div className="mt-3 p-3 bg-gradient-to-r from-purple-900/20 to-blue-900/20 rounded-lg border border-purple-500/30">
                                {suggestion.payload?.available ? (
                                  <>
                                    <div className="flex items-center gap-2 mb-2">
                                      <span className="text-xs text-purple-300 font-medium">Prompt:</span>
                                      <input
                                        type="text"
                                        id={`ai-prompt-${suggestion.id}`}
                                        placeholder="Ej: ocean waves at sunset, city traffic at night..."
                                        className="flex-1 bg-black/30 rounded px-2 py-1 text-xs text-gray-200"
                                        defaultValue={(suggestion.payload?.prompt_template as string)?.replace("{topic}", "") || ""}
                                      />
                                    </div>
                                    <div className="flex items-center gap-2 mb-2">
                                      <span className="text-xs text-purple-300">Duración:</span>
                                      <select
                                        id={`ai-duration-${suggestion.id}`}
                                        className="bg-black/30 rounded px-2 py-1 text-xs text-gray-200"
                                        defaultValue={(suggestion.payload?.default_duration as number) || 3}
                                      >
                                        <option value={2}>2s</option>
                                        <option value={3}>3s</option>
                                        <option value={4}>4s</option>
                                        <option value={5}>5s</option>
                                      </select>
                                      <span className="text-xs text-gray-500">(máx 5s para LTX)</span>
                                    </div>
                                    <Button
                                      size="sm"
                                      variant="default"
                                      className="w-full text-xs bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-500 hover:to-blue-500"
                                      onClick={() => {
                                        const prompt = (document.getElementById(`ai-prompt-${suggestion.id}`) as HTMLInputElement)?.value;
                                        const duration = parseInt((document.getElementById(`ai-duration-${suggestion.id}`) as HTMLSelectElement)?.value || "3");
                                        if (prompt) {
                                          generateAIBroll(suggestion.id, prompt, duration);
                                        }
                                      }}
                                      disabled={aiGeneratingId === suggestion.id}
                                    >
                                      {aiGeneratingId === suggestion.id ? (
                                        <><Loader2 className="w-3 h-3 animate-spin mr-1" /> Generando...</>
                                      ) : (
                                        <><Video className="w-3 h-3 mr-1" /> Generar B-roll con IA</>
                                      )}
                                    </Button>
                                    {aiStatus[suggestion.id] && (
                                      <p className="mt-2 text-[10px] text-purple-300">{aiStatus[suggestion.id]}</p>
                                    )}
                                  </>
                                ) : (
                                  <div className="text-xs text-amber-400/80">
                                    <p className="font-medium">⚠️ LTX no configurado</p>
                                    <p className="mt-1 text-gray-400">Para usar el generador AI:</p>
                                    <ul className="mt-1 ml-4 list-disc text-gray-500">
                                      {(suggestion.payload?.requirements as string[])?.map((req: string, i: number) => (
                                        <li key={i}>{req}</li>
                                      ))}
                                    </ul>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                          <div className="flex gap-1">
                            <TooltipProvider>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    size="icon"
                                    variant={suggestion.status === "approved" ? "default" : "outline"}
                                    className={`h-8 w-8 ${
                                      suggestion.status === "approved"
                                        ? "bg-green-500 hover:bg-green-600"
                                        : "border-green-500/30 text-green-400 hover:bg-green-500/10"
                                    }`}
                                    onClick={() => updateSuggestionStatus(suggestion.id, "approved")}
                                    disabled={updatingId === suggestion.id}
                                  >
                                    {updatingId === suggestion.id ? (
                                      <Loader2 className="h-4 w-4 animate-spin" />
                                    ) : (
                                      <Check className="h-4 w-4" />
                                    )}
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>Approve</TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                            <TooltipProvider>
                              <Tooltip>
                                <TooltipTrigger asChild>
                                  <Button
                                    size="icon"
                                    variant={suggestion.status === "rejected" ? "default" : "outline"}
                                    className={`h-8 w-8 ${
                                      suggestion.status === "rejected"
                                        ? "bg-red-500 hover:bg-red-600"
                                        : "border-red-500/30 text-red-400 hover:bg-red-500/10"
                                    }`}
                                    onClick={() => updateSuggestionStatus(suggestion.id, "rejected")}
                                    disabled={updatingId === suggestion.id}
                                  >
                                    <X className="h-4 w-4" />
                                  </Button>
                                </TooltipTrigger>
                                <TooltipContent>Reject</TooltipContent>
                              </Tooltip>
                            </TooltipProvider>
                          </div>
                        </div>
                      </motion.div>
                    ))}
                  </AnimatePresence>
                </div>
              </div>
            ))
          )}
        </div>

        <SheetFooter className="flex-col gap-3 pt-4 border-t border-gray-800">
          <div className="flex gap-2 w-full">
            <Button
              variant="outline"
              size="sm"
              onClick={resetAll}
              disabled={loading || suggestions.length === 0}
              className="flex-1"
            >
              <RotateCcw className="w-4 h-4 mr-2" />
              Reset All
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={approveAll}
              disabled={loading || pendingCount === 0}
              className="flex-1"
            >
              <Check className="w-4 h-4 mr-2" />
              Approve All
            </Button>
          </div>

          <div className="flex gap-2 w-full">
            <Button
              variant="outline"
              size="lg"
              onClick={generatePreview}
              disabled={isPreviewing || isFinalizing || suggestions.length === 0}
              className="flex-1 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
            >
              {isPreviewing ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Generating...
                </>
              ) : previewReady ? (
                <>
                  <Eye className="w-4 h-4 mr-2" />
                  Update Preview
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 mr-2" />
                  Preview
                </>
              )}
            </Button>
            <Button
              size="lg"
              onClick={finalizeClip}
              disabled={isPreviewing || isFinalizing || suggestions.length === 0}
              className="flex-1 bg-gradient-to-r from-rose-500 to-pink-500 hover:from-rose-600 hover:to-pink-600"
            >
              {isFinalizing ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Finalizing...
                </>
              ) : (
                <>
                  <Save className="w-4 h-4 mr-2" />
                  Finalize
                </>
              )}
            </Button>
          </div>

          {jobStatus.preview === "processing" && (
            <div className="w-full">
              <p className="text-xs text-gray-400 mb-1">Generating preview...</p>
              <Progress value={45} className="h-1" />
            </div>
          )}
          {jobStatus.finalize === "processing" && (
            <div className="w-full">
              <p className="text-xs text-gray-400 mb-1">Finalizing clip...</p>
              <Progress value={30} className="h-1" />
            </div>
          )}
          {previewReady && (
            <p className="text-xs text-green-400 text-center">
              Preview ready! Check the clip player to see changes.
            </p>
          )}
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}
