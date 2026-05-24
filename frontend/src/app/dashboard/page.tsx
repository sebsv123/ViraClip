"use client";

import { useState, useEffect, useCallback, useRef, memo, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Plus,
  Film,
  Clock,
  CheckCircle,
  Loader2,
  AlertCircle,
  Sparkles,
  X,
  Link2,
  TrendingUp,
  Trash2,
  Zap,
  Smartphone,
  Monitor,
  Subtitles,
  Scissors,
  ScanEye,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import Link from "next/link";
import { useSession } from "@/lib/auth-client";
import { useRouter } from "next/navigation";

/* ─────────────────────────────────────────────
   Types
   ───────────────────────────────────────────── */
interface Task {
  id: string;
  title?: string;
  source_title?: string;
  source_type?: string;
  clips_count?: number;
  status: "pending" | "processing" | "completed" | "failed" | "queued";
  progress?: number;
  progress_message?: string;
  created_at: string;
}

interface TaskOptions {
  processing_mode: "fast" | "balanced" | "quality" | "elite";
  num_clips: number;
  output_format: "vertical" | "original";
  add_subtitles: boolean;
  jump_cut: boolean;
  use_scene_detection: boolean;
  auto_center_face: boolean;
  caption_template?: string;
  speaker_name?: string;
  speaker_title?: string;
  brand_color?: string;
}

/* ─────────────────────────────────────────────
   Helpers
   ───────────────────────────────────────────── */
function formatDate(dateString: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(new Date(dateString));
}

function formatRelativeTime(dateString: string) {
  const date = new Date(dateString);
  const now = new Date();
  const diffInHours = Math.floor(
    (now.getTime() - date.getTime()) / (1000 * 60 * 60),
  );

  if (diffInHours < 1) return "Just now";
  if (diffInHours < 24) return `${diffInHours}h ago`;
  if (diffInHours < 48) return "Yesterday";
  return formatDate(dateString);
}

function formatDuration(seconds?: number) {
  if (!seconds || seconds <= 0) return "\u2014";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/* ─────────────────────────────────────────────
   Status Badge \u2014 Linear-app pill style
   ───────────────────────────────────────────── */
const StatusBadge = memo(function StatusBadge({
  status,
  progress,
}: {
  status: Task["status"];
  progress?: number;
}) {
  const configs = {
    pending: {
      style: {
        background: "rgba(138,143,152,0.12)",
        color: "var(--muted)",
        borderColor: "rgba(138,143,152,0.2)",
      },
      label: "Pending",
    },
    queued: {
      style: {
        background: "rgba(94,106,210,0.12)",
        color: "var(--accent)",
        borderColor: "rgba(94,106,210,0.2)",
      },
      label: "Queued",
    },
    processing: {
      style: {
        background: "rgba(234,179,8,0.12)",
        color: "var(--warn)",
        borderColor: "rgba(234,179,8,0.2)",
      },
      label: "Processing",
    },
    completed: {
      style: {
        background: "rgba(39,166,68,0.12)",
        color: "var(--success)",
        borderColor: "rgba(39,166,68,0.2)",
      },
      label: "Completed",
    },
    failed: {
      style: {
        background: "rgba(220,38,38,0.12)",
        color: "var(--danger)",
        borderColor: "rgba(220,38,38,0.2)",
      },
      label: "Failed",
    },
  };

  const config = configs[status] || configs.pending;

  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border"
      style={config.style}
    >
      {status === "processing" && (
        <Loader2 size={12} className="animate-spin" />
      )}
      {status === "completed" && <CheckCircle size={12} />}
      {status === "failed" && <AlertCircle size={12} />}
      {status === "queued" && <Clock size={12} />}
      <span>{config.label}</span>
      {status === "processing" && progress !== undefined && (
        <span>{progress}%</span>
      )}
    </span>
  );
});

/* ─────────────────────────────────────────────
   KPI Card \u2014 Linear-app style
   ───────────────────────────────────────────── */
function KpiCard({
  label,
  value,
  trend,
}: {
  label: string;
  value: string;
  trend?: { value: string; positive: boolean };
}) {
  return (
    <div
      className="flex flex-col gap-1 p-5 rounded-lg"
      style={{
        background: "var(--surface)",
        boxShadow: "var(--elev-ring)",
      }}
    >
      <span
        className="text-xs font-medium uppercase tracking-wider"
        style={{ color: "var(--meta)" }}
      >
        {label}
      </span>
      <span
        className="text-2xl font-semibold"
        style={{
          color: "var(--fg)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </span>
      {trend && (
        <span
          className="inline-flex items-center gap-1 text-xs font-medium"
          style={{
            color: trend.positive ? "var(--success)" : "var(--danger)",
          }}
        >
          <TrendingUp size={12} />
          {trend.value}
        </span>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────
   Create Task Modal
   ───────────────────────────────────────────── */
function CreateTaskModal({
  isOpen,
  onClose,
  onSubmit,
}: {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (url: string, options: TaskOptions) => void;
}) {
  const [url, setUrl] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [options, setOptions] = useState<TaskOptions>({
    processing_mode: "balanced",
    num_clips: 6,
    output_format: "vertical",
    add_subtitles: true,
    jump_cut: true,
    use_scene_detection: true,
    auto_center_face: true,
  });
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;

    setIsLoading(true);
    await onSubmit(url, options);
    setIsLoading(false);
    setUrl("");
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50"
            style={{ background: "rgba(0,0,0,0.6)" }}
            onClick={onClose}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-lg z-50"
          >
            <div
              className="p-6 rounded-lg"
              style={{
                background: "var(--surface)",
                boxShadow: "var(--elev-raised)",
              }}
            >
              {/* Header */}
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2
                    className="text-lg font-semibold"
                    style={{ color: "var(--fg)" }}
                  >
                    Create New Clips
                  </h2>
                  <p className="text-sm" style={{ color: "var(--meta)" }}>
                    Paste a YouTube URL to get started
                  </p>
                </div>
                <button
                  onClick={onClose}
                  className="p-1.5 rounded-sm transition-all"
                  style={{ color: "var(--fg-2)" }}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.background =
                      "rgba(255,255,255,0.06)")
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.background = "transparent")
                  }
                >
                  <X size={16} />
                </button>
              </div>

              <form onSubmit={handleSubmit}>
                {/* URL Input */}
                <div className="relative mb-4">
                  <Link2
                    size={16}
                    className="absolute left-3 top-1/2 -translate-y-1/2"
                    style={{ color: "var(--meta)" }}
                  />
                  <input
                    ref={inputRef}
                    type="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://youtube.com/watch?v=..."
                    className="w-full pl-9 pr-3 py-2.5 rounded-md text-sm transition-all"
                    style={{
                      background: "var(--bg)",
                      color: "var(--fg)",
                      border: "1px solid var(--border)",
                    }}
                    onFocus={(e) =>
                      (e.currentTarget.style.borderColor = "var(--accent)")
                    }
                    onBlur={(e) =>
                      (e.currentTarget.style.borderColor = "var(--border)")
                    }
                  />
                </div>

                {/* Options Grid */}
                <div className="grid grid-cols-2 gap-3 mb-4">
                  {/* Processing Mode */}
                  <div className="col-span-2">
                    <label
                      className="text-xs font-medium mb-1.5 block"
                      style={{ color: "var(--meta)" }}
                    >
                      Processing Mode
                    </label>
                    <div className="grid grid-cols-4 gap-2">
                      {(
                        ["fast", "balanced", "quality", "elite"] as const
                      ).map((mode) => (
                        <button
                          key={mode}
                          type="button"
                          onClick={() =>
                            setOptions({ ...options, processing_mode: mode })
                          }
                          className="px-3 py-2 rounded-md text-xs font-medium capitalize transition-all"
                          style={
                            options.processing_mode === mode
                              ? {
                                  background: "rgba(94,106,210,0.12)",
                                  color: "var(--accent)",
                                  border: "1px solid rgba(94,106,210,0.2)",
                                }
                              : {
                                  background: "var(--bg)",
                                  color: "var(--muted)",
                                  border: "1px solid var(--border)",
                                }
                          }
                        >
                          {mode}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Number of Clips */}
                  <div>
                    <label
                      className="text-xs font-medium mb-1.5 block"
                      style={{ color: "var(--meta)" }}
                    >
                      Clips to Generate
                    </label>
                    <select
                      value={options.num_clips}
                      onChange={(e) =>
                        setOptions({
                          ...options,
                          num_clips: Number(e.target.value),
                        })
                      }
                      className="w-full px-3 py-2 rounded-md text-sm"
                      style={{
                        background: "var(--bg)",
                        color: "var(--fg)",
                        border: "1px solid var(--border)",
                      }}
                    >
                      {[3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
                        <option key={n} value={n}>
                          {n} clips
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Output Format */}
                  <div>
                    <label
                      className="text-xs font-medium mb-1.5 block"
                      style={{ color: "var(--meta)" }}
                    >
                      Format
                    </label>
                    <div className="flex gap-2">
                      {(
                        [
                          {
                            value: "vertical",
                            label: "9:16",
                            icon: Smartphone,
                          },
                          {
                            value: "original",
                            label: "Original",
                            icon: Monitor,
                          },
                        ] as const
                      ).map(({ value, label, icon: Icon }) => (
                        <button
                          key={value}
                          type="button"
                          onClick={() =>
                            setOptions({ ...options, output_format: value })
                          }
                          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-xs font-medium transition-all"
                          style={
                            options.output_format === value
                              ? {
                                  background: "rgba(94,106,210,0.12)",
                                  color: "var(--accent)",
                                  border: "1px solid rgba(94,106,210,0.2)",
                                }
                              : {
                                  background: "var(--bg)",
                                  color: "var(--muted)",
                                  border: "1px solid var(--border)",
                                }
                          }
                        >
                          <Icon size={14} />
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Caption Template */}
                  <div className="col-span-2">
                    <label
                      className="text-xs font-medium mb-1.5 block"
                      style={{ color: "var(--meta)" }}
                    >
                      Estilo de subt\u00edtulos
                    </label>
                    <select
                      value={options.caption_template || "hormozi"}
                      onChange={(e) =>
                        setOptions({
                          ...options,
                          caption_template: e.target.value,
                        })
                      }
                      className="w-full px-3 py-2 rounded-md text-sm"
                      style={{
                        background: "var(--bg)",
                        color: "var(--fg)",
                        border: "1px solid var(--border)",
                      }}
                    >
                      <option value="hormozi">
                        Hormozi \u2014 Palabra a palabra, impacto
                      </option>
                      <option value="mrbeast">
                        MrBeast \u2014 Frases cortas, energ\u00eda alta
                      </option>
                    </select>
                  </div>

                  {/* Toggle Options */}
                  <div className="col-span-2 grid grid-cols-3 gap-2">
                    {(
                      [
                        {
                          key: "add_subtitles" as const,
                          label: "Subtitles",
                          icon: Subtitles,
                        },
                        {
                          key: "jump_cut" as const,
                          label: "Jump Cuts",
                          icon: Scissors,
                        },
                        {
                          key: "use_scene_detection" as const,
                          label: "Scene Detect",
                          icon: ScanEye,
                        },
                      ]
                    ).map(({ key, label, icon: Icon }) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() =>
                          setOptions({ ...options, [key]: !options[key] })
                        }
                        className="flex items-center justify-center gap-2 px-3 py-2.5 rounded-md text-xs font-medium transition-all"
                        style={
                          options[key]
                            ? {
                                background: "rgba(94,106,210,0.12)",
                                color: "var(--accent)",
                                border: "1px solid rgba(94,106,210,0.2)",
                              }
                            : {
                                background: "var(--bg)",
                                color: "var(--muted)",
                                border: "1px solid var(--border)",
                              }
                        }
                      >
                        <Icon size={14} />
                        {label}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Info */}
                <div
                  className="flex items-center gap-2 text-xs mb-6"
                  style={{ color: "var(--meta)" }}
                >
                  <Clock size={14} />
                  <span>Processing takes ~5 minutes</span>
                </div>

                {/* Actions */}
                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={onClose}
                    className="flex-1 px-4 py-2.5 rounded-md text-sm font-medium transition-all"
                    style={{
                      background: "var(--bg)",
                      color: "var(--fg-2)",
                      border: "1px solid var(--border)",
                    }}
                    onMouseEnter={(e) =>
                      (e.currentTarget.style.background =
                        "rgba(255,255,255,0.06)")
                    }
                    onMouseLeave={(e) =>
                      (e.currentTarget.style.background = "var(--bg)")
                    }
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={!url.trim() || isLoading}
                    className="flex-1 px-4 py-2.5 rounded-md text-sm font-medium transition-all flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{
                      background: "var(--accent)",
                      color: "#fff",
                    }}
                    onMouseEnter={(e) => {
                      if (!url.trim() || isLoading) return;
                      e.currentTarget.style.background =
                        "var(--accent-hover)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = "var(--accent)";
                    }}
                  >
                    {isLoading ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <>
                        <Sparkles size={16} />
                        Generate Clips
                      </>
                    )}
                  </button>
                </div>
              </form>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

/* ─────────────────────────────────────────────
   Empty State
   ───────────────────────────────────────────── */
function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center py-20 text-center"
    >
      <div
        className="w-16 h-16 rounded-lg flex items-center justify-center mb-5"
        style={{ background: "var(--surface)" }}
      >
        <Film size={28} style={{ color: "var(--meta)" }} />
      </div>
      <h3
        className="text-lg font-semibold mb-1"
        style={{ color: "var(--fg)" }}
      >
        No clips yet
      </h3>
      <p className="text-sm max-w-sm mb-6" style={{ color: "var(--meta)" }}>
        Upload a video to get started. Our AI will automatically generate viral
        clips for you.
      </p>
      <button
        onClick={onCreate}
        className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-all"
        style={{
          background: "var(--accent)",
          color: "#fff",
        }}
        onMouseEnter={(e) =>
          (e.currentTarget.style.background = "var(--accent-hover)")
        }
        onMouseLeave={(e) =>
          (e.currentTarget.style.background = "var(--accent)")
        }
      >
        <Plus size={16} />
        Create Your First Clip
      </button>
    </motion.div>
  );
}

/* ─────────────────────────────────────────────
   Main Dashboard Page
   ───────────────────────────────────────────── */
export default function DashboardPage() {
  const { data: session } = useSession();
  const router = useRouter();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [filter, setFilter] = useState<"all" | "processing" | "completed">(
    "all",
  );

  // Pagination
  const [page, setPage] = useState(1);
  const perPage = 10;

  // Fetch tasks
  const fetchTasks = useCallback(async () => {
    try {
      const res = await fetch("/api/tasks");
      if (res.ok) {
        const data = await res.json();
        const tasksArray = Array.isArray(data) ? data : data?.tasks || [];
        setTasks(tasksArray);
      }
    } catch (error) {
      console.error("Failed to fetch tasks:", error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
    const interval = setInterval(fetchTasks, 10000);
    return () => clearInterval(interval);
  }, [fetchTasks]);

  // Create task
  const handleCreateTask = async (url: string, options: TaskOptions) => {
    try {
      const res = await fetch("/api/tasks/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          processing_mode: options.processing_mode,
          num_clips: options.num_clips,
          output_format: options.output_format,
          add_subtitles: options.add_subtitles,
          jump_cut: options.jump_cut,
          use_scene_detection: options.use_scene_detection,
          auto_center_face: options.auto_center_face,
          caption_template: options.caption_template || "hormozi",
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setIsCreateModalOpen(false);
        fetchTasks();
        if (data.task_id) {
          router.push(`/tasks/${data.task_id}`);
        }
      } else {
        const error = await res
          .json()
          .catch(() => ({ error: "Unknown error" }));
        console.error("Failed to create task:", error);
        alert(error.error || "Failed to create task. Please try again.");
      }
    } catch (error) {
      console.error("Failed to create task:", error);
      alert("Network error. Please check your connection and try again.");
    }
  };

  // Delete task
  const handleDeleteTask = async (id: string) => {
    try {
      const res = await fetch(`/api/tasks/${id}`, { method: "DELETE" });
      if (res.ok) {
        setTasks((prev) => prev.filter((t) => t.id !== id));
      }
    } catch (error) {
      console.error("Failed to delete task:", error);
    }
  };

  // System health polling
  const [systemHealth, setSystemHealth] = useState<{
    gpu: {
      available: boolean;
      encoder: string;
      utilization_pct: number;
      vram_used_mb: number;
      vram_total_mb: number;
    };
    queue: { depth: number };
  } | null>(null);

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await fetch("/api/health/system");
        if (res.ok) setSystemHealth(await res.json());
      } catch {
        /* ignore */
      }
    };
    fetchHealth();
    const interval = setInterval(fetchHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  // Memoized stats
  const safeTasks = useMemo(
    () => (Array.isArray(tasks) ? tasks : []),
    [tasks],
  );
  const totalClips = useMemo(
    () => safeTasks.reduce((acc, t) => acc + (t.clips_count || 0), 0),
    [safeTasks],
  );
  const completedTasks = useMemo(
    () => safeTasks.filter((t) => t.status === "completed").length,
    [safeTasks],
  );
  const processingTasks = useMemo(
    () =>
      safeTasks.filter(
        (t) => t.status === "processing" || t.status === "queued",
      ).length,
    [safeTasks],
  );

  // Filtered + paginated tasks
  const filteredTasks = useMemo(
    () =>
      safeTasks.filter((task) => {
        if (filter === "all") return true;
        if (filter === "processing")
          return (
            task.status === "processing" ||
            task.status === "queued" ||
            task.status === "pending"
          );
        if (filter === "completed") return task.status === "completed";
        return true;
      }),
    [safeTasks, filter],
  );

  const totalPages = Math.max(
    1,
    Math.ceil(filteredTasks.length / perPage),
  );
  const safePage = Math.min(page, totalPages);
  const paginatedTasks = filteredTasks.slice(
    (safePage - 1) * perPage,
    safePage * perPage,
  );

  // Reset page when filter changes
  useEffect(() => {
    setPage(1);
  }, [filter]);

  if (!session?.user) {
    return (
      <div
        className="min-h-screen flex items-center justify-center"
        style={{ background: "var(--bg)" }}
      >
        <Loader2
          size={24}
          className="animate-spin"
          style={{ color: "var(--accent)" }}
        />
      </div>
    );
  }

  return (
    <div
      className="p-6 lg:p-8"
      style={{ maxWidth: "var(--container-max)", margin: "0 auto" }}
    >
      {/* ── Header ── */}
      <div className="flex items-center justify-between gap-4 mb-8">
        <div>
          <h1
            className="text-xl font-semibold mb-0.5"
            style={{ color: "var(--fg)" }}
          >
            Dashboard
          </h1>
          <p className="text-sm" style={{ color: "var(--meta)" }}>
            Manage your video clips and track processing status
          </p>
        </div>

        <button
          onClick={() => setIsCreateModalOpen(true)}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-all shrink-0"
          style={{
            background: "var(--accent)",
            color: "#fff",
          }}
          onMouseEnter={(e) =>
            (e.currentTarget.style.background = "var(--accent-hover)")
          }
          onMouseLeave={(e) =>
            (e.currentTarget.style.background = "var(--accent)")
          }
        >
          <Plus size={16} />
          Create New Clip
        </button>
      </div>

      {/* ── System Health Bar ── */}
      {systemHealth && (
        <div
          className="flex flex-wrap items-center gap-3 mb-6 p-3 rounded-md"
          style={{
            background: "var(--surface)",
            boxShadow: "var(--elev-ring)",
          }}
        >
          {/* GPU Status */}
          <div
            className="flex items-center gap-2 px-2.5 py-1.5 rounded-sm text-xs"
            style={{ background: "var(--bg)" }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{
                background: systemHealth.gpu.available
                  ? "var(--success)"
                  : "var(--danger)",
              }}
            />
            <span style={{ color: "var(--fg-2)" }}>
              {systemHealth.gpu.available ? "GPU" : "CPU"}
            </span>
            <span style={{ color: "var(--meta)" }}>
              {systemHealth.gpu.encoder}
            </span>
          </div>
          {/* VRAM */}
          {systemHealth.gpu.vram_total_mb > 0 && (
            <div
              className="flex items-center gap-2 px-2.5 py-1.5 rounded-sm text-xs"
              style={{ background: "var(--bg)" }}
            >
              <div
                className="w-16 h-1.5 rounded-full overflow-hidden"
                style={{ background: "var(--border)" }}
              >
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${(systemHealth.gpu.vram_used_mb / systemHealth.gpu.vram_total_mb) * 100}%`,
                    background: "var(--accent)",
                  }}
                />
              </div>
              <span style={{ color: "var(--meta)" }}>
                {Math.round(systemHealth.gpu.vram_used_mb / 1024)}/
                {Math.round(systemHealth.gpu.vram_total_mb / 1024)}GB
              </span>
            </div>
          )}
          {/* GPU Utilization */}
          {systemHealth.gpu.utilization_pct > 0 && (
            <div
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-sm text-xs"
              style={{ background: "var(--bg)" }}
            >
              <Zap size={12} style={{ color: "var(--warn)" }} />
              <span style={{ color: "var(--meta)" }}>
                {systemHealth.gpu.utilization_pct}%
              </span>
            </div>
          )}
          {/* Queue Depth */}
          <div
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-sm text-xs"
            style={{ background: "var(--bg)" }}
          >
            <Clock size={12} style={{ color: "var(--accent)" }} />
            <span style={{ color: "var(--meta)" }}>
              Queue: {systemHealth.queue.depth}
            </span>
          </div>
        </div>
      )}

      {/* ── A) KPI Cards ── */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-10">
        <KpiCard
          label="Total Clips"
          value={totalClips.toString()}
          trend={{ value: "+12% this week", positive: true }}
        />
        <KpiCard label="Completed" value={completedTasks.toString()} />
        <KpiCard label="Processing" value={processingTasks.toString()} />
        <KpiCard label="Videos" value={safeTasks.length.toString()} />
      </div>

      {/* ── B) Jobs Table ── */}
      <div
        className="rounded-lg overflow-hidden"
        style={{
          background: "var(--surface)",
          boxShadow: "var(--elev-ring)",
        }}
      >
        {/* Table Header + Filters */}
        <div className="flex items-center justify-between px-5 py-3">
          <h2
            className="text-sm font-semibold"
            style={{ color: "var(--fg)" }}
          >
            Jobs
          </h2>
          <div className="flex items-center gap-1">
            {(["all", "processing", "completed"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className="px-2.5 py-1 rounded-md text-xs font-medium transition-all capitalize"
                style={
                  filter === f
                    ? {
                        background: "rgba(94,106,210,0.12)",
                        color: "var(--accent)",
                      }
                    : {
                        color: "var(--muted)",
                      }
                }
                onMouseEnter={(e) => {
                  if (filter !== f)
                    e.currentTarget.style.background =
                      "rgba(255,255,255,0.06)";
                }}
                onMouseLeave={(e) => {
                  if (filter !== f)
                    e.currentTarget.style.background = "transparent";
                }}
              >
                {f === "all"
                  ? "All"
                  : f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Loading State */}
        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2
              size={20}
              className="animate-spin"
              style={{ color: "var(--meta)" }}
            />
          </div>
        ) : paginatedTasks.length === 0 ? (
          <EmptyState onCreate={() => setIsCreateModalOpen(true)} />
        ) : (
          <>
            {/* Table */}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr
                    className="text-xs font-medium uppercase tracking-wider"
                    style={{
                      color: "var(--meta)",
                      borderTop: "1px solid var(--border)",
                    }}
                  >
                    <th className="text-left px-5 py-3 font-medium">
                      Name
                    </th>
                    <th className="text-left px-5 py-3 font-medium">
                      Clips
                    </th>
                    <th className="text-left px-5 py-3 font-medium">
                      Duration
                    </th>
                    <th className="text-left px-5 py-3 font-medium">
                      Date
                    </th>
                    <th className="text-left px-5 py-3 font-medium">
                      Status
                    </th>
                    <th className="w-10 px-5 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {paginatedTasks.map((task) => (
                    <tr
                      key={task.id}
                      className="transition-all"
                      style={{
                        borderTop: "1px solid var(--border-soft)",
                      }}
                      onMouseEnter={(e) =>
                        (e.currentTarget.style.background =
                          "rgba(255,255,255,0.03)")
                      }
                      onMouseLeave={(e) =>
                        (e.currentTarget.style.background = "transparent")
                      }
                    >
                      <td className="px-5 py-3">
                        <Link
                          href={`/tasks/${task.id}`}
                          className="font-medium transition-all"
                          style={{ color: "var(--fg)" }}
                          onMouseEnter={(e) =>
                            (e.currentTarget.style.color =
                              "var(--accent)")
                          }
                          onMouseLeave={(e) =>
                            (e.currentTarget.style.color = "var(--fg)")
                          }
                        >
                          {task.source_title ||
                            task.title ||
                            "Untitled Video"}
                        </Link>
                      </td>
                      <td
                        className="px-5 py-3"
                        style={{
                          color: "var(--fg-2)",
                          fontVariantNumeric: "tabular-nums",
                        }}
                      >
                        {task.clips_count ?? "\u2014"}
                      </td>
                      <td
                        className="px-5 py-3"
                        style={{
                          color: "var(--fg-2)",
                          fontVariantNumeric: "tabular-nums",
                        }}
                      >
                        {formatDuration(
                          (task as any).duration_seconds ?? undefined,
                        )}
                      </td>
                      <td
                        className="px-5 py-3 whitespace-nowrap"
                        style={{ color: "var(--meta)" }}
                      >
                        {formatRelativeTime(task.created_at)}
                      </td>
                      <td className="px-5 py-3">
                        <StatusBadge
                          status={task.status}
                          progress={task.progress}
                        />
                      </td>
                      <td className="px-5 py-3 text-right">
                        <button
                          onClick={() => handleDeleteTask(task.id)}
                          className="p-1 rounded-sm transition-all"
                          style={{ color: "var(--meta)" }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.color =
                              "var(--danger)";
                            e.currentTarget.style.background =
                              "rgba(220,38,38,0.1)";
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.color = "var(--meta)";
                            e.currentTarget.style.background = "transparent";
                          }}
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div
              className="flex items-center justify-between px-5 py-3"
              style={{ borderTop: "1px solid var(--border)" }}
            >
              <span className="text-xs" style={{ color: "var(--meta)" }}>
                Page {safePage} of {totalPages}
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={safePage <= 1}
                  className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                  style={{
                    color: "var(--fg-2)",
                    border: "1px solid var(--border)",
                    background: "var(--bg)",
                  }}
                  onMouseEnter={(e) => {
                    if (safePage > 1)
                      e.currentTarget.style.background = "rgba(255,255,255,0.06)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "var(--bg)";
                  }}
                >
                  <ChevronLeft size={14} />
                  Previous
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={safePage >= totalPages}
                  className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium transition-all disabled:opacity-30 disabled:cursor-not-allowed"
                  style={{
                    color: "var(--fg-2)",
                    border: "1px solid var(--border)",
                    background: "var(--bg)",
                  }}
                  onMouseEnter={(e) => {
                    if (safePage < totalPages)
                      e.currentTarget.style.background = "rgba(255,255,255,0.06)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = "var(--bg)";
                  }}
                >
                  Next
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Create Task Modal */}
      <CreateTaskModal
        isOpen={isCreateModalOpen}
        onClose={() => setIsCreateModalOpen(false)}
        onSubmit={handleCreateTask}
      />
    </div>
  );
}
