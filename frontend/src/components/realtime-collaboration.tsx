"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { 
  MousePointer2, 
  Users, 
  Wifi, 
  WifiOff,
  MessageSquare,
  Clock,
  Edit3,
  Eye
} from "lucide-react";

interface RealtimeCollaborationProps {
  projectId: string;
  userId: string;
  userName: string;
  userColor: string;
}

interface Collaborator {
  userId: string;
  userName: string;
  color: string;
  cursorPosition?: { x: number; y: number };
  currentClip?: string;
  isActive: boolean;
  lastActivity: string;
}

interface Operation {
  operationId: string;
  userId: string;
  userName: string;
  operationType: string;
  data: any;
  timestamp: string;
}

interface CursorPosition {
  x: number;
  y: number;
}

export function RealtimeCollaboration({
  projectId,
  userId,
  userName,
  userColor,
}: RealtimeCollaborationProps) {
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [collaborators, setCollaborators] = useState<Collaborator[]>([]);
  const [recentOperations, setRecentOperations] = useState<Operation[]>([]);
  const [myCursor, setMyCursor] = useState<CursorPosition>({ x: 0, y: 0 });
  const [currentClip, setCurrentClip] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const cursorUpdateThrottle = useRef<NodeJS.Timeout | null>(null);

  // Initialize WebSocket connection
  useEffect(() => {
    const websocket = new WebSocket(
      `wss://${window.location.host}/ws/realtime-collab?projectId=${projectId}&userId=${userId}&userName=${encodeURIComponent(userName)}&color=${encodeURIComponent(userColor)}`
    );

    websocket.onopen = () => {
      setIsConnected(true);
      console.log("Connected to collaboration server");
    };

    websocket.onclose = () => {
      setIsConnected(false);
      console.log("Disconnected from collaboration server");
    };

    websocket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      handleMessage(message);
    };

    setWs(websocket);

    return () => {
      websocket.close();
    };
  }, [projectId, userId, userName, userColor]);

  // Handle incoming messages
  const handleMessage = useCallback((message: any) => {
    switch (message.type) {
      case "initial_state":
        // Set initial collaborators
        setCollaborators(message.participants || []);
        break;

      case "presence":
        // Handle user join/leave
        if (message.event === "joined") {
          setCollaborators((prev) => [
            ...prev,
            {
              userId: message.user.user_id,
              userName: message.user.username,
              color: message.user.color,
              isActive: true,
              lastActivity: new Date().toISOString(),
            },
          ]);
        } else if (message.event === "left") {
          setCollaborators((prev) =>
            prev.filter((c) => c.userId !== message.user.user_id)
          );
        }
        break;

      case "cursor":
        // Update cursor position
        setCollaborators((prev) =>
          prev.map((c) =>
            c.userId === message.user_id
              ? {
                  ...c,
                  cursorPosition: message.position,
                  currentClip: message.current_clip,
                  lastActivity: new Date().toISOString(),
                }
              : c
          )
        );
        break;

      case "operation":
        // Handle edit operations
        const newOperation: Operation = {
          operationId: message.operation.operation_id,
          userId: message.operation.user_id,
          userName: message.user_name || "Unknown",
          operationType: message.operation.operation_type,
          data: message.operation.data,
          timestamp: message.operation.timestamp,
        };
        setRecentOperations((prev) => [newOperation, ...prev].slice(0, 50));
        break;

      case "dashboard_update":
        // Update collaborators list
        if (message.metrics) {
          // Could update metrics here
        }
        break;
    }
  }, []);

  // Track mouse movement
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return;

      const rect = containerRef.current.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 100;
      const y = ((e.clientY - rect.top) / rect.height) * 100;

      setMyCursor({ x, y });

      // Throttle cursor updates
      if (cursorUpdateThrottle.current) {
        clearTimeout(cursorUpdateThrottle.current);
      }

      cursorUpdateThrottle.current = setTimeout(() => {
        if (ws && isConnected) {
          ws.send(
            JSON.stringify({
              type: "cursor_update",
              position: { x, y },
              current_clip: currentClip,
            })
          );
        }
      }, 50);
    };

    const container = containerRef.current;
    if (container) {
      container.addEventListener("mousemove", handleMouseMove);
    }

    return () => {
      if (container) {
        container.removeEventListener("mousemove", handleMouseMove);
      }
      if (cursorUpdateThrottle.current) {
        clearTimeout(cursorUpdateThrottle.current);
      }
    };
  }, [ws, isConnected, currentClip]);

  // Send operation to server
  const sendOperation = useCallback(
    (operationType: string, data: any) => {
      if (ws && isConnected) {
        ws.send(
          JSON.stringify({
            type: "operation",
            operation_type: operationType,
            data,
          })
        );
      }
    },
    [ws, isConnected]
  );

  // Get operation icon
  const getOperationIcon = (type: string) => {
    switch (type) {
      case "clip_add":
        return <Edit3 className="h-3 w-3" />;
      case "clip_update":
        return <Edit3 className="h-3 w-3" />;
      case "clip_remove":
        return <Edit3 className="h-3 w-3" />;
      case "comment_add":
        return <MessageSquare className="h-3 w-3" />;
      default:
        return <Edit3 className="h-3 w-3" />;
    }
  };

  // Format timestamp
  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b">
        <div className="flex items-center gap-3">
          <h2 className="font-semibold">Live Collaboration</h2>
          <Badge
            variant={isConnected ? "default" : "secondary"}
            className="flex items-center gap-1"
          >
            {isConnected ? (
              <>
                <Wifi className="h-3 w-3" />
                Connected
              </>
            ) : (
              <>
                <WifiOff className="h-3 w-3" />
                Offline
              </>
            )}
          </Badge>
        </div>
        <div className="flex items-center gap-2">
          <Users className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">
            {collaborators.filter((c) => c.isActive).length + 1} online
          </span>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Collaboration Canvas */}
        <div
          ref={containerRef}
          className="flex-1 relative bg-muted/30 overflow-hidden"
        >
          {/* My Cursor */}
          <div
            className="absolute pointer-events-none z-50 transition-all duration-100"
            style={{
              left: `${myCursor.x}%`,
              top: `${myCursor.y}%`,
              transform: "translate(-50%, -50%)",
            }}
          >
            <MousePointer2
              className="h-5 w-5"
              style={{ color: userColor }}
            />
            <span
              className="absolute top-4 left-4 text-xs px-1.5 py-0.5 rounded text-white whitespace-nowrap"
              style={{ backgroundColor: userColor }}
            >
              You
            </span>
          </div>

          {/* Other Collaborators' Cursors */}
          {collaborators
            .filter((c) => c.userId !== userId && c.cursorPosition && c.isActive)
            .map((collaborator) => (
              <div
                key={collaborator.userId}
                className="absolute pointer-events-none z-40 transition-all duration-150"
                style={{
                  left: `${collaborator.cursorPosition!.x}%`,
                  top: `${collaborator.cursorPosition!.y}%`,
                  transform: "translate(-50%, -50%)",
                }}
              >
                <MousePointer2
                  className="h-5 w-5"
                  style={{ color: collaborator.color }}
                />
                <span
                  className="absolute top-4 left-4 text-xs px-1.5 py-0.5 rounded text-white whitespace-nowrap"
                  style={{ backgroundColor: collaborator.color }}
                >
                  {collaborator.userName}
                </span>
                {collaborator.currentClip && (
                  <span className="absolute top-8 left-4 text-xs text-muted-foreground bg-background/80 px-1.5 py-0.5 rounded">
                    Viewing: {collaborator.currentClip}
                  </span>
                )}
              </div>
            ))}

          {/* Center Message */}
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="text-center">
              <p className="text-muted-foreground text-sm">
                Collaborative editing active
              </p>
              <p className="text-muted-foreground text-xs mt-1">
                Move your cursor to see others
              </p>
            </div>
          </div>
        </div>

        {/* Sidebar */}
        <div className="w-80 border-l bg-background overflow-y-auto">
          {/* Active Users */}
          <Card className="border-0 shadow-none">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <Users className="h-4 w-4" />
                Active Users
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {/* Current User */}
                <div className="flex items-center gap-3 p-2 bg-primary/5 rounded-lg">
                  <div className="relative">
                    <Avatar className="w-8 h-8">
                      <AvatarFallback style={{ backgroundColor: userColor }}>
                        {userName[0]}
                      </AvatarFallback>
                    </Avatar>
                    <div className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-green-500 border-2 border-white" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm truncate">{userName}</p>
                    <p className="text-xs text-muted-foreground">You</p>
                  </div>
                </div>

                {/* Other Collaborators */}
                {collaborators
                  .filter((c) => c.userId !== userId)
                  .map((collaborator) => (
                    <div
                      key={collaborator.userId}
                      className={`flex items-center gap-3 p-2 rounded-lg ${
                        collaborator.isActive ? "bg-muted/50" : "opacity-50"
                      }`}
                    >
                      <div className="relative">
                        <Avatar className="w-8 h-8">
                          <AvatarFallback
                            style={{ backgroundColor: collaborator.color }}
                          >
                            {collaborator.userName[0]}
                          </AvatarFallback>
                        </Avatar>
                        <div
                          className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-white ${
                            collaborator.isActive ? "bg-green-500" : "bg-gray-400"
                          }`}
                        />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-sm truncate">
                          {collaborator.userName}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {collaborator.isActive ? (
                            <span className="flex items-center gap-1">
                              <Eye className="h-3 w-3" />
                              {collaborator.currentClip
                                ? `Viewing ${collaborator.currentClip}`
                                : "Active"}
                            </span>
                          ) : (
                            "Offline"
                          )}
                        </p>
                      </div>
                    </div>
                  ))}
              </div>
            </CardContent>
          </Card>

          {/* Recent Activity */}
          <Card className="border-0 shadow-none border-t">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <Clock className="h-4 w-4" />
                Recent Activity
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3 max-h-64 overflow-y-auto">
                {recentOperations.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center py-4">
                    No recent activity
                  </p>
                ) : (
                  recentOperations.map((op) => (
                    <div
                      key={op.operationId}
                      className="flex items-start gap-3 text-sm"
                    >
                      <div className="mt-0.5">
                        {getOperationIcon(op.operationType)}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="font-medium truncate">
                          {op.userName}
                        </p>
                        <p className="text-muted-foreground text-xs">
                          {op.operationType.replace("_", " ")}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {formatTime(op.timestamp)}
                        </p>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
