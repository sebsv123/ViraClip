"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Rocket, Link2, Settings2, RefreshCw, CheckCircle2, AlertCircle,
  Loader2, Clock, Play, List, ChevronRight, Zap, FileVideo,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const STATUS_COLORS: Record<string, string> = {
  queued:      "bg-gray-400/20 text-gray-300 border-gray-400/30",
  ingesting:   "bg-blue-400/20 text-blue-300 border-blue-400/30",
  processing:  "bg-yellow-400/20 text-yellow-300 border-yellow-400/30",
  publishing:  "bg-purple-400/20 text-purple-300 border-purple-400/30",
  tracking:    "bg-cyan-400/20 text-cyan-300 border-cyan-400/30",
  done:        "bg-green-400/20 text-green-300 border-green-400/30",
  failed:      "bg-red-400/20 text-red-300 border-red-400/30",
};

interface WorkflowStep {
  name: string;
  status: string;
  started_at?: number;
  finished_at?: number;
  error?: string;
}

interface Workflow {
  workflow_id: string;
  status: string;
  task_id?: string;
  clips_produced: number;
  steps: WorkflowStep[];
  created_at: number;
  finished_at?: number;
  error?: string;
}

function formatTs(ts?: number): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString();
}

function StepTimeline({ steps }: { steps: WorkflowStep[] }) {
  return (
    <div className="space-y-1.5 mt-3">
      {steps.map((s, i) => (
        <div key={i} className="flex items-center gap-3 text-xs">
          <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
            s.status === "done" ? "bg-green-400" :
            s.status === "running" ? "bg-yellow-400 animate-pulse" :
            s.status === "failed" ? "bg-red-400" :
            s.status === "skipped" ? "bg-gray-500" : "bg-gray-700"
          }`} />
          <span className="capitalize text-white/70 w-28">{s.name.replace(/_/g, " ")}</span>
          <span className={`${
            s.status === "done" ? "text-green-400" :
            s.status === "running" ? "text-yellow-400" :
            s.status === "failed" ? "text-red-400" : "text-gray-500"
          }`}>{s.status}</span>
          {s.error && <span className="text-red-400 truncate max-w-48" title={s.error}>{s.error}</span>}
        </div>
      ))}
    </div>
  );
}

function WorkflowCard({ wf, onRefresh }: { wf: Workflow; onRefresh: () => void }) {
  const isTerminal = wf.status === "done" || wf.status === "failed";
  return (
    <Card className="border border-white/10 bg-white/5">
      <CardContent className="pt-4">
        <div className="flex items-start justify-between gap-2 mb-2">
          <div className="min-w-0">
            <p className="text-xs text-gray-500 font-mono truncate">{wf.workflow_id.slice(0, 16)}…</p>
            <div className="flex items-center gap-2 mt-1">
              <Badge variant="outline" className={`text-[10px] ${STATUS_COLORS[wf.status] || ""}`}>
                {wf.status}
              </Badge>
              {wf.clips_produced > 0 && (
                <span className="text-xs text-green-400">{wf.clips_produced} clips</span>
              )}
              {wf.task_id && (
                <span className="text-xs text-cyan-400 font-mono">task:{wf.task_id.slice(0, 8)}</span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-1 flex-shrink-0">
            {!isTerminal && (
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onRefresh}>
                <RefreshCw className="w-3 h-3" />
              </Button>
            )}
            <span className="text-[10px] text-gray-600">{formatTs(wf.created_at)}</span>
          </div>
        </div>
        {wf.error && (
          <p className="text-xs text-red-400 mb-2 flex items-center gap-1">
            <AlertCircle className="w-3 h-3" /> {wf.error}
          </p>
        )}
        <StepTimeline steps={wf.steps} />
      </CardContent>
    </Card>
  );
}

export default function AutopilotPage() {
  const router = useRouter();
  const [sourceUrl, setSourceUrl] = useState("");
  const [niche, setNiche] = useState("auto");
  const [platform, setPlatform] = useState("tiktok");
  const [maxClips, setMaxClips] = useState(5);
  const [jumpCut, setJumpCut] = useState(true);
  const [denoise, setDenoise] = useState(true);
  const [autoPublish, setAutoPublish] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState("");
  const [activeWorkflow, setActiveWorkflow] = useState<Workflow | null>(null);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [loadingList, setLoadingList] = useState(false);

  const fetchWorkflows = useCallback(async () => {
    setLoadingList(true);
    try {
      const res = await fetch(`${API}/autopilot/workflows?limit=10`);
      if (res.ok) {
        const data = await res.json();
        setWorkflows(data.workflows || []);
      }
    } finally {
      setLoadingList(false);
    }
  }, []);

  const refreshActive = useCallback(async (id: string) => {
    const res = await fetch(`${API}/autopilot/status/${id}`);
    if (res.ok) {
      const wf = await res.json();
      setActiveWorkflow(wf);
      if (wf.status !== "done" && wf.status !== "failed") {
        setTimeout(() => refreshActive(id), 5000);
      } else {
        fetchWorkflows();
      }
    }
  }, [fetchWorkflows]);

  useEffect(() => { fetchWorkflows(); }, [fetchWorkflows]);

  async function handleLaunch() {
    if (!sourceUrl.trim()) { setLaunchError("Enter a video URL"); return; }
    setLaunching(true);
    setLaunchError("");
    try {
      const res = await fetch(`${API}/autopilot/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_url: sourceUrl,
          niche,
          target_platform: platform,
          max_clips: maxClips,
          jump_cut: jumpCut,
          jump_cut_fillers: jumpCut,
          denoise_audio: denoise,
          auto_publish: autoPublish,
        }),
      });
      const data = await res.json();
      if (!res.ok) { setLaunchError(data.detail || "Failed to start"); return; }
      const wf: Workflow = {
        workflow_id: data.workflow_id,
        status: data.status,
        clips_produced: 0,
        steps: [],
        created_at: Date.now() / 1000,
      };
      setActiveWorkflow(wf);
      setSourceUrl("");
      setTimeout(() => refreshActive(data.workflow_id), 3000);
    } catch {
      setLaunchError("Could not reach backend");
    } finally {
      setLaunching(false);
    }
  }

  return (
    <div className="min-h-screen bg-[hsl(220,25%,4%)] text-white p-6">
      <div className="max-w-4xl mx-auto space-y-6">

        {/* Header */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-cyan-400/20 flex items-center justify-center">
            <Rocket className="w-5 h-5 text-cyan-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold">Auto-Pilot</h1>
            <p className="text-sm text-gray-400">
              Paste a URL → ViraClip ingests, processes, and publishes viral clips automatically
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Launch Form */}
          <div className="lg:col-span-3 space-y-4">
            <Card className="border border-white/10 bg-white/5">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm flex items-center gap-2">
                  <Link2 className="w-4 h-4 text-cyan-400" /> Source Video
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <Input
                    className="border-white/20 bg-white/5 h-10"
                    placeholder="https://youtube.com/watch?v=... or TikTok, Instagram, Twitch"
                    value={sourceUrl}
                    onChange={(e) => setSourceUrl(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleLaunch()}
                  />
                  {launchError && (
                    <p className="text-xs text-red-400 mt-1 flex items-center gap-1">
                      <AlertCircle className="w-3 h-3" /> {launchError}
                    </p>
                  )}
                </div>

                {/* Quick settings */}
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="text-xs text-gray-400 mb-1 block">Niche</Label>
                    <Select value={niche} onValueChange={setNiche}>
                      <SelectTrigger className="h-8 text-xs border-white/20 bg-white/5">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {["auto","fitness","finance","food","comedy","education","lifestyle","tech","beauty","travel"].map(n => (
                          <SelectItem key={n} value={n} className="text-xs capitalize">
                            {n === "auto" ? "Auto-detect" : n.charAt(0).toUpperCase() + n.slice(1)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="text-xs text-gray-400 mb-1 block">Platform</Label>
                    <Select value={platform} onValueChange={setPlatform}>
                      <SelectTrigger className="h-8 text-xs border-white/20 bg-white/5">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {["tiktok","instagram","youtube"].map(p => (
                          <SelectItem key={p} value={p} className="text-xs capitalize">{p}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                {/* Toggle row */}
                <div className="flex items-center gap-6">
                  <div className="flex items-center gap-2">
                    <Switch id="jc" checked={jumpCut} onCheckedChange={setJumpCut} />
                    <Label htmlFor="jc" className="text-xs text-gray-300">Jump-cut</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <Switch id="dn" checked={denoise} onCheckedChange={setDenoise} />
                    <Label htmlFor="dn" className="text-xs text-gray-300">Denoise</Label>
                  </div>
                  <div className="flex items-center gap-2">
                    <Switch id="ap" checked={autoPublish} onCheckedChange={setAutoPublish} />
                    <Label htmlFor="ap" className="text-xs text-gray-300">Auto-publish</Label>
                  </div>
                </div>

                <Button
                  className="w-full h-10 bg-cyan-500 hover:bg-cyan-600 text-black font-bold"
                  onClick={handleLaunch}
                  disabled={launching || !sourceUrl.trim()}
                >
                  {launching ? (
                    <><Loader2 className="w-4 h-4 mr-2 animate-spin" /> Starting…</>
                  ) : (
                    <><Rocket className="w-4 h-4 mr-2" /> Launch Auto-Pilot</>
                  )}
                </Button>
              </CardContent>
            </Card>

            {/* Active workflow */}
            {activeWorkflow && (
              <div>
                <p className="text-xs font-semibold text-gray-400 mb-2 flex items-center gap-1">
                  <Zap className="w-3 h-3 text-yellow-400" /> Active Workflow
                </p>
                <WorkflowCard wf={activeWorkflow} onRefresh={() => refreshActive(activeWorkflow.workflow_id)} />
              </div>
            )}
          </div>

          {/* Workflow history */}
          <div className="lg:col-span-2">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs font-semibold text-gray-400 flex items-center gap-1">
                <List className="w-3 h-3" /> Recent Workflows
              </p>
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={fetchWorkflows} disabled={loadingList}>
                <RefreshCw className={`w-3 h-3 ${loadingList ? "animate-spin" : ""}`} />
              </Button>
            </div>
            <div className="space-y-2">
              {workflows.length === 0 && !loadingList && (
                <p className="text-xs text-gray-600 text-center py-6">No workflows yet</p>
              )}
              {workflows.map((wf) => (
                <div
                  key={wf.workflow_id}
                  className="border border-white/10 rounded-xl p-3 bg-white/5 hover:bg-white/10 transition-colors cursor-default"
                >
                  <div className="flex items-center justify-between">
                    <Badge variant="outline" className={`text-[10px] ${STATUS_COLORS[wf.status] || ""}`}>
                      {wf.status}
                    </Badge>
                    <span className="text-[10px] text-gray-600">{formatTs(wf.created_at)}</span>
                  </div>
                  <p className="text-[10px] text-gray-600 font-mono mt-1">{wf.workflow_id.slice(0, 20)}…</p>
                  {wf.clips_produced > 0 && (
                    <p className="text-xs text-green-400 mt-1">{wf.clips_produced} clips produced</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Info cards */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { icon: FileVideo, label: "Ingest", desc: "Download from YouTube, TikTok, Instagram, Twitch", color: "cyan" },
            { icon: Settings2, label: "Process", desc: "Denoise → jump-cut → subtitle → virality score", color: "purple" },
            { icon: Play, label: "Publish", desc: "Auto-post to TikTok / Instagram / YouTube at optimal time", color: "pink" },
          ].map(({ icon: Icon, label, desc, color }) => (
            <div key={label} className={`p-4 rounded-xl border border-${color}-400/20 bg-${color}-400/5`}>
              <Icon className={`w-5 h-5 text-${color}-400 mb-2`} />
              <p className="text-sm font-semibold mb-1">{label}</p>
              <p className="text-xs text-gray-500">{desc}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
