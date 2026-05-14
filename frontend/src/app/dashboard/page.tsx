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
  ArrowRight,
  BarChart3,
  Sparkles,
  X,
  Link2,
  Play,
  TrendingUp,
  Calendar,
  MoreVertical,
  Trash2,
  Video,
  Settings,
  LogOut,
  Zap,
  Smartphone,
  Monitor,
  Subtitles,
  Scissors,
  ScanEye
} from "lucide-react";
import Link from "next/link";
import { useSession, signOut } from "@/lib/auth-client";
import { useRouter } from "next/navigation";
import { ShimmerButton } from "@/components/ui/shimmer-button";
import { MagicCard } from "@/components/ui/magic-card";
import { cn } from "@/lib/utils";

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

function formatDate(dateString: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric",
  }).format(new Date(dateString));
}

function formatRelativeTime(dateString: string) {
  const date = new Date(dateString);
  const now = new Date();
  const diffInHours = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60));
  
  if (diffInHours < 1) return "Just now";
  if (diffInHours < 24) return `${diffInHours}h ago`;
  if (diffInHours < 48) return "Yesterday";
  return formatDate(dateString);
}

// Status Badge Component
const StatusBadge = memo(function StatusBadge({ status, progress }: { status: Task["status"]; progress?: number }) {
  const configs = {
    pending: { color: "text-amber-400 bg-amber-400/10 border-amber-400/20", icon: Clock, label: "Pending" },
    queued: { color: "text-blue-400 bg-blue-400/10 border-blue-400/20", icon: Loader2, label: "Queued" },
    processing: { color: "text-violet-400 bg-violet-400/10 border-violet-400/20", icon: Loader2, label: "Processing" },
    completed: { color: "text-green-400 bg-green-400/10 border-green-400/20", icon: CheckCircle, label: "Completed" },
    failed: { color: "text-red-400 bg-red-400/10 border-red-400/20", icon: AlertCircle, label: "Failed" },
  };
  
  const config = configs[status] || configs.pending;
  const Icon = config.icon;
  
  return (
    <div className={cn("inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-xs font-medium", config.color)}>
      <Icon className={cn("w-3.5 h-3.5", status === "processing" && "animate-spin")} />
      <span>{config.label}</span>
      {status === "processing" && progress !== undefined && (
        <span className="ml-1">{progress}%</span>
      )}
    </div>
  );
});

// Progress Bar Component
const ProgressBar = memo(function ProgressBar({ progress, status }: { progress: number; status: Task["status"] }) {
  const getColor = () => {
    if (status === "failed") return "bg-red-500";
    if (status === "completed") return "bg-green-500";
    return "bg-gradient-to-r from-violet-500 to-fuchsia-500";
  };
  
  return (
    <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden mt-3">
      <motion.div
        className={cn("h-full rounded-full", getColor())}
        initial={{ width: 0 }}
        animate={{ width: `${progress}%` }}
        transition={{ duration: 0.5, ease: "easeOut" }}
      />
    </div>
  );
});

// Task Card Component
const TaskCard = memo(function TaskCard({ task, onDelete }: { task: Task; onDelete?: (id: string) => void }) {
  const [showActions, setShowActions] = useState(false);
  
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className="group relative p-5 rounded-2xl bg-white/[0.02] border border-white/10 hover:border-violet-500/30 transition-all"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <StatusBadge status={task.status} progress={task.progress} />
            <span className="text-xs text-white/30">{formatRelativeTime(task.created_at)}</span>
          </div>
          
          <h3 className="font-medium text-white truncate mb-1">
            {task.source_title || task.title || "Untitled Video"}
          </h3>
          
          <p className="text-sm text-white/40 truncate">
            {task.progress_message || `${task.clips_count || 0} clips will be generated`}
          </p>
          
          {(task.status === "processing" || task.status === "queued") && task.progress !== undefined && (
            <ProgressBar progress={task.progress} status={task.status} />
          )}
        </div>
        
        <div className="flex items-center gap-2">
          {(task.status === "completed" || task.status === "processing") && (
            <Link href={`/tasks/${task.id}`}>
              <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-violet-500/20 text-violet-300 text-xs font-medium hover:bg-violet-500/30 transition-colors">
                <Play className="w-3.5 h-3.5" />
                {task.status === "completed" ? "View Clips" : "View Progress"}
              </button>
            </Link>
          )}
          
          <div className="relative">
            <button
              onClick={() => setShowActions(!showActions)}
              className="p-2 rounded-lg text-white/40 hover:text-white hover:bg-white/5 transition-colors"
            >
              <MoreVertical className="w-4 h-4" />
            </button>
            
            <AnimatePresence>
              {showActions && (
                <motion.div
                  initial={{ opacity: 0, y: 8, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 8, scale: 0.95 }}
                  className="absolute right-0 top-full mt-2 w-36 py-1 rounded-xl bg-[#13131a] border border-white/10 shadow-xl z-10"
                >
                  {onDelete && (
                    <button
                      onClick={() => { onDelete(task.id); setShowActions(false); }}
                      className="flex items-center gap-2 w-full px-3 py-2 text-sm text-red-400 hover:bg-red-500/10 transition-colors"
                    >
                      <Trash2 className="w-4 h-4" />
                      Delete
                    </button>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </motion.div>
  );
});

// Create Task Modal
interface TaskOptions {
  processing_mode: "fast" | "balanced" | "quality" | "elite";
  num_clips: number;
  output_format: "vertical" | "original";
  add_subtitles: boolean;
  jump_cut: boolean;
  use_scene_detection: boolean;
  auto_center_face: boolean;
  caption_template?: string;
}

function CreateTaskModal({ isOpen, onClose, onSubmit }: { 
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
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
            onClick={onClose}
          />
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-lg z-50"
          >
            <div className="p-6 rounded-3xl bg-[#13131a] border border-white/10 shadow-2xl">
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-500 flex items-center justify-center">
                    <Sparkles className="w-5 h-5 text-white" />
                  </div>
                  <div>
                    <h2 className="text-lg font-semibold text-white">Create New Clips</h2>
                    <p className="text-sm text-white/40">Paste a YouTube URL to get started</p>
                  </div>
                </div>
                <button
                  onClick={onClose}
                  className="p-2 rounded-lg text-white/40 hover:text-white hover:bg-white/5 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
              
              <form onSubmit={handleSubmit}>
                <div className="relative mb-4">
                  <Link2 className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/30" />
                  <input
                    ref={inputRef}
                    type="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://youtube.com/watch?v=..."
                    className="w-full pl-12 pr-4 py-4 rounded-xl bg-white/5 border border-white/10 text-white placeholder:text-white/30 focus:outline-none focus:border-violet-500/50 transition-colors"
                  />
                </div>
                
                {/* Options Grid */}
                <div className="grid grid-cols-2 gap-3 mb-4">
                  {/* Processing Mode */}
                  <div className="col-span-2">
                    <label className="text-xs text-white/50 mb-1.5 block">Processing Mode</label>
                    <div className="grid grid-cols-4 gap-2">
                      {(["fast", "balanced", "quality", "elite"] as const).map((mode) => (
                        <button
                          key={mode}
                          type="button"
                          onClick={() => setOptions({ ...options, processing_mode: mode })}
                          className={cn(
                            "px-3 py-2 rounded-lg text-xs font-medium transition-colors capitalize",
                            options.processing_mode === mode
                              ? "bg-violet-500/20 text-violet-300 border border-violet-500/30"
                              : "bg-white/5 text-white/60 border border-white/10 hover:bg-white/10"
                          )}
                        >
                          {mode}
                        </button>
                      ))}
                    </div>
                  </div>
                  
                  {/* Number of Clips */}
                  <div>
                    <label className="text-xs text-white/50 mb-1.5 block">Clips to Generate</label>
                    <select
                      value={options.num_clips}
                      onChange={(e) => setOptions({ ...options, num_clips: Number(e.target.value) })}
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white text-sm focus:outline-none focus:border-violet-500/50"
                    >
                      {[3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
                        <option key={n} value={n} className="bg-[#1a1a25]">{n} clips</option>
                      ))}
                    </select>
                  </div>
                  
                  {/* Output Format */}
                  <div>
                    <label className="text-xs text-white/50 mb-1.5 block">Format</label>
                    <div className="flex gap-2">
                      {([
                        { value: "vertical", label: "9:16", icon: Smartphone },
                        { value: "original", label: "Original", icon: Monitor },
                      ] as const).map(({ value, label, icon: Icon }) => (
                        <button
                          key={value}
                          type="button"
                          onClick={() => setOptions({ ...options, output_format: value })}
                          className={cn(
                            "flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors",
                            options.output_format === value
                              ? "bg-violet-500/20 text-violet-300 border border-violet-500/30"
                              : "bg-white/5 text-white/60 border border-white/10 hover:bg-white/10"
                          )}
                        >
                          <Icon className="w-3.5 h-3.5" />
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                  
                  {/* Caption Template */}
                  <div className="col-span-2">
                    <label className="text-xs text-white/50 mb-1.5 block">Estilo de subtítulos</label>
                    <select
                      value={options.caption_template || "hormozi"}
                      onChange={(e) => setOptions({ ...options, caption_template: e.target.value })}
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white text-sm focus:outline-none focus:border-violet-500/50"
                    >
                      <option value="hormozi" className="bg-[#1a1a25]">Hormozi — Palabra a palabra, impacto</option>
                      <option value="mrbeast" className="bg-[#1a1a25]">MrBeast — Frases cortas, energía alta</option>
                    </select>
                  </div>

                  {/* Toggle Options */}
                  <div className="col-span-2 grid grid-cols-3 gap-2">
                    <button
                      type="button"
                      onClick={() => setOptions({ ...options, add_subtitles: !options.add_subtitles })}
                      className={cn(
                        "flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-xs font-medium transition-colors",
                        options.add_subtitles
                          ? "bg-green-500/15 text-green-400 border border-green-500/30"
                          : "bg-white/5 text-white/40 border border-white/10 hover:bg-white/10"
                      )}
                    >
                      <Subtitles className="w-3.5 h-3.5" />
                      Subtitles
                    </button>
                    <button
                      type="button"
                      onClick={() => setOptions({ ...options, jump_cut: !options.jump_cut })}
                      className={cn(
                        "flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-xs font-medium transition-colors",
                        options.jump_cut
                          ? "bg-blue-500/15 text-blue-400 border border-blue-500/30"
                          : "bg-white/5 text-white/40 border border-white/10 hover:bg-white/10"
                      )}
                    >
                      <Scissors className="w-3.5 h-3.5" />
                      Jump Cuts
                    </button>
                    <button
                      type="button"
                      onClick={() => setOptions({ ...options, use_scene_detection: !options.use_scene_detection })}
                      className={cn(
                        "flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-xs font-medium transition-colors",
                        options.use_scene_detection
                          ? "bg-amber-500/15 text-amber-400 border border-amber-500/30"
                          : "bg-white/5 text-white/40 border border-white/10 hover:bg-white/10"
                      )}
                    >
                      <ScanEye className="w-3.5 h-3.5" />
                      Scene Detect
                    </button>
                  </div>
                </div>
                
                <div className="flex items-center gap-3 text-sm text-white/40 mb-6">
                  <span className="flex items-center gap-1.5">
                    <Clock className="w-4 h-4" />
                    Processing takes ~5 minutes
                  </span>
                </div>
                
                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={onClose}
                    className="flex-1 px-4 py-3 rounded-xl bg-white/5 text-white font-medium hover:bg-white/10 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={!url.trim() || isLoading}
                    className="flex-1 px-4 py-3 rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white font-medium hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                  >
                    {isLoading ? (
                      <Loader2 className="w-5 h-5 animate-spin" />
                    ) : (
                      <>
                        <Sparkles className="w-5 h-5" />
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

// Empty State Component
function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center py-20 text-center"
    >
      <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-violet-500/20 to-fuchsia-500/20 flex items-center justify-center mb-6">
        <Film className="w-10 h-10 text-violet-400" />
      </div>
      <h3 className="text-xl font-semibold text-white mb-2">No clips yet</h3>
      <p className="text-white/40 max-w-sm mb-6">
        Upload a video to get started. Our AI will automatically generate viral clips for you.
      </p>
      <ShimmerButton onClick={onCreate}>
        <Plus className="w-5 h-5" />
        Create Your First Clip
      </ShimmerButton>
    </motion.div>
  );
}

// Stats Card Component
function StatsCard({ title, value, trend, icon: Icon }: { 
  title: string; 
  value: string; 
  trend?: string;
  icon: React.ElementType;
}) {
  return (
    <MagicCard className="p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-white/40 mb-1">{title}</p>
          <p className="text-2xl font-semibold text-white">{value}</p>
          {trend && (
            <div className="flex items-center gap-1 mt-2 text-xs text-green-400">
              <TrendingUp className="w-3.5 h-3.5" />
              {trend}
            </div>
          )}
        </div>
        <div className="w-10 h-10 rounded-xl bg-white/5 flex items-center justify-center">
          <Icon className="w-5 h-5 text-violet-400" />
        </div>
      </div>
    </MagicCard>
  );
}

// Main Dashboard Component
export default function DashboardPage() {
  const { data: session } = useSession();
  const router = useRouter();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [filter, setFilter] = useState<"all" | "processing" | "completed">("all");
  
  // Fetch tasks
  const fetchTasks = useCallback(async () => {
    try {
      const res = await fetch("/api/tasks");
      if (res.ok) {
        const data = await res.json();
        // Handle both array response and object with tasks property
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
        // Redirect to task progress page
        if (data.task_id) {
          router.push(`/tasks/${data.task_id}`);
        }
      } else {
        const error = await res.json().catch(() => ({ error: "Unknown error" }));
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
    gpu: { available: boolean; encoder: string; utilization_pct: number; vram_used_mb: number; vram_total_mb: number };
    queue: { depth: number };
  } | null>(null);

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const res = await fetch("/api/health/system");
        if (res.ok) setSystemHealth(await res.json());
      } catch {}
    };
    fetchHealth();
    const interval = setInterval(fetchHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  // Calculate stats - memoized to prevent recalculation on every render
  const safeTasks = useMemo(() => (Array.isArray(tasks) ? tasks : []), [tasks]);
  const totalClips = useMemo(() => safeTasks.reduce((acc, t) => acc + (t.clips_count || 0), 0), [safeTasks]);
  const completedTasks = useMemo(() => safeTasks.filter((t) => t.status === "completed").length, [safeTasks]);
  const processingTasks = useMemo(() => safeTasks.filter((t) => t.status === "processing" || t.status === "queued").length, [safeTasks]);
  const failedTasks = useMemo(() => safeTasks.filter((t) => t.status === "failed").length, [safeTasks]);

  // Filter tasks - memoized
  const filteredTasks = useMemo(() => safeTasks.filter((task) => {
    if (filter === "all") return true;
    if (filter === "processing") return task.status === "processing" || task.status === "queued" || task.status === "pending";
    if (filter === "completed") return task.status === "completed";
    return true;
  }), [safeTasks, filter]);
  
  if (!session?.user) {
    return (
      <div className="min-h-screen bg-[#0A0A0F] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-violet-500 animate-spin" />
      </div>
    );
  }
  
  return (
    <div className="p-6 lg:p-8 max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl lg:text-3xl font-semibold text-white mb-1">
              Dashboard
            </h1>
            <p className="text-white/40">
              Manage your video clips and track processing status
            </p>
          </div>
          
          <ShimmerButton onClick={() => setIsCreateModalOpen(true)}>
            <Plus className="w-5 h-5" />
            Create New Clip
          </ShimmerButton>
        </div>
        
        {/* System Health Bar */}
        {systemHealth && (
          <div className="flex flex-wrap items-center gap-3 mb-6 p-3 rounded-xl bg-white/[0.02] border border-white/10">
            {/* GPU Status */}
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5">
              <span className={cn(
                "w-2 h-2 rounded-full",
                systemHealth.gpu.available ? "bg-green-500" : "bg-red-500"
              )} />
              <span className="text-xs font-medium text-white/70">
                {systemHealth.gpu.available ? "GPU" : "CPU"}
              </span>
              <span className="text-xs text-white/50">{systemHealth.gpu.encoder}</span>
            </div>
            {/* VRAM */}
            {systemHealth.gpu.vram_total_mb > 0 && (
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5">
                <div className="w-20 h-1.5 bg-white/10 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-violet-500 to-fuchsia-500"
                    style={{ width: `${(systemHealth.gpu.vram_used_mb / systemHealth.gpu.vram_total_mb) * 100}%` }}
                  />
                </div>
                <span className="text-xs text-white/50">
                  {Math.round(systemHealth.gpu.vram_used_mb / 1024)}/{Math.round(systemHealth.gpu.vram_total_mb / 1024)}GB
                </span>
              </div>
            )}
            {/* GPU Utilization */}
            {systemHealth.gpu.utilization_pct > 0 && (
              <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5">
                <Zap className="w-3 h-3 text-amber-400" />
                <span className="text-xs text-white/50">{systemHealth.gpu.utilization_pct}%</span>
              </div>
            )}
            {/* Queue Depth */}
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5">
              <Clock className="w-3 h-3 text-blue-400" />
              <span className="text-xs text-white/50">Queue: {systemHealth.queue.depth}</span>
            </div>
          </div>
        )}

        {/* Stats Grid */}
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <StatsCard
            title="Total Clips"
            value={totalClips.toString()}
            trend="+12% this week"
            icon={Film}
          />
          <StatsCard
            title="Completed"
            value={completedTasks.toString()}
            icon={CheckCircle}
          />
          <StatsCard
            title="Processing"
            value={processingTasks.toString()}
            icon={Loader2}
          />
          <StatsCard
            title="Videos"
            value={safeTasks.length.toString()}
            icon={Video}
          />
          <StatsCard
            title="Failed"
            value={failedTasks.toString()}
            icon={AlertCircle}
          />
        </div>
        
        {/* Filters */}
        <div className="flex items-center gap-2 mb-6 overflow-x-auto pb-2">
          {(["all", "processing", "completed"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                "px-4 py-2 rounded-full text-sm font-medium transition-colors whitespace-nowrap",
                filter === f
                  ? "bg-violet-500/20 text-violet-300 border border-violet-500/30"
                  : "bg-white/5 text-white/50 hover:bg-white/10 hover:text-white"
              )}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        
        {/* Tasks List */}
        <div className="space-y-3">
          <AnimatePresence mode="popLayout">
            {isLoading ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="w-8 h-8 text-violet-500 animate-spin" />
              </div>
            ) : filteredTasks.length === 0 ? (
              <EmptyState onCreate={() => setIsCreateModalOpen(true)} />
            ) : (
              filteredTasks.map((task) => (
                <TaskCard
                  key={task.id}
                  task={task}
                  onDelete={handleDeleteTask}
                />
              ))
            )}
          </AnimatePresence>
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
