"use client";

import { useState, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { Badge } from "@/components/ui/badge";
import { 
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Scissors,
  Wand2,
  Type,
  Palette,
  Music,
  Image,
  Sparkles,
  Download,
  Undo2,
  Redo2,
  ZoomIn,
  ZoomOut,
  Grid3X3,
  Layers
} from "lucide-react";

interface ClipEditorProps {
  clipUrl: string;
  clipId: string;
  duration: number;
  onSave: (editedClip: EditedClip) => void;
}

interface EditedClip {
  clipId: string;
  startTime: number;
  endTime: number;
  effects: AppliedEffect[];
  captions: CaptionTrack[];
  thumbnail: string;
  exportSettings: ExportSettings;
}

interface AppliedEffect {
  id: string;
  type: string;
  startTime: number;
  endTime: number;
  intensity: number;
  params: Record<string, any>;
}

interface CaptionTrack {
  id: string;
  text: string;
  startTime: number;
  endTime: number;
  style: CaptionStyle;
}

interface CaptionStyle {
  font: string;
  size: number;
  color: string;
  backgroundColor: string;
  position: "top" | "middle" | "bottom";
}

interface ExportSettings {
  resolution: "720p" | "1080p" | "4K";
  format: "mp4" | "mov";
  quality: "high" | "medium" | "low";
}

const AVAILABLE_EFFECTS = [
  { id: "zoom_pulse", name: "Zoom Pulse", icon: ZoomIn, category: "viral" },
  { id: "shake", name: "Camera Shake", icon: Grid3X3, category: "viral" },
  { id: "glitch", name: "Glitch Effect", icon: Sparkles, category: "trending" },
  { id: "speed_ramp", name: "Speed Ramp", icon: Play, category: "viral" },
  { id: "text_highlight", name: "Text Highlight", icon: Type, category: "engagement" },
  { id: "emoji_pop", name: "Emoji Pop", icon: Sparkles, category: "engagement" },
  { id: "color_grade", name: "Viral Color Grade", icon: Palette, category: "aesthetic" },
  { id: "transition", name: "Smooth Transition", icon: Layers, category: "pro" },
];

const TEMPLATES = [
  { id: "tutorial", name: "Tutorial Style", description: "Clean, educational look" },
  { id: "reaction", name: "Reaction Video", description: "High energy, expressive" },
  { id: "storytime", name: "Story Time", description: "Intimate, narrative" },
  { id: "comedy", name: "Comedy Sketch", description: "Funny, punchy timing" },
  { id: "product", name: "Product Review", description: "Professional showcase" },
];

export function AdvancedClipEditor({ clipUrl, clipId, duration, onSave }: ClipEditorProps) {
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [selectedRange, setSelectedRange] = useState<[number, number]>([0, duration]);
  const [appliedEffects, setAppliedEffects] = useState<AppliedEffect[]>([]);
  const [captions, setCaptions] = useState<CaptionTrack[]>([]);
  const [selectedEffect, setSelectedEffect] = useState<string | null>(null);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [activeTab, setActiveTab] = useState<"trim" | "effects" | "captions" | "templates">("trim");
  const videoRef = useRef<HTMLVideoElement>(null);

  const togglePlay = () => {
    if (videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause();
      } else {
        videoRef.current.play();
      }
      setIsPlaying(!isPlaying);
    }
  };

  const applyEffect = (effectId: string) => {
    const newEffect: AppliedEffect = {
      id: `${effectId}_${Date.now()}`,
      type: effectId,
      startTime: selectedRange[0],
      endTime: selectedRange[1],
      intensity: 0.5,
      params: {},
    };
    setAppliedEffects([...appliedEffects, newEffect]);
  };

  const removeEffect = (effectId: string) => {
    setAppliedEffects(appliedEffects.filter(e => e.id !== effectId));
  };

  const handleSave = () => {
    const editedClip: EditedClip = {
      clipId,
      startTime: selectedRange[0],
      endTime: selectedRange[1],
      effects: appliedEffects,
      captions,
      thumbnail: "",
      exportSettings: {
        resolution: "1080p",
        format: "mp4",
        quality: "high",
      },
    };
    onSave(editedClip);
  };

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  return (
    <div className="flex flex-col h-screen bg-background">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b">
        <div className="flex items-center gap-4">
          <h1 className="text-xl font-bold">Advanced Clip Editor</h1>
          <Badge variant="outline">{formatTime(duration)}</Badge>
          {appliedEffects.length > 0 && (
            <Badge variant="secondary">
              {appliedEffects.length} effects
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm">
            <Undo2 className="h-4 w-4 mr-1" />
            Undo
          </Button>
          <Button variant="outline" size="sm">
            <Redo2 className="h-4 w-4 mr-1" />
            Redo
          </Button>
          <Button onClick={handleSave}>
            <Download className="h-4 w-4 mr-1" />
            Export Clip
          </Button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Panel - Video Preview */}
        <div className="flex-1 flex flex-col">
          {/* Video Player */}
          <div className="flex-1 flex items-center justify-center bg-black relative">
            <video
              ref={videoRef}
              src={clipUrl}
              className="max-w-full max-h-full"
              onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
              onEnded={() => setIsPlaying(false)}
            />
            
            {/* Overlay Effects Preview */}
            {appliedEffects.map((effect) => (
              <div
                key={effect.id}
                className="absolute inset-0 pointer-events-none"
                style={{
                  opacity: currentTime >= effect.startTime && currentTime <= effect.endTime ? effect.intensity : 0,
                }}
              >
                {effect.type === "zoom_pulse" && (
                  <div className="w-full h-full flex items-center justify-center">
                    <div className="animate-pulse text-white text-4xl font-bold">
                      ZOOM
                    </div>
                  </div>
                )}
                {effect.type === "glitch" && (
                  <div className="w-full h-full bg-red-500/20 animate-pulse" />
                )}
              </div>
            ))}

            {/* Caption Overlay */}
            {captions.map((caption) => (
              currentTime >= caption.startTime && currentTime <= caption.endTime && (
                <div
                  key={caption.id}
                  className="absolute bottom-20 left-0 right-0 text-center"
                >
                  <span
                    className="px-4 py-2 rounded-lg font-bold text-shadow"
                    style={{
                      fontSize: `${caption.style.size}px`,
                      color: caption.style.color,
                      backgroundColor: caption.style.backgroundColor,
                    }}
                  >
                    {caption.text}
                  </span>
                </div>
              )
            ))}
          </div>

          {/* Timeline */}
          <div className="h-48 border-t bg-muted/50 p-4">
            <div className="flex items-center gap-2 mb-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setZoomLevel(Math.max(0.5, zoomLevel - 0.25))}
              >
                <ZoomOut className="h-4 w-4" />
              </Button>
              <span className="text-sm text-muted-foreground">{zoomLevel}x</span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setZoomLevel(Math.min(3, zoomLevel + 0.25))}
              >
                <ZoomIn className="h-4 w-4" />
              </Button>
              <div className="flex-1" />
              <span className="text-sm font-mono">
                {formatTime(currentTime)} / {formatTime(duration)}
              </span>
            </div>

            {/* Timeline Tracks */}
            <div className="space-y-2">
              {/* Video Track */}
              <div className="h-12 bg-muted rounded-lg relative overflow-hidden">
                <div className="absolute inset-y-0 left-0 bg-primary/20 w-full" />
                {/* Playhead */}
                <div
                  className="absolute top-0 bottom-0 w-0.5 bg-red-500 z-10"
                  style={{ left: `${(currentTime / duration) * 100}%` }}
                />
                {/* Selection Range */}
                <div
                  className="absolute top-1 bottom-1 bg-primary/40 rounded border-2 border-primary"
                  style={{
                    left: `${(selectedRange[0] / duration) * 100}%`,
                    width: `${((selectedRange[1] - selectedRange[0]) / duration) * 100}%`,
                  }}
                />
              </div>

              {/* Effects Track */}
              {appliedEffects.length > 0 && (
                <div className="h-8 bg-muted rounded-lg relative overflow-hidden">
                  {appliedEffects.map((effect) => (
                    <TooltipProvider key={effect.id}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div
                            className="absolute top-1 bottom-1 bg-purple-500/30 rounded px-2 text-xs flex items-center cursor-pointer hover:bg-purple-500/50"
                            style={{
                              left: `${(effect.startTime / duration) * 100}%`,
                              width: `${((effect.endTime - effect.startTime) / duration) * 100}%`,
                            }}
                            onClick={() => removeEffect(effect.id)}
                          >
                            {effect.type}
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>Click to remove</p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  ))}
                </div>
              )}

              {/* Captions Track */}
              {captions.length > 0 && (
                <div className="h-8 bg-muted rounded-lg relative overflow-hidden">
                  {captions.map((caption) => (
                    <div
                      key={caption.id}
                      className="absolute top-1 bottom-1 bg-yellow-500/30 rounded px-2 text-xs flex items-center"
                      style={{
                        left: `${(caption.startTime / duration) * 100}%`,
                        width: `${((caption.endTime - caption.startTime) / duration) * 100}%`,
                      }}
                    >
                      {caption.text.slice(0, 20)}...
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Playback Controls */}
            <div className="flex items-center justify-center gap-2 mt-4">
              <Button variant="outline" size="icon" onClick={() => setCurrentTime(0)}>
                <SkipBack className="h-4 w-4" />
              </Button>
              <Button size="icon" onClick={togglePlay}>
                {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              </Button>
              <Button variant="outline" size="icon" onClick={() => setCurrentTime(duration)}>
                <SkipForward className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>

        {/* Right Panel - Tools */}
        <div className="w-80 border-l bg-muted/30 p-4 overflow-y-auto">
          {/* Tabs */}
          <div className="flex gap-1 mb-4">
            {(["trim", "effects", "captions", "templates"] as const).map((tab) => (
              <Button
                key={tab}
                variant={activeTab === tab ? "default" : "ghost"}
                size="sm"
                onClick={() => setActiveTab(tab)}
                className="flex-1 capitalize"
              >
                {tab}
              </Button>
            ))}
          </div>

          {/* Trim Panel */}
          {activeTab === "trim" && (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Scissors className="h-4 w-4" />
                    Trim Clip
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="space-y-2">
                    <label className="text-sm">Start Time</label>
                    <Slider
                      value={[selectedRange[0]]}
                      max={duration}
                      step={0.1}
                      onValueChange={([v]) => setSelectedRange([v, selectedRange[1]])}
                    />
                    <span className="text-xs text-muted-foreground">
                      {formatTime(selectedRange[0])}
                    </span>
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm">End Time</label>
                    <Slider
                      value={[selectedRange[1]]}
                      max={duration}
                      step={0.1}
                      onValueChange={([v]) => setSelectedRange([selectedRange[0], v])}
                    />
                    <span className="text-xs text-muted-foreground">
                      {formatTime(selectedRange[1])}
                    </span>
                  </div>
                  <div className="pt-2 border-t">
                    <p className="text-sm font-medium">Duration: {formatTime(selectedRange[1] - selectedRange[0])}</p>
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Effects Panel */}
          {activeTab === "effects" && (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Wand2 className="h-4 w-4" />
                    Viral Effects
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 gap-2">
                    {AVAILABLE_EFFECTS.map((effect) => (
                      <TooltipProvider key={effect.id}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <Button
                              variant="outline"
                              size="sm"
                              className="flex flex-col items-center gap-1 h-auto py-2"
                              onClick={() => applyEffect(effect.id)}
                            >
                              <effect.icon className="h-4 w-4" />
                              <span className="text-xs">{effect.name}</span>
                            </Button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p className="capitalize">{effect.category}</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    ))}
                  </div>
                </CardContent>
              </Card>

              {appliedEffects.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-sm">Applied Effects</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      {appliedEffects.map((effect) => (
                        <div
                          key={effect.id}
                          className="flex items-center justify-between p-2 bg-muted rounded"
                        >
                          <span className="text-sm">{effect.type}</span>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => removeEffect(effect.id)}
                          >
                            Remove
                          </Button>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}
            </div>
          )}

          {/* Templates Panel */}
          {activeTab === "templates" && (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-sm">Quick Templates</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {TEMPLATES.map((template) => (
                      <Button
                        key={template.id}
                        variant="outline"
                        className="w-full justify-start text-left h-auto"
                      >
                        <div>
                          <p className="font-medium">{template.name}</p>
                          <p className="text-xs text-muted-foreground">
                            {template.description}
                          </p>
                        </div>
                      </Button>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
