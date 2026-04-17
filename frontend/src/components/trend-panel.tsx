"use client";

import { useState, useEffect } from "react";
import { TrendingUp, Clock, Hash, Lightbulb, RefreshCw, ChevronDown, ChevronUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

const NICHES = [
  "auto", "fitness", "finance", "food", "comedy",
  "education", "lifestyle", "tech", "beauty", "travel",
];

interface Hook {
  phrase: string;
  engagement_boost: number;
}

interface CaptionPattern {
  pattern: string;
  avg_engagement_boost: number;
  platforms: string[];
}

interface TrendReport {
  niche: string;
  hooks: Hook[];
  caption_patterns: CaptionPattern[];
  hashtags: string[];
  best_posting_hours: Record<string, number[]>;
  trending_topics: string[];
}

interface TrendPanelProps {
  platform?: string;
  initialNiche?: string;
  compact?: boolean;
}

export function TrendPanel({ platform = "tiktok", initialNiche = "auto", compact = false }: TrendPanelProps) {
  const [niche, setNiche] = useState(initialNiche);
  const [report, setReport] = useState<TrendReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(!compact);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  async function fetchReport(selectedNiche: string) {
    setLoading(true);
    try {
      const res = await fetch(
        `${apiUrl}/trend-intelligence/report?niche=${selectedNiche}&platform=${platform}`
      );
      if (res.ok) {
        const data = await res.json();
        setReport(data);
      }
    } catch {
      // Silently fail — panel is informational
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchReport(niche);
  }, [niche, platform]);

  const bestHours = report?.best_posting_hours?.[platform] ?? [];

  return (
    <Card className="border border-white/10 bg-white/5 backdrop-blur-sm">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm font-semibold text-white">
            <TrendingUp className="w-4 h-4 text-cyan-400" />
            Trend Intelligence
          </CardTitle>
          <div className="flex items-center gap-2">
            <Select value={niche} onValueChange={setNiche}>
              <SelectTrigger className="h-7 w-28 text-xs border-white/20 bg-white/5">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {NICHES.map((n) => (
                  <SelectItem key={n} value={n} className="text-xs capitalize">
                    {n === "auto" ? "Auto-detect" : n.charAt(0).toUpperCase() + n.slice(1)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => fetchReport(niche)}
              disabled={loading}
            >
              <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
            </Button>
            {compact && (
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={() => setExpanded((p) => !p)}
              >
                {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              </Button>
            )}
          </div>
        </div>
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-4 pt-0">
          {loading && (
            <p className="text-xs text-gray-500 text-center py-2">Loading trends…</p>
          )}

          {!loading && report && (
            <>
              {/* Hook Phrases */}
              {report.hooks.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-400 mb-2 flex items-center gap-1">
                    <Lightbulb className="w-3 h-3 text-yellow-400" /> Hook Phrases
                  </p>
                  <ul className="space-y-1">
                    {report.hooks.slice(0, 3).map((h, i) => (
                      <li
                        key={i}
                        className="text-xs text-white/80 bg-white/5 rounded-lg px-3 py-2 cursor-pointer hover:bg-white/10 transition-colors"
                        onClick={() => navigator.clipboard?.writeText(h.phrase)}
                        title="Click to copy"
                      >
                        {h.phrase}
                        <span className="ml-2 text-cyan-400 text-[10px]">
                          +{Math.round((h.engagement_boost - 1) * 100)}%
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Best Posting Times */}
              {bestHours.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-400 mb-2 flex items-center gap-1">
                    <Clock className="w-3 h-3 text-purple-400" /> Best Post Times (UTC)
                  </p>
                  <div className="flex gap-2 flex-wrap">
                    {bestHours.map((h) => (
                      <Badge
                        key={h}
                        variant="outline"
                        className="text-[10px] border-purple-400/40 text-purple-300"
                      >
                        {h}:00
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {/* Hashtags */}
              {report.hashtags.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-400 mb-2 flex items-center gap-1">
                    <Hash className="w-3 h-3 text-pink-400" /> Hashtags
                  </p>
                  <div className="flex gap-1 flex-wrap">
                    {report.hashtags.slice(0, 6).map((tag) => (
                      <Badge
                        key={tag}
                        variant="secondary"
                        className="text-[10px] bg-pink-400/10 text-pink-300 border-pink-400/20 cursor-pointer hover:bg-pink-400/20"
                        onClick={() => navigator.clipboard?.writeText(`#${tag}`)}
                      >
                        #{tag}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}

              {/* Trending Topics */}
              {report.trending_topics.length > 0 && (
                <div>
                  <p className="text-xs font-semibold text-gray-400 mb-2">Trending Now</p>
                  <div className="flex gap-1 flex-wrap">
                    {report.trending_topics.slice(0, 4).map((t, i) => (
                      <Badge
                        key={i}
                        variant="outline"
                        className="text-[10px] border-white/20 text-white/60"
                      >
                        {t}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {!loading && !report && (
            <p className="text-xs text-gray-500 text-center py-2">
              Could not load trends — check backend connection
            </p>
          )}
        </CardContent>
      )}
    </Card>
  );
}
