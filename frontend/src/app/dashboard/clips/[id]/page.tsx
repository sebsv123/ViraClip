"use client";

import { useParams, useRouter } from "next/navigation";
import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useSession } from "@/lib/auth-client";
import {
  Play,
  Download,
  Share2,
  ThumbsUp,
  ThumbsDown,
  Clock,
  Zap,
  ArrowLeft,
  Loader2,
  Copy,
  Check,
  Star,
  TrendingUp,
  MessageSquare,
  AlertCircle,
  Film,
  ChevronRight
} from "lucide-react";
import Link from "next/link";
import { AppShell } from "@/components/app-shell";
import { VideoPlayer } from "@/components/video-player";
import { MagicCard } from "@/components/ui/magic-card";
import { ShimmerButton } from "@/components/ui/shimmer-button";
import { cn } from "@/lib/utils";

interface Clip {
  id: string;
  task_id: string;
  filename: string;
  file_path: string;
  duration: number;
  start_time?: string;
  end_time?: string;
  viral_score?: number;
  virality_score?: number;
  hook_score?: number;
  engagement_score?: number;
  shareability_score?: number;
  rating?: number;
  thumbs?: 'thumbs_up' | 'thumbs_down' | 'neutral';
  created_at: string;
  text?: string;
  social_title?: string;
  social_description?: string;
  suggested_hashtags?: string[];
  thumbnail_url?: string;
  hook_type?: string;
  reasoning?: string;
}

interface Task {
  id: string;
  source_title: string;
  source_type: string;
  status: string;
  created_at: string;
}

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function formatDate(dateString: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric"
  }).format(new Date(dateString));
}

// Score Bar Component
function ScoreBar({ label, score, color }: { label: string; score: number; color: string }) {
  const colors: Record<string, string> = {
    green: "from-green-500 to-emerald-500",
    blue: "from-blue-500 to-cyan-500",
    purple: "from-violet-500 to-fuchsia-500",
    orange: "from-orange-500 to-amber-500",
  };

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <span className="text-white/60">{label}</span>
        <span className="text-white font-medium">{score.toFixed(1)}</span>
      </div>
      <div className="h-2 bg-white/10 rounded-full overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${(score / 10) * 100}%` }}
          transition={{ duration: 0.8, delay: 0.2 }}
          className={cn("h-full rounded-full bg-gradient-to-r", colors[color] || colors.purple)}
        />
      </div>
    </div>
  );
}

// Empty State
function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="w-16 h-16 rounded-2xl bg-white/5 flex items-center justify-center mb-4">
        <Film className="w-8 h-8 text-white/30" />
      </div>
      <h3 className="text-lg font-medium text-white mb-2">Clip not found</h3>
      <p className="text-white/40 text-sm mb-6">The clip you're looking for doesn't exist or has been deleted.</p>
      <Link href="/dashboard">
        <ShimmerButton variant="outline">
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </ShimmerButton>
      </Link>
    </div>
  );
}

export default function ClipDetailPage() {
  const params = useParams();
  const router = useRouter();
  const clipId = params.id as string;
  const { data: session } = useSession();
  
  const [clip, setClip] = useState<Clip | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(true);
  const [feedback, setFeedback] = useState<string>("");
  const [copied, setCopied] = useState(false);
  const [thumbs, setThumbs] = useState<'thumbs_up' | 'thumbs_down' | 'neutral' | null>(null);
  const [isSubmittingFeedback, setIsSubmittingFeedback] = useState(false);

  useEffect(() => {
    if (session?.user?.id && clipId) {
      loadClip();
    }
  }, [clipId, session]);

  const loadClip = async () => {
    try {
      setLoading(true);
      const res = await fetch(`/api/clips/${clipId}`);
      if (res.ok) {
        const data = await res.json();
        setClip(data.clip);
        setTask(data.task);
        setThumbs(data.clip.thumbs || null);
      }
    } catch (error) {
      console.error("Failed to load clip:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async () => {
    if (!clip) return;
    
    try {
      const res = await fetch(`/api/clips/${clipId}/download`);
      if (res.ok) {
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = clip.filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);
      }
    } catch (error) {
      console.error("Download failed:", error);
    }
  };

  const handleShare = async () => {
    if (!clip) return;
    
    try {
      await navigator.clipboard.writeText(`${window.location.origin}/dashboard/clips/${clipId}`);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
    }
  };

  const handleThumbs = async (type: 'thumbs_up' | 'thumbs_down') => {
    if (!clip || thumbs === type) return;
    
    try {
      const res = await fetch(`/api/clips/${clipId}/thumbs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating: type, task_id: clip?.task_id }),
      });
      
      if (res.ok) {
        setThumbs(type);
      }
    } catch (error) {
      console.error("Failed to rate:", error);
    }
  };

  const submitFeedback = async () => {
    if (!clip || !feedback.trim()) return;
    
    setIsSubmittingFeedback(true);
    try {
      await fetch(`/api/clips/${clipId}/thumbs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating: "neutral", task_id: clip?.task_id, feedback_text: feedback }),
      });
      setFeedback("");
    } catch (error) {
      console.error("Failed to submit feedback:", error);
    } finally {
      setIsSubmittingFeedback(false);
    }
  };

  if (!session?.user) {
    return (
      <div className="min-h-screen bg-[#0A0A0F] flex items-center justify-center">
        <Loader2 className="w-8 h-8 text-violet-500 animate-spin" />
      </div>
    );
  }

  if (loading) {
    return (
      <AppShell user={session.user}>
        <div className="p-6 lg:p-8">
          <div className="flex items-center gap-2 mb-8">
            <div className="w-8 h-8 rounded-lg bg-white/5 animate-pulse" />
            <div className="w-32 h-4 bg-white/5 rounded animate-pulse" />
          </div>
          <div className="aspect-video bg-white/5 rounded-2xl animate-pulse mb-6" />
          <div className="grid lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-4">
              <div className="h-8 bg-white/5 rounded animate-pulse" />
              <div className="h-4 bg-white/5 rounded animate-pulse w-2/3" />
            </div>
            <div className="space-y-4">
              <div className="h-32 bg-white/5 rounded-xl animate-pulse" />
            </div>
          </div>
        </div>
      </AppShell>
    );
  }

  if (!clip) {
    return (
      <AppShell user={session.user}>
        <div className="p-6 lg:p-8">
          <EmptyState />
        </div>
      </AppShell>
    );
  }

  const videoUrl = `/api/clips/${clipId}/stream`;
  const viralityScores = [
    { label: "Overall", score: clip.viral_score || clip.virality_score || 0, color: "purple" },
    { label: "Hook", score: clip.hook_score || 0, color: "blue" },
    { label: "Engagement", score: clip.engagement_score || 0, color: "green" },
    { label: "Shareability", score: clip.shareability_score || 0, color: "orange" },
  ];

  return (
    <AppShell user={session.user}>
      <div className="p-6 lg:p-8 max-w-7xl mx-auto">
        {/* Breadcrumbs */}
        <div className="flex items-center gap-2 text-sm text-white/40 mb-6">
          <Link href="/dashboard" className="hover:text-white transition-colors">
            Dashboard
          </Link>
          <ChevronRight className="w-4 h-4" />
          <Link href="/list" className="hover:text-white transition-colors">
            My Clips
          </Link>
          <ChevronRight className="w-4 h-4" />
          <span className="text-white">Clip Details</span>
        </div>

        {/* Header */}
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl lg:text-3xl font-semibold text-white mb-2">
              {clip.social_title || `Clip from ${task?.source_title || "Unknown Video"}`}
            </h1>
            <div className="flex items-center gap-4 text-sm text-white/40">
              <span className="flex items-center gap-1.5">
                <Clock className="w-4 h-4" />
                {formatDuration(clip.duration)}
              </span>
              <span>•</span>
              <span>{formatDate(clip.created_at)}</span>
              {clip.hook_type && (
                <>
                  <span>•</span>
                  <span className="px-2 py-0.5 rounded-full bg-violet-500/20 text-violet-300 text-xs">
                    {clip.hook_type}
                  </span>
                </>
              )}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={handleShare}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-white/5 text-white hover:bg-white/10 transition-colors"
            >
              {copied ? <Check className="w-4 h-4" /> : <Share2 className="w-4 h-4" />}
              <span className="hidden sm:inline">{copied ? "Copied!" : "Share"}</span>
            </button>
            <ShimmerButton onClick={handleDownload}>
              <Download className="w-4 h-4" />
              Download
            </ShimmerButton>
          </div>
        </div>

        {/* Main Content Grid */}
        <div className="grid lg:grid-cols-3 gap-8">
          {/* Left Column - Video */}
          <div className="lg:col-span-2 space-y-6">
            <VideoPlayer
              src={videoUrl}
              poster={clip.thumbnail_url}
              title={clip.social_title}
              onDownload={handleDownload}
              onShare={handleShare}
              className="shadow-2xl"
            />

            {/* AI Analysis */}
            {clip.reasoning && (
              <MagicCard className="p-5">
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500/20 to-fuchsia-500/20 flex items-center justify-center flex-shrink-0">
                    <Zap className="w-5 h-5 text-violet-400" />
                  </div>
                  <div>
                    <h3 className="font-medium text-white mb-1">AI Analysis</h3>
                    <p className="text-sm text-white/60 leading-relaxed">{clip.reasoning}</p>
                  </div>
                </div>
              </MagicCard>
            )}

            {/* Transcript */}
            {clip.text && (
              <div className="p-5 rounded-2xl bg-white/[0.02] border border-white/10">
                <h3 className="font-medium text-white mb-3">Transcript</h3>
                <p className="text-sm text-white/60 leading-relaxed">{clip.text}</p>
              </div>
            )}

            {/* Feedback Section */}
            <div className="p-5 rounded-2xl bg-white/[0.02] border border-white/10">
              <h3 className="font-medium text-white mb-4">Rate this clip</h3>
              
              <div className="flex items-center gap-3 mb-4">
                <button
                  onClick={() => handleThumbs('thumbs_up')}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 rounded-xl transition-all",
                    thumbs === 'thumbs_up'
                      ? "bg-green-500/20 text-green-400 border border-green-500/30"
                      : "bg-white/5 text-white/60 hover:bg-white/10"
                  )}
                >
                  <ThumbsUp className="w-4 h-4" />
                  Helpful
                </button>
                <button
                  onClick={() => handleThumbs('thumbs_down')}
                  className={cn(
                    "flex items-center gap-2 px-4 py-2 rounded-xl transition-all",
                    thumbs === 'thumbs_down'
                      ? "bg-red-500/20 text-red-400 border border-red-500/30"
                      : "bg-white/5 text-white/60 hover:bg-white/10"
                  )}
                >
                  <ThumbsDown className="w-4 h-4" />
                  Not helpful
                </button>
              </div>

              <div className="flex gap-2">
                <input
                  type="text"
                  value={feedback}
                  onChange={(e) => setFeedback(e.target.value)}
                  placeholder="Additional feedback (optional)..."
                  className="flex-1 px-4 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white placeholder:text-white/30 focus:outline-none focus:border-violet-500/50"
                />
                <button
                  onClick={submitFeedback}
                  disabled={!feedback.trim() || isSubmittingFeedback}
                  className="px-4 py-2.5 rounded-xl bg-violet-500/20 text-violet-300 font-medium hover:bg-violet-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isSubmittingFeedback ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                  ) : (
                    <MessageSquare className="w-5 h-5" />
                  )}
                </button>
              </div>
            </div>
          </div>

          {/* Right Column - Stats & Info */}
          <div className="space-y-6">
            {/* Virality Scores */}
            <MagicCard className="p-5">
              <div className="flex items-center gap-2 mb-5">
                <TrendingUp className="w-5 h-5 text-violet-400" />
                <h3 className="font-medium text-white">Virality Scores</h3>
              </div>
              <div className="space-y-4">
                {viralityScores.map((score) => (
                  <ScoreBar
                    key={score.label}
                    label={score.label}
                    score={score.score}
                    color={score.color}
                  />
                ))}
              </div>
            </MagicCard>

            {/* Social Copy */}
            {(clip.social_title || clip.social_description || clip.suggested_hashtags) && (
              <MagicCard className="p-5">
                <div className="flex items-center gap-2 mb-4">
                  <MessageSquare className="w-5 h-5 text-violet-400" />
                  <h3 className="font-medium text-white">Social Copy</h3>
                </div>
                
                {clip.social_title && (
                  <div className="mb-4">
                    <p className="text-xs text-white/40 mb-1">Title</p>
                    <p className="text-sm text-white">{clip.social_title}</p>
                  </div>
                )}
                
                {clip.social_description && (
                  <div className="mb-4">
                    <p className="text-xs text-white/40 mb-1">Description</p>
                    <p className="text-sm text-white/80">{clip.social_description}</p>
                  </div>
                )}
                
                {clip.suggested_hashtags && clip.suggested_hashtags.length > 0 && (
                  <div>
                    <p className="text-xs text-white/40 mb-2">Hashtags</p>
                    <div className="flex flex-wrap gap-2">
                      {clip.suggested_hashtags.map((tag) => (
                        <span
                          key={tag}
                          className="px-2 py-1 rounded-lg bg-white/5 text-white/60 text-xs"
                        >
                          #{tag}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </MagicCard>
            )}

            {/* Source Info */}
            {task && (
              <div className="p-5 rounded-2xl bg-white/[0.02] border border-white/10">
                <h3 className="font-medium text-white mb-3">Source</h3>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-white/40">Video</span>
                    <span className="text-white truncate max-w-[150px]">{task.source_title}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-white/40">Type</span>
                    <span className="text-white capitalize">{task.source_type}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-white/40">Created</span>
                    <span className="text-white">{formatDate(task.created_at)}</span>
                  </div>
                </div>
              </div>
            )}

            {/* Quick Actions */}
            <div className="p-5 rounded-2xl bg-gradient-to-br from-violet-500/10 to-fuchsia-500/10 border border-violet-500/20">
              <h3 className="font-medium text-white mb-4">Quick Actions</h3>
              <div className="space-y-2">
                <button
                  onClick={handleDownload}
                  className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-white/5 text-white hover:bg-white/10 transition-colors"
                >
                  <Download className="w-4 h-4" />
                  Download Clip
                </button>
                <Link href={`/tasks/${clip.task_id}`} className="block">
                  <button className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-white/5 text-white hover:bg-white/10 transition-colors">
                    <ArrowLeft className="w-4 h-4" />
                    View Full Task
                  </button>
                </Link>
              </div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
