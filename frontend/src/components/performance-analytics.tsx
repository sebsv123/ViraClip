"use client";

import { useState, useEffect } from "react";
import { BarChart3, TrendingUp, Award, RefreshCw, Eye, ThumbsUp, Share2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface TemplateStats {
  template: string;
  viral_count: number;
  total_count: number;
  avg_views: number;
  avg_engagement_rate: number;
  viral_rate: number;
}

interface PerformanceAnalyticsProps {
  compact?: boolean;
}

const PLATFORM_COLORS: Record<string, string> = {
  tiktok:    "bg-pink-400/20 text-pink-300 border-pink-400/30",
  instagram: "bg-purple-400/20 text-purple-300 border-purple-400/30",
  youtube:   "bg-red-400/20 text-red-300 border-red-400/30",
};

function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function PerformanceAnalytics({ compact = false }: PerformanceAnalyticsProps) {
  const [templates, setTemplates] = useState<TemplateStats[]>([]);
  const [loading, setLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  async function fetchStats() {
    setLoading(true);
    try {
      const res = await fetch(`${apiUrl}/performance-webhook/top-templates?limit=5`);
      if (res.ok) {
        const data = await res.json();
        setTemplates(data.templates || []);
        setLastUpdated(new Date());
      }
    } catch {
      // Silently fail — panel is informational
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { fetchStats(); }, []);

  if (compact && templates.length === 0) return null;

  return (
    <Card className="border border-white/10 bg-white/5 backdrop-blur-sm">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-sm font-semibold text-white">
            <BarChart3 className="w-4 h-4 text-pink-400" />
            Performance Analytics
          </CardTitle>
          <div className="flex items-center gap-2">
            {lastUpdated && (
              <span className="text-[10px] text-gray-600">
                {lastUpdated.toLocaleTimeString()}
              </span>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={fetchStats}
              disabled={loading}
            >
              <RefreshCw className={`w-3 h-3 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="pt-0 space-y-3">
        {loading && templates.length === 0 && (
          <p className="text-xs text-gray-500 text-center py-3">Loading analytics…</p>
        )}

        {!loading && templates.length === 0 && (
          <p className="text-xs text-gray-600 text-center py-3">
            No performance data yet — receive webhooks to populate
          </p>
        )}

        {templates.map((t, i) => (
          <div key={t.template} className="space-y-1.5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                {i === 0 && <Award className="w-3.5 h-3.5 text-yellow-400" />}
                <span className="text-xs font-medium text-white capitalize">{t.template}</span>
                <Badge variant="outline" className="text-[10px] border-green-400/30 text-green-300">
                  {Math.round(t.viral_rate * 100)}% viral
                </Badge>
              </div>
              <span className="text-[10px] text-gray-500">{t.viral_count}/{t.total_count} clips</span>
            </div>

            {/* Mini stat row */}
            <div className="flex gap-3 text-[10px] text-gray-500">
              <span className="flex items-center gap-1">
                <Eye className="w-2.5 h-2.5" /> {fmt(t.avg_views)} avg
              </span>
              <span className="flex items-center gap-1">
                <TrendingUp className="w-2.5 h-2.5" />
                {(t.avg_engagement_rate * 100).toFixed(1)}% eng
              </span>
            </div>

            {/* Progress bar */}
            <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-pink-500 to-purple-500 rounded-full transition-all"
                style={{ width: `${Math.min(100, t.viral_rate * 100)}%` }}
              />
            </div>

            {i < templates.length - 1 && <div className="border-t border-white/5" />}
          </div>
        ))}

        {templates.length > 0 && (
          <p className="text-[10px] text-gray-600 text-right">
            Powered by performance webhooks
          </p>
        )}
      </CardContent>
    </Card>
  );
}
