"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Play,
  Pause,
  Volume2,
  VolumeX,
  Maximize,
  Minimize,
  Download,
  Film,
  Clock,
  HardDrive,
  Hash,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface ClipMeta {
  clip_order: number;
  duration: number;
  filename?: string;
  file_size?: number;
  video_url: string;
  thumbnail_url?: string | null;
}

interface ClipVideoPlayerProps {
  src: string;
  poster?: string;
  clip: ClipMeta;
  apiUrl: string;
  className?: string;
}

function formatFileSize(bytes?: number): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

export function ClipVideoPlayer({
  src,
  poster,
  clip,
  apiUrl,
  className,
}: ClipVideoPlayerProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showControls, setShowControls] = useState(true);
  const controlsTimeoutRef = useRef<NodeJS.Timeout>(undefined);
  const [isLoaded, setIsLoaded] = useState(false);

  // Reset player state when collapsing
  useEffect(() => {
    if (!isExpanded && videoRef.current) {
      videoRef.current.pause();
      setIsPlaying(false);
      setProgress(0);
      setCurrentTime(0);
    }
  }, [isExpanded]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const handleTimeUpdate = () => {
      setCurrentTime(video.currentTime);
      setProgress((video.currentTime / video.duration) * 100);
    };

    const handleLoadedMetadata = () => {
      setDuration(video.duration);
      setIsLoaded(true);
    };

    const handleEnded = () => {
      setIsPlaying(false);
    };

    video.addEventListener("timeupdate", handleTimeUpdate);
    video.addEventListener("loadedmetadata", handleLoadedMetadata);
    video.addEventListener("ended", handleEnded);

    return () => {
      video.removeEventListener("timeupdate", handleTimeUpdate);
      video.removeEventListener("loadedmetadata", handleLoadedMetadata);
      video.removeEventListener("ended", handleEnded);
    };
  }, [isExpanded]);

  const togglePlay = useCallback(() => {
    if (videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause();
      } else {
        videoRef.current.play();
      }
      setIsPlaying(!isPlaying);
    }
  }, [isPlaying]);

  const toggleMute = useCallback(() => {
    if (videoRef.current) {
      videoRef.current.muted = !isMuted;
      setIsMuted(!isMuted);
    }
  }, [isMuted]);

  const toggleFullscreen = useCallback(async () => {
    if (!containerRef.current) return;
    if (!isFullscreen) {
      try {
        await containerRef.current.requestFullscreen();
        setIsFullscreen(true);
      } catch {
        // fallback: try video element
        if (videoRef.current) {
          try {
            await videoRef.current.requestFullscreen();
            setIsFullscreen(true);
          } catch {}
        }
      }
    } else {
      try {
        await document.exitFullscreen();
        setIsFullscreen(false);
      } catch {}
    }
  }, [isFullscreen]);

  useEffect(() => {
    const handleFsChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener("fullscreenchange", handleFsChange);
    return () => document.removeEventListener("fullscreenchange", handleFsChange);
  }, []);

  const handleSeek = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const newTime = (parseFloat(e.target.value) / 100) * duration;
      if (videoRef.current) {
        videoRef.current.currentTime = newTime;
        setProgress(parseFloat(e.target.value));
      }
    },
    [duration],
  );

  const handleMouseMove = useCallback(() => {
    setShowControls(true);
    if (controlsTimeoutRef.current) {
      clearTimeout(controlsTimeoutRef.current);
    }
    controlsTimeoutRef.current = setTimeout(() => {
      if (isPlaying) {
        setShowControls(false);
      }
    }, 3000);
  }, [isPlaying]);

  const formatTime = (time: number) => {
    const minutes = Math.floor(time / 60);
    const seconds = Math.floor(time % 60);
    return `${minutes}:${seconds.toString().padStart(2, "0")}`;
  };

  const downloadUrl = `${apiUrl}${clip.video_url}`;
  const downloadFilename = clip.filename || `clip_${clip.clip_order}.mp4`;

  // Thumbnail view (collapsed)
  if (!isExpanded) {
    return (
      <motion.div
        layout
        className={cn("relative group cursor-pointer", className)}
        onClick={() => setIsExpanded(true)}
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.2 }}
      >
        <div className="relative rounded-xl overflow-hidden bg-black/40 border border-white/10 hover:border-cyan-500/50 transition-all duration-300">
          {/* Thumbnail */}
          <div className="aspect-[9/16] relative">
            {poster ? (
              <img
                src={poster}
                alt={`Clip ${clip.clip_order}`}
                className="absolute inset-0 w-full h-full object-cover"
                loading="lazy"
              />
            ) : (
              <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-gray-900 to-gray-800">
                <Film className="w-12 h-12 text-white/20" />
              </div>
            )}

            {/* Gradient overlay */}
            <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-black/30" />

            {/* Play button overlay */}
            <div className="absolute inset-0 flex items-center justify-center">
              <motion.div
                whileHover={{ scale: 1.1 }}
                className="w-14 h-14 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center group-hover:bg-white/30 transition-all"
              >
                <Play className="w-6 h-6 text-white ml-0.5" />
              </motion.div>
            </div>

            {/* Clip number badge */}
            <div className="absolute top-2 left-2">
              <span className="px-2 py-1 rounded-lg bg-black/60 backdrop-blur-sm text-xs font-medium text-white border border-white/10">
                #{clip.clip_order}
              </span>
            </div>

            {/* Duration badge */}
            <div className="absolute bottom-2 right-2">
              <span className="px-2 py-1 rounded-lg bg-black/60 backdrop-blur-sm text-xs font-medium text-white/80 flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {formatDuration(clip.duration)}
              </span>
            </div>

            {/* Expand hint */}
            <div className="absolute bottom-2 left-2 opacity-0 group-hover:opacity-100 transition-opacity">
              <span className="px-2 py-1 rounded-lg bg-cyan-500/80 text-xs font-medium text-white flex items-center gap-1">
                <ChevronDown className="w-3 h-3" />
                Play
              </span>
            </div>
          </div>
        </div>
      </motion.div>
    );
  }

  // Expanded video player view
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className={cn("w-full", className)}
    >
      <div className="rounded-xl overflow-hidden border border-white/10 bg-black/40">
        {/* Video Player */}
        <div
          ref={containerRef}
          className="relative bg-black rounded-lg overflow-hidden"
          onMouseMove={handleMouseMove}
          onMouseLeave={() => isPlaying && setShowControls(false)}
        >
          <video
            ref={videoRef}
            src={src}
            poster={poster}
            className="w-full aspect-[9/16] max-h-[70vh] object-contain mx-auto"
            onClick={togglePlay}
            playsInline
            preload="metadata"
          />

          {/* Loading state */}
          {!isLoaded && (
            <div className="absolute inset-0 flex items-center justify-center bg-black/60">
              <div className="w-10 h-10 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin" />
            </div>
          )}

          {/* Play/Pause overlay (when paused) */}
          <AnimatePresence>
            {!isPlaying && isLoaded && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="absolute inset-0 flex items-center justify-center bg-black/30 cursor-pointer"
                onClick={togglePlay}
              >
                <motion.div
                  whileHover={{ scale: 1.1 }}
                  whileTap={{ scale: 0.95 }}
                  className="w-16 h-16 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center"
                >
                  <Play className="w-7 h-7 text-white ml-0.5" />
                </motion.div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Top bar - clip info + collapse */}
          <AnimatePresence>
            {showControls && (
              <motion.div
                initial={{ opacity: 0, y: -20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -20 }}
                className="absolute top-0 left-0 right-0 p-3 bg-gradient-to-b from-black/80 to-transparent"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 rounded-md bg-cyan-500/20 text-cyan-400 text-xs font-medium">
                      Clip #{clip.clip_order}
                    </span>
                    <span className="text-white/60 text-xs">
                      {formatDuration(clip.duration)}
                    </span>
                  </div>
                  <button
                    onClick={() => setIsExpanded(false)}
                    className="p-1.5 rounded-lg bg-white/10 backdrop-blur-sm text-white/80 hover:bg-white/20 hover:text-white transition-all"
                    title="Collapse"
                  >
                    <ChevronUp className="w-4 h-4" />
                  </button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Bottom controls */}
          <AnimatePresence>
            {showControls && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: 20 }}
                className="absolute bottom-0 left-0 right-0 p-3 bg-gradient-to-t from-black/90 via-black/50 to-transparent"
              >
                {/* Seek bar */}
                <div className="mb-2">
                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={progress}
                    onChange={handleSeek}
                    className="w-full h-1 bg-white/20 rounded-full appearance-none cursor-pointer
                      [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3.5
                      [&::-webkit-slider-thumb]:h-3.5 [&::-webkit-slider-thumb]:rounded-full
                      [&::-webkit-slider-thumb]:bg-cyan-400 [&::-webkit-slider-thumb]:shadow-lg
                      [&::-webkit-slider-thumb]:shadow-cyan-400/50"
                  />
                </div>

                {/* Controls row */}
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {/* Play/Pause */}
                    <button
                      onClick={togglePlay}
                      className="w-9 h-9 rounded-full bg-white/10 backdrop-blur-sm flex items-center justify-center hover:bg-white/20 transition-all"
                    >
                      {isPlaying ? (
                        <Pause className="w-4 h-4 text-white" />
                      ) : (
                        <Play className="w-4 h-4 text-white ml-0.5" />
                      )}
                    </button>

                    {/* Mute */}
                    <button
                      onClick={toggleMute}
                      className="p-1.5 rounded-lg text-white/70 hover:text-white hover:bg-white/10 transition-all"
                    >
                      {isMuted ? (
                        <VolumeX className="w-4 h-4" />
                      ) : (
                        <Volume2 className="w-4 h-4" />
                      )}
                    </button>

                    {/* Time */}
                    <span className="text-white/60 text-xs tabular-nums min-w-[80px]">
                      {formatTime(currentTime)} / {formatTime(duration)}
                    </span>
                  </div>

                  <div className="flex items-center gap-1">
                    {/* Download */}
                    <a
                      href={downloadUrl}
                      download={downloadFilename}
                      className="p-1.5 rounded-lg text-white/70 hover:text-white hover:bg-white/10 transition-all"
                      title="Download clip"
                    >
                      <Download className="w-4 h-4" />
                    </a>

                    {/* Fullscreen */}
                    <button
                      onClick={toggleFullscreen}
                      className="p-1.5 rounded-lg text-white/70 hover:text-white hover:bg-white/10 transition-all"
                      title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
                    >
                      {isFullscreen ? (
                        <Minimize className="w-4 h-4" />
                      ) : (
                        <Maximize className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Metadata bar */}
        <div className="px-4 py-3 flex items-center gap-4 text-xs text-white/50 border-t border-white/5">
          <span className="flex items-center gap-1.5">
            <Hash className="w-3 h-3 text-cyan-400/60" />
            Clip {clip.clip_order}
          </span>
          <span className="flex items-center gap-1.5">
            <Clock className="w-3 h-3 text-cyan-400/60" />
            {formatDuration(clip.duration)}
          </span>
          {clip.file_size && (
            <span className="flex items-center gap-1.5">
              <HardDrive className="w-3 h-3 text-cyan-400/60" />
              {formatFileSize(clip.file_size)}
            </span>
          )}
          <div className="ml-auto">
            <a
              href={downloadUrl}
              download={downloadFilename}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 transition-all text-xs font-medium"
            >
              <Download className="w-3.5 h-3.5" />
              Download
            </a>
          </div>
        </div>
      </div>
    </motion.div>
  );
}
