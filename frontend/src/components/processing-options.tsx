"use client";

import { useState } from "react";
import { Scissors, Volume2, Mic, Link2, CheckCircle2, Loader2, AlertCircle } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export interface ProcessingConfig {
  jump_cut: boolean;
  jump_cut_fillers: boolean;
  denoise_audio: boolean;
  add_voiceover: boolean;
  voiceover_text: string;
}

interface ProcessingOptionsProps {
  value: ProcessingConfig;
  onChange: (config: ProcessingConfig) => void;
}

export const DEFAULT_PROCESSING_CONFIG: ProcessingConfig = {
  jump_cut: false,
  jump_cut_fillers: true,
  denoise_audio: false,
  add_voiceover: false,
  voiceover_text: "",
};

export function ProcessingOptions({ value, onChange }: ProcessingOptionsProps) {
  function set<K extends keyof ProcessingConfig>(key: K, val: ProcessingConfig[K]) {
    onChange({ ...value, [key]: val });
  }

  return (
    <Card className="border border-white/10 bg-white/5 backdrop-blur-sm">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold text-white flex items-center gap-2">
          <Scissors className="w-4 h-4 text-cyan-400" />
          Processing Enhancements
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Jump-Cut Toggle */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <Label className="text-sm text-white flex items-center gap-2">
              <Scissors className="w-3.5 h-3.5 text-cyan-400" />
              Jump-Cut Engine
              {value.jump_cut && <Badge className="text-[10px] bg-cyan-400/20 text-cyan-300 border-cyan-400/30 ml-1">ON</Badge>}
            </Label>
            <p className="text-xs text-gray-500 mt-0.5">
              Auto-removes silence gaps and filler words (um, uh, you know…)
            </p>
            {value.jump_cut && (
              <div className="mt-2 flex items-center gap-2">
                <Switch
                  id="jump-cut-fillers"
                  checked={value.jump_cut_fillers}
                  onCheckedChange={(v) => set("jump_cut_fillers", v)}
                />
                <Label htmlFor="jump-cut-fillers" className="text-xs text-gray-400">
                  Also remove filler words
                </Label>
              </div>
            )}
          </div>
          <Switch
            id="jump-cut"
            checked={value.jump_cut}
            onCheckedChange={(v) => set("jump_cut", v)}
          />
        </div>

        <div className="border-t border-white/10" />

        {/* Audio Denoiser Toggle */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <Label className="text-sm text-white flex items-center gap-2">
              <Volume2 className="w-3.5 h-3.5 text-purple-400" />
              Audio Denoiser
              {value.denoise_audio && <Badge className="text-[10px] bg-purple-400/20 text-purple-300 border-purple-400/30 ml-1">ON</Badge>}
            </Label>
            <p className="text-xs text-gray-500 mt-0.5">
              Removes background noise + normalises loudness to −14 LUFS
            </p>
          </div>
          <Switch
            id="denoise"
            checked={value.denoise_audio}
            onCheckedChange={(v) => set("denoise_audio", v)}
          />
        </div>

        <div className="border-t border-white/10" />

        {/* Voiceover Toggle */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1">
            <Label className="text-sm text-white flex items-center gap-2">
              <Mic className="w-3.5 h-3.5 text-pink-400" />
              AI Voiceover
              {value.add_voiceover && <Badge className="text-[10px] bg-pink-400/20 text-pink-300 border-pink-400/30 ml-1">ON</Badge>}
            </Label>
            <p className="text-xs text-gray-500 mt-0.5">
              Generate TTS narration (OpenAI or ElevenLabs) mixed into clips
            </p>
            {value.add_voiceover && (
              <Input
                className="mt-2 h-8 text-xs border-white/20 bg-white/5"
                placeholder="Enter narration script…"
                value={value.voiceover_text}
                onChange={(e) => set("voiceover_text", e.target.value)}
                maxLength={500}
              />
            )}
          </div>
          <Switch
            id="voiceover"
            checked={value.add_voiceover}
            onCheckedChange={(v) => set("add_voiceover", v)}
          />
        </div>
      </CardContent>
    </Card>
  );
}


/* ─── URL Ingestion Widget ─────────────────────────────────────────────────── */

interface UrlIngestWidgetProps {
  onIngested: (localPath: string, title: string) => void;
  apiUrl?: string;
}

export function UrlIngestWidget({ onIngested, apiUrl = "" }: UrlIngestWidgetProps) {
  const [url, setUrl] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [message, setMessage] = useState("");
  const [platform, setPlatform] = useState("");

  const base = apiUrl || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  async function handleIngest() {
    if (!url.trim()) return;
    setStatus("loading");
    setMessage("");
    try {
      // Detect platform first
      const detectRes = await fetch(`${base}/ingest/detect-platform?url=${encodeURIComponent(url)}`);
      if (detectRes.ok) {
        const { platform: p } = await detectRes.json();
        setPlatform(p);
      }

      // Ingest
      const res = await fetch(`${base}/ingest/url`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      const data = await res.json();
      if (data.success && data.local_path) {
        setStatus("done");
        setMessage(`Downloaded: ${data.title || url}`);
        onIngested(data.local_path, data.title || "");
      } else {
        setStatus("error");
        setMessage(data.error || "Download failed");
      }
    } catch (err) {
      setStatus("error");
      setMessage("Failed to reach backend");
    }
  }

  return (
    <div className="space-y-2">
      <Label className="text-sm text-white flex items-center gap-2">
        <Link2 className="w-3.5 h-3.5 text-cyan-400" />
        Import from URL
        <Badge variant="outline" className="text-[10px] border-cyan-400/30 text-cyan-400">
          YouTube · TikTok · Instagram · Twitch
        </Badge>
      </Label>
      <div className="flex gap-2">
        <Input
          className="h-9 text-sm border-white/20 bg-white/5 flex-1"
          placeholder="https://youtube.com/watch?v=..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleIngest()}
          disabled={status === "loading"}
        />
        <Button
          size="sm"
          className="h-9 bg-cyan-500 hover:bg-cyan-600 text-black font-semibold"
          onClick={handleIngest}
          disabled={!url.trim() || status === "loading"}
        >
          {status === "loading" ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            "Import"
          )}
        </Button>
      </div>

      {status === "done" && (
        <p className="text-xs text-green-400 flex items-center gap-1">
          <CheckCircle2 className="w-3 h-3" /> {message}
          {platform && <span className="text-gray-500 ml-1">({platform})</span>}
        </p>
      )}
      {status === "error" && (
        <p className="text-xs text-red-400 flex items-center gap-1">
          <AlertCircle className="w-3 h-3" /> {message}
        </p>
      )}
    </div>
  );
}
