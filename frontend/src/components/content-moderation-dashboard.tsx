"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { 
  Shield, 
  AlertTriangle, 
  CheckCircle2, 
  XCircle,
  Search,
  Filter,
  Eye,
  FileText,
  User,
  Clock,
  MoreHorizontal
} from "lucide-react";

interface ModerationItem {
  id: string;
  contentId: string;
  title: string;
  type: "video" | "text" | "thumbnail";
  status: "approved" | "flagged" | "blocked" | "pending";
  categories: string[];
  confidence: number;
  entities: Array<{
    text: string;
    type: string;
    confidence: number;
  }>;
  reviewedAt: string;
  reviewer?: string;
}

export function ContentModerationDashboard() {
  const [items, setItems] = useState<ModerationItem[]>([
    {
      id: "mod_1",
      contentId: "clip_001",
      title: "Tutorial: Advanced Editing Techniques",
      type: "video",
      status: "approved",
      categories: ["safe"],
      confidence: 0.95,
      entities: [
        { text: "Adobe Premiere", type: "product", confidence: 0.92 },
        { text: "YouTube", type: "organization", confidence: 0.88 }
      ],
      reviewedAt: "2024-01-15T10:30:00Z",
      reviewer: "system"
    },
    {
      id: "mod_2",
      contentId: "clip_002",
      title: "Controversial Discussion",
      type: "video",
      status: "flagged",
      categories: ["sensitive_topic"],
      confidence: 0.72,
      entities: [
        { text: "Election 2024", type: "event", confidence: 0.85 }
      ],
      reviewedAt: "2024-01-15T11:15:00Z",
      reviewer: "auto"
    },
    {
      id: "mod_3",
      contentId: "clip_003",
      title: "Quick Tips Compilation",
      type: "text",
      status: "approved",
      categories: ["safe"],
      confidence: 0.98,
      entities: [],
      reviewedAt: "2024-01-15T09:45:00Z"
    }
  ]);

  const [searchQuery, setSearchQuery] = useState("");
  const [filterStatus, setFilterStatus] = useState<string>("all");

  const filteredItems = items.filter(item => {
    const matchesSearch = item.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
                         item.contentId.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = filterStatus === "all" || item.status === filterStatus;
    return matchesSearch && matchesStatus;
  });

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "approved": return <CheckCircle2 className="h-5 w-5 text-green-500" />;
      case "flagged": return <AlertTriangle className="h-5 w-5 text-yellow-500" />;
      case "blocked": return <XCircle className="h-5 w-5 text-red-500" />;
      case "pending": return <Clock className="h-5 w-5 text-blue-500" />;
      default: return <Shield className="h-5 w-5 text-gray-500" />;
    }
  };

  const getStatusBadge = (status: string) => {
    const variants: Record<string, any> = {
      approved: "default",
      flagged: "secondary",
      blocked: "destructive",
      pending: "outline"
    };
    return <Badge variant={variants[status] || "default"}>{status}</Badge>;
  };

  const stats = {
    approved: items.filter(i => i.status === "approved").length,
    flagged: items.filter(i => i.status === "flagged").length,
    blocked: items.filter(i => i.status === "blocked").length,
    pending: items.filter(i => i.status === "pending").length
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Shield className="h-8 w-8 text-blue-500" />
            Content Moderation
          </h1>
          <p className="text-muted-foreground">
            AI-powered content review and moderation
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline">
            <FileText className="h-4 w-4 mr-2" />
            Export Report
          </Button>
          <Button>
            <Shield className="h-4 w-4 mr-2" />
            Run Moderation
          </Button>
        </div>
      </div>

      {/* Stats Overview */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Approved</p>
                <p className="text-2xl font-bold text-green-600">{stats.approved}</p>
              </div>
              <CheckCircle2 className="h-8 w-8 text-green-500 opacity-50" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Flagged</p>
                <p className="text-2xl font-bold text-yellow-600">{stats.flagged}</p>
              </div>
              <AlertTriangle className="h-8 w-8 text-yellow-500 opacity-50" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Blocked</p>
                <p className="text-2xl font-bold text-red-600">{stats.blocked}</p>
              </div>
              <XCircle className="h-8 w-8 text-red-500 opacity-50" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Pending</p>
                <p className="text-2xl font-bold text-blue-600">{stats.pending}</p>
              </div>
              <Clock className="h-8 w-8 text-blue-500 opacity-50" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="p-4">
          <div className="flex flex-col md:flex-row gap-4">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search content..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10"
              />
            </div>
            <div className="flex gap-2">
              <Button
                variant={filterStatus === "all" ? "default" : "outline"}
                onClick={() => setFilterStatus("all")}
              >
                All
              </Button>
              <Button
                variant={filterStatus === "flagged" ? "default" : "outline"}
                onClick={() => setFilterStatus("flagged")}
              >
                Flagged
              </Button>
              <Button
                variant={filterStatus === "pending" ? "default" : "outline"}
                onClick={() => setFilterStatus("pending")}
              >
                Pending
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Moderation Items */}
      <div className="space-y-4">
        {filteredItems.map((item) => (
          <Card key={item.id}>
            <CardContent className="p-4">
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-4">
                  {getStatusIcon(item.status)}
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold">{item.title}</h3>
                      {getStatusBadge(item.status)}
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {item.contentId} • {item.type}
                    </p>
                    
                    {/* Categories */}
                    <div className="flex gap-2 mt-2">
                      {item.categories.map((cat) => (
                        <Badge key={cat} variant="outline" className="text-xs">
                          {cat}
                        </Badge>
                      ))}
                    </div>

                    {/* Confidence */}
                    <div className="mt-2">
                      <div className="flex items-center gap-2 text-sm">
                        <span className="text-muted-foreground">Confidence:</span>
                        <Progress value={item.confidence * 100} className="w-24 h-2" />
                        <span className="text-sm font-medium">
                          {(item.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                    </div>

                    {/* Detected Entities */}
                    {item.entities.length > 0 && (
                      <div className="mt-2">
                        <p className="text-sm text-muted-foreground">Detected Entities:</p>
                        <div className="flex flex-wrap gap-2 mt-1">
                          {item.entities.map((entity, idx) => (
                            <Badge key={idx} variant="secondary" className="text-xs">
                              {entity.text} ({entity.type})
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
                
                <div className="flex items-center gap-2">
                  <div className="text-right text-sm text-muted-foreground">
                    <p>{new Date(item.reviewedAt).toLocaleString()}</p>
                    {item.reviewer && (
                      <p>by {item.reviewer}</p>
                    )}
                  </div>
                  <Button variant="ghost" size="icon">
                    <Eye className="h-4 w-4" />
                  </Button>
                  <Button variant="ghost" size="icon">
                    <MoreHorizontal className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
