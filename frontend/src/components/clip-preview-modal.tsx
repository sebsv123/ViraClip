"use client";

import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  X,
  Play,
  Pause,
  Volume2,
  VolumeX,
  Sparkles,
  TrendingUp,
  Target,
  Zap,
  Share2,
  Shuffle,
  Music,
  Download,
  Subtitles,
} from "lucide-react";

/* ─────────────────────────────────────────────
   Types
   ───────────────────────────────────────────── */

interface ClipPreviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  clip: {
    filename: string;
    video_url: string;
    duration: number;
    virality_score: number;
    hook_score?: number;
    engagement_score?: number;
    value_score?: number;
    shareability_score?: number;
    hook_type?: string | null;
    social_title?: string | null;
    social_description?: string | null;
    suggested_hashtags?: string[];
    cta_overlay_applied?: boolean;
    emoji_overlays_applied?: boolean;
    variants?: Array<{
      path: string;
      variant: string;
      label: string;
      type: string;
    }>;
  };
}

/* ─────────────────────────────────────────────
   Helpers
   ───────────────────────────────────────────── */

function formatDuration(seconds: number) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function getScoreColor(score: number): string {
  if (score >= 8) return "var(--success)";
  if (score >= 6) return "var(--warn)";
  if (score >= 4) return "var(--danger)";
  return "var(--danger)";
}

/* ─────────────────────────────────────────────
   Score bar — Linear style
   ───────────────────────────────────────────── */

function ScoreBar({ label, score, icon: Icon }: { label: string; score: number; icon: React.ElementType }) {
  return (
    <div
      className="flex items-center justify-between px-3 py-2.5 rounded-sm transition-all"
      style={{
        background: "rgba(255,255,255,0.02)",
        border: "1px solid var(--border-soft)",
      }}
    >
      <div className="flex items-center gap-2">
        <Icon size={14} style={{ color: "var(--meta)" }} />
        <span className="text-xs font-medium" style={{ color: "var(--fg-2)" }}>
          {label}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <div
          style={{
            width: 80,
            height: 4,
            background: "rgba(255,255,255,0.08)",
            borderRadius: "var(--radius-pill)",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              width: `${score * 10}%`,
              height: "100%",
              background: getScoreColor(score),
              borderRadius: "var(--radius-pill)",
              transition: "width var(--motion-base) var(--ease-standard)",
            }}
          />
        </div>
        <span
          className="text-xs font-semibold"
          style={{
            color: getScoreColor(score),
            fontVariantNumeric: "tabular-nums",
            minWidth: 28,
            textAlign: "right",
          }}
        >
          {score}
        </span>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────
   Component
   ───────────────────────────────────────────── */

export function ClipPreviewModal({ isOpen, onClose, clip }: ClipPreviewModalProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [progress, setProgress] = useState(0);
  const progressBarRef = useRef<HTMLDivElement>(null);

  /* ── Video controls ── */
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const onTimeUpdate = () => {
      setProgress(video.currentTime / video.duration);
    };
    const onPlay = () => setIsPlaying(true);
    const onPause = () => setIsPlaying(false);

    video.addEventListener("timeupdate", onTimeUpdate);
    video.addEventListener("play", onPlay);
    video.addEventListener("pause", onPause);

    return () => {
      video.removeEventListener("timeupdate", onTimeUpdate);
      video.removeEventListener("play", onPlay);
      video.removeEventListener("pause", onPause);
    };
  }, [isOpen]);

  const togglePlay = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) video.play();
    else video.pause();
  };

  const toggleMute = () => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !video.muted;
    setIsMuted(video.muted);
  };

  const handleProgressClick = (e: React.MouseEvent) => {
    const bar = progressBarRef.current;
    const video = videoRef.current;
    if (!bar || !video) return;
    const rect = bar.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    video.currentTime = x * video.duration;
  };

  /* ── Hook type description ── */
  const hookDescriptions: Record<string, string> = {
    question: "Abre con una pregunta convincente que crea curiosidad.",
    statement: "Afirmación audaz que capta la atención de inmediato.",
    statistic: "Hook basado en datos que genera credibilidad.",
    story: "Hook narrativo que construye conexión emocional.",
    contrast: "Comparación antes/después que muestra transformación.",
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Overlay */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-[1000]"
            style={{
              background: "rgba(0,0,0,0.7)",
              backdropFilter: "blur(4px)",
            }}
            onClick={onClose}
          />

          {/* Container */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 12 }}
            transition={{ duration: 0.2, ease: [0.2, 0, 0, 1] }}
            className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-[1000] flex flex-col"
            style={{
              width: 420,
              maxHeight: "90dvh",
              background: "var(--surface)",
              boxShadow: "var(--elev-raised)",
              border: "var(--elev-ring)",
              borderRadius: "var(--radius-lg)",
              overflow: "hidden",
            }}
          >
            {/* ── Header ── */}
            <div
              className="flex items-center justify-between shrink-0"
              style={{
                height: 48,
                padding: "0 var(--space-4)",
                borderBottom: "1px solid var(--border)",
              }}
            >
              <span
                className="text-sm font-medium"
                style={{
                  color: "var(--fg)",
                  fontWeight: 510,
                  fontFeatureSettings: '"cv01", "ss03"',
                }}
              >
                Clip Preview
              </span>
              <button
                onClick={onClose}
                className="p-1 rounded-sm transition-all"
                style={{ color: "var(--muted)" }}
                onMouseEnter={(e) => (e.currentTarget.style.color = "var(--fg)")}
                onMouseLeave={(e) => (e.currentTarget.style.color = "var(--muted)")}
              >
                <X size={16} />
              </button>
            </div>

            {/* ── Scrollable content ── */}
            <div className="flex-1 overflow-y-auto">
              {/* Video zone */}
              <div
                style={{
                  aspectRatio: "9/16",
                  background: "#000",
                  width: "100%",
                  maxHeight: "60dvh",
                  position: "relative",
                }}
              >
                <video
                  ref={videoRef}
                  src={clip.video_url}
                  autoPlay
                  loop
                  className="w-full h-full"
                  style={{ objectFit: "contain" }}
                />

                {/* Custom video controls */}
                <div
                  className="absolute bottom-0 left-0 right-0 flex items-center gap-2 px-3 py-2"
                  style={{
                    background: "linear-gradient(transparent, rgba(0,0,0,0.7))",
                  }}
                >
                  {/* Play/Pause */}
                  <button
                    onClick={togglePlay}
                    className="p-0.5 rounded-sm transition-all"
                    style={{ color: "var(--fg-2)" }}
                    onMouseEnter={(e) => (e.currentTarget.style.color = "var(--fg)")}
                    onMouseLeave={(e) => (e.currentTarget.style.color = "var(--fg-2)")}
                  >
                    {isPlaying ? <Pause size={18} /> : <Play size={18} />}
                  </button>

                  {/* Progress bar */}
                  <div
                    ref={progressBarRef}
                    onClick={handleProgressClick}
                    className="flex-1 cursor-pointer"
                    style={{
                      height: 3,
                      background: "rgba(255,255,255,0.15)",
                      borderRadius: "var(--radius-pill)",
                      position: "relative",
                    }}
                  >
                    <div
                      style={{
                        width: `${progress * 100}%`,
                        height: "100%",
                        background: "var(--fg)",
                        borderRadius: "var(--radius-pill)",
                        transition: "width 0.1s linear",
                      }}
                    />
                  </div>

                  {/* Time */}
                  <span
                    className="text-xs"
                    style={{
                      color: "var(--fg-2)",
                      fontVariantNumeric: "tabular-nums",
                      minWidth: 32,
                    }}
                  >
                    {formatDuration(clip.duration)}
                  </span>

                  {/* Volume */}
                  <button
                    onClick={toggleMute}
                    className="p-0.5 rounded-sm transition-all"
                    style={{ color: "var(--fg-2)" }}
                    onMouseEnter={(e) => (e.currentTarget.style.color = "var(--fg)")}
                    onMouseLeave={(e) => (e.currentTarget.style.color = "var(--fg-2)")}
                  >
                    {isMuted ? <VolumeX size={18} /> : <Volume2 size={18} />}
                  </button>
                </div>
              </div>

              {/* ── Content sections ── */}
              <div className="p-4 space-y-4">
                {/* Virality Score */}
                <div
                  className="p-4 rounded-md"
                  style={{
                    background: "rgba(255,255,255,0.02)",
                    border: "1px solid var(--border-soft)",
                  }}
                >
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <p
                        className="text-sm font-medium"
                        style={{
                          color: "var(--fg)",
                          fontWeight: 510,
                          fontFeatureSettings: '"cv01", "ss03"',
                        }}
                      >
                        Virality Score
                      </p>
                      <p className="text-xs" style={{ color: "var(--meta)" }}>
                        Predicted viral potential
                      </p>
                    </div>
                    <span
                      className="text-2xl font-semibold"
                      style={{
                        color: getScoreColor(clip.virality_score),
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      {clip.virality_score}
                      <span className="text-sm" style={{ color: "var(--meta)" }}>
                        /10
                      </span>
                    </span>
                  </div>

                  <div
                    style={{
                      height: 6,
                      background: "rgba(255,255,255,0.08)",
                      borderRadius: "var(--radius-pill)",
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        width: `${clip.virality_score * 10}%`,
                        height: "100%",
                        background: getScoreColor(clip.virality_score),
                        borderRadius: "var(--radius-pill)",
                        transition: "width var(--motion-base) var(--ease-standard)",
                      }}
                    />
                  </div>

                  <div className="mt-3">
                    <span
                      className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                      style={{
                        background: clip.virality_score >= 8
                          ? "rgba(39,166,68,0.12)"
                          : clip.virality_score >= 6
                          ? "rgba(234,179,8,0.12)"
                          : "rgba(220,38,38,0.12)",
                        color: clip.virality_score >= 8
                          ? "var(--success)"
                          : clip.virality_score >= 6
                          ? "var(--warn)"
                          : "var(--danger)",
                        border: clip.virality_score >= 8
                          ? "1px solid rgba(39,166,68,0.2)"
                          : clip.virality_score >= 6
                          ? "1px solid rgba(234,179,8,0.2)"
                          : "1px solid rgba(220,38,38,0.2)",
                      }}
                    >
                      {clip.virality_score >= 8 && "🔥 High Viral Potential"}
                      {clip.virality_score >= 6 && clip.virality_score < 8 && "⚡ Good Potential"}
                      {clip.virality_score < 6 && "📈 Needs Optimization"}
                    </span>
                  </div>
                </div>

                {/* Detailed Metrics */}
                <div className="space-y-2">
                  <p
                    className="text-xs font-medium uppercase tracking-wider"
                    style={{
                      color: "var(--meta)",
                      letterSpacing: "0.08em",
                      fontFeatureSettings: '"cv01", "ss03"',
                    }}
                  >
                    Detailed Metrics
                  </p>
                  {clip.hook_score !== undefined && (
                    <ScoreBar label="Hook Score" score={clip.hook_score} icon={Target} />
                  )}
                  {clip.engagement_score !== undefined && (
                    <ScoreBar label="Engagement Score" score={clip.engagement_score} icon={Zap} />
                  )}
                  {clip.value_score !== undefined && (
                    <ScoreBar label="Value Score" score={clip.value_score} icon={TrendingUp} />
                  )}
                  {clip.shareability_score !== undefined && (
                    <ScoreBar label="Shareability Score" score={clip.shareability_score} icon={Share2} />
                  )}
                </div>

                {/* Hook Type */}
                {clip.hook_type && clip.hook_type !== "none" && (
                  <div
                    className="p-3 rounded-md"
                    style={{
                      background: "rgba(94,106,210,0.08)",
                      border: "1px solid rgba(94,106,210,0.15)",
                    }}
                  >
                    <div className="flex items-start gap-2">
                      <Target size={16} style={{ color: "var(--accent)", marginTop: 2, flexShrink: 0 }} />
                      <div>
                        <p
                          className="text-xs font-medium mb-1"
                          style={{ color: "var(--accent)" }}
                        >
                          Hook Type Detected
                        </p>
                        <span
                          className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium capitalize"
                          style={{
                            background: "rgba(94,106,210,0.12)",
                            color: "var(--accent)",
                            border: "1px solid rgba(94,106,210,0.2)",
                          }}
                        >
                          {clip.hook_type.replace("_", " ")}
                        </span>
                        <p className="text-xs mt-2" style={{ color: "var(--fg-2)" }}>
                          {hookDescriptions[clip.hook_type] || ""}
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Social Copy */}
                {(clip.social_title || clip.social_description || clip.suggested_hashtags) && (
                  <div
                    className="p-3 rounded-md space-y-2"
                    style={{
                      background: "rgba(255,255,255,0.02)",
                      border: "1px solid var(--border-soft)",
                    }}
                  >
                    <p
                      className="text-xs font-medium flex items-center gap-1.5"
                      style={{ color: "var(--fg-2)" }}
                    >
                      <Share2 size={12} />
                      Suggested Social Media Copy
                    </p>
                    {clip.social_title && (
                      <div>
                        <p className="text-xs" style={{ color: "var(--meta)" }}>Title:</p>
                        <p className="text-sm" style={{ color: "var(--fg)" }}>{clip.social_title}</p>
                      </div>
                    )}
                    {clip.social_description && (
                      <div>
                        <p className="text-xs" style={{ color: "var(--meta)" }}>Description:</p>
                        <p className="text-sm" style={{ color: "var(--fg)" }}>{clip.social_description}</p>
                      </div>
                    )}
                    {clip.suggested_hashtags && clip.suggested_hashtags.length > 0 && (
                      <div>
                        <p className="text-xs" style={{ color: "var(--meta)" }}>Hashtags:</p>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {clip.suggested_hashtags.map((tag, idx) => (
                            <span
                              key={idx}
                              className="inline-flex items-center px-2 py-0.5 rounded-full text-xs"
                              style={{
                                background: "rgba(255,255,255,0.04)",
                                color: "var(--fg-2)",
                                border: "1px solid var(--border-soft)",
                              }}
                            >
                              #{tag}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Viral Polish */}
                {(clip.cta_overlay_applied || clip.emoji_overlays_applied || (clip.variants && clip.variants.length > 0)) && (
                  <div
                    className="p-3 rounded-md"
                    style={{
                      background: "rgba(255,255,255,0.02)",
                      border: "1px solid var(--border-soft)",
                    }}
                  >
                    <p
                      className="text-xs font-medium flex items-center gap-1.5 mb-2"
                      style={{ color: "var(--fg-2)" }}
                    >
                      <Sparkles size={12} />
                      Viral Polish Applied
                    </p>
                    {(clip.cta_overlay_applied || clip.emoji_overlays_applied) && (
                      <div className="flex flex-wrap gap-2 mb-2">
                        {clip.cta_overlay_applied && (
                          <span
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs"
                            style={{
                              background: "rgba(94,106,210,0.1)",
                              color: "var(--accent)",
                              border: "1px solid rgba(94,106,210,0.2)",
                            }}
                          >
                            <Target size={10} /> CTA Overlay
                          </span>
                        )}
                        {clip.emoji_overlays_applied && (
                          <span
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs"
                            style={{
                              background: "rgba(255,255,255,0.04)",
                              color: "var(--fg-2)",
                              border: "1px solid var(--border-soft)",
                            }}
                          >
                            😀 Emoji Cues
                          </span>
                        )}
                      </div>
                    )}
                    {clip.variants && clip.variants.length > 0 && (
                      <div>
                        <p className="text-xs mb-1.5 flex items-center gap-1" style={{ color: "var(--meta)" }}>
                          <Shuffle size={10} /> A/B Variants ({clip.variants.length})
                        </p>
                        <div className="space-y-1">
                          {clip.variants.map((v, vi) => (
                            <div
                              key={vi}
                              className="flex items-center justify-between px-2 py-1.5 rounded-sm"
                              style={{ background: "rgba(255,255,255,0.03)" }}
                            >
                              <div className="flex items-center gap-2 min-w-0">
                                {v.type === "caption_style" ? (
                                  <Subtitles size={12} style={{ color: "var(--accent)", flexShrink: 0 }} />
                                ) : (
                                  <Music size={12} style={{ color: "var(--meta)", flexShrink: 0 }} />
                                )}
                                <span
                                  className="text-xs truncate"
                                  style={{ color: "var(--fg-2)", maxWidth: 180 }}
                                  title={v.label}
                                >
                                  {v.label}
                                </span>
                              </div>
                              <a
                                href={`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/clips/${clip.video_url.split("/")[2]}/${v.path.split("/").pop()}`}
                                download
                                className="text-xs shrink-0 ml-2 transition-all"
                                style={{ color: "var(--accent)" }}
                                onMouseEnter={(e) => (e.currentTarget.style.color = "var(--accent-hover)")}
                                onMouseLeave={(e) => (e.currentTarget.style.color = "var(--accent)")}
                              >
                                <Download size={12} />
                              </a>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Pro Tips */}
                <div
                  className="p-3 rounded-md"
                  style={{
                    background: "rgba(255,255,255,0.02)",
                    border: "1px solid var(--border-soft)",
                  }}
                >
                  <p
                    className="text-xs font-medium flex items-center gap-1.5 mb-2"
                    style={{ color: "var(--fg-2)" }}
                  >
                    <Sparkles size={12} />
                    Pro Tips to Boost Performance
                  </p>
                  <ul className="text-xs space-y-1" style={{ color: "var(--muted)" }}>
                    {clip.virality_score < 7 && (
                      <li>{"\u2022"} Consider re-editing to strengthen the hook in the first 3 seconds</li>
                    )}
                    {clip.engagement_score && clip.engagement_score < 7 && (
                      <li>{"\u2022"} Add a call-to-action or question to boost engagement</li>
                    )}
                    {(!clip.suggested_hashtags || clip.suggested_hashtags.length === 0) && (
                      <li>{"\u2022"} Add relevant trending hashtags when posting</li>
                    )}
                    <li>{"\u2022"} Post during peak hours (6-9pm in your target timezone)</li>
                    <li>{"\u2022"} Reply to first 10 comments within 30 minutes for algorithm boost</li>
                  </ul>
                </div>
              </div>
            </div>

            {/* ── Footer ── */}
            <div
              className="flex items-center justify-end gap-3 shrink-0"
              style={{
                padding: "var(--space-4)",
                borderTop: "1px solid var(--border)",
              }}
            >
              <button
                className="btn btn-ghost"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "var(--space-2)",
                  padding: "8px 16px",
                  borderRadius: "var(--radius-sm)",
                  fontFamily: "var(--font-display)",
                  fontSize: "var(--text-sm)",
                  fontWeight: 510,
                  fontFeatureSettings: '"cv01", "ss03"',
                  lineHeight: 1,
                  cursor: "pointer",
                  border: "1px solid rgba(36,40,44,1)",
                  background: "rgba(255,255,255,0.02)",
                  color: "#e2e4e7",
                  transition: "background-color var(--motion-fast) var(--ease-standard)",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.05)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.02)"; }}
              >
                Editar
              </button>
              <button
                className="btn btn-primary"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "var(--space-2)",
                  padding: "8px 16px",
                  borderRadius: "var(--radius-sm)",
                  fontFamily: "var(--font-display)",
                  fontSize: "var(--text-sm)",
                  fontWeight: 510,
                  fontFeatureSettings: '"cv01", "ss03"',
                  lineHeight: 1,
                  cursor: "pointer",
                  border: "1px solid transparent",
                  background: "var(--accent)",
                  color: "#ffffff",
                  transition: "background-color var(--motion-fast) var(--ease-standard)",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "var(--accent-hover)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = "var(--accent)"; }}
              >
                Exportar
              </button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
