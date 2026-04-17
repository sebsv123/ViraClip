"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { 
  DollarSign, 
  TrendingUp, 
  TrendingDown, 
  AlertTriangle,
  Server,
  HardDrive,
  Cpu,
  Wifi,
  Lightbulb,
  Download
} from "lucide-react";

interface CostMetric {
  resource: string;
  cost: number;
  usage: number;
  trend: "up" | "down" | "stable";
  efficiency: number;
}

interface Optimization {
  id: string;
  resource: string;
  action: string;
  potentialSavings: number;
  priority: "high" | "medium" | "low";
}

export function CostOptimizationDashboard() {
  const [metrics] = useState<CostMetric[]>([
    { resource: "Compute (EC2)", cost: 450.50, usage: 75, trend: "up", efficiency: 0.75 },
    { resource: "Storage (S3)", cost: 125.30, usage: 62, trend: "stable", efficiency: 0.62 },
    { resource: "Bandwidth", cost: 89.20, usage: 45, trend: "down", efficiency: 0.45 },
    { resource: "AI Inference", cost: 234.80, usage: 88, trend: "up", efficiency: 0.88 },
    { resource: "Database", cost: 156.40, usage: 70, trend: "stable", efficiency: 0.70 }
  ]);

  const [optimizations] = useState<Optimization[]>([
    {
      id: "opt_1",
      resource: "Storage",
      action: "Move old clips to cold storage",
      potentialSavings: 45.50,
      priority: "high"
    },
    {
      id: "opt_2",
      resource: "Compute",
      action: "Enable auto-scaling for workers",
      potentialSavings: 120.00,
      priority: "high"
    },
    {
      id: "opt_3",
      resource: "AI Inference",
      action: "Batch requests for better throughput",
      potentialSavings: 35.20,
      priority: "medium"
    },
    {
      id: "opt_4",
      resource: "Bandwidth",
      action: "Enable CDN caching",
      potentialSavings: 25.80,
      priority: "medium"
    }
  ]);

  const totalCost = metrics.reduce((sum, m) => sum + m.cost, 0);
  const potentialSavings = optimizations.reduce((sum, o) => sum + o.potentialSavings, 0);
  const budgetLimit = 1500;
  const budgetUsed = (totalCost / budgetLimit) * 100;

  const getTrendIcon = (trend: string) => {
    switch (trend) {
      case "up": return <TrendingUp className="h-4 w-4 text-red-500" />;
      case "down": return <TrendingDown className="h-4 w-4 text-green-500" />;
      default: return <span className="text-gray-500">→</span>;
    }
  };

  const getResourceIcon = (resource: string) => {
    if (resource.includes("Compute")) return <Cpu className="h-5 w-5" />;
    if (resource.includes("Storage")) return <HardDrive className="h-5 w-5" />;
    if (resource.includes("Bandwidth")) return <Wifi className="h-5 w-5" />;
    if (resource.includes("AI")) return <Lightbulb className="h-5 w-5" />;
    return <Server className="h-5 w-5" />;
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-2">
            <DollarSign className="h-8 w-8 text-green-600" />
            Cost Optimization
          </h1>
          <p className="text-muted-foreground">
            Monitor and optimize cloud infrastructure costs
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline">
            <Download className="h-4 w-4 mr-2" />
            Export Report
          </Button>
          <Button>
            <Lightbulb className="h-4 w-4 mr-2" />
            Run Optimization
          </Button>
        </div>
      </div>

      {/* Budget Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Current Month</p>
                <p className="text-3xl font-bold">${totalCost.toFixed(2)}</p>
              </div>
              <DollarSign className="h-10 w-10 text-muted-foreground opacity-50" />
            </div>
            <div className="mt-4">
              <div className="flex justify-between text-sm mb-1">
                <span>Budget used</span>
                <span>{budgetUsed.toFixed(1)}%</span>
              </div>
              <Progress value={budgetUsed} className={budgetUsed > 80 ? "bg-red-200" : ""} />
              <p className="text-sm text-muted-foreground mt-2">
                Budget: ${budgetLimit}/month
              </p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Potential Savings</p>
                <p className="text-3xl font-bold text-green-600">
                  ${potentialSavings.toFixed(2)}
                </p>
              </div>
              <TrendingDown className="h-10 w-10 text-green-500 opacity-50" />
            </div>
            <p className="text-sm text-muted-foreground mt-4">
              {optimizations.length} optimization opportunities found
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Projected Monthly</p>
                <p className="text-3xl font-bold">${(totalCost * 1.2).toFixed(2)}</p>
              </div>
              <TrendingUp className="h-10 w-10 text-yellow-500 opacity-50" />
            </div>
            <div className="mt-4">
              <Badge variant={budgetUsed > 90 ? "destructive" : budgetUsed > 75 ? "secondary" : "default"}>
                {budgetUsed > 90 ? "Over Budget Risk" : budgetUsed > 75 ? "Approaching Limit" : "On Track"}
              </Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Cost Breakdown */}
      <Card>
        <CardHeader>
          <CardTitle>Cost by Resource</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {metrics.map((metric) => (
              <div key={metric.resource} className="flex items-center justify-between p-4 border rounded-lg">
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 bg-muted rounded-lg flex items-center justify-center">
                    {getResourceIcon(metric.resource)}
                  </div>
                  <div>
                    <p className="font-medium">{metric.resource}</p>
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <span>Efficiency: {(metric.efficiency * 100).toFixed(0)}%</span>
                      {getTrendIcon(metric.trend)}
                    </div>
                  </div>
                </div>
                <div className="text-right">
                  <p className="font-semibold">${metric.cost.toFixed(2)}</p>
                  <p className="text-sm text-muted-foreground">
                    {metric.usage}% utilization
                  </p>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Optimization Recommendations */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Lightbulb className="h-5 w-5" />
            Optimization Recommendations
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {optimizations.map((opt) => (
              <div
                key={opt.id}
                className="flex items-center justify-between p-4 bg-muted/50 rounded-lg"
              >
                <div className="flex items-start gap-3">
                  <AlertTriangle className={`h-5 w-5 ${
                    opt.priority === "high" ? "text-red-500" : "text-yellow-500"
                  }`} />
                  <div>
                    <p className="font-medium">{opt.action}</p>
                    <p className="text-sm text-muted-foreground">
                      Resource: {opt.resource} • Priority: {opt.priority}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-4">
                  <div className="text-right">
                    <p className="font-semibold text-green-600">
                      Save ${opt.potentialSavings.toFixed(2)}/mo
                    </p>
                  </div>
                  <Button size="sm">Apply</Button>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
