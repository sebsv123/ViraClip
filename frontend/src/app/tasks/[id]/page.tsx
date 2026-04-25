"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
} from "@/components/ui/sheet";
import { useSession } from "@/lib/auth-client";
import { formatSupportMessage, parseApiError } from "@/lib/api-error";
import {
  ArrowLeft,
  Download,
  Star,
  AlertCircle,
  Trash2,
  Edit2,
  X,
  Check,
  Zap,
  MessageSquare,
  TrendingUp,
  Share2,
  Clock,
  Scissors,
  SplitSquareVertical,
  GitMerge,
  RefreshCw,
  Subtitles,
  Settings2,
  Type,
  Clapperboard,
  Sparkles,
  Bot,
  Send,
  BrainCircuit,
  Target,
  MousePointer,
  Wand2,
  Film,
  Volume2,
  CheckCircle2,
  XCircle,
  Layers,
  Loader2,
  Shuffle,
  Music,
  Lightbulb,
} from "lucide-react";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import { Progress } from "@/components/ui/progress";
import Link from "next/link";
import DynamicVideoPlayer from "@/components/dynamic-video-player";

interface Clip {
  id: string;
  filename: string;
  file_path: string;
  start_time: string;
  end_time: string;
  duration: number;
  text: string;
  relevance_score: number;
  reasoning: string;
  clip_order: number;
  created_at: string;
  video_url: string;
  // Virality scores
  virality_score: number;
  hook_score: number;
  engagement_score: number;
  value_score: number;
  shareability_score: number;
  hook_type: string | null;
  intensity?: number;
  vfx_trigger?: string;
  bgm_style?: string;
  // P3: Social copy
  social_title?: string | null;
  social_description?: string | null;
  suggested_hashtags?: string[];
  // P4: Thumbnail
  thumbnail_url?: string | null;
  thumbnail_filename?: string | null;
  // B-3: Face detection
  face_detected?: boolean | null;
  // P2.4: Hook preview score
  hook_preview_score?: number;
  // P3.5: A/B variant
  variant?: string | null;
  variant_group?: string | null;
  // V3 Phase 4: Social Intelligence
  strategic_advice?: string | null;
  conversion_tips?: string | null;
  // B.6: User rating
  user_rating?: number | null;
  // Phase 9: Creative Engine
  creative_enhanced?: boolean;
  hook_reorder_applied?: boolean;
  hook_already_optimized?: boolean;
  hook_text?: string;
  zoom_punch_applied?: boolean;
  color_grade_applied?: boolean;
  sfx_injected?: number;
  loudnorm_applied?: boolean;
  preset_used?: string;
  broll_overlays?: number;
  qa_passed?: boolean;
  qa_issues?: string[];
  pacing_score?: number | null;
  emotion_score?: number | null;
  improvements?: string[];
  // Smart Auto-Editor
  smart_edit_decisions?: number;
  smart_edit_summary?: string;
  smart_edit_time_saved?: number;
  text_pops_applied?: number;
  // Phase 10: Viral Polish & A/B
  cta_overlay_applied?: boolean;
  emoji_overlays_applied?: boolean;
  variants?: Array<{
    path: string;
    variant: string;  // "caption" | "bgm"
    label: string;
    type: string;
  }>;
}

interface TaskDetails {
  id: string;
  user_id: string;
  source_id: string;
  source_title: string;
  source_type: string;
  status: string;
  progress?: number;
  progress_message?: string;
  clips_count: number;
  created_at: string;
  updated_at: string;
  font_family?: string;
  font_size?: number;
  font_color?: string;
  caption_template?: string;
  include_broll?: boolean;
  analysis?: {
    summary?: string;
    key_topics?: string[];
    most_relevant_segments?: Array<{
      theme?: string;
      virality_score?: number;
      reasoning?: string;
    }>;
  };
}

interface FontOption {
  name: string;
  display_name: string;
}

export default function TaskPage() {
  const params = useParams();
  const router = useRouter();
  const { data: session } = useSession();
  const [task, setTask] = useState<TaskDetails | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [progressMessage, setProgressMessage] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [editedTitle, setEditedTitle] = useState("");
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);
  const [deletingClipId, setDeletingClipId] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [selectedClipIds, setSelectedClipIds] = useState<string[]>([]);
  const [editingClipId, setEditingClipId] = useState<string | null>(null);
  const [startOffset, setStartOffset] = useState("0");
  const [endOffset, setEndOffset] = useState("0");
  const [splitTime, setSplitTime] = useState("5");
  const [captionText, setCaptionText] = useState("");
  const [captionPosition, setCaptionPosition] = useState("bottom");
  const [highlightWords, setHighlightWords] = useState("");
  const [exportPreset, setExportPreset] = useState("tiktok");
  const [activeTopicFilter, setActiveTopicFilter] = useState<string | null>(null);
  const [clipRatings, setClipRatings] = useState<Record<string, number>>({});
  // P3.1: AI refine state
  const [refiningClipId, setRefiningClipId] = useState<string | null>(null);
  const [refineInstruction, setRefineInstruction] = useState("");
  const [isRefining, setIsRefining] = useState(false);
  const [refineResult, setRefineResult] = useState<{ action: string; reasoning: string } | null>(null);

  const [projectFontFamily, setProjectFontFamily] = useState("TikTokSans-Regular");
  const [projectFontSize, setProjectFontSize] = useState("24");
  const [projectFontColor, setProjectFontColor] = useState("#FFFFFF");
  const [projectCaptionTemplate, setProjectCaptionTemplate] = useState("default");
  const [projectIncludeBroll, setProjectIncludeBroll] = useState(false);
  const [isApplyingSettings, setIsApplyingSettings] = useState(false);
  const [settingsSheetOpen, setSettingsSheetOpen] = useState(false);
  const [availableFonts, setAvailableFonts] = useState<FontOption[]>([]);
  const [availableTemplates, setAvailableTemplates] = useState<
    Array<{ id: string; name: string; description: string; animation: string }>
  >([]);
  const hasTriggeredAutoRefresh = useRef(false);
  const notifiedRef = useRef(false);

  // Music picker state
  const [musicTracks, setMusicTracks] = useState<Array<{id: string; label: string}>>([]);
  const [musicPickerClipId, setMusicPickerClipId] = useState<string | null>(null);
  const [selectedTrack, setSelectedTrack] = useState<string>("");
  const [isApplyingMusic, setIsApplyingMusic] = useState(false);
  const [musicAppliedClipId, setMusicAppliedClipId] = useState<string | null>(null);

  // Interactive waiting experience states
  const [clickCount, setClickCount] = useState(0);
  const [currentTipIndex, setCurrentTipIndex] = useState(0);
  const [showConfetti, setShowConfetti] = useState(false);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  // Viral tips that rotate during processing
  const viralTips = [
    { icon: Zap, text: "Videos with hooks in the first 3 seconds get 65% more retention" },
    { icon: Target, text: "Ask a question in your first sentence to boost engagement" },
    { icon: MessageSquare, text: "Reply to every comment in the first hour to boost reach" },
    { icon: TrendingUp, text: "Post when your audience is most active (check analytics)" },
    { icon: Sparkles, text: "Trending audio can increase discoverability by 40%" },
    { icon: Clock, text: "15-45 second clips perform best for viral content" },
    { icon: Subtitles, text: "85% of viewers watch videos without sound - add captions!" },
    { icon: Wand2, text: "Your best hook: 'Here's why...' or 'The secret to...'" },
    { icon: Star, text: "Post consistently: 3-5 videos per week is the sweet spot" },
    { icon: BrainCircuit, text: "AI-optimized clips adapt to your audience preferences" },
  ];

  // Load available music tracks once
  useEffect(() => {
    fetch(`${apiUrl}/clips/music/tracks`)
      .then(r => r.json())
      .then(d => { if (d.tracks) setMusicTracks(d.tracks); })
      .catch(() => {});
  }, [apiUrl]);

  // Rotate tips every 8 seconds during processing
  useEffect(() => {
    if (task?.status !== "processing" && task?.status !== "queued") return;
    const interval = setInterval(() => {
      setCurrentTipIndex((prev) => (prev + 1) % viralTips.length);
    }, 8000);
    return () => clearInterval(interval);
  }, [task?.status]);

  // Confetti effect at milestones
  useEffect(() => {
    if (progress > 0 && progress % 25 === 0 && progress !== 100) {
      setShowConfetti(true);
      setTimeout(() => setShowConfetti(false), 2000);
    }
  }, [progress]);

  const handleApplyMusic = async (clipId: string) => {
    if (!selectedTrack) return;
    setIsApplyingMusic(true);
    try {
      const res = await fetch(`${apiUrl}/clips/${clipId}/apply-music`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ track: selectedTrack }),
      });
      if (res.ok) {
        setMusicAppliedClipId(clipId);
        setMusicPickerClipId(null);
        setTimeout(() => setMusicAppliedClipId(null), 3000);
      }
    } finally {
      setIsApplyingMusic(false);
    }
  };

  const getStatusBadge = (status: string) => {
    const map: Record<string, { label: string; className: string }> = {
      completed: { label: "Completed", className: "bg-green-500/15 text-green-400 border-green-500/30" },
      processing: { label: "Processing", className: "bg-blue-500/15 text-blue-400 border-blue-500/30" },
      queued: { label: "Queued", className: "bg-amber-500/15 text-amber-400 border-amber-500/30" },
      failed: { label: "Failed", className: "bg-red-500/15 text-red-400 border-red-500/30" },
      error: { label: "Error", className: "bg-red-500/15 text-red-400 border-red-500/30" },
    };
    const s = map[status] ?? { label: status, className: "bg-white/5 text-gray-300 border-white/10" };
    return (
      <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${s.className}`}>{s.label}</span>
    );
  };

  const fireCompletionNotification = useCallback((clipCount: number) => {
    if (notifiedRef.current) return;
    notifiedRef.current = true;
    if (typeof window === "undefined") return;
    if ("Notification" in window && Notification.permission === "default") {
      void Notification.requestPermission();
    }
    if ("Notification" in window && Notification.permission === "granted") {
      new Notification("ViraClip — clips ready!", {
        body: `${clipCount} clip${clipCount !== 1 ? "s" : ""} generated successfully.`,
        icon: "/favicon.ico",
      });
    }
    document.title = `✅ Done — ViraClip`;
  }, []);

  const rateClip = async (clipId: string, rating: number) => {
    setClipRatings((prev) => ({ ...prev, [clipId]: rating }));
    try {
      await fetch(`${apiUrl}/clips/${clipId}/rating`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating }),
      });
    } catch {
      setClipRatings((prev) => ({ ...prev, [clipId]: prev[clipId] }));
    }
  };
  const taskApiUrl = "/api/tasks";

  const buildSupportError = useCallback(async (response: Response, fallbackMessage: string) => {
    const parsed = await parseApiError(response, fallbackMessage);
    return formatSupportMessage(parsed);
  }, []);

  const triggerAutoRefresh = useCallback(() => {
    if (hasTriggeredAutoRefresh.current) return;
    hasTriggeredAutoRefresh.current = true;
    setTimeout(() => {
      window.location.reload();
    }, 700);
  }, []);

  const fetchTaskStatus = useCallback(
    async (retryCount = 0, maxRetries = 5) => {
      if (!params.id) return false;

      try {
        const taskResponse = await fetch(`${taskApiUrl}/${params.id}`, {
          cache: "no-store",
        });

        // Handle 404 with retry logic (task might not be persisted yet)
        if (taskResponse.status === 404 && retryCount < maxRetries) {
          console.log(
            `Task not found yet, retrying in ${(retryCount + 1) * 500}ms... (${retryCount + 1}/${maxRetries})`,
          );
          await new Promise((resolve) => setTimeout(resolve, (retryCount + 1) * 500));
          return fetchTaskStatus(retryCount + 1, maxRetries);
        }

        if (!taskResponse.ok) {
          throw new Error(await buildSupportError(taskResponse, `Failed to fetch task: ${taskResponse.status}`));
        }

        const taskData = await taskResponse.json();
        setTask(taskData);
        setProjectFontFamily(taskData.font_family || "TikTokSans-Regular");
        setProjectFontSize(String(taskData.font_size || 24));
        setProjectFontColor(taskData.font_color || "#FFFFFF");
        setProjectCaptionTemplate(taskData.caption_template || "default");
        setProjectIncludeBroll(Boolean(taskData.include_broll));

        // Fetch clips if task is completed or processing (incremental clips)
        if (taskData.status === "completed" || taskData.status === "processing") {
          const clipsResponse = await fetch(`${taskApiUrl}/${params.id}/clips`, {
            cache: "no-store",
          });

          if (!clipsResponse.ok) {
            throw new Error(await buildSupportError(clipsResponse, `Failed to fetch clips: ${clipsResponse.status}`));
          }

          const clipsData = await clipsResponse.json();
          const nextClips = clipsData.clips || [];
          setClips((prev) => {
            if (taskData.status === "completed") {
              return nextClips;
            }

            const merged = new Map<string, Clip>();
            for (const clip of prev) {
              merged.set(clip.id, clip);
            }
            for (const clip of nextClips) {
              merged.set(clip.id, clip);
            }
            return Array.from(merged.values()).sort(
              (a, b) => (a.clip_order ?? 0) - (b.clip_order ?? 0),
            );
          });
        }

        return true;
      } catch (err) {
        console.error("Error fetching task data:", err);
        setError(err instanceof Error ? err.message : "Failed to load task");
        return false;
      }
    },
    [buildSupportError, params.id, taskApiUrl],
  );

  // Initial fetch - runs immediately, doesn't wait for session
  useEffect(() => {
    if (!params.id) return;

    const fetchTaskData = async () => {
      try {
        setIsLoading(true);
        await fetchTaskStatus();
      } finally {
        setIsLoading(false);
      }
    };

    fetchTaskData();
  }, [params.id, fetchTaskStatus]);

  useEffect(() => {
    const loadFonts = async () => {
      try {
        const response = await fetch("/api/fonts", { cache: "no-store" });
        if (!response.ok) {
          return;
        }
        const data = await response.json();
        setAvailableFonts(data.fonts || []);
      } catch (loadError) {
        console.error("Failed to load fonts:", loadError);
      }
    };

    void loadFonts();

    const loadTemplates = async () => {
      try {
        const response = await fetch(`${apiUrl}/caption-templates`);
        if (response.ok) {
          const data = await response.json();
          setAvailableTemplates(data.templates || []);
        }
      } catch (error) {
        console.error("Failed to load caption templates:", error);
      }
    };
    void loadTemplates();
  }, [apiUrl]);

  // document.title progress indicator
  useEffect(() => {
    const status = task?.status;
    if (!status || status === "completed" || status === "failed") return;
    const pct = progress > 0 ? ` ${progress}%` : "";
    document.title = `⏳${pct} Processing — ViraClip`;
    return () => {
      document.title = "ViraClip";
    };
  }, [task?.status, progress]);

  // SSE effect - real-time progress updates
  useEffect(() => {
    const taskStatus = task?.status;
    if (!params.id || !taskStatus) return;

    // Only connect to SSE if task is queued or processing
    if (taskStatus !== "queued" && taskStatus !== "processing") return;

    const eventSource = new EventSource(`${taskApiUrl}/${params.id}/progress`);

    console.log("📡 Connected to SSE for real-time progress");

    eventSource.addEventListener("status", (e) => {
      const data = JSON.parse(e.data);
      console.log("📊 Status:", data);
      setProgress(data.progress || 0);
      setProgressMessage(data.message || "");

      if (data.status === "completed") {
        void fetchTaskStatus().then((ok) => {
          if (ok) fireCompletionNotification(clips.length);
          triggerAutoRefresh();
        });
      }
    });

    eventSource.addEventListener("progress", (e) => {
      const data = JSON.parse(e.data);
      console.log("📈 Progress:", data);
      setProgress(data.progress || 0);
      setProgressMessage(data.message || "");

      // Update task status if provided
      if (data.status) {
        setTask((currentTask) => (currentTask ? { ...currentTask, status: data.status } : currentTask));

        if (data.status === "completed") {
          void fetchTaskStatus().then((ok) => {
            if (ok) fireCompletionNotification(clips.length);
            triggerAutoRefresh();
          });
        }
      }
    });

    eventSource.addEventListener("clip_ready", (e) => {
      const data = JSON.parse(e.data);
      console.log("🎬 Clip ready:", data.clip_index + 1, "/", data.total_clips);
      if (data.clip) {
        setClips((prev) => {
          const exists = prev.some((c: Clip) => c.id === data.clip.id);
          if (exists) return prev;
          return [...prev, data.clip].sort(
            (a: Clip, b: Clip) => (a.clip_order ?? 0) - (b.clip_order ?? 0),
          );
        });
      }
    });

    eventSource.addEventListener("close", async (e) => {
      const data = JSON.parse(e.data);
      console.log("✅ Task completed:", data.status);
      eventSource.close();

      // Refresh task and clips
      await fetchTaskStatus();
      fireCompletionNotification(clips.length);
      triggerAutoRefresh();
    });

    eventSource.addEventListener("error", (e) => {
      console.error("❌ SSE error:", e);
      const maybeMessageEvent = e as MessageEvent<string>;
      if (typeof maybeMessageEvent.data === "string" && maybeMessageEvent.data.length > 0) {
        const data = JSON.parse(maybeMessageEvent.data);
        setError(data.error || "Connection error");
      }
      eventSource.close();
    });

    return () => {
      console.log("🔌 Disconnecting SSE");
      eventSource.close();
    };
  }, [params.id, task?.status, fetchTaskStatus, taskApiUrl, triggerAutoRefresh, fireCompletionNotification, clips.length]); // Re-run when task status changes

  const formatDuration = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  const getScoreColor = (score: number) => {
    if (score >= 0.8) return "bg-green-100 text-green-800";
    if (score >= 0.6) return "bg-yellow-100 text-yellow-800";
    return "bg-red-100 text-red-800";
  };

  const getViralityColor = (score: number) => {
    if (score >= 80) return "text-green-600";
    if (score >= 60) return "text-yellow-600";
    if (score >= 40) return "text-orange-600";
    return "text-red-600";
  };

  const getViralityBgColor = (score: number) => {
    if (score >= 80) return "bg-green-500";
    if (score >= 60) return "bg-yellow-500";
    if (score >= 40) return "bg-orange-500";
    return "bg-red-500";
  };

  const getHookTypeLabel = (hookType: string | null) => {
    const labels: Record<string, string> = {
      question: "Question Hook",
      statement: "Bold Statement",
      statistic: "Data/Stats",
      story: "Story Hook",
      contrast: "Contrast Hook",
      none: "No Hook",
    };
    return labels[hookType || "none"] || hookType || "None";
  };

  const getIntensityColor = (intensity: number) => {
    if (intensity >= 0.8) return "text-red-600 bg-red-50 border-red-200";
    if (intensity >= 0.5) return "text-orange-600 bg-orange-50 border-orange-200";
    return "text-blue-600 bg-blue-50 border-blue-200";
  };

  // P2.4: Hook preview score color — gradient from low (gray) to high (orange-red)
  const getHookPreviewColor = (score: number) => {
    if (score >= 75) return "bg-orange-500 text-white";
    if (score >= 55) return "bg-amber-400 text-white";
    if (score >= 35) return "bg-yellow-400 text-gray-800";
    return "bg-gray-200 text-gray-400";
  };

  const handleEditTitle = async () => {
    if (!editedTitle.trim() || !session?.user?.id || !params.id) return;

    try {
      const response = await fetch(`${taskApiUrl}/${params.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title: editedTitle }),
      });

      if (response.ok) {
        setTask(task ? { ...task, source_title: editedTitle } : null);
        setIsEditing(false);
      } else {
        alert(await buildSupportError(response, "Failed to update title"));
      }
    } catch (err) {
      console.error("Error updating title:", err);
      alert(err instanceof Error ? err.message : "Failed to update title");
    }
  };

  const handleDeleteTask = async () => {
    if (!session?.user?.id || !params.id) return;

    setIsDeleting(true);
    try {
      const response = await fetch(`${taskApiUrl}/${params.id}`, {
        method: "DELETE",
      });

      if (response.ok) {
        router.push("/list");
      } else {
        alert(await buildSupportError(response, "Failed to delete task"));
      }
    } catch (err) {
      console.error("Error deleting task:", err);
      alert(err instanceof Error ? err.message : "Failed to delete task");
    } finally {
      setIsDeleting(false);
      setShowDeleteDialog(false);
    }
  };

  const handleDeleteClip = async (clipId: string) => {
    if (!session?.user?.id || !params.id) return;

    try {
      const response = await fetch(`${taskApiUrl}/${params.id}/clips/${clipId}`, {
        method: "DELETE",
      });

      if (response.ok) {
        setClips(clips.filter((clip) => clip.id !== clipId));
        setDeletingClipId(null);
      } else {
        alert(await buildSupportError(response, "Failed to delete clip"));
      }
    } catch (err) {
      console.error("Error deleting clip:", err);
      alert(err instanceof Error ? err.message : "Failed to delete clip");
    }
  };

  const handleToggleClipSelection = (clipId: string) => {
    setSelectedClipIds((prev) => {
      if (prev.includes(clipId)) {
        return prev.filter((id) => id !== clipId);
      }
      return [...prev, clipId];
    });
  };

  const handleTrimClip = async (clipId: string) => {
    if (!session?.user?.id || !params.id) return;
    const response = await fetch(`${taskApiUrl}/${params.id}/clips/${clipId}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        start_offset: Number(startOffset || "0"),
        end_offset: Number(endOffset || "0"),
      }),
    });
    if (!response.ok) {
      alert(await buildSupportError(response, "Failed to trim clip"));
      return;
    }
    await fetchTaskStatus();
  };

  const handleSplitClip = async (clipId: string) => {
    if (!session?.user?.id || !params.id) return;
    const response = await fetch(`${taskApiUrl}/${params.id}/clips/${clipId}/split`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ split_time: Number(splitTime || "5") }),
    });
    if (!response.ok) {
      alert(await buildSupportError(response, "Failed to split clip"));
      return;
    }
    await fetchTaskStatus();
  };

  const handleMergeClips = async () => {
    if (!session?.user?.id || !params.id || selectedClipIds.length < 2) return;
    const response = await fetch(`${taskApiUrl}/${params.id}/clips/merge`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ clip_ids: selectedClipIds }),
    });
    if (!response.ok) {
      alert(await buildSupportError(response, "Failed to merge clips"));
      return;
    }
    setSelectedClipIds([]);
    await fetchTaskStatus();
  };

  const handleUpdateCaptions = async (clipId: string) => {
    if (!session?.user?.id || !params.id) return;
    const response = await fetch(`${taskApiUrl}/${params.id}/clips/${clipId}/captions`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        caption_text: captionText,
        position: captionPosition,
        highlight_words: highlightWords
          .split(",")
          .map((w) => w.trim())
          .filter(Boolean),
      }),
    });
    if (!response.ok) {
      alert(await buildSupportError(response, "Failed to update captions"));
      return;
    }
    await fetchTaskStatus();
  };

  const handleApplyProjectSettings = async () => {
    if (!session?.user?.id || !params.id) return;
    const parsedSize = Number(projectFontSize || "24");
    const safeFontSize = Number.isFinite(parsedSize) ? Math.max(12, Math.min(72, Math.round(parsedSize))) : 24;
    const normalizedColor = /^#[0-9A-Fa-f]{6}$/.test(projectFontColor) ? projectFontColor : "#FFFFFF";

    setIsApplyingSettings(true);
    try {
      const response = await fetch(`${taskApiUrl}/${params.id}/settings`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          font_family: projectFontFamily,
          font_size: safeFontSize,
          font_color: normalizedColor,
          caption_template: projectCaptionTemplate,
          include_broll: projectIncludeBroll,
          apply_to_existing: true,
        }),
      });
      if (!response.ok) {
        alert(await buildSupportError(response, "Failed to apply settings"));
        return;
      }
      await fetchTaskStatus();
    } finally {
      setIsApplyingSettings(false);
    }
  };

  // P3.1: AI refine a clip with a natural language instruction
  const handleRefineClip = async (clipId: string) => {
    if (!refineInstruction.trim() || !task?.id) return;
    setIsRefining(true);
    setRefineResult(null);
    try {
      const res = await fetch(`${taskApiUrl}/${task.id}/clips/${clipId}/refine`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: refineInstruction }),
      });
      if (!res.ok) {
        const msg = await buildSupportError(res, "AI refine failed");
        setRefineResult({ action: "error", reasoning: msg });
        return;
      }
      const json = await res.json();
      setRefineResult({ action: json.action ?? "done", reasoning: json.reasoning ?? "" });
      setRefineInstruction("");
      // Refresh clips if the action mutated something
      if (json.action && json.action !== "noop" && json.action !== "error") {
        await fetchTaskStatus();
      }
    } catch (err) {
      setRefineResult({ action: "error", reasoning: String(err) });
    } finally {
      setIsRefining(false);
    }
  };

  const handleExportClip = async (clipId: string, fallbackFilename: string) => {
    if (!session?.user?.id || !task?.id) return;

    const response = await fetch(`${taskApiUrl}/${task.id}/clips/${clipId}/export?preset=${exportPreset}`, {
      cache: "no-store",
    });

    if (!response.ok) {
      alert(await buildSupportError(response, "Failed to export clip"));
      return;
    }

    const blob = await response.blob();
    const blobUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = `${fallbackFilename.replace(/\.mp4$/i, "")}_${exportPreset}.mp4`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(blobUrl);
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] text-white flex">
        <aside className="w-64 bg-[#0a0a0f] border-r border-white/5 min-h-screen flex flex-col">
          <div className="p-6">
            <div className="flex items-center gap-3">
              <div className="relative w-10 h-10">
                <div className="absolute inset-0 bg-gradient-to-br from-cyan-400 via-purple-500 to-pink-500 rounded-xl" />
                <div className="absolute inset-[2px] bg-[#0a0a0f] rounded-xl flex items-center justify-center">
                  <Zap className="w-5 h-5 text-cyan-400" />
                </div>
              </div>
              <span className="text-xl font-bold">
                Vira<span className="text-cyan-400">Clip</span>
              </span>
            </div>
          </div>
        </aside>
        <main className="flex-1 flex items-center justify-center">
          <div className="flex items-center gap-3">
            <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
            <span className="text-gray-400">Loading task details...</span>
          </div>
        </main>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] text-white flex">
        <aside className="w-64 bg-[#0a0a0f] border-r border-white/5 min-h-screen flex flex-col">
          <div className="p-6">
            <div className="flex items-center gap-3">
              <div className="relative w-10 h-10">
                <div className="absolute inset-0 bg-gradient-to-br from-cyan-400 via-purple-500 to-pink-500 rounded-xl" />
                <div className="absolute inset-[2px] bg-[#0a0a0f] rounded-xl flex items-center justify-center">
                  <Zap className="w-5 h-5 text-cyan-400" />
                </div>
              </div>
              <span className="text-xl font-bold">
                Vira<span className="text-cyan-400">Clip</span>
              </span>
            </div>
          </div>
        </aside>
        <main className="flex-1 flex items-center justify-center p-8">
          <div className="text-center">
            <AlertCircle className="w-16 h-16 text-red-400 mx-auto mb-4" />
            <p className="text-gray-400 mb-4">{error}</p>
            <Link href="/list" className="text-cyan-400 hover:underline">
              Back to My Clips
            </Link>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white flex">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-[#0a0a0f]/80 backdrop-blur-xl border-b border-white/5 px-8 py-4">
        <div className="flex items-center gap-4">
          <Link href="/list">
            <button className="p-2 rounded-lg hover:bg-white/10 text-gray-400 hover:text-white transition-colors">
              <ArrowLeft className="w-5 h-5" />
            </button>
          </Link>
          {task && (
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-3">
                {isEditing ? (
                  <>
                    <input
                      type="text"
                      value={editedTitle}
                      onChange={(e) => setEditedTitle(e.target.value)}
                      className="flex-1 px-4 py-2 bg-white/5 border border-white/10 rounded-xl text-white focus:border-cyan-500/50 focus:outline-none"
                      autoFocus
                    />
                    <button
                      onClick={handleEditTitle}
                      disabled={!editedTitle.trim()}
                      className="p-2 rounded-lg bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 disabled:opacity-50"
                    >
                      <Check className="w-5 h-5" />
                    </button>
                    <button
                      onClick={() => {
                        setIsEditing(false);
                        setEditedTitle(task.source_title);
                      }}
                      className="p-2 rounded-lg hover:bg-white/10 text-gray-400 hover:text-white"
                    >
                      <X className="w-5 h-5" />
                    </button>
                  </>
                ) : (
                  <>
                    <h1 className="text-xl font-bold text-white truncate">
                      {task.source_title}
                    </h1>
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => {
                          setIsEditing(true);
                          setEditedTitle(task.source_title);
                        }}
                        className="p-2 rounded-lg hover:bg-white/10 text-gray-400 hover:text-white transition-colors"
                      >
                        <Edit2 className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => setShowDeleteDialog(true)}
                        className="p-2 rounded-lg hover:bg-red-500/10 text-red-400 hover:text-red-300 transition-colors"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </>
                )}
              </div>
              <div className="flex items-center gap-3 text-sm text-gray-500 mt-1">
                <span className="px-2 py-0.5 rounded-full bg-white/5 border border-white/10 capitalize">
                  {task.source_type}
                </span>
                <span>{new Date(task.created_at).toLocaleDateString()}</span>
                <span>•</span>
                <span>{clips.length} clips</span>
                <span>•</span>
                {getStatusBadge(task.status)}
              </div>
            </div>
          )}
        </div>
      </header>

      {/* Main Content */}
      <div className="max-w-6xl mx-auto px-4 py-8">
        {task?.status === "processing" || task?.status === "queued" ? (
          <div className="space-y-8">
            {/* Main Progress Experience */}
            <div className="max-w-2xl mx-auto">
              <motion.div 
                className="rounded-3xl border border-white/10 bg-gradient-to-br from-violet-500/10 via-fuchsia-500/5 to-transparent p-8 relative overflow-hidden"
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
              >
                {/* Animated background orbs */}
                <div className="absolute inset-0 overflow-hidden pointer-events-none">
                  <motion.div
                    className="absolute -top-20 -right-20 w-40 h-40 bg-violet-500/20 rounded-full blur-3xl"
                    animate={{ scale: [1, 1.2, 1], opacity: [0.3, 0.5, 0.3] }}
                    transition={{ duration: 4, repeat: Infinity }}
                  />
                  <motion.div
                    className="absolute -bottom-20 -left-20 w-40 h-40 bg-fuchsia-500/20 rounded-full blur-3xl"
                    animate={{ scale: [1.2, 1, 1.2], opacity: [0.3, 0.5, 0.3] }}
                    transition={{ duration: 4, repeat: Infinity, delay: 2 }}
                  />
                </div>

                {/* Confetti burst */}
                {showConfetti && (
                  <div className="absolute inset-0 flex items-center justify-center pointer-events-none z-10">
                    <motion.div
                      initial={{ scale: 0 }}
                      animate={{ scale: [0, 1.5, 0] }}
                      transition={{ duration: 0.8 }}
                      className="text-4xl"
                    >
                      🎉
                    </motion.div>
                  </div>
                )}

                {/* Header with animated status */}
                <div className="relative flex items-center justify-between mb-8">
                  <div className="flex items-center gap-4">
                    <motion.div 
                      className="relative"
                      animate={task.status === "processing" ? { rotate: 360 } : {}}
                      transition={task.status === "processing" ? { duration: 8, repeat: Infinity, ease: "linear" } : {}}
                    >
                      <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-violet-500/30 to-fuchsia-500/30 flex items-center justify-center border border-white/10">
                        {task.status === "queued" ? (
                          <Clock className="w-8 h-8 text-amber-400" />
                        ) : (
                          <Zap className="w-8 h-8 text-violet-400" />
                        )}
                      </div>
                    </motion.div>
                    <div>
                      <motion.h3 
                        className="text-xl font-bold text-white"
                        key={progressMessage}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                      >
                        {task.status === "queued" ? "In Queue" : progress >= 90 ? "Almost Done!" : "Creating Magic"}
                      </motion.h3>
                      <p className="text-sm text-white/50">
                        {clips.length > 0 ? (
                          <span className="text-green-400">{clips.length} clip{clips.length !== 1 ? "s" : ""} ready!</span>
                        ) : (
                          "This won't take long..."
                        )}
                      </p>
                    </div>
                  </div>
                  
                  {/* Big percentage with pulse */}
                  <div className="text-right">
                    <motion.span 
                      className="text-4xl font-bold text-white tabular-nums"
                      key={progress}
                      initial={{ scale: 1.2 }}
                      animate={{ scale: 1 }}
                    >
                      {progress}%
                    </motion.span>
                  </div>
                </div>

                {/* Enhanced progress bar with glow */}
                <div className="relative mb-6">
                  <div className="h-4 bg-white/5 rounded-full overflow-hidden border border-white/10">
                    <motion.div
                      className="h-full rounded-full bg-gradient-to-r from-violet-500 via-fuchsia-500 to-pink-500 relative"
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.max(progress, 3)}%` }}
                      transition={{ duration: 0.8, ease: "easeOut" }}
                    >
                      <motion.div
                        className="absolute inset-0 bg-gradient-to-r from-transparent via-white/30 to-transparent"
                        animate={{ x: ["-100%", "100%"] }}
                        transition={{ duration: 1.5, repeat: Infinity, ease: "linear" }}
                      />
                    </motion.div>
                  </div>
                </div>

                {/* Progress message with typing effect feel */}
                <div className="mb-8">
                  <motion.p 
                    className="text-white/80 flex items-center gap-3 text-sm"
                    key={progressMessage}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                  >
                    <span className="flex items-center justify-center w-6 h-6 rounded-full bg-violet-500/20">
                      {progress < 25 ? <Download className="w-3 h-3 text-violet-400" /> :
                       progress < 50 ? <Subtitles className="w-3 h-3 text-violet-400" /> :
                       progress < 75 ? <BrainCircuit className="w-3 h-3 text-violet-400" /> :
                       <Film className="w-3 h-3 text-violet-400" />}
                    </span>
                    {progressMessage || (task.status === "queued" ? "Waiting for available worker..." : "Starting up the AI engines...")}
                  </motion.p>
                </div>

                {/* Processing stages with connecting line */}
                <div className="relative">
                  <div className="absolute top-6 left-0 right-0 h-0.5 bg-white/10 -z-10" />
                  <div className="grid grid-cols-4 gap-3">
                    {[
                      { label: "Download", icon: Download, threshold: 10, emoji: "📥" },
                      { label: "Analyze", icon: BrainCircuit, threshold: 40, emoji: "🧠" },
                      { label: "Create", icon: Wand2, threshold: 60, emoji: "✨" },
                      { label: "Polish", icon: Sparkles, threshold: 85, emoji: "💎" },
                    ].map((stage) => {
                      const isActive = progress >= stage.threshold;
                      const isCurrent = progress >= stage.threshold && progress < (stage.threshold + 25);
                      return (
                        <motion.div
                          key={stage.label}
                          className={`flex flex-col items-center gap-2 p-3 rounded-xl transition-all duration-300 ${
                            isActive
                              ? "bg-white/10 text-white border border-white/20"
                              : "bg-transparent text-white/30"
                          }`}
                          animate={isCurrent ? { scale: [1, 1.05, 1] } : {}}
                          transition={{ duration: 2, repeat: Infinity }}
                        >
                          <div className={`w-10 h-10 rounded-full flex items-center justify-center text-lg ${
                            isActive ? "bg-violet-500/20" : "bg-white/5"
                          }`}>
                            {isActive ? stage.emoji : <stage.icon className="w-4 h-4" />}
                          </div>
                          <span className="text-xs font-medium">{stage.label}</span>
                        </motion.div>
                      );
                    })}
                  </div>
                </div>
              </motion.div>
            </div>

            {/* Rotating Viral Tip Card */}
            <motion.div 
              className="max-w-2xl mx-auto"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
            >
              <div className="rounded-2xl border border-amber-500/20 bg-gradient-to-r from-amber-500/10 to-orange-500/10 p-5">
                <div className="flex items-start gap-4">
                  <div className="w-10 h-10 rounded-xl bg-amber-500/20 flex items-center justify-center flex-shrink-0">
                    <Lightbulb className="w-5 h-5 text-amber-400" />
                  </div>
                  <div className="flex-1">
                    <p className="text-xs text-amber-400/70 uppercase tracking-wide font-medium mb-1">
                      Pro Tip #{currentTipIndex + 1}/{viralTips.length}
                    </p>
                    <AnimatePresence mode="wait">
                      <motion.p
                        key={currentTipIndex}
                        className="text-white/90 text-sm leading-relaxed"
                        initial={{ opacity: 0, x: 20 }}
                        animate={{ opacity: 1, x: 0 }}
                        exit={{ opacity: 0, x: -20 }}
                        transition={{ duration: 0.3 }}
                      >
                        {viralTips[currentTipIndex].text}
                      </motion.p>
                    </AnimatePresence>
                  </div>
                  <div className="flex gap-1">
                    {viralTips.map((_, idx) => (
                      <button
                        key={idx}
                        onClick={() => setCurrentTipIndex(idx)}
                        className={`w-1.5 h-1.5 rounded-full transition-colors ${
                          idx === currentTipIndex ? "bg-amber-400" : "bg-white/20"
                        }`}
                      />
                    ))}
                  </div>
                </div>
              </div>
            </motion.div>

            {/* Interactive Mini-Game Card */}
            <motion.div 
              className="max-w-2xl mx-auto"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
            >
              <div className="rounded-2xl border border-cyan-500/20 bg-gradient-to-br from-cyan-500/10 to-blue-500/10 p-5">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-cyan-500/20 flex items-center justify-center">
                      <MousePointer className="w-5 h-5 text-cyan-400" />
                    </div>
                    <div>
                      <p className="text-white font-medium text-sm">Click Challenge</p>
                      <p className="text-white/50 text-xs">How many times can you click?</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-2xl font-bold text-cyan-400 tabular-nums">{clickCount}</p>
                    <p className="text-xs text-white/40">clicks</p>
                  </div>
                </div>
                
                <motion.button
                  onClick={() => setClickCount(c => c + 1)}
                  className="w-full py-4 rounded-xl bg-gradient-to-r from-cyan-500/20 to-blue-500/20 border border-cyan-500/30 text-cyan-400 font-medium hover:from-cyan-500/30 hover:to-blue-500/30 transition-all active:scale-95"
                  whileTap={{ scale: 0.95 }}
                >
                  <span className="flex items-center justify-center gap-2">
                    <Sparkles className="w-4 h-4" />
                    Tap here while you wait!
                    <Sparkles className="w-4 h-4" />
                  </span>
                </motion.button>

                {clickCount > 0 && (
                  <motion.p 
                    className="text-center text-xs text-white/40 mt-3"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                  >
                    {clickCount < 20 ? "Good start! Keep going! 🔥" :
                     clickCount < 50 ? "You're on fire! 🔥🔥" :
                     clickCount < 100 ? "Incredible speed! ⚡" :
                     "LEGENDARY! You're a clicking machine! 🏆"}
                  </motion.p>
                )}
              </div>
            </motion.div>

            {/* Content Analysis Section */}
            {task?.analysis && (
              <div className="mb-8 rounded-lg border border-zinc-700 bg-zinc-900/50 p-6">
                <h3 className="text-sm font-semibold text-zinc-400 uppercase tracking-wide mb-4">
                  Content Analysis
                </h3>
                {task.analysis.summary && (
                  <div className="mb-4">
                    <p className="text-sm text-zinc-300 leading-relaxed">{task.analysis.summary}</p>
                  </div>
                )}
                {task.analysis.key_topics && task.analysis.key_topics.length > 0 && (
                  <div>
                    <div className="flex flex-wrap gap-2 items-center">
                      <span className="text-xs text-zinc-500 mr-1 self-center">Capítulos:</span>
                      {/* "All" pill */}
                      <span
                        onClick={() => setActiveTopicFilter(null)}
                        className={`px-3 py-1 rounded-full text-xs font-medium border cursor-pointer transition-colors select-none
                          ${activeTopicFilter === null
                            ? "bg-blue-600 text-white border-blue-500"
                            : "bg-zinc-800 text-zinc-400 border-zinc-700 hover:bg-zinc-700"
                          }`}
                      >
                        Todos ({clips.length})
                      </span>
                      {task.analysis.key_topics.map((topic: string) => {
                        const matchCount = clips.filter((c) =>
                          c.text?.toLowerCase().includes(topic.toLowerCase().split(" ")[0])
                        ).length;
                        return (
                          <span
                            key={topic}
                            onClick={() => setActiveTopicFilter(activeTopicFilter === topic ? null : topic)}
                            className={`px-3 py-1 rounded-full text-xs font-medium border cursor-pointer transition-colors select-none
                              ${activeTopicFilter === topic
                                ? "bg-blue-600 text-white border-blue-500"
                                : "bg-blue-900/40 text-blue-300 border-blue-700/50 hover:bg-blue-900/60"
                              }`}
                          >
                            {topic} {matchCount > 0 && `(${matchCount})`}
                          </span>
                        );
                      })}
                    </div>
                    {activeTopicFilter && (
                      <p className="text-xs text-zinc-500 mt-2">
                        Mostrando clips relacionados con <span className="text-blue-400">"{activeTopicFilter}"</span>
                        {" · "}
                        <button onClick={() => setActiveTopicFilter(null)} className="underline hover:text-zinc-300">
                          Ver todos
                        </button>
                      </p>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Live clips grid — shows clips as they render */}
            {clips.length > 0 && (
              <div className="grid gap-6">
                <p className="text-sm text-neutral-500 text-center">
                  {activeTopicFilter
                    ? `${clips.filter((c) =>
                        c.text?.toLowerCase().includes(activeTopicFilter.toLowerCase().split(" ")[0])
                      ).length} clip(s) en "${activeTopicFilter}"`
                    : `${clips.length} clip${clips.length !== 1 ? "s" : ""} ready`}
                </p>
                {clips
                  .filter((clip) => {
                    if (!activeTopicFilter) return true;
                    const keyword = activeTopicFilter.toLowerCase().split(" ")[0];
                    return clip.text?.toLowerCase().includes(keyword);
                  })
                  .map((clip) => (
                    <Card key={clip.id} className="overflow-hidden">
                      <CardContent className="p-0">
                        <div className="flex flex-col lg:flex-row">
                          <div className="relative flex-shrink-0 bg-black rounded-lg overflow-hidden m-3">
                            <DynamicVideoPlayer src={`${apiUrl}${clip.video_url}`} poster="/placeholder-video.jpg" />
                          </div>
                          <div className="p-6 flex-1">
                            <div className="flex items-start justify-between mb-4">
                              <div>
                                <h3 className="font-semibold text-lg text-black mb-1">Clip {clip.clip_order}</h3>
                                <div className="flex items-center gap-2 text-sm text-gray-400">
                                  <span>{clip.start_time} - {clip.end_time}</span>
                                  <span>•</span>
                                  <span>{formatDuration(clip.duration)}</span>
                                </div>
                              </div>
                              <div className="flex items-center gap-2">
                                {clip.virality_score > 0 && (
                                  <Badge className={`${getViralityBgColor(clip.virality_score)} text-white`}>
                                    <Zap className="w-3 h-3 mr-1" />
                                    {clip.virality_score}
                                  </Badge>
                                )}
                                <Badge className={getScoreColor(clip.relevance_score)}>
                                  <Star className="w-3 h-3 mr-1" />
                                  {(clip.relevance_score * 100).toFixed(0)}%
                                </Badge>
                              </div>
                            </div>
                            {clip.text && (
                              <div className="mb-4">
                                <h4 className="font-medium text-black mb-2">Transcript</h4>
                                <p className="text-sm text-gray-300 bg-white/3 p-3 rounded">{clip.text}</p>
                              </div>
                            )}
                            {clip.reasoning && (
                              <div className="mb-4">
                                <h4 className="font-medium text-black mb-2">AI Analysis</h4>
                                <p className="text-sm text-gray-400">{clip.reasoning}</p>
                              </div>
                            )}
                            <div className="flex items-center gap-3 flex-wrap">
                              <div className="flex items-center gap-1" title="Rate this clip">
                                {[1, 2, 3, 4, 5].map((star) => (
                                  <button
                                    key={star}
                                    onClick={() => rateClip(clip.id, star)}
                                    className="p-0.5 transition-transform hover:scale-110 focus:outline-none"
                                    aria-label={`Rate ${star} star${star !== 1 ? "s" : ""}`}
                                  >
                                    <Star
                                      className={`w-5 h-5 ${
                                        star <= (clipRatings[clip.id] ?? clip.user_rating ?? 0)
                                          ? "fill-yellow-400 text-yellow-400"
                                          : "text-gray-300"
                                      }`}
                                    />
                                  </button>
                                ))}
                              </div>
                              <Button size="sm" variant="outline" asChild>
                                <a href={`${apiUrl}${clip.video_url}`} download={clip.filename}>
                                  <Download className="w-4 h-4" />
                                  Download
                                </a>
                              </Button>
                            </div>
                          </div>
                        </div>
                      </CardContent>
                    </Card>
                  ))}
              </div>
            )}
          </div>
        ) : !task ? (
          <div className="flex flex-col items-center justify-center min-h-[50vh] py-16">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 bg-neutral-300 rounded-full animate-[pulse_1.4s_ease-in-out_infinite]" />
              <span className="w-2 h-2 bg-neutral-300 rounded-full animate-[pulse_1.4s_ease-in-out_0.2s_infinite]" />
              <span className="w-2 h-2 bg-neutral-300 rounded-full animate-[pulse_1.4s_ease-in-out_0.4s_infinite]" />
            </div>
          </div>
        ) : task?.status === "error" ? (
          <Card>
            <CardContent className="p-8 text-center">
              <div className="text-red-600 mb-4">
                <AlertCircle className="w-12 h-12 mx-auto mb-2" />
                <h2 className="text-xl font-semibold">Processing Failed</h2>
              </div>
              <p className="text-gray-400 mb-4">There was an error processing your video. Please try again.</p>
              <Link href="/">
                <Button>
                  <ArrowLeft className="w-4 h-4" />
                  Back to Home
                </Button>
              </Link>
            </CardContent>
          </Card>
        ) : clips.length === 0 ? (
          <Card>
            <CardContent className="p-8 text-center">
              {task?.status === "completed" ? (
                <>
                  <div className="text-yellow-600 mb-4">
                    <AlertCircle className="w-12 h-12 mx-auto mb-2" />
                    <h2 className="text-xl font-semibold">No Clips Generated</h2>
                  </div>
                  <p className="text-gray-400 mb-4">
                    The task completed but no clips were generated. The video may not have had suitable content for
                    clipping.
                  </p>
                  <Link href="/">
                    <Button>
                      <ArrowLeft className="w-4 h-4" />
                      Try Another Video
                    </Button>
                  </Link>
                </>
              ) : (
                <>
                  <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center mx-auto mb-4">
                    <Clock className="w-8 h-8 text-blue-500 animate-pulse" />
                  </div>
                  <h2 className="text-xl font-semibold text-black mb-2">Still Generating...</h2>
                  <p className="text-gray-400">
                    Your clips are being generated. This page will refresh automatically when they&apos;re ready.
                  </p>
                </>
              )}
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-6">
            <div className="flex items-center justify-between">
              <Button variant="outline" size="sm" onClick={() => setSettingsSheetOpen(true)}>
                <Settings2 className="w-4 h-4" />
                Project Settings
              </Button>
              {selectedClipIds.length >= 2 && (
                <Button variant="outline" size="sm" onClick={handleMergeClips}>
                  <GitMerge className="w-4 h-4" />
                  Merge Selected ({selectedClipIds.length})
                </Button>
              )}
            </div>

            <Sheet open={settingsSheetOpen} onOpenChange={setSettingsSheetOpen}>
              <SheetContent side="right" className="sm:max-w-md overflow-y-auto">
                <SheetHeader>
                  <SheetTitle className="flex items-center gap-2">
                    <Settings2 className="w-4 h-4" />
                    Project Settings
                  </SheetTitle>
                  <SheetDescription>
                    Configure font, caption, and B-roll settings for this task&apos;s clips.
                  </SheetDescription>
                </SheetHeader>

                <div className="space-y-5 px-4">
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-gray-500">Font</label>
                    <Select value={projectFontFamily} onValueChange={setProjectFontFamily}>
                      <SelectTrigger>
                        <SelectValue placeholder="Font family" />
                      </SelectTrigger>
                      <SelectContent>
                        {availableFonts.map((font) => (
                          <SelectItem key={font.name} value={font.name}>
                            <span className="flex items-center gap-2">
                              <Type className="w-3 h-3" />
                              {font.display_name}
                            </span>
                          </SelectItem>
                        ))}
                        {availableFonts.length === 0 && (
                          <SelectItem value="TikTokSans-Regular">TikTok Sans Regular</SelectItem>
                        )}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-gray-500">Size</label>
                    <Input
                      type="number"
                      min={12}
                      max={72}
                      value={projectFontSize}
                      onChange={(e) => setProjectFontSize(e.target.value)}
                      placeholder="Font size"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-gray-500">Color</label>
                    <div className="flex items-center gap-2">
                      <input
                        type="color"
                        value={projectFontColor}
                        onChange={(e) => setProjectFontColor(e.target.value)}
                        className="h-9 w-9 rounded border border-gray-300 cursor-pointer"
                      />
                      <Input
                        value={projectFontColor}
                        onChange={(e) => setProjectFontColor(e.target.value)}
                        placeholder="#FFFFFF"
                      />
                    </div>
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-gray-500">Caption Template</label>
                    <Select value={projectCaptionTemplate} onValueChange={setProjectCaptionTemplate}>
                      <SelectTrigger>
                        <SelectValue>
                          {availableTemplates.find((t) => t.id === projectCaptionTemplate)?.name || "Select style"}
                        </SelectValue>
                      </SelectTrigger>
                      <SelectContent>
                        {availableTemplates.map((template) => (
                          <SelectItem key={template.id} value={template.id}>
                            <div>
                              <div className="font-medium">{template.name}</div>
                              <div className="text-xs text-gray-500">{template.description}</div>
                            </div>
                          </SelectItem>
                        ))}
                        {availableTemplates.length === 0 && <SelectItem value="default">Default</SelectItem>}
                      </SelectContent>
                    </Select>
                    {/* P2.6: hint about auto platform selection */}
                    {projectCaptionTemplate === "default" && (
                      <p className="text-[10px] text-gray-400 leading-tight">
                        ✨ Auto-selects per platform: TikTok → Viral Pro / Hormozi, Reels → TikTok / Subtitles, Shorts →
                        Subtitles
                      </p>
                    )}
                  </div>

                  <label className="flex items-center gap-2 text-sm text-gray-300">
                    <input
                      type="checkbox"
                      checked={projectIncludeBroll}
                      onChange={(e) => setProjectIncludeBroll(e.target.checked)}
                      className="rounded"
                    />
                    Include B-roll
                  </label>
                </div>

                <SheetFooter>
                  <Button
                    className="w-full"
                    onClick={() => {
                      handleApplyProjectSettings();
                      setSettingsSheetOpen(false);
                    }}
                    disabled={isApplyingSettings}
                  >
                    {isApplyingSettings ? "Applying..." : "Apply to All Clips"}
                  </Button>
                </SheetFooter>
              </SheetContent>
            </Sheet>

            {clips.map((clip) => (
              <Card key={clip.id} className="overflow-hidden glass-card hover:shadow-xl transition-shadow duration-300">
                <CardContent className="p-0">
                  <div className="flex flex-col lg:flex-row">
                    {/* Video Player */}
                    <div className="relative flex-shrink-0 bg-black rounded-lg overflow-hidden m-3">
                      <DynamicVideoPlayer
                        src={`${apiUrl}${clip.video_url}`}
                        poster={clip.thumbnail_url ? `${apiUrl}${clip.thumbnail_url}` : "/placeholder-video.jpg"}
                      />
                    </div>

                    {/* Clip Details */}
                    <div className="p-6 flex-1">
                      <div className="flex items-start justify-between mb-4">
                        <div className="flex-1">
                          <label className="flex items-center gap-2 text-xs text-gray-400 mb-2">
                            <input
                              type="checkbox"
                              checked={selectedClipIds.includes(clip.id)}
                              onChange={() => handleToggleClipSelection(clip.id)}
                            />
                            Select for merge
                          </label>
                          <h3 className="font-semibold text-lg text-black mb-1">Clip {clip.clip_order}</h3>
                          <div className="flex items-center gap-2 text-sm text-gray-400">
                            <span>
                              {clip.start_time} - {clip.end_time}
                            </span>
                            <span>•</span>
                            <span>{formatDuration(clip.duration)}</span>
                          </div>
                        </div>
                        <div className="flex flex-col items-end gap-2">
                          <div className="flex items-center gap-2">
                            {clip.virality_score > 0 && (
                              <Badge className={`${getViralityBgColor(clip.virality_score)} text-white shadow-lg`}>
                                <Zap className="w-3 h-3 mr-1" />
                                {clip.virality_score}
                              </Badge>
                            )}
                            {/* V3 Intensity Badge */}
                            {clip.intensity !== undefined && (
                              <Badge variant="outline" className={`${getIntensityColor(clip.intensity)} glass-badge shadow-sm`}>
                                <TrendingUp className="w-3 h-3 mr-1" />
                                {(clip.intensity * 10).toFixed(1)} Intensity
                              </Badge>
                            )}
                            <Badge className={getScoreColor(clip.relevance_score)}>
                              <Star className="w-3 h-3 mr-1" />
                              {(clip.relevance_score * 100).toFixed(0)}%
                            </Badge>
                            {/* P2.4: Hook preview score badge */}
                            {clip.hook_preview_score !== undefined && clip.hook_preview_score > 0 && (
                              <Badge
                                variant="outline"
                                className={`${getHookPreviewColor(clip.hook_preview_score)} border-0 shadow-sm`}
                                title="Hook Preview Score — how likely the opening seconds are to stop scrolling"
                              >
                                🎣 {clip.hook_preview_score}
                              </Badge>
                            )}
                            {/* P3.5: A/B variant badge */}
                            {clip.variant && (
                              <Badge
                                variant="outline"
                                className="bg-blue-50 text-blue-700 border-blue-200 shadow-sm font-semibold"
                                title={`A/B variant ${clip.variant} — different caption template for split testing`}
                              >
                                A/B {clip.variant}
                              </Badge>
                            )}
                          </div>
                          {clip.bgm_style && (
                            <Badge variant="secondary" className="text-[10px] h-5 bg-purple-50 text-purple-700 border-purple-100">
                              🎵 {clip.bgm_style}
                            </Badge>
                          )}
                        </div>
                      </div>

                      {/* Virality Score Breakdown */}
                      {clip.virality_score > 0 && (
                        <div className="mb-4 p-3 bg-white/3 rounded-lg">
                          <div className="flex items-center justify-between mb-3">
                            <h4 className="font-medium text-black text-sm flex items-center gap-1">
                              <Zap className="w-4 h-4" />
                              Virality Score
                            </h4>
                            <span className={`text-lg font-bold ${getViralityColor(clip.virality_score)}`}>
                              {clip.virality_score}/100
                            </span>
                          </div>

                          <div className="grid grid-cols-2 gap-3 text-xs">
                            {/* Hook Score */}
                            <div className="space-y-1">
                              <div className="flex items-center justify-between">
                                <span className="flex items-center gap-1 text-gray-400">
                                  <MessageSquare className="w-3 h-3" />
                                  Hook
                                </span>
                                <span className="font-medium">{clip.hook_score}/25</span>
                              </div>
                              <Progress value={(clip.hook_score / 25) * 100} className="h-1.5" />
                            </div>

                            {/* Engagement Score */}
                            <div className="space-y-1">
                              <div className="flex items-center justify-between">
                                <span className="flex items-center gap-1 text-gray-400">
                                  <TrendingUp className="w-3 h-3" />
                                  Engagement
                                </span>
                                <span className="font-medium">{clip.engagement_score}/25</span>
                              </div>
                              <Progress value={(clip.engagement_score / 25) * 100} className="h-1.5" />
                            </div>

                            {/* Value Score */}
                            <div className="space-y-1">
                              <div className="flex items-center justify-between">
                                <span className="flex items-center gap-1 text-gray-400">
                                  <Star className="w-3 h-3" />
                                  Value
                                </span>
                                <span className="font-medium">{clip.value_score}/25</span>
                              </div>
                              <Progress value={(clip.value_score / 25) * 100} className="h-1.5" />
                            </div>

                            {/* Shareability Score */}
                            <div className="space-y-1">
                              <div className="flex items-center justify-between">
                                <span className="flex items-center gap-1 text-gray-400">
                                  <Share2 className="w-3 h-3" />
                                  Shareability
                                </span>
                                <span className="font-medium">{clip.shareability_score}/25</span>
                              </div>
                              <Progress value={(clip.shareability_score / 25) * 100} className="h-1.5" />
                            </div>
                          </div>

                          {clip.hook_type && clip.hook_type !== "none" && (
                            <div className="mt-3 pt-2 border-t">
                              <Badge variant="outline" className="text-xs">
                                {getHookTypeLabel(clip.hook_type)}
                              </Badge>
                            </div>
                          )}
                        </div>
                      )}

                      {clip.text && (
                        <div className="mb-4">
                          <h4 className="font-medium text-black mb-2">Transcript</h4>
                          <p className="text-sm text-gray-300 bg-white/3 p-3 rounded">{clip.text}</p>
                        </div>
                      )}

                      {/* Phase 9: Creative Engine Panel */}
                      {clip.creative_enhanced && (
                        <div className="mb-4 p-4 bg-gradient-to-br from-cyan-950/60 to-purple-950/60 border border-cyan-800/40 rounded-lg">
                          <div className="flex items-center justify-between mb-3">
                            <div className="flex items-center gap-2">
                              <Wand2 className="w-4 h-4 text-cyan-400" />
                              <h4 className="font-bold text-sm text-cyan-300 uppercase tracking-wider">Creative Engine</h4>
                            </div>
                            {clip.preset_used && (
                              <span className="text-xs bg-cyan-900/60 text-cyan-300 border border-cyan-700/40 rounded-full px-2 py-0.5 font-mono">
                                {clip.preset_used}
                              </span>
                            )}
                          </div>

                          {/* Effect flags */}
                          <div className="grid grid-cols-2 gap-2 mb-3">
                            <div className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded ${
                              clip.hook_reorder_applied ? "bg-emerald-900/40 text-emerald-300" : "bg-white/5 text-gray-500"
                            }`}>
                              <Film className="w-3 h-3" />
                              Hook Flash {clip.hook_reorder_applied ? "✓" : "—"}
                            </div>
                            <div className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded ${
                              clip.zoom_punch_applied ? "bg-emerald-900/40 text-emerald-300" : "bg-white/5 text-gray-500"
                            }`}>
                              <Layers className="w-3 h-3" />
                              Zoom Punch {clip.zoom_punch_applied ? "✓" : "—"}
                            </div>
                            <div className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded ${
                              clip.loudnorm_applied ? "bg-emerald-900/40 text-emerald-300" : "bg-white/5 text-gray-500"
                            }`}>
                              <Volume2 className="w-3 h-3" />
                              EBU R128 {clip.loudnorm_applied ? "✓" : "—"}
                            </div>
                            <div className={`flex items-center gap-1.5 text-xs px-2 py-1 rounded ${
                              clip.color_grade_applied ? "bg-emerald-900/40 text-emerald-300" : "bg-white/5 text-gray-500"
                            }`}>
                              <Sparkles className="w-3 h-3" />
                              Color Grade {clip.color_grade_applied ? "✓" : "—"}
                            </div>
                          </div>

                          {/* Pacing + Emotion sub-scores */}
                          {(clip.pacing_score != null || clip.emotion_score != null) && (
                            <div className="grid grid-cols-2 gap-2 mb-3">
                              {clip.pacing_score != null && (
                                <div className="space-y-1">
                                  <div className="flex items-center justify-between text-xs">
                                    <span className="text-gray-400 flex items-center gap-1"><Clock className="w-3 h-3" />Pacing</span>
                                    <span className="text-cyan-300 font-medium">{Math.round(clip.pacing_score)}</span>
                                  </div>
                                  <Progress value={clip.pacing_score} className="h-1" />
                                </div>
                              )}
                              {clip.emotion_score != null && (
                                <div className="space-y-1">
                                  <div className="flex items-center justify-between text-xs">
                                    <span className="text-gray-400 flex items-center gap-1"><Zap className="w-3 h-3" />Emotion</span>
                                    <span className="text-purple-300 font-medium">{Math.round(clip.emotion_score)}</span>
                                  </div>
                                  <Progress value={clip.emotion_score} className="h-1" />
                                </div>
                              )}
                            </div>
                          )}

                          {/* B-roll + SFX counts */}
                          <div className="flex flex-wrap gap-3 mb-3 text-xs">
                            {clip.broll_overlays !== undefined && clip.broll_overlays > 0 && (
                              <span className="text-purple-300">🎬 {clip.broll_overlays} B-roll{clip.broll_overlays !== 1 ? "s" : ""}</span>
                            )}
                            {clip.sfx_injected !== undefined && clip.sfx_injected > 0 && (
                              <span className="text-cyan-300">🔊 {clip.sfx_injected} SFX</span>
                            )}
                            {clip.smart_edit_decisions !== undefined && clip.smart_edit_decisions > 0 && (
                              <span className="text-amber-300">✂️ {clip.smart_edit_decisions} edit{clip.smart_edit_decisions !== 1 ? "s" : ""}{clip.smart_edit_time_saved ? ` · ${clip.smart_edit_time_saved.toFixed(1)}s saved` : ""}</span>
                            )}
                            {clip.text_pops_applied !== undefined && clip.text_pops_applied > 0 && (
                              <span className="text-pink-300">💥 {clip.text_pops_applied} keyword pop{clip.text_pops_applied !== 1 ? "s" : ""}</span>
                            )}
                          </div>

                          {clip.hook_text && (
                            <div className="text-xs text-cyan-200 italic mb-2">Hook: &ldquo;{clip.hook_text}&rdquo;</div>
                          )}

                          {/* Improvement suggestions */}
                          {clip.improvements && clip.improvements.length > 0 && (
                            <div className="mb-3">
                              <p className="text-xs text-amber-400 font-medium mb-1">💡 Suggestions</p>
                              <ul className="space-y-0.5">
                                {clip.improvements.slice(0, 3).map((imp, i) => (
                                  <li key={i} className="text-xs text-amber-200/80">• {imp}</li>
                                ))}
                              </ul>
                            </div>
                          )}

                          <div className={`flex items-center gap-1.5 text-xs font-medium ${
                            clip.qa_passed ? "text-emerald-400" : "text-amber-400"
                          }`}>
                            {clip.qa_passed
                              ? <><CheckCircle2 className="w-3.5 h-3.5" /> QA Passed</>
                              : <><XCircle className="w-3.5 h-3.5" /> QA Issues: {(clip.qa_issues || []).join(", ")}</>
                            }
                          </div>
                        </div>
                      )}

                      {/* Phase 10: Viral Polish panel */}
                      {(clip.cta_overlay_applied || clip.emoji_overlays_applied || (clip.variants && clip.variants.length > 0)) && (
                        <div className="mb-4 p-4 bg-gradient-to-br from-rose-950/50 to-orange-950/50 border border-rose-800/40 rounded-lg">
                          <div className="flex items-center gap-2 mb-3">
                            <Sparkles className="w-4 h-4 text-rose-400" />
                            <h4 className="font-bold text-sm text-rose-300 uppercase tracking-wider">Viral Polish</h4>
                          </div>

                          {/* Applied effects badges */}
                          <div className="flex flex-wrap gap-2 mb-3">
                            {clip.cta_overlay_applied && (
                              <span className="flex items-center gap-1 text-xs bg-orange-900/50 text-orange-300 border border-orange-700/40 rounded-full px-2 py-0.5">
                                <Target className="w-3 h-3" /> CTA Overlay
                              </span>
                            )}
                            {clip.emoji_overlays_applied && (
                              <span className="flex items-center gap-1 text-xs bg-pink-900/50 text-pink-300 border border-pink-700/40 rounded-full px-2 py-0.5">
                                😀 Emoji Cues
                              </span>
                            )}
                          </div>

                          {/* A/B Variants */}
                          {clip.variants && clip.variants.length > 0 && (
                            <div>
                              <p className="text-xs text-rose-400 font-medium mb-2 flex items-center gap-1">
                                <Shuffle className="w-3 h-3" /> A/B Variants ({clip.variants.length})
                              </p>
                              <div className="space-y-1.5">
                                {clip.variants.map((v, vi) => (
                                  <div key={vi} className="flex items-center justify-between bg-black/30 rounded px-2 py-1.5">
                                    <div className="flex items-center gap-2">
                                      {v.type === "caption_style" ? (
                                        <Subtitles className="w-3 h-3 text-cyan-400 flex-shrink-0" />
                                      ) : (
                                        <Music className="w-3 h-3 text-purple-400 flex-shrink-0" />
                                      )}
                                      <span className="text-xs text-gray-300 truncate max-w-[160px]" title={v.label}>{v.label}</span>
                                    </div>
                                    <a
                                      href={`${apiUrl}/clips/${clip.video_url.split("/")[2]}/${v.path.split("/").pop()}`}
                                      download
                                      className="text-xs text-rose-400 hover:text-rose-300 font-medium ml-2 flex-shrink-0"
                                    >
                                      <Download className="w-3 h-3" />
                                    </a>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      {/* ViraClip V3: Viral Intelligence & Tactical Tips */}
                      {(clip.strategic_advice || clip.conversion_tips) && (
                        <div className="mb-4 p-4 bg-blue-50/50 border border-blue-100 rounded-lg backdrop-blur-sm">
                          <div className="flex items-center gap-2 mb-3 text-blue-800">
                            <BrainCircuit className="w-5 h-5 text-blue-600" />
                            <h4 className="font-bold text-sm tracking-tight uppercase">Viral Intelligence</h4>
                          </div>
                          <div className="space-y-3">
                            {clip.strategic_advice && (
                              <div className="flex gap-3">
                                <div className="mt-1 p-1 bg-blue-100 rounded-md">
                                  <Target className="w-3.5 h-3.5 text-blue-700" />
                                </div>
                                <div>
                                  <span className="text-[10px] font-bold text-blue-400 uppercase leading-none block mb-1">Psychological Hook</span>
                                  <p className="text-sm text-blue-900 leading-relaxed font-medium">
                                    {clip.strategic_advice}
                                  </p>
                                </div>
                              </div>
                            )}
                            {clip.conversion_tips && (
                              <div className="flex gap-3 pt-2 border-t border-blue-100/50">
                                <div className="mt-1 p-1 bg-green-100 rounded-md">
                                  <MousePointer className="w-3.5 h-3.5 text-green-700" />
                                </div>
                                <div>
                                  <span className="text-[10px] font-bold text-green-500 uppercase leading-none block mb-1">Conversion Tactic</span>
                                  <p className="text-sm text-gray-300 leading-relaxed italic">
                                    {clip.conversion_tips}
                                  </p>
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      {clip.reasoning && (
                        <div className="mb-4">
                          <h4 className="font-medium text-black mb-2">AI Analysis</h4>
                          <p className="text-sm text-gray-400">{clip.reasoning}</p>
                        </div>
                      )}

                      {/* P3: Social Copy Panel */}
                      {(clip.social_title || clip.social_description || (clip.suggested_hashtags && clip.suggested_hashtags.length > 0)) && (
                        <div className="mb-4 p-3 bg-gradient-to-r from-purple-50 to-pink-50 border border-purple-100 rounded-lg">
                          <h4 className="font-medium text-purple-800 mb-2 text-sm flex items-center gap-1">
                            📱 Social Media Copy
                          </h4>
                          {clip.social_title && (
                            <div className="mb-2">
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-xs text-gray-500 font-medium">TITLE</span>
                                <button
                                  onClick={() => navigator.clipboard.writeText(clip.social_title!)}
                                  className="text-xs text-purple-400 hover:text-purple-800 font-medium"
                                  title="Copy title"
                                >
                                  Copy
                                </button>
                              </div>
                              <p className="text-sm font-semibold text-gray-800 bg-white rounded px-2 py-1 border border-purple-100">{clip.social_title}</p>
                            </div>
                          )}
                          {clip.social_description && (
                            <div className="mb-2">
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-xs text-gray-500 font-medium">DESCRIPTION</span>
                                <button
                                  onClick={() => navigator.clipboard.writeText(clip.social_description!)}
                                  className="text-xs text-purple-400 hover:text-purple-800 font-medium"
                                  title="Copy description"
                                >
                                  Copy
                                </button>
                              </div>
                              <p className="text-sm text-gray-300 bg-white rounded px-2 py-1 border border-purple-100">{clip.social_description}</p>
                            </div>
                          )}
                          {clip.suggested_hashtags && clip.suggested_hashtags.length > 0 && (
                            <div>
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-xs text-gray-500 font-medium">HASHTAGS</span>
                                <button
                                  onClick={() => navigator.clipboard.writeText((clip.suggested_hashtags || []).join(' '))}
                                  className="text-xs text-purple-400 hover:text-purple-800 font-medium"
                                  title="Copy hashtags"
                                >
                                  Copy
                                </button>
                              </div>
                              <div className="flex flex-wrap gap-1">
                                {clip.suggested_hashtags.map((tag, idx) => (
                                  <span key={idx} className="text-xs bg-purple-100 text-purple-700 rounded-full px-2 py-0.5 cursor-pointer hover:bg-purple-200"
                                    onClick={() => navigator.clipboard.writeText(tag)}>
                                    {tag}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}

                      <div className="flex items-center gap-1 mb-3" title="Rate this clip">
                        {[1, 2, 3, 4, 5].map((star) => (
                          <button
                            key={star}
                            onClick={() => rateClip(clip.id, star)}
                            className="p-0.5 transition-transform hover:scale-110 focus:outline-none"
                            aria-label={`Rate ${star} star${star !== 1 ? 's' : ''}`}
                          >
                            <Star
                              className={`w-5 h-5 ${
                                star <= (clipRatings[clip.id] ?? clip.user_rating ?? 0)
                                  ? "fill-yellow-400 text-yellow-400"
                                  : "text-gray-300"
                              }`}
                            />
                          </button>
                        ))}
                      </div>

                      <div className="flex gap-2">
                        <Button size="sm" variant="outline" asChild>
                          <a href={`${apiUrl}${clip.video_url}`} download={clip.filename}>
                            <Download className="w-4 h-4" />
                            Download
                          </a>
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => handleExportClip(clip.id, clip.filename)}>
                          <Download className="w-4 h-4" />
                          Export
                        </Button>
                        <Select value={exportPreset} onValueChange={setExportPreset}>
                          <SelectTrigger className="h-8 w-28">
                            <SelectValue placeholder="Preset" />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="tiktok">TikTok</SelectItem>
                            <SelectItem value="reels">Reels</SelectItem>
                            <SelectItem value="shorts">Shorts</SelectItem>
                          </SelectContent>
                        </Select>
                        <Button
                          size="sm"
                          variant="outline"
                          className="text-red-600 hover:text-red-700 hover:bg-red-50 border-red-200"
                          onClick={() => setDeletingClipId(clip.id)}
                        >
                          <Trash2 className="w-4 h-4" />
                          Delete
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => {
                            setEditingClipId(editingClipId === clip.id ? null : clip.id);
                            setCaptionText(clip.text || "");
                          }}
                        >
                          <Scissors className="w-4 h-4" />
                          Edit
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className={musicAppliedClipId === clip.id ? "border-green-500 text-green-400" : ""}
                          onClick={() => setMusicPickerClipId(musicPickerClipId === clip.id ? null : clip.id)}
                        >
                          <Music className="w-4 h-4" />
                          {musicAppliedClipId === clip.id ? "Applied!" : "Music"}
                        </Button>
                      </div>

                      {musicPickerClipId === clip.id && (
                        <div className="mt-3 p-3 border border-purple-500/30 rounded-lg bg-purple-500/5 flex flex-wrap gap-2 items-center">
                          <Select value={selectedTrack} onValueChange={setSelectedTrack}>
                            <SelectTrigger className="h-8 w-48">
                              <SelectValue placeholder="Choose a track…" />
                            </SelectTrigger>
                            <SelectContent>
                              {musicTracks.map(t => (
                                <SelectItem key={t.id} value={t.id}>{t.label}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <Button
                            size="sm"
                            disabled={!selectedTrack || isApplyingMusic}
                            onClick={() => handleApplyMusic(clip.id)}
                          >
                            {isApplyingMusic ? <Loader2 className="w-4 h-4 animate-spin" /> : <Music className="w-4 h-4" />}
                            {isApplyingMusic ? "Applying…" : "Apply"}
                          </Button>
                          <span className="text-xs text-gray-500">Music is mixed with ducking — voice stays clear</span>
                        </div>
                      )}

                      {editingClipId === clip.id && (
                        <div className="mt-4 p-3 border rounded-lg space-y-3 bg-white/3">
                          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                            <Input
                              value={startOffset}
                              onChange={(e) => setStartOffset(e.target.value)}
                              placeholder="Start trim (sec)"
                            />
                            <Input
                              value={endOffset}
                              onChange={(e) => setEndOffset(e.target.value)}
                              placeholder="End trim (sec)"
                            />
                            <Button size="sm" onClick={() => handleTrimClip(clip.id)}>
                              <Scissors className="w-4 h-4" />
                              Trim
                            </Button>
                          </div>
                          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                            <Input
                              value={splitTime}
                              onChange={(e) => setSplitTime(e.target.value)}
                              placeholder="Split at (sec)"
                            />
                            <Button size="sm" variant="outline" onClick={() => handleSplitClip(clip.id)}>
                              <SplitSquareVertical className="w-4 h-4" />
                              Split
                            </Button>
                            <Button size="sm" variant="outline" onClick={() => handleTrimClip(clip.id)}>
                              <RefreshCw className="w-4 h-4" />
                              Regenerate
                            </Button>
                          </div>
                          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
                            <Input
                              value={captionText}
                              onChange={(e) => setCaptionText(e.target.value)}
                              placeholder="Caption text"
                            />
                            <Select value={captionPosition} onValueChange={setCaptionPosition}>
                              <SelectTrigger>
                                <SelectValue placeholder="Caption position" />
                              </SelectTrigger>
                              <SelectContent>
                                <SelectItem value="top">Top</SelectItem>
                                <SelectItem value="middle">Middle</SelectItem>
                                <SelectItem value="bottom">Bottom</SelectItem>
                              </SelectContent>
                            </Select>
                            <Input
                              value={highlightWords}
                              onChange={(e) => setHighlightWords(e.target.value)}
                              placeholder="Highlights: word1, word2"
                            />
                          </div>
                          <Button size="sm" variant="outline" onClick={() => handleUpdateCaptions(clip.id)}>
                            <Subtitles className="w-4 h-4" />
                            Update Captions
                          </Button>
                        </div>
                      )}

                      {/* P3.1: AI Refine panel */}
                      <div className="mt-3 border border-purple-500/20 rounded-lg bg-purple-500/5">
                        <button
                          className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium text-purple-300 hover:bg-purple-500/10 rounded-lg transition-colors"
                          onClick={() => {
                            setRefiningClipId(refiningClipId === clip.id ? null : clip.id);
                            setRefineResult(null);
                          }}
                        >
                          <Sparkles className="w-4 h-4" />
                          AI Refine
                          <span className="ml-auto text-xs text-purple-400">
                            {refiningClipId === clip.id ? "▲" : "▼"}
                          </span>
                        </button>
                        {refiningClipId === clip.id && (
                          <div className="px-3 pb-3 space-y-2">
                            <p className="text-xs text-purple-400">
                              Describe what you want to change: <em>"trim 3 seconds from the start"</em>, <em>"make the hook more energetic"</em>, <em>"use the subtitles template"</em>…
                            </p>
                            <div className="flex gap-2">
                              <Input
                                value={refineInstruction}
                                onChange={(e) => setRefineInstruction(e.target.value)}
                                onKeyDown={(e) => e.key === "Enter" && !isRefining && handleRefineClip(clip.id)}
                                placeholder="e.g. Remove the first 2 seconds"
                                className="text-sm"
                              />
                              <Button
                                size="sm"
                                onClick={() => handleRefineClip(clip.id)}
                                disabled={isRefining || !refineInstruction.trim()}
                                className="bg-purple-600 hover:bg-purple-700 text-white shrink-0"
                              >
                                {isRefining ? (
                                  <RefreshCw className="w-4 h-4 animate-spin" />
                                ) : (
                                  <Send className="w-4 h-4" />
                                )}
                              </Button>
                            </div>
                            {refineResult && (
                              <div className={`text-xs rounded p-2 ${refineResult.action === "error" ? "bg-red-500/10 text-red-400 border border-red-500/30" : "bg-green-500/10 text-green-400 border border-green-500/30"}`}>
                                <span className="font-semibold capitalize">
                                  {refineResult.action === "noop" ? "No changes needed" : refineResult.action === "error" ? "Error" : `✓ ${refineResult.action.replace("_", " ")}`}
                                </span>
                                {refineResult.reasoning && (
                                  <span className="ml-1 text-current/80">— {refineResult.reasoning}</span>
                                )}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </div>

      {/* Delete Task Confirmation Dialog */}
      <AlertDialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Generation</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this generation? This will permanently delete all clips and cannot be
              undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={handleDeleteTask} className="bg-red-600 hover:bg-red-700">
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}