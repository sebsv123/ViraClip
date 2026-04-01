"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { 
  BarChart3, 
  TrendingUp, 
  Users, 
  Video, 
  Zap,
  Activity,
  Target,
  Clock
} from "lucide-react";

interface AnalyticsData {
  totalClips: number;
  totalViews: number;
  avgViralityScore: number;
  processingTime: number;
  activeTasks: number;
  topPerformingClip: {
    title: string;
    score: number;
    views: number;
  } | null;
  recentActivity: Array<{
    action: string;
    timestamp: string;
    details: string;
  }>;
  metrics: {
    cpu: number;
    memory: number;
    queue: number;
  };
}

export function DashboardAnalytics() {
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [wsConnected, setWsConnected] = useState(false);

  useEffect(() => {
    // Connect to WebSocket for real-time updates
    const ws = new WebSocket(`wss://${window.location.host}/ws/analytics`);
    
    ws.onopen = () => {
      setWsConnected(true);
      console.log("Analytics WebSocket connected");
    };
    
    ws.onmessage = (event) => {
      const update = JSON.parse(event.data);
      setData(update);
    };
    
    ws.onclose = () => {
      setWsConnected(false);
    };

    // Initial fetch
    fetchAnalytics();

    return () => ws.close();
  }, []);

  const fetchAnalytics = async () => {
    try {
      const response = await fetch("/api/analytics/dashboard");
      const analyticsData = await response.json();
      setData(analyticsData);
    } catch (error) {
      console.error("Failed to fetch analytics:", error);
    }
  };

  if (!data) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 p-4">
        {[...Array(4)].map((_, i) => (
          <Card key={i} className="animate-pulse">
            <CardHeader className="h-20 bg-muted rounded" />
            <CardContent className="h-24 bg-muted rounded mt-2" />
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-6 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Analytics Dashboard</h1>
          <p className="text-muted-foreground">
            Real-time insights into your content performance
          </p>
        </div>
        <Badge variant={wsConnected ? "default" : "secondary"}>
          {wsConnected ? "● Live" : "○ Offline"}
        </Badge>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="Total Clips"
          value={data.totalClips.toString()}
          change="+12%"
          icon={<Video className="h-4 w-4" />}
          trend="up"
        />
        <MetricCard
          title="Avg Virality Score"
          value={`${data.avgViralityScore.toFixed(1)}/100`}
          change="+5.2%"
          icon={<Target className="h-4 w-4" />}
          trend="up"
        />
        <MetricCard
          title="Processing Time"
          value={`${data.processingTime}s`}
          change="-15%"
          icon={<Clock className="h-4 w-4" />}
          trend="down"
        />
        <MetricCard
          title="Active Tasks"
          value={data.activeTasks.toString()}
          change="3 queued"
          icon={<Activity className="h-4 w-4" />}
          trend="neutral"
        />
      </div>

      {/* Main Content Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Performance Chart */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart3 className="h-5 w-5" />
              Performance Overview
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-[300px] flex items-end justify-between gap-2">
              {/* Simulated bar chart */}
              {[65, 78, 82, 91, 85, 88, 94, 89, 92, 96, 88, 91].map((value, i) => (
                <div key={i} className="flex-1 flex flex-col items-center gap-2">
                  <div
                    className="w-full bg-primary rounded-t transition-all duration-500"
                    style={{ height: `${value * 2.5}px` }}
                  />
                  <span className="text-xs text-muted-foreground">
                    {i + 1}d
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* System Health */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Zap className="h-5 w-5" />
              System Health
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>CPU Usage</span>
                <span className="font-medium">{data.metrics.cpu}%</span>
              </div>
              <Progress value={data.metrics.cpu} />
            </div>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>Memory</span>
                <span className="font-medium">{data.metrics.memory}%</span>
              </div>
              <Progress value={data.metrics.memory} />
            </div>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span>Queue</span>
                <span className="font-medium">{data.metrics.queue} tasks</span>
              </div>
              <Progress 
                value={Math.min(data.metrics.queue * 10, 100)} 
                className="bg-yellow-100"
              />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Bottom Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top Performing Clip */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5" />
              Top Performing Clip
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.topPerformingClip ? (
              <div className="space-y-4">
                <div className="flex items-center gap-4">
                  <div className="w-24 h-16 bg-muted rounded-lg" />
                  <div className="flex-1">
                    <h3 className="font-semibold line-clamp-1">
                      {data.topPerformingClip.title}
                    </h3>
                    <div className="flex items-center gap-4 mt-1 text-sm text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <Target className="h-3 w-3" />
                        Score: {data.topPerformingClip.score}
                      </span>
                      <span className="flex items-center gap-1">
                        <Users className="h-3 w-3" />
                        {data.topPerformingClip.views.toLocaleString()} views
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-muted-foreground">No clips processed yet</p>
            )}
          </CardContent>
        </Card>

        {/* Recent Activity */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5" />
              Recent Activity
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3 max-h-[200px] overflow-y-auto">
              {data.recentActivity.map((activity, i) => (
                <div key={i} className="flex items-start gap-3 text-sm">
                  <div className="w-2 h-2 rounded-full bg-primary mt-1.5" />
                  <div className="flex-1">
                    <p className="font-medium">{activity.action}</p>
                    <p className="text-muted-foreground text-xs">
                      {activity.details}
                    </p>
                    <p className="text-muted-foreground text-xs">
                      {new Date(activity.timestamp).toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              ))}
              {data.recentActivity.length === 0 && (
                <p className="text-muted-foreground">No recent activity</p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function MetricCard({
  title,
  value,
  change,
  icon,
  trend,
}: {
  title: string;
  value: string;
  change: string;
  icon: React.ReactNode;
  trend: "up" | "down" | "neutral";
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        <div className="h-4 w-4 text-muted-foreground">{icon}</div>
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
        <p
          className={`text-xs ${
            trend === "up"
              ? "text-green-600"
              : trend === "down"
              ? "text-red-600"
              : "text-muted-foreground"
          }`}
        >
          {change} from last month
        </p>
      </CardContent>
    </Card>
  );
}
