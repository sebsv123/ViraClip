"use client";

import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { TrendingUp, Flame, Sparkles, Target } from "lucide-react";

interface ViralityScoreBadgeProps {
  score: number;
  size?: "sm" | "md" | "lg";
  showIcon?: boolean;
  showTooltip?: boolean;
}

export function ViralityScoreBadge({ 
  score, 
  size = "md", 
  showIcon = true,
  showTooltip = true 
}: ViralityScoreBadgeProps) {
  const getScoreData = (score: number) => {
    if (score >= 9) {
      return {
        label: "Viral",
        color: "bg-gradient-to-r from-red-500 to-orange-500 text-white",
        icon: Flame,
        description: "🔥 Exceptional viral potential! This content has all the elements of a viral hit."
      };
    }
    if (score >= 8) {
      return {
        label: "Excellent",
        color: "bg-gradient-to-r from-green-500 to-emerald-500 text-white",
        icon: Sparkles,
        description: "⭐ Excellent viral potential. High chance of strong engagement."
      };
    }
    if (score >= 7) {
      return {
        label: "Strong",
        color: "bg-gradient-to-r from-green-400 to-green-500 text-white",
        icon: TrendingUp,
        description: "📈 Strong potential. Good fundamentals for engagement."
      };
    }
    if (score >= 6) {
      return {
        label: "Good",
        color: "bg-gradient-to-r from-yellow-400 to-yellow-500 text-gray-900",
        icon: Target,
        description: "✅ Good potential. Consider minor optimizations."
      };
    }
    if (score >= 5) {
      return {
        label: "Fair",
        color: "bg-gradient-to-r from-yellow-300 to-yellow-400 text-gray-900",
        icon: Target,
        description: "⚡ Fair potential. Optimize hook and pacing for better results."
      };
    }
    return {
      label: "Needs Work",
      color: "bg-gradient-to-r from-orange-400 to-red-400 text-white",
      icon: Target,
      description: "💡 Needs optimization. Review hook, pacing, and content value."
    };
  };

  const data = getScoreData(score);
  const Icon = data.icon;

  const sizeClasses = {
    sm: "text-xs px-2 py-0.5",
    md: "text-sm px-3 py-1",
    lg: "text-base px-4 py-1.5"
  };

  const iconSizes = {
    sm: "w-3 h-3",
    md: "w-4 h-4",
    lg: "w-5 h-5"
  };

  const badge = (
    <div 
      className={`inline-flex items-center gap-1.5 rounded-full font-semibold shadow-sm ${data.color} ${sizeClasses[size]}`}
    >
      {showIcon && <Icon className={iconSizes[size]} />}
      <span>{score}/10</span>
      <span className="opacity-90">·</span>
      <span className="font-medium">{data.label}</span>
    </div>
  );

  if (!showTooltip) {
    return badge;
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="cursor-help">
            {badge}
          </div>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">
          <p className="font-semibold mb-1">Virality Score: {score}/10</p>
          <p className="text-xs">{data.description}</p>
          <p className="text-xs mt-2 opacity-75">
            Based on AI analysis of hook quality, engagement potential, content value, and shareability.
          </p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
