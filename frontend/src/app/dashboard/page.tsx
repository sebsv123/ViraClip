"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import {
  Bolt, Plus, Video, Settings, LogOut, Film, Clock, CheckCircle,
  Loader2, AlertCircle, ArrowRight, BarChart3, Sparkles, X, Link2
} from "lucide-react";
import Link from "next/link";
import { useSession, signOut } from "@/lib/auth-client";
import { useRouter } from "next/navigation";

interface Task {
  id: string;
  title?: string;
  source_title?: string;
  source_type?: string;
  clips_count?: number;
  status: string;
  progress?: number;
  progress_message?: string;
  created_at: string;
}

function formatDate(dateString: string) {
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", year: "numeric",
  }).format(new Date(dateString));
}

function Sidebar() {
  const router = useRouter();
  const { data: session } = useSession();
  const user = session?.user;
  const navItems = [
    { icon: Video, label: "Dashboard", href: "/dashboard" },
    { icon: Film, label: "My Clips", href: "/list" },
    { icon: Settings, label: "Settings", href: "/settings" },
  ];
  const initials = user?.name
    ? user.name.split(" ").map((n: string) => n[0]).join("").slice(0, 2).toUpperCase()
    : user?.email?.[0]?.toUpperCase() ?? "?";

  return (
    <aside className="w-64 bg-[#0a0a0f] border-r border-white/5 min-h-screen flex flex-col">
      <div className="p-6">
        <Link href="/dashboard" className="flex items-center gap-3">
          <div className="relative w-10 h-10">
            <div className="absolute inset-0 bg-gradient-to-br from-cyan-400 via-purple-500 to-pink-500 rounded-xl" />
            <div className="absolute inset-[2px] bg-[#0a0a0f] rounded-xl flex items-center justify-center">
              <Bolt className="w-5 h-5 text-cyan-400" />
            </div>
          </div>
          <span className="text-xl font-bold">Vira<span className="text-cyan-400">Clip</span></span>
        </Link>
      </div>
      <nav className="flex-1 px-4">
        <div className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = typeof window !== "undefined" && window.location.pathname === item.href;
            return (
              <Link key={item.label} href={item.href}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all ${
                  active ? "bg-cyan-500/10 text-cyan-400 border border-cyan-500/20" : "text-gray-400 hover:bg-white/5 hover:text-white"
                }`}>
                <Icon className="w-5 h-5" />
                <span className="font-medium">{item.label}</span>
              </Link>
            );
          })}
        </div>
      </nav>
      <div className="p-4 border-t border-white/5 space-y-3">
        {/* User info card */}
        {user && (
          <div className="flex items-center gap-3 px-3 py-3 rounded-xl bg-white/5 border border-white/8">
            <div className="w-9 h-9 rounded-full bg-gradient-to-br from-cyan-500 to-purple-500 flex items-center justify-center flex-shrink-0 text-sm font-bold text-black">
              {initials}
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-white truncate">{user.name || "User"}</p>
              <p className="text-xs text-gray-500 truncate">{user.email}</p>
            </div>
            <div className="w-2 h-2 rounded-full bg-green-400 flex-shrink-0" title="Online" />
          </div>
        )}
        <button
          onClick={async () => { await signOut(); router.push("/sign-in"); }}
          className="flex items-center gap-3 px-4 py-2.5 w-full rounded-xl text-gray-400 hover:bg-red-500/10 hover:text-red-400 transition-all">
          <LogOut className="w-4 h-4" />
          <span className="font-medium text-sm">Sign Out</span>
        </button>
      </div>
    </aside>
  );
}

function TaskCard({ task }: { task: Task }) {
  const statusIcons: Record<string, React.ReactNode> = {
    completed: <CheckCircle className="w-5 h-5 text-green-400" />,
    processing: <Loader2 className="w-5 h-5 animate-spin text-cyan-400" />,
    queued: <Clock className="w-5 h-5 text-amber-400" />,
    failed: <AlertCircle className="w-5 h-5 text-red-400" />,
    needs_review: <Clock className="w-5 h-5 text-purple-400" />,
    fast_fail_editing_zero: <AlertCircle className="w-5 h-5 text-red-400" />,
  };
  const statusColors: Record<string, string> = {
    completed: "bg-green-500/10 border-green-500/20",
    processing: "bg-cyan-500/10 border-cyan-500/20",
    queued: "bg-amber-500/10 border-amber-500/20",
    failed: "bg-red-500/10 border-red-500/20",
    error: "bg-red-500/10 border-red-500/20",
    needs_review: "bg-purple-500/10 border-purple-500/20",
    fast_fail_editing_zero: "bg-orange-500/10 border-orange-500/20",
  };
  const title = task.title || task.source_title || "Untitled Project";
  return (
    <Link href={`/tasks/${task.id}`}>
      <div className={`p-5 rounded-2xl border ${statusColors[task.status] || "bg-white/5 border-white/10"} hover:scale-[1.02] transition-transform cursor-pointer group`}>
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500/20 to-purple-500/20 flex items-center justify-center">
              <Film className="w-6 h-6 text-cyan-400" />
            </div>
            <div>
              <h3 className="font-semibold text-white group-hover:text-cyan-400 transition-colors line-clamp-1">{title}</h3>
              <p className="text-sm text-gray-500">{task.source_type || "video"} &bull; {task.clips_count ?? 0} clips</p>
            </div>
          </div>
          {statusIcons[task.status] || <Clock className="w-5 h-5 text-gray-400" />}
        </div>
        {(task.status === "processing" || task.status === "queued") && (
          <div className="mb-3">
            <div className="flex justify-between text-xs text-gray-500 mb-1">
              <span>{task.status === "queued" ? "Waiting in queue..." : (task.progress_message || "Processing...")}</span>
              <span>{task.progress ?? 0}%</span>
            </div>
            <div className="w-full bg-white/10 rounded-full h-1.5">
              <div
                className="bg-cyan-400 h-1.5 rounded-full transition-all duration-500"
                style={{ width: `${task.progress ?? 0}%` }}
              />
            </div>
          </div>
        )}
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">{formatDate(task.created_at)}</span>
          <ArrowRight className="w-4 h-4 text-gray-500 group-hover:text-cyan-400 transition-colors" />
        </div>
      </div>
    </Link>
  );
}

function Toggle({ label, desc, checked, onChange }: { label: string; desc?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={`flex items-start gap-3 p-3 rounded-xl border transition-all text-left w-full ${checked ? "bg-cyan-500/10 border-cyan-500/30" : "bg-white/3 border-white/8 hover:border-white/20"}`}>
      <div className={`mt-0.5 w-4 h-4 rounded flex-shrink-0 flex items-center justify-center border transition-all ${checked ? "bg-cyan-500 border-cyan-500" : "border-white/30"}`}>
        {checked && <svg className="w-2.5 h-2.5 text-black" fill="none" viewBox="0 0 10 10"><path d="M1.5 5l2.5 2.5 4.5-4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
      </div>
      <div>
        <div className="text-sm font-medium text-white">{label}</div>
        {desc && <div className="text-xs text-gray-500 mt-0.5">{desc}</div>}
      </div>
    </button>
  );
}

function NewClipModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [url, setUrl] = useState("");
  const [mode, setMode] = useState("balanced");
  const [numClips, setNumClips] = useState(3);
  const [platform, setPlatform] = useState("all");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  // Feature toggles
  const [jumpCut, setJumpCut] = useState(true);
  const [zoomOnCuts, setZoomOnCuts] = useState(true);
  const [autoFace, setAutoFace] = useState(true);
  const [subtitles, setSubtitles] = useState(true);
  const [captionTemplate, setCaptionTemplate] = useState("pop_in");
  const [broll, setBroll] = useState(true);
  const [overlays, setOverlays] = useState(true);
  const [denoiseAudio, setDenoiseAudio] = useState(true);
  const [audioDucking, setAudioDucking] = useState(true);
  const [sceneDetection, setSceneDetection] = useState(true);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) { setError("Please enter a YouTube URL"); return; }
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/tasks/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: { url: url.trim() },
          processing_mode: mode,
          num_clips: numClips,
          target_platform: platform,
          // Video effects
          jump_cut: jumpCut,
          zoom_on_cuts: zoomOnCuts,
          auto_center_face: autoFace,
          use_scene_detection: sceneDetection,
          // Captions
          add_subtitles: subtitles,
          caption_template: captionTemplate,
          // B-roll & overlays
          include_broll: broll,
          contextual_overlays: overlays,
          // Audio
          denoise_audio: denoiseAudio,
          audio_ducking: audioDucking,
        }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data?.detail || data?.error || `Error ${res.status}`);
      }
      onCreated();
      onClose();
    } catch (err: any) {
      setError(err.message || "Failed to create task");
    } finally {
      setLoading(false);
    }
  };

  const inputCls = "w-full px-3 py-2.5 bg-white/5 border border-white/10 rounded-xl text-white text-sm focus:outline-none focus:border-cyan-500/50";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="w-full max-w-2xl bg-[#0e0e16] border border-white/10 rounded-2xl relative flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-white/5 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-cyan-500/20 to-purple-500/20 flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-cyan-400" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">New Clip Project</h2>
              <p className="text-xs text-gray-500">Configure features before generating</p>
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white p-1">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto flex-1 p-6 space-y-6">
          <form id="clip-form" onSubmit={handleSubmit}>
            {/* URL */}
            <div className="mb-5">
              <label className="block text-sm font-medium text-gray-300 mb-2">YouTube URL</label>
              <div className="relative">
                <Link2 className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                <input type="url" value={url} onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://www.youtube.com/watch?v=..."
                  className="w-full pl-10 pr-4 py-3 bg-white/5 border border-white/10 rounded-xl text-white placeholder-gray-600 focus:outline-none focus:border-cyan-500/50" />
              </div>
            </div>

            {/* Basic settings */}
            <div className="grid grid-cols-3 gap-3 mb-6">
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1.5">Mode</label>
                <select value={mode} onChange={(e) => setMode(e.target.value)} className={inputCls}>
                  <option value="fast">Fast ⚡</option>
                  <option value="balanced">Balanced</option>
                  <option value="quality">Quality ✨</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1.5">Clips</label>
                <input type="number" min={1} max={10} value={numClips}
                  onChange={(e) => setNumClips(Number(e.target.value))} className={inputCls} />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-400 mb-1.5">Platform</label>
                <select value={platform} onChange={(e) => setPlatform(e.target.value)} className={inputCls}>
                  <option value="all">All Platforms</option>
                  <option value="tiktok">TikTok</option>
                  <option value="reels">Reels</option>
                  <option value="shorts">Shorts</option>
                </select>
              </div>
            </div>

            {/* Video Effects */}
            <div className="mb-5">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Video Effects</p>
              <div className="grid grid-cols-2 gap-2">
                <Toggle label="Jump Cuts" desc="Remove silences automatically" checked={jumpCut} onChange={setJumpCut} />
                <Toggle label="Zoom on Cuts" desc="Dynamic zoom at each cut point" checked={zoomOnCuts} onChange={setZoomOnCuts} />
                <Toggle label="Auto Face Center" desc="Keep speaker centered in frame" checked={autoFace} onChange={setAutoFace} />
                <Toggle label="Scene Detection" desc="Detect scene changes for better cuts" checked={sceneDetection} onChange={setSceneDetection} />
              </div>
            </div>

            {/* Captions */}
            <div className="mb-5">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Captions</p>
              <Toggle label="Animated Captions" desc="Word-by-word animated subtitles" checked={subtitles} onChange={setSubtitles} />
              {subtitles && (
                <div className="mt-2">
                  <label className="block text-xs font-medium text-gray-400 mb-1.5">Caption Style</label>
                  <div className="grid grid-cols-3 gap-2">
                    {[["pop_in","Pop In 🔥"],["highlight","Highlight"],["fade","Fade"],["bounce","Bounce"],["karaoke","Karaoke"],["default","Default"]].map(([val, label]) => (
                      <button key={val} type="button" onClick={() => setCaptionTemplate(val)}
                        className={`py-2 px-3 rounded-lg text-xs font-medium border transition-all ${captionTemplate === val ? "bg-purple-500/20 border-purple-500/40 text-purple-300" : "bg-white/5 border-white/10 text-gray-400 hover:border-white/20"}`}>
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* B-roll & Overlays */}
            <div className="mb-5">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">B-Roll & Overlays</p>
              <div className="grid grid-cols-2 gap-2">
                <Toggle label="B-Roll Insertion" desc="Auto-insert relevant stock footage" checked={broll} onChange={setBroll} />
                <Toggle label="Contextual Overlays" desc="Topic-related image overlays" checked={overlays} onChange={setOverlays} />
              </div>
            </div>

            {/* Audio */}
            <div className="mb-5">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">Audio</p>
              <div className="grid grid-cols-2 gap-2">
                <Toggle label="Denoise Audio" desc="Remove background noise" checked={denoiseAudio} onChange={setDenoiseAudio} />
                <Toggle label="Audio Ducking" desc="Lower music under speech" checked={audioDucking} onChange={setAudioDucking} />
              </div>
            </div>

            {error && <p className="text-sm text-red-400 mb-3">{error}</p>}
          </form>
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-white/5 flex-shrink-0">
          <button form="clip-form" type="submit" disabled={loading}
            className="w-full py-3 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 text-black font-bold rounded-xl transition-all flex items-center justify-center gap-2">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
            {loading ? "Submitting..." : "Generate Viral Clips"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { data: session } = useSession();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);

  const loadTasks = useCallback(async () => {
    try {
      const res = await fetch("/api/tasks/");
      if (res.ok) {
        const data = await res.json();
        setTasks((data.tasks || []).slice(0, 6));
      }
    } catch (_) {}
    finally { setLoading(false); }
  }, []);

  const tasksRef = useRef<Task[]>([]);
  useEffect(() => { tasksRef.current = tasks; }, [tasks]);

  const isLoadingRef = useRef(false);

  useEffect(() => {
    loadTasks();
    const interval = setInterval(() => {
      const active = tasksRef.current.some((t) => t.status === "queued" || t.status === "processing");
      if (active && !isLoadingRef.current) {
        isLoadingRef.current = true;
        loadTasks().finally(() => { isLoadingRef.current = false; });
      }
    }, 10000);
    return () => clearInterval(interval);
  }, [loadTasks]);

  const completedCount = tasks.filter((t) => t.status === "completed").length;
  const totalClips = tasks.reduce((acc, t) => acc + (t.clips_count ?? 0), 0);

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white flex">
      {showModal && <NewClipModal onClose={() => setShowModal(false)} onCreated={loadTasks} />}
      <Sidebar />
      <main className="flex-1 overflow-auto">
        <header className="sticky top-0 z-40 bg-[#0a0a0f]/80 backdrop-blur-xl border-b border-white/5 px-8 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold">Dashboard</h1>
              <p className="text-sm text-gray-500">Welcome back{session?.user?.name ? `, ${session.user.name}` : ""}</p>
            </div>
            <button
              onClick={() => setShowModal(true)}
              className="flex items-center gap-2 px-6 py-3 bg-cyan-500 hover:bg-cyan-400 text-black font-semibold rounded-xl transition-all hover:shadow-[0_0_30px_-5px_rgba(34,211,238,0.5)]">
              <Plus className="w-5 h-5" />
              New Clip Project
            </button>
          </div>
        </header>

        <div className="p-8">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
              <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center mb-4">
                <Film className="w-5 h-5 text-cyan-400" />
              </div>
              <div className="text-2xl font-bold mb-1">{tasks.length}</div>
              <div className="text-sm text-gray-500">Total Projects</div>
            </div>
            <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
              <div className="w-10 h-10 rounded-lg bg-green-500/10 flex items-center justify-center mb-4">
                <CheckCircle className="w-5 h-5 text-green-400" />
              </div>
              <div className="text-2xl font-bold mb-1">{completedCount}</div>
              <div className="text-sm text-gray-500">Completed</div>
            </div>
            <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
              <div className="w-10 h-10 rounded-lg bg-purple-500/10 flex items-center justify-center mb-4">
                <Sparkles className="w-5 h-5 text-purple-400" />
              </div>
              <div className="text-2xl font-bold mb-1">{totalClips}</div>
              <div className="text-sm text-gray-500">Clips Generated</div>
            </div>
          </div>

          <div className="mb-8">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold">Recent Projects</h2>
              <Link href="/list" className="text-sm text-cyan-400 hover:text-cyan-300 flex items-center gap-1">
                View All <ArrowRight className="w-4 h-4" />
              </Link>
            </div>
            {loading ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {[1,2,3,4].map((i) => (
                  <div key={i} className="p-5 rounded-2xl bg-white/5 border border-white/10 animate-pulse h-32" />
                ))}
              </div>
            ) : tasks.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-cyan-500/10 to-purple-500/10 border border-white/10 flex items-center justify-center mb-6">
                  <Film className="w-10 h-10 text-gray-600" />
                </div>
                <h3 className="text-lg font-semibold text-gray-400 mb-2">No projects yet</h3>
                <p className="text-gray-600 mb-6">Click &quot;New Clip Project&quot; to generate your first viral clips</p>
                <button
                  onClick={() => setShowModal(true)}
                  className="flex items-center gap-2 px-6 py-3 bg-cyan-500 hover:bg-cyan-400 text-black font-semibold rounded-xl transition-all">
                  <Plus className="w-4 h-4" />
                  Create First Project
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {tasks.map((task) => <TaskCard key={task.id} task={task} />)}
              </div>
            )}
          </div>

          {tasks.length > 0 && (
            <div className="p-6 rounded-2xl bg-gradient-to-br from-cyan-500/10 to-purple-500/10 border border-cyan-500/20 flex items-center justify-between">
              <div>
                <h3 className="font-semibold text-white mb-1">Ready to create more clips?</h3>
                <p className="text-sm text-gray-500">Paste any YouTube URL and let the AI do the work</p>
              </div>
              <button
                onClick={() => setShowModal(true)}
                className="flex items-center gap-2 px-6 py-3 bg-cyan-500 hover:bg-cyan-400 text-black font-semibold rounded-xl transition-all whitespace-nowrap">
                <Plus className="w-4 h-4" />
                New Project
              </button>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}