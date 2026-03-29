"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
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
  MousePointer2,
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

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
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
        void fetchTaskStatus().then(() => triggerAutoRefresh());
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
          void fetchTaskStatus().then(() => triggerAutoRefresh());
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
  }, [params.id, task?.status, fetchTaskStatus, taskApiUrl, triggerAutoRefresh]); // Re-run when task status changes

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
    return "bg-gray-200 text-gray-600";
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
      <div className="min-h-screen bg-white p-4">
        <div className="max-w-6xl mx-auto">
          <div className="mb-6">
            <Skeleton className="h-8 w-48 mb-2" />
            <Skeleton className="h-4 w-96" />
          </div>
          <div className="grid gap-6">
            {[1, 2, 3].map((i) => (
              <Card key={i}>
                <CardContent className="p-6">
                  <Skeleton className="h-48 w-full mb-4" />
                  <Skeleton className="h-4 w-full mb-2" />
                  <Skeleton className="h-4 w-3/4" />
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-white p-4">
        <div className="max-w-6xl mx-auto">
          <Alert>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
          <Link href="/" className="mt-4 inline-block">
            <Button variant="outline">
              <ArrowLeft className="w-4 h-4" />
              Back to Home
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-white">
      {/* Header */}
      <div className="border-b bg-white">
        <div className="max-w-6xl mx-auto px-4 py-6">
          <div className="flex items-center gap-4 mb-4">
            <Link href="/">
              <Button variant="ghost" size="sm">
                <ArrowLeft className="w-4 h-4" />
                Back
              </Button>
            </Link>
          </div>

          {task && (
            <div>
              <div className="flex items-center gap-3 mb-2">
                {isEditing ? (
                  <div className="flex items-center gap-2 flex-1">
                    <Input
                      value={editedTitle}
                      onChange={(e) => setEditedTitle(e.target.value)}
                      className="text-2xl font-bold h-auto py-1"
                      autoFocus
                    />
                    <Button size="sm" onClick={handleEditTitle} disabled={!editedTitle.trim()}>
                      <Check className="w-4 h-4" />
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setIsEditing(false);
                        setEditedTitle(task.source_title);
                      }}
                    >
                      <X className="w-4 h-4" />
                    </Button>
                  </div>
                ) : (
                  <>
                    <h1 className={`text-2xl font-bold text-black ${task.status === "processing" || task.status === "queued" ? "shimmer" : ""}`}>
                      <span className="text-blue-600">ViraClip</span> Studio
                    </h1>
                    <div className="flex items-center gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          setIsEditing(true);
                          setEditedTitle(task.source_title);
                        }}
                      >
                        <Edit2 className="w-4 h-4" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-red-600 hover:text-red-700 hover:bg-red-50"
                        onClick={() => setShowDeleteDialog(true)}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </>
                )}
              </div>
              <div className="flex items-center gap-4 text-sm text-gray-600">
                <Badge variant="outline" className="capitalize">
                  {task.source_type}
                </Badge>
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span className="flex items-center gap-1 cursor-default">
                        <Clock className="w-4 h-4" />
                        {new Date(task.created_at).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" })}
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>
                      {new Date(task.created_at).toLocaleString(undefined, {
                        year: "numeric",
                        month: "long",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                        timeZoneName: "short",
                      })}
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
                {task.status === "completed" ? (
                  <span>
                    {clips.length} {clips.length === 1 ? "clip" : "clips"} generated
                  </span>
                ) : task.status === "processing" ? (
                  <div className="relative group">
                    <Badge className="bg-blue-100 text-blue-800 cursor-default shimmer">Processing</Badge>
                    <div className="absolute top-full mt-2 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-md border bg-popover px-3 py-1.5 text-sm text-popover-foreground shadow-md opacity-0 scale-95 transition-all group-hover:opacity-100 group-hover:scale-100 pointer-events-none">
                      🔍&nbsp;&nbsp;We&apos;re currently processing your video. Check back in a couple minutes.
                    </div>
                  </div>
                ) : task.status === "queued" ? (
                  <Badge className="bg-yellow-100 text-yellow-800">Queued</Badge>
                ) : (
                  <Badge variant="outline" className="capitalize">
                    {task.status}
                  </Badge>
                )}
                {task.status === "completed" && clips.length > 0 && (
                  <Link href={`/tasks/${task.id}/edit`}>
                    <Button size="sm" variant="outline">
                      <Clapperboard className="w-4 h-4" />
                      Open Editor
                    </Button>
                  </Link>
                )}
                {(task.status === "queued" || task.status === "processing") && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      await fetch(`${taskApiUrl}/${task.id}/cancel`, {
                        method: "POST",
                      });
                      await fetchTaskStatus();
                    }}
                  >
                    Cancel
                  </Button>
                )}
                {(task.status === "cancelled" || task.status === "error") && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={async () => {
                      await fetch(`${taskApiUrl}/${task.id}/resume`, {
                        method: "POST",
                      });
                      await fetchTaskStatus();
                    }}
                  >
                    Resume
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-6xl mx-auto px-4 py-8">
        {task?.status === "processing" || task?.status === "queued" ? (
          <div className="space-y-8">
            {/* Progress indicator */}
            <div className="flex flex-col items-center py-8">
              {/* Minimal animated dots */}
              <div className="relative group flex items-center gap-1.5 mb-8 cursor-default">
                <span className="w-2 h-2 bg-neutral-800 rounded-full animate-[pulse_1.4s_ease-in-out_infinite]" />
                <span className="w-2 h-2 bg-neutral-800 rounded-full animate-[pulse_1.4s_ease-in-out_0.2s_infinite]" />
                <span className="w-2 h-2 bg-neutral-800 rounded-full animate-[pulse_1.4s_ease-in-out_0.4s_infinite]" />
                <div className="absolute top-full mt-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-md border bg-popover px-3 py-1.5 text-sm text-popover-foreground shadow-md opacity-0 scale-95 transition-all group-hover:opacity-100 group-hover:scale-100 pointer-events-none">
                  ☕&nbsp;&nbsp;Grab a coffee, and come back to ready-to-post clips.
                </div>
              </div>

              {/* Status message */}
              <p className="shimmer text-neutral-600/60 text-sm tracking-wide mb-8">
                {progressMessage || (task.status === "queued" ? "Waiting in queue" : "Processing")}
              </p>

              {/* Minimal progress bar */}
              {progress > 0 && (
                <div className="w-48">
                  <div className="h-px bg-neutral-200 w-full relative overflow-hidden">
                    <div
                      className="absolute inset-y-0 left-0 bg-neutral-800 transition-all duration-700 ease-out"
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                  <p className="text-[11px] text-neutral-400 text-center mt-3 tabular-nums">{progress}%</p>
                </div>
              )}
            </div>

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
                        const matchCount = clips.filter(c =>
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
                            {topic}{matchCount > 0 && ` (${matchCount})`}
                          </span>
                        );
                      })}
                    </div>
                    {activeTopicFilter && (
                      <p className="text-xs text-zinc-500 mt-2">
                        Mostrando clips relacionados con <span className="text-blue-400">"{activeTopicFilter}"</span>
                        {" · "}
                        <button onClick={() => setActiveTopicFilter(null)} className="underline hover:text-zinc-300">Ver todos</button>
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
                    ? `${clips.filter(c => c.text?.toLowerCase().includes(activeTopicFilter.toLowerCase().split(" ")[0])).length} clip(s) en "${activeTopicFilter}"`
                    : `${clips.length} clip${clips.length !== 1 ? "s" : ""} ready`
                  }
                </p>
                {clips.filter(clip => {
                  if (!activeTopicFilter) return true;
                  const keyword = activeTopicFilter.toLowerCase().split(" ")[0];
                  return clip.text?.toLowerCase().includes(keyword);
                }).map((clip) => (
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
                              <div className="flex items-center gap-2 text-sm text-gray-600">
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
                              <p className="text-sm text-gray-700 bg-gray-50 p-3 rounded">{clip.text}</p>
                            </div>
                          )}
                          {clip.reasoning && (
                            <div className="mb-4">
                              <h4 className="font-medium text-black mb-2">AI Analysis</h4>
                              <p className="text-sm text-gray-600">{clip.reasoning}</p>
                            </div>
                          )}
                          <Button size="sm" variant="outline" asChild>
                            <a href={`${apiUrl}${clip.video_url}`} download={clip.filename}>
                              <Download className="w-4 h-4" />
                              Download
                            </a>
                          </Button>
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
              <p className="text-gray-600 mb-4">There was an error processing your video. Please try again.</p>
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
                  <p className="text-gray-600 mb-4">
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
                  <p className="text-gray-600">
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
                        ✨ Auto-selects per platform: TikTok → Viral Pro / Hormozi, Reels → TikTok / Subtitles, Shorts → Subtitles
                      </p>
                    )}
                  </div>

                  <label className="flex items-center gap-2 text-sm text-gray-700">
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
                          <label className="flex items-center gap-2 text-xs text-gray-600 mb-2">
                            <input
                              type="checkbox"
                              checked={selectedClipIds.includes(clip.id)}
                              onChange={() => handleToggleClipSelection(clip.id)}
                            />
                            Select for merge
                          </label>
                          <h3 className="font-semibold text-lg text-black mb-1">Clip {clip.clip_order}</h3>
                          <div className="flex items-center gap-2 text-sm text-gray-600">
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
                            {/* P2.4: Hook Preview Score badge */}
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
                        <div className="mb-4 p-3 bg-gray-50 rounded-lg">
                          <div className="flex items-center justify-between mb-3">
                            <h4 className="font-medium text-black text-sm flex items-center gap-2">
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
                                <span className="flex items-center gap-1 text-gray-600">
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
                                <span className="flex items-center gap-1 text-gray-600">
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
                                <span className="flex items-center gap-1 text-gray-600">
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
                                <span className="flex items-center gap-1 text-gray-600">
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
                          <p className="text-sm text-gray-700 bg-gray-50 p-3 rounded">{clip.text}</p>
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
                                  <MousePointer2 className="w-3.5 h-3.5 text-green-700" />
                                </div>
                                <div>
                                  <span className="text-[10px] font-bold text-green-500 uppercase leading-none block mb-1">Conversion Tactic</span>
                                  <p className="text-sm text-gray-700 leading-relaxed italic">
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
                          <p className="text-sm text-gray-600">{clip.reasoning}</p>
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
                                  className="text-xs text-purple-600 hover:text-purple-800 font-medium"
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
                                  className="text-xs text-purple-600 hover:text-purple-800 font-medium"
                                  title="Copy description"
                                >
                                  Copy
                                </button>
                              </div>
                              <p className="text-sm text-gray-700 bg-white rounded px-2 py-1 border border-purple-100">{clip.social_description}</p>
                            </div>
                          )}
                          {clip.suggested_hashtags && clip.suggested_hashtags.length > 0 && (
                            <div>
                              <div className="flex items-center justify-between mb-1">
                                <span className="text-xs text-gray-500 font-medium">HASHTAGS</span>
                                <button
                                  onClick={() => navigator.clipboard.writeText((clip.suggested_hashtags || []).join(' '))}
                                  className="text-xs text-purple-600 hover:text-purple-800 font-medium"
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
                      </div>

                      {editingClipId === clip.id && (
                        <div className="mt-4 p-3 border rounded-lg space-y-3 bg-gray-50">
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
                      <div className="mt-3 border border-purple-200 rounded-lg bg-purple-50/50">
                        <button
                          className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium text-purple-700 hover:bg-purple-50 rounded-lg transition-colors"
                          onClick={() => {
                            setRefiningClipId(refiningClipId === clip.id ? null : clip.id);
                            setRefineResult(null);
                          }}
                        >
                          <Sparkles className="w-4 h-4" />
                          AI Refine
                          <span className="ml-auto text-xs text-purple-500">
                            {refiningClipId === clip.id ? "▲" : "▼"}
                          </span>
                        </button>
                        {refiningClipId === clip.id && (
                          <div className="px-3 pb-3 space-y-2">
                            <p className="text-xs text-purple-600">
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
                              <div className={`text-xs rounded p-2 ${refineResult.action === "error" ? "bg-red-50 text-red-700 border border-red-200" : "bg-green-50 text-green-700 border border-green-200"}`}>
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