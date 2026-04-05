"use client";

import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Checkbox } from "@/components/ui/checkbox";
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
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
import { useSession } from "@/lib/auth-client";
import { formatSupportMessage, parseApiError } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import {
  ArrowLeft,
  Clock,
  PlayCircle,
  AlertCircle,
  CheckCircle,
  Loader2,
  PauseCircle,
  RotateCcw,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";

interface Task {
  id: string;
  user_id: string;
  source_id: string;
  source_title: string;
  source_type: string;
  status: string;
  clips_count: number;
  created_at: string;
  updated_at: string;
}

type BatchAction = "cancel" | "resume" | "delete" | null;

const ACTIVE_TASK_STATUSES = ["queued", "processing"];
const RESUMABLE_TASK_STATUSES = ["cancelled", "error"];

async function fetchTasksList() {
  const response = await fetch("/api/tasks/", {
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch tasks: ${response.status}`);
  }

  const data = await response.json();
  return (data.tasks || []) as Task[];
}

async function buildSupportError(response: Response, fallbackMessage: string) {
  const parsed = await parseApiError(response, fallbackMessage);
  return formatSupportMessage(parsed);
}

const STATUS_CONFIG: Record<
  string,
  { label: string; dotClass: string; bgClass: string; textClass: string }
> = {
  completed: {
    label: "Completed",
    dotClass: "bg-green-400",
    bgClass: "bg-green-500/10 border-green-500/20",
    textClass: "text-green-400",
  },
  processing: {
    label: "Processing",
    dotClass: "bg-cyan-400 animate-pulse",
    bgClass: "bg-cyan-500/10 border-cyan-500/20",
    textClass: "text-cyan-400",
  },
  queued: {
    label: "Queued",
    dotClass: "bg-amber-400",
    bgClass: "bg-amber-500/10 border-amber-500/20",
    textClass: "text-amber-400",
  },
  error: {
    label: "Error",
    dotClass: "bg-red-400",
    bgClass: "bg-red-500/10 border-red-500/20",
    textClass: "text-red-400",
  },
  cancelled: {
    label: "Cancelled",
    dotClass: "bg-gray-400",
    bgClass: "bg-gray-500/10 border-gray-500/20",
    textClass: "text-gray-400",
  },
};

export default function ListPage() {
  const { data: session, isPending } = useSession();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTaskIds, setSelectedTaskIds] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [batchNotice, setBatchNotice] = useState<{
    tone: "success" | "error";
    message: string;
  } | null>(null);
  const [activeBatchAction, setActiveBatchAction] = useState<BatchAction>(null);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  useEffect(() => {
    const loadTasks = async () => {
      if (!session?.user?.id) {
        setTasks([]);
        setSelectedTaskIds([]);
        setIsLoading(false);
        return;
      }

      try {
        setIsLoading(true);
        setError(null);
        const nextTasks = await fetchTasksList();
        setTasks(nextTasks);
        setSelectedTaskIds((current) =>
          current.filter((taskId) => nextTasks.some((task) => task.id === taskId)),
        );
      } catch (err) {
        console.error("Error fetching tasks:", err);
        setError(err instanceof Error ? err.message : "Failed to load tasks");
      } finally {
        setIsLoading(false);
      }
    };

    void loadTasks();
  }, [session?.user?.id]);

  const refreshTasks = async () => {
    const nextTasks = await fetchTasksList();
    setTasks(nextTasks);
    setSelectedTaskIds((current) =>
      current.filter((taskId) => nextTasks.some((task) => task.id === taskId)),
    );
  };

  const selectedTasks = tasks.filter((task) => selectedTaskIds.includes(task.id));
  const selectedCount = selectedTasks.length;
  const completedCount = tasks.filter((task) => task.status === "completed").length;
  const activeCount = tasks.filter((task) => ACTIVE_TASK_STATUSES.includes(task.status)).length;
  const attentionCount = tasks.filter((task) => RESUMABLE_TASK_STATUSES.includes(task.status)).length;
  const cancelableCount = selectedTasks.filter((task) =>
    ACTIVE_TASK_STATUSES.includes(task.status),
  ).length;
  const resumableCount = selectedTasks.filter((task) =>
    RESUMABLE_TASK_STATUSES.includes(task.status),
  ).length;
  const allVisibleSelected = tasks.length > 0 && tasks.every((task) => selectedTaskIds.includes(task.id));
  const someSelected = selectedCount > 0 && !allVisibleSelected;

  const formatDate = (dateString: string) => {
    const date = new Date(dateString);
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  };

  const handleToggleTask = (taskId: string) => {
    setBatchNotice(null);
    setSelectedTaskIds((current) => {
      if (current.includes(taskId)) {
        return current.filter((id) => id !== taskId);
      }
      return [...current, taskId];
    });
  };

  const handleToggleAllVisible = () => {
    setBatchNotice(null);
    if (allVisibleSelected) {
      setSelectedTaskIds([]);
      return;
    }
    setSelectedTaskIds(tasks.map((task) => task.id));
  };

  const runBatchAction = async (
    action: Exclude<BatchAction, null>,
    targetTaskIds: string[],
    requestFactory: (taskId: string) => Promise<Response>,
    labels: {
      empty: string;
      fallback: string;
      success: (count: number) => string;
      partial: (successCount: number, failureCount: number, firstError: string) => string;
    },
  ) => {
    if (!session?.user?.id) return;

    if (targetTaskIds.length === 0) {
      setBatchNotice({ tone: "error", message: labels.empty });
      return;
    }

    setActiveBatchAction(action);
    setBatchNotice(null);

    const results = await Promise.allSettled(
      targetTaskIds.map(async (taskId) => {
        const response = await requestFactory(taskId);
        if (!response.ok) {
          throw new Error(await buildSupportError(response, labels.fallback));
        }
        return taskId;
      }),
    );

    const fulfilled = results.filter(
      (result): result is PromiseFulfilledResult<string> => result.status === "fulfilled",
    );
    const rejected = results.filter(
      (result): result is PromiseRejectedResult => result.status === "rejected",
    );

    try {
      if (fulfilled.length > 0) await refreshTasks();

      if (rejected.length === 0) {
        setBatchNotice({ tone: "success", message: labels.success(fulfilled.length) });
      } else {
        const firstFailure = rejected[0]?.reason;
        const firstError =
          firstFailure instanceof Error
            ? firstFailure.message
            : typeof firstFailure === "string"
              ? firstFailure
              : labels.fallback;
        setBatchNotice({
          tone: "error",
          message: labels.partial(fulfilled.length, rejected.length, firstError),
        });
      }
    } catch (refreshError) {
      console.error("Error refreshing task list:", refreshError);
      setBatchNotice({
        tone: "error",
        message:
          refreshError instanceof Error
            ? refreshError.message
            : "The batch action finished, but the list could not be refreshed.",
      });
    } finally {
      setActiveBatchAction(null);
    }
  };

  const handleCancelSelected = async () => {
    const targetTaskIds = selectedTasks
      .filter((task) => ACTIVE_TASK_STATUSES.includes(task.status))
      .map((task) => task.id);

    await runBatchAction(
      "cancel",
      targetTaskIds,
      (taskId) => fetch(`/api/tasks/${taskId}/cancel`, { method: "POST" }),
      {
        empty: "No active generations in selection to cancel.",
        fallback: "Failed to cancel generation",
        success: (count) => `${count} generation${count === 1 ? "" : "s"} cancelled.`,
        partial: (s, f, err) => `${s} cancelled, ${f} failed. ${err}`,
      },
    );
  };

  const handleResumeSelected = async () => {
    const targetTaskIds = selectedTasks
      .filter((task) => RESUMABLE_TASK_STATUSES.includes(task.status))
      .map((task) => task.id);

    await runBatchAction(
      "resume",
      targetTaskIds,
      (taskId) => fetch(`/api/tasks/${taskId}/resume`, { method: "POST" }),
      {
        empty: "No failed or cancelled generations in selection to resume.",
        fallback: "Failed to resume generation",
        success: (count) => `${count} generation${count === 1 ? "" : "s"} resumed.`,
        partial: (s, f, err) => `${s} resumed, ${f} failed. ${err}`,
      },
    );
  };

  const handleDeleteSelected = async () => {
    const targetTaskIds = [...selectedTaskIds];

    await runBatchAction(
      "delete",
      targetTaskIds,
      (taskId) => fetch(`/api/tasks/${taskId}`, { method: "DELETE" }),
      {
        empty: "Select at least one generation to delete.",
        fallback: "Failed to delete generation",
        success: (count) => `${count} generation${count === 1 ? "" : "s"} deleted.`,
        partial: (s, f, err) => `${s} deleted, ${f} failed. ${err}`,
      },
    );

    setShowDeleteDialog(false);
  };

  /* ── Loading / Auth gates ─────────────────────────────────── */

  if (isPending) {
    return (
      <div className="min-h-screen bg-white flex items-center justify-center p-4">
        <div className="space-y-4">
          <Skeleton className="h-4 w-32 mx-auto" />
          <Skeleton className="h-4 w-48 mx-auto" />
          <Skeleton className="h-4 w-24 mx-auto" />
        </div>
      </div>
    );
  }

  if (!session?.user) {
    return (
      <div className="min-h-screen bg-white">
        <div className="max-w-4xl mx-auto px-4 py-24 text-center">
          <h1 className="text-3xl font-bold text-black mb-4">Sign In Required</h1>
          <p className="text-gray-600 mb-8">
            You need to be signed in to view your generations.
          </p>
          <Link href="/sign-in">
            <Button size="lg">Sign In</Button>
          </Link>
        </div>
      </div>
    );
  }

  /* ── Status badge renderer ────────────────────────────────── */

  const getStatusBadge = (status: string) => {
    const config = STATUS_CONFIG[status];
    if (!config) {
      return (
        <Badge variant="outline" className="capitalize">
          {status}
        </Badge>
      );
    }
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
          config.bgClass,
          config.textClass,
        )}
      >
        <span className={cn("h-1.5 w-1.5 rounded-full", config.dotClass)} />
        {config.label}
      </span>
    );
  };

  /* ── Main render ──────────────────────────────────────────── */

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white flex">
      {/* ── Sidebar ──────────────────────────────────────── */}
      <aside className="w-64 bg-[#0a0a0f] border-r border-white/5 min-h-screen flex flex-col">
        <div className="p-6">
          <Link href="/" className="flex items-center gap-3">
            <div className="relative w-10 h-10">
              <div className="absolute inset-0 bg-gradient-to-br from-cyan-400 via-purple-500 to-pink-500 rounded-xl" />
              <div className="absolute inset-[2px] bg-[#0a0a0f] rounded-xl flex items-center justify-center">
                <Zap className="w-5 h-5 text-cyan-400" />
              </div>
            </div>
            <span className="text-xl font-bold">
              Vira<span className="text-cyan-400">Clip</span>
            </span>
          </Link>
        </div>

        <nav className="flex-1 px-4">
          <div className="space-y-1">
            {[
              { label: "Dashboard", href: "/dashboard", active: false },
              { label: "My Clips", href: "/list", active: true },
              { label: "Analytics", href: "/analytics", active: false },
              { label: "Settings", href: "/settings", active: false },
            ].map((item) => (
              <Link
                key={item.label}
                href={item.href}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all ${
                  item.active 
                    ? "bg-cyan-500/10 text-cyan-400 border border-cyan-500/20" 
                    : "text-gray-400 hover:bg-white/5 hover:text-white"
                }`}
              >
                <span className="font-medium">{item.label}</span>
              </Link>
            ))}
          </div>
        </nav>
      </aside>

      {/* ── Main Content ──────────────────────────────────────── */}
      <main className="flex-1 overflow-auto">
        {/* ── Page header ──────────────────────────────────────── */}
        <header className="sticky top-0 z-40 bg-[#0a0a0f]/80 backdrop-blur-xl border-b border-white/5 px-8 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold">My Clips</h1>
              <p className="text-sm text-gray-500">
                {tasks.length} total &middot; manage and review your clips
              </p>
            </div>

            <div className="flex items-center gap-3">
              {!isLoading && !error && tasks.length > 0 && (
                <div className="flex items-center gap-2">
                  {completedCount > 0 && (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-green-500/10 border border-green-500/20 px-2.5 py-1 text-xs font-medium text-green-400">
                      <span className="h-1.5 w-1.5 rounded-full bg-green-400" />
                      {completedCount} done
                    </span>
                  )}
                  {activeCount > 0 && (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-cyan-500/10 border border-cyan-500/20 px-2.5 py-1 text-xs font-medium text-cyan-400">
                      <span className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse" />
                      {activeCount} active
                    </span>
                  )}
                  {attentionCount > 0 && (
                    <span className="inline-flex items-center gap-1.5 rounded-full bg-red-500/10 border border-red-500/20 px-2.5 py-1 text-xs font-medium text-red-400">
                      <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
                      {attentionCount} need attention
                    </span>
                  )}
                </div>
              )}
              
              <Link href="/new">
                <button className="flex items-center gap-2 px-6 py-3 bg-cyan-500 hover:bg-cyan-400 text-black font-semibold rounded-xl transition-all hover:shadow-[0_0_30px_-5px_rgba(34,211,238,0.5)]">
                  <Plus className="w-5 h-5" />
                  New Project
                </button>
              </Link>
            </div>
          </div>
        </header>

        {/* ── Content ──────────────────────────────────────────── */}
        <div className={cn("p-8", selectedCount > 0 && "pb-28")}>
          {/* Batch notice */}
          {batchNotice && (
            <div className={cn(
              "mb-4 p-4 rounded-xl border flex items-center gap-3",
              batchNotice.tone === "success"
                ? "border-green-500/30 bg-green-500/10 text-green-400"
                : "border-red-500/30 bg-red-500/10 text-red-400",
            )}>
              {batchNotice.tone === "success" ? (
                <CheckCircle className="w-5 h-5" />
              ) : (
                <AlertCircle className="w-5 h-5" />
              )}
              <p className="text-sm">{batchNotice.message}</p>
            </div>
          )}

          {isLoading ? (
            <div className="space-y-3">
              {[1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className="flex items-center gap-4 rounded-xl border border-white/10 bg-white/5 p-4"
                >
                  <div className="h-5 w-5 rounded bg-white/10 animate-pulse" />
                  <div className="flex-1 space-y-2">
                    <div className="h-4 w-64 bg-white/10 rounded animate-pulse" />
                    <div className="h-3 w-40 bg-white/10 rounded animate-pulse" />
                  </div>
                  <div className="h-6 w-20 rounded-full bg-white/10 animate-pulse" />
                </div>
              ))}
            </div>
          ) : error ? (
            <div className="p-4 rounded-xl border border-red-500/30 bg-red-500/10 text-red-400 flex items-center gap-3">
              <AlertCircle className="w-5 h-5" />
              <p>{error}</p>
            </div>
          ) : tasks.length === 0 ? (
            <div className="p-12 text-center border border-white/10 rounded-2xl bg-white/5">
              <div className="w-16 h-16 bg-gradient-to-br from-cyan-500/20 to-purple-500/20 rounded-2xl flex items-center justify-center mx-auto mb-4">
                <PlayCircle className="w-8 h-8 text-cyan-400" />
              </div>
              <h2 className="text-xl font-semibold text-white mb-2">No generations yet</h2>
              <p className="text-gray-500 mb-6 text-sm">
                Start by processing your first video to create clips.
              </p>
              <Link href="/new">
                <button className="px-6 py-3 bg-cyan-500 hover:bg-cyan-400 text-black font-semibold rounded-xl transition-all hover:shadow-[0_0_30px_-5px_rgba(34,211,238,0.5)]">
                  Create New Generation
                </button>
              </Link>
            </div>
          ) : (
            <>
              {/* ── Table header row ────────────────────────────── */}
              <div className="mb-4 flex items-center gap-4 px-4 py-2">
                <Checkbox
                  checked={allVisibleSelected ? true : someSelected ? "indeterminate" : false}
                  onCheckedChange={handleToggleAllVisible}
                  disabled={activeBatchAction !== null}
                  aria-label="Select all generations"
                  className="data-[state=indeterminate]:bg-gray-500 data-[state=indeterminate]:border-gray-500 border-white/20"
                />
                <span className="text-xs font-medium uppercase tracking-widest text-gray-500">
                  {selectedCount > 0 ? `${selectedCount} of ${tasks.length} selected` : "Select"}
                </span>
              </div>

          {/* ── Task list ───────────────────────────────────── */}
          <div className="space-y-2">
            {tasks.map((task) => {
              const isSelected = selectedTaskIds.includes(task.id);

              return (
                <div
                  key={task.id}
                  className={cn(
                    "group relative flex items-start gap-4 rounded-xl border p-4 transition-all duration-150",
                    isSelected
                      ? "border-cyan-500/30 bg-cyan-500/5"
                      : "border-white/10 bg-white/5 hover:border-white/20",
                  )}
                >
                  {/* Selection indicator bar */}
                  <div
                    className={cn(
                      "absolute left-0 top-3 bottom-3 w-0.5 rounded-full transition-all duration-150",
                      isSelected ? "bg-cyan-400" : "bg-transparent",
                    )}
                  />

                  {/* Checkbox */}
                  <div className="pt-0.5 pl-1">
                    <Checkbox
                      checked={isSelected}
                      onCheckedChange={() => handleToggleTask(task.id)}
                      disabled={activeBatchAction !== null}
                      aria-label={
                        isSelected
                          ? `Deselect ${task.source_title}`
                          : `Select ${task.source_title}`
                      }
                      className="border-white/20 data-[state=checked]:bg-cyan-500 data-[state=checked]:border-cyan-500"
                    />
                  </div>

                  {/* Content — links to task detail */}
                  <Link href={`/tasks/${task.id}`} className="flex-1 min-w-0">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0">
                        <h3 className="truncate text-sm font-semibold text-white transition-colors group-hover:text-cyan-400">
                          {task.source_title}
                        </h3>
                        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
                          <span className="uppercase tracking-wide font-medium text-gray-400">
                            {task.source_type}
                          </span>
                          <span className="w-px h-3 bg-white/10" />
                          <span className="flex items-center gap-1">
                            <Clock className="w-3 h-3" />
                            {formatDate(task.created_at)}
                          </span>
                          <span className="w-px h-3 bg-white/10" />
                          <span>
                            {task.clips_count} {task.clips_count === 1 ? "clip" : "clips"}
                          </span>
                        </div>
                      </div>

                      <div className="flex-shrink-0">
                        {getStatusBadge(task.status)}
                      </div>
                    </div>
                  </Link>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>

    {/* ── Floating batch command bar ────────────────────────── */}
    {selectedCount > 0 && (
      <div
        className="fixed inset-x-0 bottom-0 z-50 flex justify-center px-4 pb-5 pointer-events-none"
        style={{ animation: "command-bar-in 0.25s cubic-bezier(0.16, 1, 0.3, 1) both" }}
      >
        <div
          className="pointer-events-auto flex items-center gap-1 rounded-2xl border border-white/10 bg-[#0a0a0f] px-2 py-2 shadow-2xl"
          style={{ animation: "command-bar-pulse 3s ease-in-out infinite" }}
        >
          {/* Select all checkbox */}
          <div className="flex items-center gap-2.5 pl-2 pr-3">
            <Checkbox
              checked={allVisibleSelected ? true : someSelected ? "indeterminate" : false}
              onCheckedChange={handleToggleAllVisible}
              disabled={activeBatchAction !== null}
              aria-label="Select all"
              className="border-white/20 data-[state=checked]:bg-cyan-500 data-[state=checked]:text-white data-[state=checked]:border-cyan-500 data-[state=indeterminate]:bg-gray-500 data-[state=indeterminate]:border-gray-500"
            />
            <span className="text-sm font-medium text-white tabular-nums">
              {selectedCount}
              <span className="text-gray-500 ml-0.5"> selected</span>
            </span>
          </div>

          <span className="w-px h-6 bg-white/10" />

          {/* Action buttons */}
          <div className="flex items-center gap-0.5 px-1">
            <button
              onClick={() => void handleCancelSelected()}
              disabled={cancelableCount === 0 || activeBatchAction !== null}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 disabled:text-gray-600 disabled:hover:bg-transparent transition-colors"
            >
              {activeBatchAction === "cancel" ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <PauseCircle className="w-4 h-4" />
              )}
              <span className="hidden sm:inline">Cancel</span>
              {cancelableCount > 0 && (
                <span className="text-xs text-gray-500">{cancelableCount}</span>
              )}
            </button>

            <button
              onClick={() => void handleResumeSelected()}
              disabled={resumableCount === 0 || activeBatchAction !== null}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 disabled:text-gray-600 disabled:hover:bg-transparent transition-colors"
            >
              {activeBatchAction === "resume" ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RotateCcw className="w-4 h-4" />
              )}
              <span className="hidden sm:inline">Resume</span>
              {resumableCount > 0 && (
                <span className="text-xs text-gray-500">{resumableCount}</span>
              )}
            </button>

            <span className="w-px h-6 bg-white/10" />

            <button
              onClick={() => setShowDeleteDialog(true)}
              disabled={selectedCount === 0 || activeBatchAction !== null}
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-red-400 hover:text-red-300 hover:bg-red-500/10 disabled:text-gray-600 disabled:hover:bg-transparent transition-colors"
            >
              {activeBatchAction === "delete" ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Trash2 className="w-4 h-4" />
              )}
              <span className="hidden sm:inline">Delete</span>
            </button>
          </div>

          <span className="w-px h-6 bg-white/10" />

          {/* Clear selection */}
          <button
            onClick={() => {
              setSelectedTaskIds([]);
              setBatchNotice(null);
            }}
            disabled={activeBatchAction !== null}
            className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-white/10 rounded-xl"
            aria-label="Clear selection"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>
    )}

    {/* ── Delete confirmation dialog ────────────────────────── */}
    {showDeleteDialog && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm">
        <div className="p-6 rounded-2xl border border-white/10 bg-[#0a0a0f] max-w-md w-full mx-4">
          <h2 className="text-xl font-bold mb-2">Delete {selectedCount} generation{selectedCount === 1 ? "" : "s"}?</h2>
          <p className="text-gray-400 mb-6">
            This will permanently remove {selectedCount === 1 ? "this generation" : "these generations"} and all associated clips. This cannot be undone.
          </p>
          <div className="flex gap-3 justify-end">
            <button
              onClick={() => setShowDeleteDialog(false)}
              disabled={activeBatchAction === "delete"}
              className="px-4 py-2 rounded-lg border border-white/10 text-gray-400 hover:text-white hover:bg-white/5 transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={() => void handleDeleteSelected()}
              disabled={activeBatchAction === "delete" || selectedCount === 0}
              className="px-4 py-2 rounded-lg bg-red-500 hover:bg-red-400 text-white font-medium transition-colors"
            >
              {activeBatchAction === "delete" ? (
                <span className="flex items-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Deleting...
                </span>
              ) : (
                "Delete"
              )}
            </button>
          </div>
        </div>
      </div>
    )}
  </main>
</div>
  );
}
