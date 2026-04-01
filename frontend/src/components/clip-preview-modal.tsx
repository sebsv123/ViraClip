"use client";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Sparkles, TrendingUp, Target, Zap, Share2 } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

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
  };
}

export function ClipPreviewModal({ isOpen, onClose, clip }: ClipPreviewModalProps) {
  const getScoreColor = (score: number) => {
    if (score >= 8) return "text-green-600";
    if (score >= 6) return "text-yellow-600";
    if (score >= 4) return "text-orange-600";
    return "text-red-600";
  };

  const getProgressColor = (score: number) => {
    if (score >= 8) return "bg-green-500";
    if (score >= 6) return "bg-yellow-500";
    if (score >= 4) return "bg-orange-500";
    return "bg-red-500";
  };

  const formatDuration = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-purple-600" />
            Clip Preview & Analytics
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-6">
          {/* Video Preview */}
          <div className="relative bg-black rounded-lg overflow-hidden aspect-[9/16] max-h-[500px] mx-auto">
            <video
              src={clip.video_url}
              controls
              autoPlay
              loop
              className="w-full h-full object-contain"
            />
            <div className="absolute bottom-2 right-2 bg-black/70 text-white text-xs px-2 py-1 rounded">
              {formatDuration(clip.duration)}
            </div>
          </div>

          {/* Virality Score Overview */}
          <div className="bg-gradient-to-br from-purple-50 to-blue-50 rounded-lg p-6">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h3 className="text-lg font-semibold text-gray-900">Virality Score</h3>
                <p className="text-sm text-gray-600">Predicted viral potential</p>
              </div>
              <div className={`text-4xl font-bold ${getScoreColor(clip.virality_score)}`}>
                {clip.virality_score}
                <span className="text-xl text-gray-400">/10</span>
              </div>
            </div>
            
            <Progress 
              value={clip.virality_score * 10} 
              className="h-3"
              indicatorClassName={getProgressColor(clip.virality_score)}
            />

            <div className="mt-4 flex items-center gap-2 text-sm">
              {clip.virality_score >= 8 && (
                <Badge className="bg-green-100 text-green-800">
                  🔥 High Viral Potential
                </Badge>
              )}
              {clip.virality_score >= 6 && clip.virality_score < 8 && (
                <Badge className="bg-yellow-100 text-yellow-800">
                  ⚡ Good Potential
                </Badge>
              )}
              {clip.virality_score < 6 && (
                <Badge className="bg-orange-100 text-orange-800">
                  📈 Needs Optimization
                </Badge>
              )}
            </div>
          </div>

          {/* Detailed Metrics */}
          <div className="space-y-3">
            <h4 className="font-semibold text-gray-900">Detailed Metrics</h4>

            {/* Hook Score */}
            {clip.hook_score !== undefined && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex items-center justify-between p-3 bg-white border rounded-lg hover:bg-gray-50 cursor-help transition-colors">
                      <div className="flex items-center gap-2">
                        <Target className="w-4 h-4 text-purple-600" />
                        <span className="text-sm font-medium">Hook Score</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Progress 
                          value={clip.hook_score * 10} 
                          className="w-32 h-2"
                          indicatorClassName={getProgressColor(clip.hook_score)}
                        />
                        <span className={`text-sm font-bold ${getScoreColor(clip.hook_score)}`}>
                          {clip.hook_score}/10
                        </span>
                      </div>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">
                    <p className="font-semibold mb-1">Hook Quality</p>
                    <p className="text-xs">
                      Measures how well the first 3 seconds capture attention. 
                      High hook scores correlate with lower scroll-away rates.
                    </p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}

            {/* Engagement Score */}
            {clip.engagement_score !== undefined && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex items-center justify-between p-3 bg-white border rounded-lg hover:bg-gray-50 cursor-help transition-colors">
                      <div className="flex items-center gap-2">
                        <Zap className="w-4 h-4 text-yellow-600" />
                        <span className="text-sm font-medium">Engagement Score</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Progress 
                          value={clip.engagement_score * 10} 
                          className="w-32 h-2"
                          indicatorClassName={getProgressColor(clip.engagement_score)}
                        />
                        <span className={`text-sm font-bold ${getScoreColor(clip.engagement_score)}`}>
                          {clip.engagement_score}/10
                        </span>
                      </div>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">
                    <p className="font-semibold mb-1">Engagement Potential</p>
                    <p className="text-xs">
                      Predicts likelihood of comments, likes, and saves. 
                      Content that provokes emotion or curiosity scores higher.
                    </p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}

            {/* Value Score */}
            {clip.value_score !== undefined && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex items-center justify-between p-3 bg-white border rounded-lg hover:bg-gray-50 cursor-help transition-colors">
                      <div className="flex items-center gap-2">
                        <TrendingUp className="w-4 h-4 text-blue-600" />
                        <span className="text-sm font-medium">Value Score</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Progress 
                          value={clip.value_score * 10} 
                          className="w-32 h-2"
                          indicatorClassName={getProgressColor(clip.value_score)}
                        />
                        <span className={`text-sm font-bold ${getScoreColor(clip.value_score)}`}>
                          {clip.value_score}/10
                        </span>
                      </div>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">
                    <p className="font-semibold mb-1">Content Value</p>
                    <p className="text-xs">
                      Measures educational or entertainment value. 
                      High-value content gets saved and shared more often.
                    </p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}

            {/* Shareability Score */}
            {clip.shareability_score !== undefined && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <div className="flex items-center justify-between p-3 bg-white border rounded-lg hover:bg-gray-50 cursor-help transition-colors">
                      <div className="flex items-center gap-2">
                        <Share2 className="w-4 h-4 text-green-600" />
                        <span className="text-sm font-medium">Shareability Score</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Progress 
                          value={clip.shareability_score * 10} 
                          className="w-32 h-2"
                          indicatorClassName={getProgressColor(clip.shareability_score)}
                        />
                        <span className={`text-sm font-bold ${getScoreColor(clip.shareability_score)}`}>
                          {clip.shareability_score}/10
                        </span>
                      </div>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent className="max-w-xs">
                    <p className="font-semibold mb-1">Share Potential</p>
                    <p className="text-xs">
                      Likelihood of viewers sharing to friends/groups. 
                      Surprising, funny, or relatable content scores higher.
                    </p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>

          {/* Hook Type */}
          {clip.hook_type && clip.hook_type !== "none" && (
            <div className="bg-purple-50 border border-purple-200 rounded-lg p-4">
              <div className="flex items-start gap-2">
                <Target className="w-5 h-5 text-purple-600 mt-0.5" />
                <div>
                  <p className="font-semibold text-purple-900 mb-1">Hook Type Detected</p>
                  <Badge className="bg-purple-100 text-purple-800 capitalize">
                    {clip.hook_type.replace('_', ' ')}
                  </Badge>
                  <p className="text-sm text-purple-700 mt-2">
                    {clip.hook_type === 'question' && 'Opens with a compelling question that creates curiosity.'}
                    {clip.hook_type === 'statement' && 'Bold statement that grabs attention immediately.'}
                    {clip.hook_type === 'statistic' && 'Data-driven hook that builds credibility.'}
                    {clip.hook_type === 'story' && 'Story-based hook that builds emotional connection.'}
                    {clip.hook_type === 'contrast' && 'Before/after or comparison hook that shows transformation.'}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Social Copy */}
          {(clip.social_title || clip.social_description || clip.suggested_hashtags) && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
              <h4 className="font-semibold text-blue-900 flex items-center gap-2">
                <Share2 className="w-4 h-4" />
                Suggested Social Media Copy
              </h4>
              
              {clip.social_title && (
                <div>
                  <p className="text-xs text-blue-700 font-medium mb-1">Title:</p>
                  <p className="text-sm text-blue-900">{clip.social_title}</p>
                </div>
              )}

              {clip.social_description && (
                <div>
                  <p className="text-xs text-blue-700 font-medium mb-1">Description:</p>
                  <p className="text-sm text-blue-900">{clip.social_description}</p>
                </div>
              )}

              {clip.suggested_hashtags && clip.suggested_hashtags.length > 0 && (
                <div>
                  <p className="text-xs text-blue-700 font-medium mb-1">Hashtags:</p>
                  <div className="flex flex-wrap gap-1">
                    {clip.suggested_hashtags.map((tag, idx) => (
                      <Badge key={idx} variant="outline" className="text-blue-600">
                        #{tag}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Pro Tips */}
          <div className="bg-gradient-to-r from-purple-50 to-pink-50 border border-purple-200 rounded-lg p-4">
            <h4 className="font-semibold text-purple-900 mb-2 flex items-center gap-2">
              <Sparkles className="w-4 h-4" />
              Pro Tips to Boost Performance
            </h4>
            <ul className="text-sm text-purple-800 space-y-1">
              {clip.virality_score < 7 && (
                <li>• Consider re-editing to strengthen the hook in the first 3 seconds</li>
              )}
              {clip.engagement_score && clip.engagement_score < 7 && (
                <li>• Add a call-to-action or question to boost engagement</li>
              )}
              {(!clip.suggested_hashtags || clip.suggested_hashtags.length === 0) && (
                <li>• Add relevant trending hashtags when posting</li>
              )}
              <li>• Post during peak hours (6-9pm in your target timezone)</li>
              <li>• Reply to first 10 comments within 30 minutes for algorithm boost</li>
            </ul>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
