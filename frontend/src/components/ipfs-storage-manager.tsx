"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { 
  Database, 
  Upload, 
  Globe, 
  CheckCircle2,
  Copy,
  ExternalLink,
  Clock,
  HardDrive,
  Wifi
} from "lucide-react";

interface IPFSContent {
  id: string;
  contentId: string;
  ipfsHash: string;
  contentType: string;
  size: number;
  status: "pending" | "uploading" | "pinned" | "replicated" | "failed";
  gateways: string[];
  pinnedAt: string;
}

interface IPFSGateway {
  id: string;
  url: string;
  region: string;
  latency: number;
  reliability: number;
}

export function IPFSStorageManager() {
  const [contents, setContents] = useState<IPFSContent[]>([
    {
      id: "ipfs_1",
      contentId: "clip_001",
      ipfsHash: "QmX4zYtG5Dk2mR9bF8cJ3aL7sN6pQ1wE4rT8yU2iO9pA5",
      contentType: "video",
      size: 157286400, // 150 MB
      status: "replicated",
      gateways: [
        "https://ipfs.io/ipfs/QmX4zYtG5Dk2mR9bF8cJ3aL7sN6pQ1wE4rT8yU2iO9pA5",
        "https://cloudflare-ipfs.com/ipfs/QmX4zYtG5Dk2mR9bF8cJ3aL7sN6pQ1wE4rT8yU2iO9pA5"
      ],
      pinnedAt: "2024-01-15T10:30:00Z"
    },
    {
      id: "ipfs_2",
      contentId: "clip_002",
      ipfsHash: "QmY7aKbH8E3nL0pR5cG9fI4bJ8mN2rO6xS9zV3uP8iL0qB",
      contentType: "thumbnail",
      size: 2097152, // 2 MB
      status: "pinned",
      gateways: [
        "https://ipfs.io/ipfs/QmY7aKbH8E3nL0pR5cG9fI4bJ8mN2rO6xS9zV3uP8iL0qB"
      ],
      pinnedAt: "2024-01-15T11:15:00Z"
    }
  ]);

  const [gateways] = useState<IPFSGateway[]>([
    { id: "ipfs_io", url: "https://ipfs.io/ipfs/", region: "Global", latency: 45, reliability: 95 },
    { id: "cloudflare", url: "https://cloudflare-ipfs.com/ipfs/", region: "Global", latency: 25, reliability: 98 },
    { id: "pinata", url: "https://gateway.pinata.cloud/ipfs/", region: "US-East", latency: 85, reliability: 92 },
    { id: "dweb", url: "https://dweb.link/ipfs/", region: "Global", latency: 55, reliability: 90 }
  ]);

  const [isUploading, setIsUploading] = useState(false);

  const totalSize = contents.reduce((sum, c) => sum + c.size, 0);
  const pinnedCount = contents.filter(c => c.status === "pinned" || c.status === "replicated").length;

  const formatSize = (bytes: number) => {
    if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(2) + " GB";
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(2) + " MB";
    if (bytes >= 1024) return (bytes / 1024).toFixed(2) + " KB";
    return bytes + " B";
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
  };

  const getStatusBadge = (status: string) => {
    const variants: Record<string, any> = {
      pending: "secondary",
      uploading: "default",
      pinned: "default",
      replicated: "outline",
      failed: "destructive"
    };
    return <Badge variant={variants[status] || "default"}>{status}</Badge>;
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Database className="h-8 w-8 text-blue-500" />
            IPFS Storage Manager
          </h1>
          <p className="text-muted-foreground">
            Decentralized content storage on IPFS
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline">
            <Wifi className="h-4 w-4 mr-2" />
            Test Gateways
          </Button>
          <Button disabled={isUploading}>
            <Upload className="h-4 w-4 mr-2" />
            {isUploading ? "Uploading..." : "Upload to IPFS"}
          </Button>
        </div>
      </div>

      {/* Stats Overview */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total Content</p>
                <p className="text-2xl font-bold">{contents.length}</p>
              </div>
              <HardDrive className="h-8 w-8 text-muted-foreground opacity-50" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total Size</p>
                <p className="text-2xl font-bold">{formatSize(totalSize)}</p>
              </div>
              <Database className="h-8 w-8 text-muted-foreground opacity-50" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Pinned</p>
                <p className="text-2xl font-bold">{pinnedCount}</p>
              </div>
              <CheckCircle2 className="h-8 w-8 text-green-500 opacity-50" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Active Gateways</p>
                <p className="text-2xl font-bold">{gateways.length}</p>
              </div>
              <Globe className="h-8 w-8 text-muted-foreground opacity-50" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* IPFS Content List */}
      <Card>
        <CardHeader>
          <CardTitle>Stored Content</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {contents.map((content) => (
              <div key={content.id} className="p-4 border rounded-lg">
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <h3 className="font-semibold">{content.contentId}</h3>
                      {getStatusBadge(content.status)}
                      <Badge variant="outline">{content.contentType}</Badge>
                    </div>
                    
                    {/* IPFS Hash */}
                    <div className="flex items-center gap-2 p-2 bg-muted rounded-lg">
                      <Database className="h-4 w-4 text-muted-foreground" />
                      <code className="text-sm flex-1 truncate">
                        {content.ipfsHash}
                      </code>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => copyToClipboard(content.ipfsHash)}
                      >
                        <Copy className="h-4 w-4" />
                      </Button>
                    </div>

                    {/* Gateways */}
                    <div className="mt-3 space-y-1">
                      {content.gateways.map((gateway, idx) => (
                        <div key={idx} className="flex items-center gap-2 text-sm">
                          <Globe className="h-3 w-3 text-muted-foreground" />
                          <span className="text-muted-foreground flex-1 truncate">
                            {gateway}
                          </span>
                          <Button variant="ghost" size="sm" asChild>
                            <a href={gateway} target="_blank" rel="noopener noreferrer">
                              <ExternalLink className="h-3 w-3" />
                            </a>
                          </Button>
                        </div>
                      ))}
                    </div>

                    <div className="flex items-center gap-4 mt-2 text-sm text-muted-foreground">
                      <span>Size: {formatSize(content.size)}</span>
                      <span>Pinned: {new Date(content.pinnedAt).toLocaleString()}</span>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Gateway Status */}
      <Card>
        <CardHeader>
          <CardTitle>IPFS Gateways</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {gateways.map((gateway) => (
              <div key={gateway.id} className="p-4 border rounded-lg">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Globe className="h-5 w-5" />
                    <span className="font-medium">{gateway.id}</span>
                  </div>
                  <Badge variant={gateway.latency < 50 ? "default" : gateway.latency < 100 ? "secondary" : "destructive"}>
                    {gateway.latency}ms
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground mb-2">{gateway.url}</p>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">{gateway.region}</span>
                  <span>Reliability: {gateway.reliability}%</span>
                </div>
                <Progress value={gateway.reliability} className="mt-2" />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
