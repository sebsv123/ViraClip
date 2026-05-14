"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  AudioLines,
  Clapperboard,
  Download,
  Gauge,
  Layers,
  Palette,
  Scissors,
  SplitSquareVertical,
  Subtitles,
  Volume2,
  VolumeX,
} from "lucide-react";
import { useSession } from "@/lib/auth-client";
import { formatSupportMessage, parseApiError } from "@/lib/api-error";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Slider } from "@/components/ui/slider";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

interface TaskDetails {
  id: string;
  source_title: string;
  source_type: string;
  status: string;
  clips_count: number;
}

interface Clip {
  id: string;
  filename: string;
  clip_order: number;
  duration: number;
  start_time: string;
  end_time: string;
  text: string;
  video_url: string;
}

interface VideoFx {
  brightness: number;
  contrast: number;
  saturation: number;
  blur: number;
  hue: number;
  zoom: number;
}

interface BrowserVideoSample {
  displayWidth: number;
  displayHeight: number;
  timestamp: number;
  draw: (ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D, x: number, y: number) => void;
}

interface BrowserAudioSample {
  timestamp: number;
  numberOfChannels: number;
  sampleRate: number;
  allocationSize: (options: { planeIndex: number; format: "f32" }) => number;
  copyTo: (target: Float32Array, options: { planeIndex: number; format: "f32" }) => void;
}

const MIN_GAP_SECONDS = 0.25;

const DEFAULT_VIDEO_FX: VideoFx = {
  brightness: 100,
  contrast: 100,
  saturation: 100,
  blur: 0,
  hue: 0,
  zoom: 1,
};

const EXPORT_DIMENSIONS = {
  tiktok: { width: 1080, height: 1920 },
  reels: { width: 1080, height: 1920 },
  shorts: { width: 1080, height: 1920 },
} as const;

export default function TaskEditPage() {
  const params = useParams();
  const { data: session } = useSession();
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const taskApiUrl = "/api/tasks";

  const [task, setTask] = useState<TaskDetails | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [mergeSelection, setMergeSelection] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [trimRange, setTrimRange] = useState<[number, number]>([0, 1]);
  const [splitTime, setSplitTime] = useState(1);
  const [captionText, setCaptionText] = useState("");
  const [captionPosition, setCaptionPosition] = useState("bottom");
  const [highlightWords, setHighlightWords] = useState<string[]>([]);
  const [subtitleSize, setSubtitleSize] = useState(52);
  const [subtitleY, setSubtitleY] = useState(78);

  const [volume, setVolume] = useState(100);
  const [isMuted, setIsMuted] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [videoFx, setVideoFx] = useState<VideoFx>(DEFAULT_VIDEO_FX);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  const [exportPreset, setExportPreset] = useState("tiktok");
  const [exportProgress, setExportProgress] = useState<number | null>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);

  const selectedClip = useMemo(
    () => clips.find((clip) => clip.id === selectedClipId) ?? null,
    [clips, selectedClipId]
  );

  const videoStyle = useMemo(
    () => ({
      filter: `brightness(${videoFx.brightness}%) contrast(${videoFx.contrast}%) saturate(${videoFx.saturation}%) blur(${videoFx.blur}px) hue-rotate(${videoFx.hue}deg)`,
      transform: `scale(${videoFx.zoom})`,
      transformOrigin: "center center",
    }),
    [videoFx]
  );

  const subtitleWords = useMemo(
    () => captionText.split(/\s+/).map((word) => word.trim()).filter(Boolean),
    [captionText]
  );

  const activeSubtitleWords = useMemo(() => {
    const start = Math.max(0, Math.floor((currentTime / Math.max(selectedClip?.duration || 1, 1)) * subtitleWords.length));
    return subtitleWords.slice(start, start + 6);
  }, [currentTime, selectedClip?.duration, subtitleWords]);

  const getSubtitleWordsAtTime = useCallback(
    (timeSeconds: number, durationSeconds: number) => {
      if (subtitleWords.length === 0) return [] as string[];
      const safeDuration = Math.max(durationSeconds, 0.01);
      const progress = clamp(timeSeconds / safeDuration, 0, 0.9999);
      const wordIndex = Math.floor(progress * subtitleWords.length);
      const startIndex = Math.max(0, wordIndex - 1);
      return subtitleWords.slice(startIndex, startIndex + 6);
    },
    [subtitleWords]
  );

  const formatDuration = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

  const buildSupportError = useCallback(async (response: Response, fallbackMessage: string) => {
    const parsed = await parseApiError(response, fallbackMessage);
    return formatSupportMessage(parsed);
  }, []);

  const fetchEditorData = useCallback(async () => {
    if (!params.id) return;
    setError(null);

    try {
      const taskResponse = await fetch(`${taskApiUrl}/${params.id}`, { cache: "no-store" });
      if (!taskResponse.ok) {
        throw new Error(await buildSupportError(taskResponse, `Failed to fetch task: ${taskResponse.status}`));
      }

      const taskData = (await taskResponse.json()) as TaskDetails;
      setTask(taskData);

      if (taskData.status !== "completed") {
        setClips([]);
        return;
      }

      const clipsResponse = await fetch(`${taskApiUrl}/${params.id}/clips`, { cache: "no-store" });
      if (!clipsResponse.ok) {
        throw new Error(await buildSupportError(clipsResponse, `Failed to fetch clips: ${clipsResponse.status}`));
      }

      const clipsData = await clipsResponse.json();
      const nextClips = (clipsData.clips || []) as Clip[];
      setClips(nextClips);

      setSelectedClipId((current) => {
        if (current && nextClips.some((clip) => clip.id === current)) return current;
        return nextClips[0]?.id ?? null;
      });

      setMergeSelection((current) => current.filter((id) => nextClips.some((clip) => clip.id === id)));
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "Failed to load editor");
    }
  }, [buildSupportError, params.id, taskApiUrl]);

  useEffect(() => {
    const run = async () => {
      setIsLoading(true);
      try {
        await fetchEditorData();
      } finally {
        setIsLoading(false);
      }
    };
    void run();
  }, [fetchEditorData]);

  useEffect(() => {
    if (!selectedClip) return;
    const safeDuration = Math.max(selectedClip.duration, MIN_GAP_SECONDS * 2);
    setTrimRange([0, safeDuration]);
    setSplitTime(clamp(safeDuration / 2, MIN_GAP_SECONDS, safeDuration - MIN_GAP_SECONDS));
    setCaptionText(selectedClip.text || "");
    setHighlightWords([]);
    setCurrentTime(0);
    setVideoFx(DEFAULT_VIDEO_FX);
    setSubtitleY(78);
    setSubtitleSize(52);
  }, [selectedClip]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.volume = clamp(volume / 100, 0, 1);
    video.muted = isMuted;
    video.playbackRate = playbackRate;
  }, [volume, isMuted, playbackRate]);

  const withSaving = async (action: () => Promise<void>) => {
    setIsSaving(true);
    try {
      await action();
      await fetchEditorData();
    } finally {
      setIsSaving(false);
    }
  };

  const handleTrim = async () => {
    if (!selectedClip || !session?.user?.id || !task?.id) return;
    const startOffset = Number(trimRange[0].toFixed(2));
    const endOffset = Number((selectedClip.duration - trimRange[1]).toFixed(2));

    await withSaving(async () => {
      const response = await fetch(`${taskApiUrl}/${task.id}/clips/${selectedClip.id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ start_offset: startOffset, end_offset: endOffset }),
      });
      if (!response.ok) throw new Error(await buildSupportError(response, "Failed to trim clip"));
    });
  };

  const handleSplit = async (splitAt?: number) => {
    if (!selectedClip || !session?.user?.id || !task?.id) return;
    const value = splitAt ?? splitTime;
    await withSaving(async () => {
      const response = await fetch(`${taskApiUrl}/${task.id}/clips/${selectedClip.id}/split`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ split_time: Number(value.toFixed(2)) }),
      });
      if (!response.ok) throw new Error(await buildSupportError(response, "Failed to split clip"));
    });
  };

  const handleUpdateCaptions = async () => {
    if (!selectedClip || !session?.user?.id || !task?.id) return;

    await withSaving(async () => {
      const response = await fetch(`${taskApiUrl}/${task.id}/clips/${selectedClip.id}/captions`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          caption_text: captionText,
          position: captionPosition,
          highlight_words: highlightWords,
        }),
      });
      if (!response.ok) throw new Error(await buildSupportError(response, "Failed to update captions"));
    });
  };

  const handleMerge = async () => {
    if (!session?.user?.id || !task?.id || mergeSelection.length < 2) return;
    await withSaving(async () => {
      const response = await fetch(`${taskApiUrl}/${task.id}/clips/merge`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ clip_ids: mergeSelection }),
      });
      if (!response.ok) throw new Error(await buildSupportError(response, "Failed to merge selected clips"));
    });
    setMergeSelection([]);
  };

  const handleExport = async () => {
    if (!selectedClip || !session?.user?.id || !task?.id) return;
    setIsSaving(true);
    setExportProgress(0);

    try {
      const sourceResponse = await fetch(`${apiUrl}${selectedClip.video_url}`);
      if (!sourceResponse.ok) {
        throw new Error(`Failed to fetch source clip: ${sourceResponse.status}`);
      }

      const sourceBlob = await sourceResponse.blob();

      const {
        Input,
        Output,
        Conversion,
        ALL_FORMATS,
        BlobSource,
        BufferTarget,
        Mp4OutputFormat,
        AudioSample,
      } = await import("mediabunny");

      const outputSize = EXPORT_DIMENSIONS[exportPreset as keyof typeof EXPORT_DIMENSIONS] || EXPORT_DIMENSIONS.tiktok;
      const trimStart = trimRange[0];
      const trimEnd = trimRange[1];
      const targetDuration = Math.max(trimEnd - trimStart, 0.1);
      const highlightSet = new Set(highlightWords);

      const input = new Input({
        source: new BlobSource(sourceBlob),
        formats: ALL_FORMATS,
      });

      const output = new Output({
        format: new Mp4OutputFormat(),
        target: new BufferTarget(),
      });

      let canvas: OffscreenCanvas | HTMLCanvasElement | null = null;
      let ctx: CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null = null;

      const conversion = await Conversion.init({
        input,
        output,
        trim: {
          start: trimStart,
          end: trimEnd,
        },
        video: {
          forceTranscode: true,
          process: (sample) => {
            const browserSample = sample as unknown as BrowserVideoSample;
            if (!canvas || !ctx) {
              if (typeof OffscreenCanvas !== "undefined") {
                canvas = new OffscreenCanvas(outputSize.width, outputSize.height);
                ctx = canvas.getContext("2d");
              } else {
                const fallbackCanvas = document.createElement("canvas");
                fallbackCanvas.width = outputSize.width;
                fallbackCanvas.height = outputSize.height;
                canvas = fallbackCanvas;
                ctx = fallbackCanvas.getContext("2d");
              }
            }

            if (!ctx || !canvas) {
              return sample;
            }

            const scale = Math.min(outputSize.width / browserSample.displayWidth, outputSize.height / browserSample.displayHeight);
            const drawWidth = browserSample.displayWidth * scale;
            const drawHeight = browserSample.displayHeight * scale;
            const drawX = (outputSize.width - drawWidth) / 2;
            const drawY = (outputSize.height - drawHeight) / 2;

            ctx.clearRect(0, 0, outputSize.width, outputSize.height);
            ctx.fillStyle = "black";
            ctx.fillRect(0, 0, outputSize.width, outputSize.height);

            ctx.save();
            ctx.filter = `brightness(${videoFx.brightness}%) contrast(${videoFx.contrast}%) saturate(${videoFx.saturation}%) blur(${videoFx.blur}px) hue-rotate(${videoFx.hue}deg)`;

            const centerX = drawX + drawWidth / 2;
            const centerY = drawY + drawHeight / 2;
            ctx.translate(centerX, centerY);
            ctx.scale(videoFx.zoom, videoFx.zoom);
            ctx.translate(-centerX, -centerY);

            browserSample.draw(ctx, drawX, drawY);
            ctx.restore();

            const subtitleAtTime = getSubtitleWordsAtTime(browserSample.timestamp, targetDuration);
            if (subtitleAtTime.length > 0) {
              const fontSize = Math.max(24, Math.round(subtitleSize));
              ctx.font = `700 ${fontSize}px ui-sans-serif, system-ui, sans-serif`;
              ctx.textAlign = "center";
              ctx.textBaseline = "middle";

              const text = subtitleAtTime.join(" ");
              const metrics = ctx.measureText(text);
              const textWidth = Math.max(metrics.width, 32);
              const y = (subtitleY / 100) * outputSize.height;
              const boxPaddingX = 22;
              const boxPaddingY = 14;

              ctx.fillStyle = "rgba(0,0,0,0.7)";
              const left = outputSize.width / 2 - textWidth / 2 - boxPaddingX;
              const top = y - fontSize / 2 - boxPaddingY;
              const width = textWidth + boxPaddingX * 2;
              const height = fontSize + boxPaddingY * 2;
              ctx.beginPath();
              ctx.roundRect(left, top, width, height, 16);
              ctx.fill();

              let cursorX = outputSize.width / 2 - textWidth / 2;
              for (const word of subtitleAtTime) {
                const cleanedWord = word.toLowerCase().replace(/[^a-z0-9']/g, "");
                ctx.fillStyle = highlightSet.has(cleanedWord) ? "#fde047" : "#ffffff";
                ctx.fillText(word, cursorX + ctx.measureText(word).width / 2, y);
                cursorX += ctx.measureText(`${word} `).width;
              }
            }

            return canvas;
          },
        },
        audio: {
          forceTranscode: true,
          process: (sample) => {
            const browserSample = sample as unknown as BrowserAudioSample;
            if (isMuted || volume !== 100) {
              const gain = isMuted ? 0 : volume / 100;
              const bytes = browserSample.allocationSize({ planeIndex: 0, format: "f32" });
              const data = new Float32Array(bytes / 4);
              browserSample.copyTo(data, { planeIndex: 0, format: "f32" });

              for (let i = 0; i < data.length; i += 1) {
                data[i] *= gain;
              }

              return new AudioSample({
                data,
                format: "f32",
                numberOfChannels: browserSample.numberOfChannels,
                sampleRate: browserSample.sampleRate,
                timestamp: browserSample.timestamp,
              });
            }

            return sample;
          },
        },
      });

      conversion.onProgress = (progress: number) => {
        setExportProgress(Math.round(progress * 100));
      };

      await conversion.execute();

      const targetBuffer = output.target.buffer as ArrayBuffer;
      const blob = new Blob([targetBuffer], { type: "video/mp4" });
      const blobUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = blobUrl;
      link.download = `${selectedClip.filename.replace(/\.mp4$/i, "")}_${exportPreset}_browser.mp4`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(blobUrl);
      setExportProgress(100);
    } finally {
      setIsSaving(false);
      setTimeout(() => setExportProgress(null), 800);
    }
  };

  const selectClip = (clip: Clip) => {
    setSelectedClipId(clip.id);
  };

  const toggleMergeSelection = (clipId: string) => {
    setMergeSelection((current) => (current.includes(clipId) ? current.filter((id) => id !== clipId) : [...current, clipId]));
  };

  const toggleHighlightedWord = (word: string) => {
    const cleaned = word.toLowerCase().replace(/[^a-z0-9']/g, "").trim();
    if (!cleaned) return;
    setHighlightWords((current) => (current.includes(cleaned) ? current.filter((value) => value !== cleaned) : [...current, cleaned]));
  };

  const handleTrimRangeChange = (value: number[]) => {
    if (!selectedClip || value.length !== 2) return;
    const min = 0;
    const max = selectedClip.duration;
    let nextStart = clamp(value[0], min, max);
    let nextEnd = clamp(value[1], min, max);

    if (nextEnd - nextStart < MIN_GAP_SECONDS) {
      if (nextStart + MIN_GAP_SECONDS <= max) nextEnd = nextStart + MIN_GAP_SECONDS;
      else {
        nextStart = max - MIN_GAP_SECONDS;
        nextEnd = max;
      }
    }
    setTrimRange([nextStart, nextEnd]);
  };

  const seekTo = (seconds: number) => {
    if (!videoRef.current || !selectedClip) return;
    const target = clamp(seconds, 0, selectedClip.duration);
    videoRef.current.currentTime = target;
    setCurrentTime(target);
  };

  const handleTimeUpdate = () => {
    if (!videoRef.current) return;
    setCurrentTime(videoRef.current.currentTime || 0);
  };

  const setTrimInToPlayhead = () => {
    setTrimRange(([, end]) => {
      const nextStart = Math.min(currentTime, end - MIN_GAP_SECONDS);
      return [clamp(nextStart, 0, Math.max(end - MIN_GAP_SECONDS, 0)), end];
    });
  };

  const setTrimOutToPlayhead = () => {
    if (!selectedClip) return;
    setTrimRange(([start]) => {
      const nextEnd = Math.max(currentTime, start + MIN_GAP_SECONDS);
      return [start, clamp(nextEnd, start + MIN_GAP_SECONDS, selectedClip.duration)];
    });
  };

  const resetPreviewAdjustments = () => {
    setVideoFx(DEFAULT_VIDEO_FX);
    setVolume(100);
    setIsMuted(false);
    setPlaybackRate(1);
    setSubtitleSize(52);
    setSubtitleY(78);
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] p-4">
        <div className="max-w-7xl mx-auto space-y-4">
          <Skeleton className="h-10 w-56 bg-white/10" />
          <Skeleton className="h-[420px] w-full bg-white/10" />
          <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
            <Skeleton className="h-[520px] xl:col-span-7 bg-white/10" />
            <Skeleton className="h-[520px] xl:col-span-5 bg-white/10" />
          </div>
        </div>
      </div>
    );
  }

  try {
    return (
    <div className="min-h-screen bg-[#0a0a0f] text-white">
      <div className="border-b border-white/5 bg-[#0a0a0f]/80 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-4 py-5 flex items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <Link href={`/tasks/${params.id}`}>
                <Button variant="ghost" size="sm" className="text-gray-300 hover:text-white">
                  <ArrowLeft className="w-4 h-4" />
                  Back to Task
                </Button>
              </Link>
              <Badge variant="outline" className="border-white/10 text-gray-300">Studio Editor</Badge>
            </div>
            <h1 className="text-2xl font-bold text-white">{task?.source_title || "Clip Editor"}</h1>
          </div>
          <Button onClick={handleExport} disabled={!selectedClip || isSaving} className="bg-cyan-500 hover:bg-cyan-400 text-black font-semibold">
            <Download className="w-4 h-4" />
            {exportProgress !== null ? `Exporting ${exportProgress}%` : "Export Selected"}
          </Button>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
        {error && (
          <Alert className="border-red-500/30 bg-red-500/10">
            <AlertDescription className="text-red-300">{error}</AlertDescription>
          </Alert>
        )}

        {!task ? (
          <Alert className="border-white/10 bg-white/5">
            <AlertDescription className="text-gray-300">Task not found.</AlertDescription>
          </Alert>
        ) : task.status !== "completed" ? (
          <Card className="bg-white/5 border-white/10">
            <CardContent className="p-8 text-center space-y-3">
              <p className="text-lg font-semibold text-white">This editor is available once processing completes.</p>
              <p className="text-gray-400">Current status: {task.status}</p>
              <Link href={`/tasks/${task.id}`}>
                <Button variant="outline" className="border-white/10 text-gray-300 hover:text-white">Return to Task</Button>
              </Link>
            </CardContent>
          </Card>
        ) : clips.length === 0 ? (
          <Card className="bg-white/5 border-white/10">
            <CardContent className="p-8 text-center space-y-3">
              <p className="text-lg font-semibold text-white">No clips to edit yet.</p>
              <Link href={`/tasks/${task.id}`}>
                <Button variant="outline" className="border-white/10 text-gray-300 hover:text-white">Return to Task</Button>
              </Link>
            </CardContent>
          </Card>
        ) : (
          <>
            <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
              <Card className="xl:col-span-7 bg-white/5 border-white/10">
                <CardContent className="p-4 lg:p-5 space-y-4">
                  {selectedClip ? (
                    <>
                      <div className="rounded-xl bg-black overflow-hidden relative">
                        <video
                          ref={videoRef}
                          key={selectedClip.id}
                          src={`${apiUrl}${selectedClip.video_url}`}
                          controls
                          onTimeUpdate={handleTimeUpdate}
                          onPlay={() => setIsPlaying(true)}
                          onPause={() => setIsPlaying(false)}
                          className="w-full max-h-[520px] object-contain"
                          style={videoStyle}
                        />

                        <div
                          className="absolute left-1/2 -translate-x-1/2 px-4 py-1.5 rounded-full bg-black/70 text-white text-center pointer-events-none"
                          style={{
                            bottom: `${subtitleY}%`,
                            fontSize: `${subtitleSize / 2.5}px`,
                          }}
                        >
                          {activeSubtitleWords.length > 0 ? (
                            activeSubtitleWords.map((word, index) => {
                              const cleaned = word.toLowerCase().replace(/[^a-z0-9']/g, "");
                              const highlighted = highlightWords.includes(cleaned);
                              return (
                                <span key={`${word}-${index}`} className={highlighted ? "text-yellow-300" : "text-white"}>
                                  {word}{index === activeSubtitleWords.length - 1 ? "" : " "}
                                </span>
                              );
                            })
                          ) : (
                            <span>Subtitle preview</span>
                          )}
                        </div>
                      </div>

                      <div className="border border-white/10 rounded-lg p-3 space-y-3">
                        <div className="flex items-center justify-between text-sm text-gray-400">
                          <span>Playhead: {formatDuration(currentTime)} / {formatDuration(selectedClip.duration)}</span>
                          <span>{isPlaying ? "Playing" : "Paused"}</span>
                        </div>

                        <Slider
                          min={0}
                          max={selectedClip.duration}
                          value={[currentTime]}
                          step={0.01}
                          onValueChange={(value) => seekTo(value[0] || 0)}
                        />

                        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
                          <Button variant="outline" size="sm" className="border-white/10 text-gray-300 hover:text-white" onClick={() => seekTo(Math.max(0, currentTime - 1))}>-1s</Button>
                          <Button variant="outline" size="sm" className="border-white/10 text-gray-300 hover:text-white" onClick={() => seekTo(Math.min(selectedClip.duration, currentTime + 1))}>+1s</Button>
                          <Button variant="outline" size="sm" className="border-white/10 text-gray-300 hover:text-white" onClick={setTrimInToPlayhead}>Set In</Button>
                          <Button variant="outline" size="sm" className="border-white/10 text-gray-300 hover:text-white" onClick={setTrimOutToPlayhead}>Set Out</Button>
                        </div>
                      </div>

                      <div className="border border-white/10 rounded-lg p-3 space-y-3">
                        <div className="flex items-center justify-between text-sm text-gray-300">
                          <span className="font-medium">Trim Range</span>
                          <span>{formatDuration(trimRange[0])} - {formatDuration(trimRange[1])}</span>
                        </div>
                        <Slider
                          min={0}
                          max={selectedClip.duration}
                          value={trimRange}
                          step={0.01}
                          onValueChange={handleTrimRangeChange}
                        />
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                          <Button onClick={handleTrim} disabled={isSaving} className="bg-cyan-500 hover:bg-cyan-400 text-black font-semibold">
                            <Scissors className="w-4 h-4" />
                            Apply Trim
                          </Button>
                          <Button variant="outline" className="border-white/10 text-gray-300 hover:text-white" onClick={() => seekTo(trimRange[0])}>Jump In</Button>
                          <Button variant="outline" className="border-white/10 text-gray-300 hover:text-white" onClick={() => seekTo(trimRange[1])}>Jump Out</Button>
                        </div>
                      </div>
                    </>
                  ) : (
                    <p className="text-sm text-gray-400">Select a clip to start editing.</p>
                  )}
                </CardContent>
              </Card>

              <div className="xl:col-span-5 space-y-4">
                <Card className="bg-white/5 border-white/10">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base flex items-center gap-2 text-white">
                      <Layers className="w-4 h-4" />
                      Fine Controls
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-5">
                    <div className="space-y-3">
                      <div className="flex items-center justify-between text-sm text-gray-300">
                        <span className="flex items-center gap-2"><SplitSquareVertical className="w-4 h-4" />Split</span>
                        <span>{splitTime.toFixed(2)}s</span>
                      </div>
                      <Slider
                        min={MIN_GAP_SECONDS}
                        max={Math.max((selectedClip?.duration || MIN_GAP_SECONDS) - MIN_GAP_SECONDS, MIN_GAP_SECONDS)}
                        value={[splitTime]}
                        step={0.01}
                        onValueChange={(value) => setSplitTime(value[0] || MIN_GAP_SECONDS)}
                      />
                      <div className="grid grid-cols-2 gap-2">
                        <Button variant="outline" className="border-white/10 text-gray-300 hover:text-white" onClick={() => setSplitTime(currentTime)} disabled={!selectedClip}>Set to Playhead</Button>
                        <Button variant="outline" className="border-white/10 text-gray-300 hover:text-white" onClick={() => void handleSplit()} disabled={isSaving || !selectedClip}>Split Clip</Button>
                      </div>
                    </div>

                    <div className="space-y-3">
                      <div className="text-sm font-medium flex items-center gap-2 text-gray-200"><AudioLines className="w-4 h-4" />Audio</div>
                      <div className="space-y-2">
                        <div className="flex items-center justify-between text-xs text-gray-400">
                          <span>Volume</span>
                          <span>{volume}%</span>
                        </div>
                        <Slider min={0} max={200} step={1} value={[volume]} onValueChange={(v) => setVolume(v[0] || 0)} />
                      </div>
                      <div className="space-y-2">
                        <div className="flex items-center justify-between text-xs text-gray-400">
                          <span>Playback Rate</span>
                          <span>{playbackRate.toFixed(2)}x</span>
                        </div>
                        <Slider min={0.5} max={2} step={0.05} value={[playbackRate]} onValueChange={(v) => setPlaybackRate(v[0] || 1)} />
                      </div>
                      <Button variant="outline" className="w-full border-white/10 text-gray-300 hover:text-white" onClick={() => setIsMuted((m) => !m)}>
                        {isMuted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
                        {isMuted ? "Unmute" : "Mute"}
                      </Button>
                    </div>

                    <div className="space-y-3">
                      <div className="text-sm font-medium flex items-center gap-2 text-gray-200"><Palette className="w-4 h-4" />Video FX</div>
                      {[
                        ["Brightness", "brightness", 40, 180, 1],
                        ["Contrast", "contrast", 40, 180, 1],
                        ["Saturation", "saturation", 0, 220, 1],
                        ["Blur", "blur", 0, 8, 0.1],
                        ["Hue", "hue", -180, 180, 1],
                        ["Zoom", "zoom", 1, 2, 0.01],
                      ].map(([label, key, min, max, step]) => {
                        const typedKey = key as keyof VideoFx;
                        const currentValue = videoFx[typedKey];
                        return (
                          <div key={key} className="space-y-1.5">
                            <div className="flex items-center justify-between text-xs text-gray-400">
                              <span>{label}</span>
                              <span>{currentValue}</span>
                            </div>
                            <Slider
                              min={Number(min)}
                              max={Number(max)}
                              step={Number(step)}
                              value={[currentValue]}
                              onValueChange={(value) => setVideoFx((current) => ({ ...current, [typedKey]: value[0] ?? currentValue }))}
                            />
                          </div>
                        );
                      })}
                    </div>

                    <Button variant="outline" className="w-full border-white/10 text-gray-300 hover:text-white" onClick={resetPreviewAdjustments}>
                      <Gauge className="w-4 h-4" />
                      Reset Preview Adjustments
                    </Button>
                  </CardContent>
                </Card>

                <Card className="bg-white/5 border-white/10">
                  <CardHeader className="pb-3">
                    <CardTitle className="text-base flex items-center gap-2 text-white">
                      <Subtitles className="w-4 h-4" />
                      Subtitle Control
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    <textarea
                      value={captionText}
                      onChange={(e) => setCaptionText(e.target.value)}
                      placeholder="Edit subtitle script"
                      className="w-full min-h-24 rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-cyan-400"
                    />

                    <div className="grid grid-cols-2 gap-2">
                      <Select value={captionPosition} onValueChange={setCaptionPosition}>
                        <SelectTrigger className="bg-white/5 border-white/10 text-white">
                          <SelectValue placeholder="Position" />
                        </SelectTrigger>
                        <SelectContent className="bg-[#1a1a2e] border-white/10 text-white">
                          <SelectItem value="top">Top</SelectItem>
                          <SelectItem value="middle">Middle</SelectItem>
                          <SelectItem value="bottom">Bottom</SelectItem>
                        </SelectContent>
                      </Select>

                      <Select value={exportPreset} onValueChange={setExportPreset}>
                        <SelectTrigger className="bg-white/5 border-white/10 text-white">
                          <SelectValue placeholder="Preset" />
                        </SelectTrigger>
                        <SelectContent className="bg-[#1a1a2e] border-white/10 text-white">
                          <SelectItem value="tiktok">TikTok</SelectItem>
                          <SelectItem value="reels">Reels</SelectItem>
                          <SelectItem value="shorts">Shorts</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="space-y-2">
                      <div className="flex items-center justify-between text-xs text-gray-400">
                        <span>Subtitle Size</span>
                        <span>{subtitleSize}</span>
                      </div>
                      <Slider min={28} max={88} step={1} value={[subtitleSize]} onValueChange={(v) => setSubtitleSize(v[0] || 52)} />
                    </div>

                    <div className="space-y-2">
                      <div className="flex items-center justify-between text-xs text-gray-400">
                        <span>Vertical Offset</span>
                        <span>{subtitleY}%</span>
                      </div>
                      <Slider min={10} max={85} step={1} value={[subtitleY]} onValueChange={(v) => setSubtitleY(v[0] || 78)} />
                    </div>

                    <div className="space-y-2">
                      <div className="text-xs text-gray-400">Highlight words (click to toggle)</div>
                      <div className="max-h-28 overflow-y-auto rounded-md border border-white/10 bg-white/5 p-2 flex flex-wrap gap-1.5">
                        {subtitleWords.length === 0 ? (
                          <span className="text-xs text-gray-500">No words yet.</span>
                        ) : (
                          subtitleWords.map((word, index) => {
                            const cleaned = word.toLowerCase().replace(/[^a-z0-9']/g, "");
                            const highlighted = cleaned ? highlightWords.includes(cleaned) : false;
                            return (
                              <button
                                key={`${word}-${index}`}
                                type="button"
                                onClick={() => toggleHighlightedWord(word)}
                                className={`px-1.5 py-0.5 rounded text-xs border ${
                                  highlighted ? "bg-yellow-500/20 border-yellow-500/50 text-yellow-300" : "bg-white/10 border-white/10 text-gray-300"
                                }`}
                              >
                                {word}
                              </button>
                            );
                          })
                        )}
                      </div>
                    </div>

                    <Button onClick={handleUpdateCaptions} disabled={isSaving || !selectedClip} className="w-full bg-cyan-500 hover:bg-cyan-400 text-black font-semibold">
                      Save Subtitle Changes
                    </Button>
                  </CardContent>
                </Card>
              </div>
            </div>

            <Card className="bg-white/5 border-white/10">
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2 text-white">
                  <Clapperboard className="w-4 h-4" />
                  Clips
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {mergeSelection.length >= 2 && (
                  <div className="flex justify-end">
                    <Button variant="outline" className="border-white/10 text-gray-300 hover:text-white" onClick={handleMerge} disabled={isSaving}>
                      Merge Selected ({mergeSelection.length})
                    </Button>
                  </div>
                )}
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {clips.map((clip) => (
                    <div
                      key={clip.id}
                      className={`relative rounded-lg border p-3 cursor-pointer transition-colors ${
                        selectedClipId === clip.id
                          ? "border-cyan-500 bg-cyan-500/10"
                          : "border-white/10 bg-white/5 hover:border-white/20"
                      }`}
                      onClick={() => selectClip(clip)}
                    >
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-white truncate">{clip.filename}</p>
                          <p className="text-xs text-gray-400 mt-0.5">{formatDuration(clip.duration)}</p>
                        </div>
                        <input
                          type="checkbox"
                          checked={mergeSelection.includes(clip.id)}
                          onChange={(e) => {
                            e.stopPropagation();
                            toggleMergeSelection(clip.id);
                          }}
                          className="ml-2 mt-0.5 accent-cyan-500"
                        />
                      </div>
                      {clip.video_url && (
                        <div className="mt-2 aspect-video rounded overflow-hidden bg-black/40">
                          <video
                            src={clip.video_url}
                            className="w-full h-full object-cover"
                            muted
                            preload="metadata"
                          />
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </>
        )}
        </div>
      </div>
    );
  } catch (error) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center p-4">
        <div className="text-center">
          <h2 className="text-xl font-semibold text-red-400 mb-2">Something went wrong</h2>
          <p className="text-gray-400 mb-4">{(error as Error).message}</p>
          <Link href="/dashboard" className="text-cyan-400 hover:underline">
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }
}
