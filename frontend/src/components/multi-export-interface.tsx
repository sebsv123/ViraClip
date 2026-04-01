"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { 
  Share2, 
  Youtube, 
  Instagram, 
  Facebook, 
  Twitter, 
  Linkedin,
  Download,
  CheckCircle2,
  Loader2,
  Calendar,
  Clock,
  Settings,
  Globe
} from "lucide-react";

interface MultiExportProps {
  clipId: string;
  clipUrl: string;
  clipTitle: string;
  thumbnailUrl: string;
}

interface PlatformConfig {
  id: string;
  name: string;
  icon: React.ElementType;
  color: string;
  maxDuration: number;
  aspectRatio: string;
  recommendedResolution: string;
  connected: boolean;
}

interface ExportJob {
  platformId: string;
  status: "pending" | "uploading" | "processing" | "published" | "failed";
  progress: number;
  url?: string;
  error?: string;
  scheduledFor?: string;
}

const PLATFORMS: PlatformConfig[] = [
  {
    id: "youtube",
    name: "YouTube Shorts",
    icon: Youtube,
    color: "#FF0000",
    maxDuration: 60,
    aspectRatio: "9:16",
    recommendedResolution: "1080x1920",
    connected: false,
  },
  {
    id: "tiktok",
    name: "TikTok",
    icon: Share2,
    color: "#000000",
    maxDuration: 180,
    aspectRatio: "9:16",
    recommendedResolution: "1080x1920",
    connected: false,
  },
  {
    id: "instagram",
    name: "Instagram Reels",
    icon: Instagram,
    color: "#E4405F",
    maxDuration: 90,
    aspectRatio: "9:16",
    recommendedResolution: "1080x1920",
    connected: false,
  },
  {
    id: "facebook",
    name: "Facebook",
    icon: Facebook,
    color: "#1877F2",
    maxDuration: 240,
    aspectRatio: "9:16",
    recommendedResolution: "1080x1920",
    connected: false,
  },
  {
    id: "twitter",
    name: "Twitter/X",
    icon: Twitter,
    color: "#1DA1F2",
    maxDuration: 140,
    aspectRatio: "9:16",
    recommendedResolution: "1080x1920",
    connected: false,
  },
  {
    id: "linkedin",
    name: "LinkedIn",
    icon: Linkedin,
    color: "#0A66C2",
    maxDuration: 600,
    aspectRatio: "9:16",
    recommendedResolution: "1080x1920",
    connected: false,
  },
];

export function MultiExportInterface({ clipId, clipUrl, clipTitle, thumbnailUrl }: MultiExportProps) {
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([]);
  const [exportJobs, setExportJobs] = useState<ExportJob[]>([]);
  const [isExporting, setIsExporting] = useState(false);
  const [scheduleDate, setScheduleDate] = useState<string>("");
  const [captions, setCaptions] = useState<Record<string, string>>({});
  const [hashtags, setHashtags] = useState<Record<string, string>>({});
  const [showAdvanced, setShowAdvanced] = useState(false);

  const togglePlatform = (platformId: string) => {
    setSelectedPlatforms((prev) =>
      prev.includes(platformId)
        ? prev.filter((id) => id !== platformId)
        : [...prev, platformId]
    );
  };

  const handleExport = async () => {
    setIsExporting(true);
    
    // Initialize export jobs
    const jobs: ExportJob[] = selectedPlatforms.map((platformId) => ({
      platformId,
      status: "pending",
      progress: 0,
    }));
    
    setExportJobs(jobs);

    // Simulate export process
    for (let i = 0; i < selectedPlatforms.length; i++) {
      const platformId = selectedPlatforms[i];
      
      // Update status to uploading
      setExportJobs((prev) =>
        prev.map((job) =>
          job.platformId === platformId ? { ...job, status: "uploading", progress: 25 } : job
        )
      );
      
      await new Promise((resolve) => setTimeout(resolve, 1500));
      
      // Update to processing
      setExportJobs((prev) =>
        prev.map((job) =>
          job.platformId === platformId ? { ...job, status: "processing", progress: 60 } : job
        )
      );
      
      await new Promise((resolve) => setTimeout(resolve, 2000));
      
      // Complete
      setExportJobs((prev) =>
        prev.map((job) =>
          job.platformId === platformId
            ? {
                ...job,
                status: "published",
                progress: 100,
                url: `https://${platformId}.com/video/${clipId}`,
              }
            : job
        )
      );
    }
    
    setIsExporting(false);
  };

  const getStatusIcon = (status: ExportJob["status"]) => {
    switch (status) {
      case "pending":
        return <Clock className="h-4 w-4 text-muted-foreground" />;
      case "uploading":
      case "processing":
        return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />;
      case "published":
        return <CheckCircle2 className="h-4 w-4 text-green-500" />;
      case "failed":
        return <div className="h-4 w-4 rounded-full bg-red-500" />;
      default:
        return null;
    }
  };

  const getStatusText = (status: ExportJob["status"]) => {
    switch (status) {
      case "pending":
        return "Pending";
      case "uploading":
        return "Uploading...";
      case "processing":
        return "Processing...";
      case "published":
        return "Published";
      case "failed":
        return "Failed";
      default:
        return "";
    }
  };

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Export to Social Media</h1>
          <p className="text-muted-foreground">
            Publish your clip to multiple platforms at once
          </p>
        </div>
        <Button variant="outline" onClick={() => setShowAdvanced(!showAdvanced)}>
          <Settings className="h-4 w-4 mr-2" />
          {showAdvanced ? "Hide" : "Show"} Advanced
        </Button>
      </div>

      {/* Clip Preview */}
      <Card>
        <CardContent className="p-4">
          <div className="flex gap-4">
            <div className="w-32 h-48 bg-muted rounded-lg overflow-hidden flex-shrink-0">
              {thumbnailUrl ? (
                <img
                  src={thumbnailUrl}
                  alt={clipTitle}
                  className="w-full h-full object-cover"
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                  No thumbnail
                </div>
              )}
            </div>
            <div className="flex-1">
              <h3 className="font-semibold text-lg">{clipTitle}</h3>
              <p className="text-sm text-muted-foreground mt-1">
                Clip ID: {clipId}
              </p>
              <div className="flex gap-2 mt-3">
                <Button variant="outline" size="sm">
                  <Download className="h-4 w-4 mr-1" />
                  Download
                </Button>
                <Button variant="outline" size="sm">
                  <Globe className="h-4 w-4 mr-1" />
                  Preview
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Platform Selection */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Share2 className="h-5 w-5" />
            Select Platforms
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            {PLATFORMS.map((platform) => {
              const Icon = platform.icon;
              const isSelected = selectedPlatforms.includes(platform.id);
              const job = exportJobs.find((j) => j.platformId === platform.id);

              return (
                <div
                  key={platform.id}
                  className={`relative p-4 rounded-lg border-2 cursor-pointer transition-all ${
                    isSelected
                      ? "border-primary bg-primary/5"
                      : "border-muted hover:border-muted-foreground"
                  }`}
                  onClick={() => !isExporting && togglePlatform(platform.id)}
                >
                  <div className="flex items-start gap-3">
                    <div
                      className="p-2 rounded-lg"
                      style={{ backgroundColor: `${platform.color}20` }}
                    >
                      <Icon
                        className="h-6 w-6"
                        style={{ color: platform.color }}
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h4 className="font-medium truncate">{platform.name}</h4>
                      <p className="text-xs text-muted-foreground">
                        {platform.maxDuration}s max
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {platform.aspectRatio}
                      </p>
                    </div>
                  </div>

                  {job && (
                    <div className="mt-3">
                      <div className="flex items-center gap-2 text-xs mb-1">
                        {getStatusIcon(job.status)}
                        <span>{getStatusText(job.status)}</span>
                      </div>
                      <Progress value={job.progress} className="h-1" />
                      {job.url && (
                        <a
                          href={job.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-blue-500 hover:underline mt-1 block"
                        >
                          View on {platform.name}
                        </a>
                      )}
                    </div>
                  )}

                  {isSelected && !job && (
                    <div className="absolute top-2 right-2">
                      <CheckCircle2 className="h-5 w-5 text-primary" />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Scheduling */}
      {showAdvanced && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Calendar className="h-5 w-5" />
              Schedule Publication
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex gap-4">
              <div className="flex-1">
                <label className="text-sm font-medium mb-2 block">
                  Publish Date & Time
                </label>
                <input
                  type="datetime-local"
                  className="w-full p-2 border rounded-md"
                  value={scheduleDate}
                  onChange={(e) => setScheduleDate(e.target.value)}
                />
              </div>
            </div>
            <p className="text-sm text-muted-foreground mt-2">
              Leave empty to publish immediately
            </p>
          </CardContent>
        </Card>
      )}

      {/* Caption & Hashtags */}
      {showAdvanced && selectedPlatforms.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Captions & Hashtags</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {selectedPlatforms.map((platformId) => {
              const platform = PLATFORMS.find((p) => p.id === platformId);
              if (!platform) return null;

              return (
                <div key={platformId} className="space-y-2">
                  <label className="text-sm font-medium flex items-center gap-2">
                    <platform.icon className="h-4 w-4" />
                    {platform.name} Caption
                  </label>
                  <textarea
                    className="w-full p-2 border rounded-md text-sm"
                    rows={2}
                    placeholder={`Write caption for ${platform.name}...`}
                    value={captions[platformId] || ""}
                    onChange={(e) =>
                      setCaptions({ ...captions, [platformId]: e.target.value })
                    }
                  />
                  <input
                    type="text"
                    className="w-full p-2 border rounded-md text-sm"
                    placeholder="#hashtag1 #hashtag2 #hashtag3"
                    value={hashtags[platformId] || ""}
                    onChange={(e) =>
                      setHashtags({ ...hashtags, [platformId]: e.target.value })
                    }
                  />
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* Export Button */}
      <div className="flex items-center justify-between pt-4">
        <div className="text-sm text-muted-foreground">
          {selectedPlatforms.length === 0 ? (
            "Select at least one platform"
          ) : (
            <>
              Publishing to <strong>{selectedPlatforms.length}</strong> platforms
            </>
          )}
        </div>
        <Button
          size="lg"
          disabled={selectedPlatforms.length === 0 || isExporting}
          onClick={handleExport}
        >
          {isExporting ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Publishing...
            </>
          ) : (
            <>
              <Share2 className="h-4 w-4 mr-2" />
              Publish Now
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
