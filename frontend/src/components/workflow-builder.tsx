"use client";

import { useState, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { 
  Play, 
  Pause, 
  Save, 
  Plus, 
  Trash2, 
  Settings,
  ArrowRight,
  GitBranch,
  Zap,
  Video,
  Sparkles,
  Music,
  Share2,
  Bell,
  Clock,
  Webhook,
  CheckCircle2,
  XCircle,
  RotateCcw
} from "lucide-react";

interface WorkflowNode {
  id: string;
  type: string;
  name: string;
  config: Record<string, any>;
  position: { x: number; y: number };
  inputs: string[];
  outputs: string[];
  status?: "idle" | "running" | "completed" | "failed";
}

interface WorkflowConnection {
  id: string;
  source: string;
  target: string;
}

interface WorkflowData {
  id: string;
  name: string;
  description: string;
  status: "draft" | "active" | "paused";
  nodes: WorkflowNode[];
  connections: WorkflowConnection[];
}

const NODE_TYPES = [
  { type: "trigger", name: "Trigger", icon: Zap, color: "bg-yellow-500" },
  { type: "extract_video", name: "Extract Video", icon: Video, color: "bg-blue-500" },
  { type: "ai_analyze", name: "AI Analysis", icon: Sparkles, color: "bg-purple-500" },
  { type: "generate_clips", name: "Generate Clips", icon: Video, color: "bg-green-500" },
  { type: "apply_effects", name: "Apply Effects", icon: Sparkles, color: "bg-pink-500" },
  { type: "add_music", name: "Add Music", icon: Music, color: "bg-indigo-500" },
  { type: "export", name: "Export", icon: Share2, color: "bg-cyan-500" },
  { type: "notification", name: "Notification", icon: Bell, color: "bg-orange-500" },
  { type: "delay", name: "Delay", icon: Clock, color: "bg-gray-500" },
  { type: "webhook", name: "Webhook", icon: Webhook, color: "bg-red-500" },
  { type: "condition", name: "Condition", icon: GitBranch, color: "bg-teal-500" },
];

export function WorkflowBuilder() {
  const [workflow, setWorkflow] = useState<WorkflowData>({
    id: "wf_001",
    name: "Viral Shorts Pipeline",
    description: "Automatically create viral shorts from uploaded videos",
    status: "draft",
    nodes: [
      {
        id: "node_1",
        type: "trigger",
        name: "Video Uploaded",
        config: { event: "video.uploaded" },
        position: { x: 50, y: 200 },
        inputs: [],
        outputs: ["node_2"],
        status: "idle"
      },
      {
        id: "node_2",
        type: "ai_analyze",
        name: "AI Analysis",
        config: { model: "virality_v2" },
        position: { x: 250, y: 200 },
        inputs: ["node_1"],
        outputs: ["node_3"],
        status: "idle"
      },
      {
        id: "node_3",
        type: "generate_clips",
        name: "Generate 5 Clips",
        config: { count: 5, duration: 60 },
        position: { x: 450, y: 200 },
        inputs: ["node_2"],
        outputs: ["node_4"],
        status: "idle"
      },
      {
        id: "node_4",
        type: "apply_effects",
        name: "Apply Effects",
        config: { effects: ["zoom_pulse", "captions"] },
        position: { x: 650, y: 200 },
        inputs: ["node_3"],
        outputs: ["node_5"],
        status: "idle"
      },
      {
        id: "node_5",
        type: "export",
        name: "Export Multi-Platform",
        config: { platforms: ["youtube", "tiktok"] },
        position: { x: 850, y: 200 },
        inputs: ["node_4"],
        outputs: ["node_6"],
        status: "idle"
      },
      {
        id: "node_6",
        type: "notification",
        name: "Send Notification",
        config: { channel: "email" },
        position: { x: 1050, y: 200 },
        inputs: ["node_5"],
        outputs: [],
        status: "idle"
      }
    ],
    connections: [
      { id: "conn_1", source: "node_1", target: "node_2" },
      { id: "conn_2", source: "node_2", target: "node_3" },
      { id: "conn_3", source: "node_3", target: "node_4" },
      { id: "conn_4", source: "node_4", target: "node_5" },
      { id: "conn_5", source: "node_5", target: "node_6" },
    ]
  });

  const [selectedNode, setSelectedNode] = useState<WorkflowNode | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [draggedNode, setDraggedNode] = useState<string | null>(null);

  const handleRunWorkflow = async () => {
    setIsRunning(true);
    
    // Simulate workflow execution
    for (const node of workflow.nodes) {
      setWorkflow(prev => ({
        ...prev,
        nodes: prev.nodes.map(n => 
          n.id === node.id ? { ...n, status: "running" } : n
        )
      }));
      
      await new Promise(resolve => setTimeout(resolve, 800));
      
      setWorkflow(prev => ({
        ...prev,
        nodes: prev.nodes.map(n => 
          n.id === node.id ? { ...n, status: "completed" } : n
        )
      }));
    }
    
    setIsRunning(false);
  };

  const handleAddNode = (type: string) => {
    const nodeType = NODE_TYPES.find(nt => nt.type === type);
    if (!nodeType) return;

    const newNode: WorkflowNode = {
      id: `node_${Date.now()}`,
      type,
      name: nodeType.name,
      config: {},
      position: { x: 300 + Math.random() * 200, y: 300 + Math.random() * 100 },
      inputs: [],
      outputs: [],
      status: "idle"
    };

    setWorkflow(prev => ({
      ...prev,
      nodes: [...prev.nodes, newNode]
    }));
  };

  const handleDeleteNode = (nodeId: string) => {
    setWorkflow(prev => ({
      ...prev,
      nodes: prev.nodes.filter(n => n.id !== nodeId),
      connections: prev.connections.filter(
        c => c.source !== nodeId && c.target !== nodeId
      )
    }));
    if (selectedNode?.id === nodeId) {
      setSelectedNode(null);
    }
  };

  const getNodeIcon = (type: string) => {
    const nodeType = NODE_TYPES.find(nt => nt.type === type);
    const Icon = nodeType?.icon || Zap;
    return <Icon className="h-5 w-5" />;
  };

  const getNodeColor = (type: string) => {
    const nodeType = NODE_TYPES.find(nt => nt.type === type);
    return nodeType?.color || "bg-gray-500";
  };

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <div className="border-b p-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div>
            <h1 className="text-2xl font-bold">{workflow.name}</h1>
            <p className="text-sm text-muted-foreground">{workflow.description}</p>
          </div>
          <Badge variant={workflow.status === "active" ? "default" : "secondary"}>
            {workflow.status}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setWorkflow(prev => ({ ...prev, status: prev.status === "active" ? "paused" : "active" }))}
          >
            {workflow.status === "active" ? <Pause className="h-4 w-4 mr-1" /> : <Play className="h-4 w-4 mr-1" />}
            {workflow.status === "active" ? "Pause" : "Activate"}
          </Button>
          <Button
            size="sm"
            onClick={handleRunWorkflow}
            disabled={isRunning}
          >
            {isRunning ? (
              <RotateCcw className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <Play className="h-4 w-4 mr-1" />
            )}
            {isRunning ? "Running..." : "Test Run"}
          </Button>
          <Button variant="outline" size="sm">
            <Save className="h-4 w-4 mr-1" />
            Save
          </Button>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar - Node Palette */}
        <div className="w-64 border-r bg-muted/30 p-4 overflow-y-auto">
          <h3 className="font-semibold mb-4">Node Palette</h3>
          <div className="space-y-2">
            {NODE_TYPES.map((nodeType) => (
              <button
                key={nodeType.type}
                onClick={() => handleAddNode(nodeType.type)}
                className="w-full flex items-center gap-3 p-3 rounded-lg bg-card hover:bg-accent transition-colors text-left"
              >
                <div className={`w-8 h-8 ${nodeType.color} rounded-lg flex items-center justify-center text-white`}>
                  <nodeType.icon className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium">{nodeType.name}</span>
              </button>
            ))}
          </div>

          <Separator className="my-4" />

          <h3 className="font-semibold mb-4">Templates</h3>
          <div className="space-y-2">
            <button className="w-full p-3 rounded-lg bg-card hover:bg-accent transition-colors text-left">
              <p className="font-medium text-sm">Viral Shorts</p>
              <p className="text-xs text-muted-foreground">Auto-extract viral moments</p>
            </button>
            <button className="w-full p-3 rounded-lg bg-card hover:bg-accent transition-colors text-left">
              <p className="font-medium text-sm">Tutorial Pipeline</p>
              <p className="text-xs text-muted-foreground">Educational content workflow</p>
            </button>
          </div>
        </div>

        {/* Main Canvas */}
        <div className="flex-1 bg-muted/50 relative overflow-auto">
          <div className="absolute inset-0" style={{ minWidth: "1200px", minHeight: "600px" }}>
            {/* Grid Background */}
            <div 
              className="absolute inset-0 opacity-10"
              style={{
                backgroundImage: `
                  linear-gradient(to right, #888 1px, transparent 1px),
                  linear-gradient(to bottom, #888 1px, transparent 1px)
                `,
                backgroundSize: "20px 20px"
              }}
            />

            {/* Connections */}
            <svg className="absolute inset-0 w-full h-full pointer-events-none">
              {workflow.connections.map((conn) => {
                const sourceNode = workflow.nodes.find(n => n.id === conn.source);
                const targetNode = workflow.nodes.find(n => n.id === conn.target);
                if (!sourceNode || !targetNode) return null;

                return (
                  <g key={conn.id}>
                    <line
                      x1={sourceNode.position.x + 100}
                      y1={sourceNode.position.y + 30}
                      x2={targetNode.position.x}
                      y2={targetNode.position.y + 30}
                      stroke="currentColor"
                      strokeWidth="2"
                      className="text-muted-foreground"
                    />
                    <polygon
                      points={`${targetNode.position.x},${targetNode.position.y + 30} ${targetNode.position.x - 8},${targetNode.position.y + 26} ${targetNode.position.x - 8},${targetNode.position.y + 34}`}
                      fill="currentColor"
                      className="text-muted-foreground"
                    />
                  </g>
                );
              })}
            </svg>

            {/* Nodes */}
            {workflow.nodes.map((node) => (
              <div
                key={node.id}
                className={`absolute cursor-pointer transition-all ${
                  selectedNode?.id === node.id ? "ring-2 ring-primary" : ""
                }`}
                style={{ 
                  left: node.position.x, 
                  top: node.position.y,
                  width: "200px"
                }}
                onClick={() => setSelectedNode(node)}
              >
                <Card className={`border-2 ${
                  node.status === "running" ? "border-yellow-500" :
                  node.status === "completed" ? "border-green-500" :
                  node.status === "failed" ? "border-red-500" :
                  "border-transparent"
                }`}>
                  <CardContent className="p-3">
                    <div className="flex items-center gap-3">
                      <div className={`w-10 h-8 ${getNodeColor(node.type)} rounded-lg flex items-center justify-center text-white`}>
                        {getNodeIcon(node.type)}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-sm truncate">{node.name}</p>
                        <p className="text-xs text-muted-foreground capitalize">{node.type.replace("_", " ")}</p>
                      </div>
                      {node.status === "completed" && <CheckCircle2 className="h-4 w-4 text-green-500" />}
                      {node.status === "failed" && <XCircle className="h-4 w-4 text-red-500" />}
                      {node.status === "running" && <RotateCcw className="h-4 w-4 text-yellow-500 animate-spin" />}
                    </div>
                  </CardContent>
                </Card>
              </div>
            ))}
          </div>
        </div>

        {/* Properties Panel */}
        {selectedNode && (
          <div className="w-80 border-l bg-card p-4 overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold">Node Properties</h3>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handleDeleteNode(selectedNode.id)}
              >
                <Trash2 className="h-4 w-4 text-destructive" />
              </Button>
            </div>

            <div className="space-y-4">
              <div>
                <label className="text-sm font-medium">Name</label>
                <input
                  type="text"
                  className="w-full mt-1 p-2 border rounded-md"
                  value={selectedNode.name}
                  onChange={(e) => {
                    setWorkflow(prev => ({
                      ...prev,
                      nodes: prev.nodes.map(n =>
                        n.id === selectedNode.id ? { ...n, name: e.target.value } : n
                      )
                    }));
                    setSelectedNode({ ...selectedNode, name: e.target.value });
                  }}
                />
              </div>

              <div>
                <label className="text-sm font-medium">Type</label>
                <p className="text-sm text-muted-foreground capitalize mt-1">
                  {selectedNode.type.replace("_", " ")}
                </p>
              </div>

              <div>
                <label className="text-sm font-medium">Configuration</label>
                <div className="mt-2 p-3 bg-muted rounded-lg">
                  <pre className="text-xs overflow-auto">
                    {JSON.stringify(selectedNode.config, null, 2)}
                  </pre>
                </div>
              </div>

              <Separator />

              <div>
                <label className="text-sm font-medium">Connections</label>
                <div className="mt-2 space-y-2">
                  <p className="text-xs text-muted-foreground">
                    Inputs: {selectedNode.inputs.length > 0 ? selectedNode.inputs.join(", ") : "None"}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Outputs: {selectedNode.outputs.length > 0 ? selectedNode.outputs.join(", ") : "None"}
                  </p>
                </div>
              </div>

              {selectedNode.status && (
                <>
                  <Separator />
                  <div>
                    <label className="text-sm font-medium">Status</label>
                    <Badge 
                      variant={
                        selectedNode.status === "completed" ? "default" :
                        selectedNode.status === "failed" ? "destructive" :
                        selectedNode.status === "running" ? "secondary" :
                        "outline"
                      }
                      className="mt-2"
                    >
                      {selectedNode.status}
                    </Badge>
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Missing import
import { Separator } from "@/components/ui/separator";
