"use client";

import { useParams } from "next/navigation";
import { useState, useEffect } from "react";
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
  Check
} from "lucide-react";
import Link from "next/link";
import { api } from "@/lib/api-client";

interface Clip {
  id: string;
  task_id: string;
  filename: string;
  duration: number;
  viral_score?: number;
  rating?: number;
  thumbs?: 'thumbs_up' | 'thumbs_down' | 'neutral';
  created_at: string;
}

export default function ClipDetailPage() {
  const params = useParams();
  const clipId = params.id as string;
  const { data: session } = useSession();
  const [clip, setClip] = useState<Clip | null>(null);
  const [loading, setLoading] = useState(true);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (session?.user?.id) {
      loadClip();
    }
  }, [clipId, session]);

  const loadClip = async () => {
    try {
      setLoading(true);
      const data = await api.getClip(clipId, session!.user.id);
      setClip(data);
      setFeedback(data.thumbs || null);
    } catch (error) {
      console.error('Failed to load clip:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleFeedback = async (thumbs: 'thumbs_up' | 'thumbs_down') => {
    if (!session?.user?.id || !clip) return;
    
    try {
      await api.thumbsClip(clipId, thumbs, session.user.id, clip.task_id);
      setFeedback(thumbs);
      setClip({ ...clip, thumbs });
    } catch (error) {
      console.error('Failed to submit feedback:', error);
    }
  };

  const handleDownload = async (preset?: string) => {
    if (!session?.user?.id) return;

    try {
      const blob = await api.downloadClip(clipId, session.user.id, preset);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `viraclip-${clipId}${preset ? `-${preset}` : ''}.mp4`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Failed to download clip:', error);
    }
  };

  const handleShare = () => {
    const shareUrl = `${window.location.origin}/dashboard/clips/${clipId}`;
    navigator.clipboard.writeText(shareUrl);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const formatDuration = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const formatDate = (dateString: string) => {
    return new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    }).format(new Date(dateString));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Loader2 className="w-8 h-8 animate-spin text-cyan-400" />
      </div>
    );
  }

  if (!clip) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen">
        <div className="text-center">
          <h2 className="text-2xl font-bold text-white mb-2">Clip not found</h2>
          <p className="text-gray-400 mb-6">This clip doesn't exist or you don't have access to it.</p>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 px-6 py-3 bg-cyan-500 hover:bg-cyan-400 text-black font-semibold rounded-xl transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  const videoUrl = api.getClipUrl(clip.filename);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Back button */}
      <Link
        href="/dashboard"
        className="inline-flex items-center gap-2 text-gray-400 hover:text-white transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Dashboard
      </Link>

      {/* Video Player */}
      <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden">
        <video
          src={videoUrl}
          controls
          className="w-full aspect-video bg-black"
          preload="metadata"
        >
          Your browser does not support the video tag.
        </video>
      </div>

      {/* Clip Info & Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Metadata */}
        <div className="lg:col-span-2 space-y-6">
          {/* Details Card */}
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
            <h2 className="text-xl font-bold text-white mb-4">Clip Details</h2>
            
            <div className="grid grid-cols-2 gap-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-purple-500/10 flex items-center justify-center">
                  <Clock className="w-5 h-5 text-purple-400" />
                </div>
                <div>
                  <div className="text-sm text-gray-400">Duration</div>
                  <div className="text-lg font-semibold text-white">
                    {formatDuration(clip.duration)}
                  </div>
                </div>
              </div>

              {clip.viral_score && (
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center">
                    <Zap className="w-5 h-5 text-cyan-400" />
                  </div>
                  <div>
                    <div className="text-sm text-gray-400">Viral Score</div>
                    <div className="text-lg font-semibold text-white">
                      {clip.viral_score}/100
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="mt-4 pt-4 border-t border-gray-800">
              <div className="text-sm text-gray-400">Created</div>
              <div className="text-white">{formatDate(clip.created_at)}</div>
            </div>
          </div>

          {/* Feedback Card */}
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
            <h3 className="text-lg font-semibold text-white mb-4">How's this clip?</h3>
            <p className="text-sm text-gray-400 mb-4">
              Your feedback helps our AI improve future clips
            </p>

            <div className="flex gap-3">
              <button
                onClick={() => handleFeedback('thumbs_up')}
                className={`flex-1 flex items-center justify-center gap-2 px-6 py-3 rounded-xl font-medium transition-all ${
                  feedback === 'thumbs_up'
                    ? 'bg-green-500/20 border-2 border-green-500/40 text-green-400'
                    : 'bg-gray-800 border border-gray-700 text-gray-400 hover:border-green-500/40 hover:text-green-400'
                }`}
              >
                <ThumbsUp className="w-5 h-5" />
                Great Clip
              </button>

              <button
                onClick={() => handleFeedback('thumbs_down')}
                className={`flex-1 flex items-center justify-center gap-2 px-6 py-3 rounded-xl font-medium transition-all ${
                  feedback === 'thumbs_down'
                    ? 'bg-red-500/20 border-2 border-red-500/40 text-red-400'
                    : 'bg-gray-800 border border-gray-700 text-gray-400 hover:border-red-500/40 hover:text-red-400'
                }`}
              >
                <ThumbsDown className="w-5 h-5" />
                Needs Work
              </button>
            </div>
          </div>
        </div>

        {/* Right: Actions */}
        <div className="space-y-4">
          {/* Download Card */}
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
            <h3 className="text-lg font-semibold text-white mb-4">Download</h3>
            
            <div className="space-y-2">
              <button
                onClick={() => handleDownload()}
                className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-cyan-500 hover:bg-cyan-400 text-black font-semibold rounded-xl transition-colors"
              >
                <Download className="w-4 h-4" />
                Download Original
              </button>

              <button
                onClick={() => handleDownload('tiktok')}
                className="w-full flex items-center gap-2 px-4 py-3 bg-gray-800 hover:bg-gray-700 text-white rounded-xl transition-colors"
              >
                <Download className="w-4 h-4" />
                TikTok (9:16)
              </button>

              <button
                onClick={() => handleDownload('instagram')}
                className="w-full flex items-center gap-2 px-4 py-3 bg-gray-800 hover:bg-gray-700 text-white rounded-xl transition-colors"
              >
                <Download className="w-4 h-4" />
                Instagram Reels (9:16)
              </button>

              <button
                onClick={() => handleDownload('youtube')}
                className="w-full flex items-center gap-2 px-4 py-3 bg-gray-800 hover:bg-gray-700 text-white rounded-xl transition-colors"
              >
                <Download className="w-4 h-4" />
                YouTube Shorts (9:16)
              </button>
            </div>
          </div>

          {/* Share Card */}
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
            <h3 className="text-lg font-semibold text-white mb-4">Share</h3>
            
            <button
              onClick={handleShare}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-gray-800 hover:bg-gray-700 text-white rounded-xl transition-colors"
            >
              {copied ? (
                <>
                  <Check className="w-4 h-4 text-green-400" />
                  <span className="text-green-400">Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="w-4 h-4" />
                  Copy Share Link
                </>
              )}
            </button>
          </div>

          {/* Tips Card */}
          <div className="bg-gradient-to-br from-purple-500/10 to-pink-500/10 border border-purple-500/20 rounded-2xl p-6">
            <h4 className="text-sm font-semibold text-purple-300 mb-2">💡 Pro Tip</h4>
            <p className="text-xs text-gray-400">
              Post your clips at peak hours (6-9 PM) for maximum engagement. 
              Use trending sounds and hashtags for better reach!
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
