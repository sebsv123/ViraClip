"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { 
  Activity, 
  Cpu, 
  HardDrive, 
  Wifi, 
  Server,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  RefreshCw,
  TrendingUp,
  TrendingDown,
  Minus
} from "lucide-react";

interface ServiceStatus {
  name: string;
  status: "healthy" | "degraded" | "unhealthy" | "down";
  latency: number;
  lastCheck: string;
}

interface SystemMetrics {
  cpu: number;
  memory: number;
  disk: number;
  network: number;
  uptime: number;
}

export function SystemHealthDashboard() {
  const [metrics, setMetrics] = useState<SystemMetrics>({
    cpu: 45,
    memory: 62,
    disk: 78,
    network: 12,
    uptime: 86400 * 7
  });
  
  const [services, setServices] = useState<ServiceStatus[]>([
    { name: "API Server", status: "healthy", latency: 45, lastCheck: "2024-01-15T10:30:00Z" },
    { name: "Video Processor", status: "healthy", latency: 120, lastCheck: "2024-01-15T10:30:00Z" },
    { name: "AI Worker", status: "healthy", latency: 85, lastCheck: "2024-01-15T10:30:00Z" },
    { name: "Database", status: "healthy", latency: 15, lastCheck: "2024-01-15T10:30:00Z" },
    { name: "Redis Cache", status: "healthy", latency: 5, lastCheck: "2024-01-15T10:30:00Z" },
    { name: "Storage", status: "degraded", latency: 250, lastCheck: "2024-01-15T10:30:00Z" }
  ]);

  const [isRefreshing, setIsRefreshing] = useState(false);

  const refreshData = async () => {
    setIsRefreshing(true);
    // Simulate API call
    await new Promise(resolve => setTimeout(resolve, 1000));
    setIsRefreshing(false);
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "healthy": return <CheckCircle2 className="h-5 w-5 text-green-500" />;
      case "degraded": return <AlertTriangle className="h-5 w-5 text-yellow-500" />;
      case "unhealthy": return <AlertTriangle className="h-5 w-5 text-orange-500" />;
      case "down": return <XCircle className="h-5 w-5 text-red-500" />;
      default: return <Minus className="h-5 w-5 text-gray-500" />;
    }
  };

  const getStatusBadge = (status: string) => {
    const variants: Record<string, any> = {
      healthy: "default",
      degraded: "secondary",
      unhealthy: "destructive",
      down: "destructive"
    };
    return <Badge variant={variants[status] || "default"}>{status}</Badge>;
  };

  const formatUptime = (seconds: number) => {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    return `${days}d ${hours}h`;
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <Activity className="h-8 w-8 text-green-500" />
            System Health
          </h1>
          <p className="text-muted-foreground">
            Real-time monitoring and health status
          </p>
        </div>
        <Button onClick={refreshData} disabled={isRefreshing}>
          <RefreshCw className={`h-4 w-4 mr-2 ${isRefreshing ? "animate-spin" : ""}`} />
          {isRefreshing ? "Refreshing..." : "Refresh"}
        </Button>
      </div>

      {/* Overall Status */}
      <Card className="bg-gradient-to-r from-green-500/10 to-blue-500/10">
        <CardContent className="p-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-16 h-16 bg-green-500 rounded-full flex items-center justify-center">
                <CheckCircle2 className="h-8 w-8 text-white" />
              </div>
              <div>
                <h2 className="text-2xl font-bold">All Systems Operational</h2>
                <p className="text-muted-foreground">
                  Uptime: {formatUptime(metrics.uptime)} • Last updated: Just now
                </p>
              </div>
            </div>
            <div className="text-right">
              <div className="text-3xl font-bold">99.9%</div>
              <div className="text-sm text-muted-foreground">Availability</div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Resource Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">CPU Usage</CardTitle>
            <Cpu className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{metrics.cpu}%</div>
            <Progress value={metrics.cpu} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2">
              {metrics.cpu < 70 ? <TrendingDown className="h-3 w-3 inline mr-1" /> : <TrendingUp className="h-3 w-3 inline mr-1" />}
              {metrics.cpu < 70 ? "Normal load" : "High load"}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Memory</CardTitle>
            <Server className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{metrics.memory}%</div>
            <Progress value={metrics.memory} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2">
              8.2 GB / 16 GB used
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Disk</CardTitle>
            <HardDrive className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{metrics.disk}%</div>
            <Progress value={metrics.disk} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2">
              780 GB / 1 TB used
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">Network</CardTitle>
            <Wifi className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{metrics.network} MB/s</div>
            <Progress value={(metrics.network / 100) * 100} className="mt-2" />
            <p className="text-xs text-muted-foreground mt-2">
              Stable connection
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Services Status */}
      <Tabs defaultValue="services" className="w-full">
        <TabsList>
          <TabsTrigger value="services">Services</TabsTrigger>
          <TabsTrigger value="metrics">Metrics History</TabsTrigger>
          <TabsTrigger value="alerts">Alerts</TabsTrigger>
        </TabsList>

        <TabsContent value="services">
          <Card>
            <CardHeader>
              <CardTitle>Service Status</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                {services.map((service) => (
                  <div
                    key={service.name}
                    className="flex items-center justify-between p-4 border rounded-lg"
                  >
                    <div className="flex items-center gap-4">
                      {getStatusIcon(service.status)}
                      <div>
                        <p className="font-medium">{service.name}</p>
                        <p className="text-sm text-muted-foreground">
                          Last check: {new Date(service.lastCheck).toLocaleTimeString()}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                      <div className="text-right">
                        <p className="text-sm font-medium">{service.latency}ms</p>
                        <p className="text-xs text-muted-foreground">Latency</p>
                      </div>
                      {getStatusBadge(service.status)}
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="metrics">
          <Card>
            <CardHeader>
              <CardTitle>Historical Metrics</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="h-[300px] flex items-center justify-center text-muted-foreground">
                <Activity className="h-16 w-16 mr-4" />
                <div>
                  <p className="font-medium">Metrics visualization</p>
                  <p className="text-sm">Historical data chart would render here</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="alerts">
          <Card>
            <CardHeader>
              <CardTitle>Recent Alerts</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                <div className="flex items-center gap-3 p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
                  <AlertTriangle className="h-5 w-5 text-yellow-600" />
                  <div className="flex-1">
                    <p className="font-medium text-yellow-800">High latency detected</p>
                    <p className="text-sm text-yellow-700">Storage service latency above threshold</p>
                  </div>
                  <span className="text-sm text-yellow-600">2m ago</span>
                </div>
                <div className="flex items-center gap-3 p-3 bg-green-50 border border-green-200 rounded-lg">
                  <CheckCircle2 className="h-5 w-5 text-green-600" />
                  <div className="flex-1">
                    <p className="font-medium text-green-800">System recovered</p>
                    <p className="text-sm text-green-700">All services back to normal</p>
                  </div>
                  <span className="text-sm text-green-600">1h ago</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
