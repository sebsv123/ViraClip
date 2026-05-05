"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Input } from "@/components/ui/input";
import { 
  Users, 
  Plus, 
  MoreVertical, 
  Crown,
  Edit3,
  MessageSquare,
  Share2,
  Clock,
  CheckCircle2,
  AlertCircle,
  Send,
  UserPlus,
  Settings,
  Folder
} from "lucide-react";

interface TeamProject {
  id: string;
  name: string;
  description: string;
  owner: TeamMember;
  members: TeamMember[];
  clips: Clip[];
  status: "active" | "archived" | "completed";
  createdAt: string;
  lastModified: string;
}

interface TeamMember {
  id: string;
  name: string;
  email: string;
  avatar?: string;
  role: "owner" | "admin" | "editor" | "viewer";
  status: "online" | "offline" | "busy";
  lastActive?: string;
}

interface Clip {
  id: string;
  title: string;
  thumbnail?: string;
  status: "draft" | "review" | "approved" | "published";
  assignedTo?: string;
  comments: Comment[];
  versions: number;
  updatedAt: string;
}

interface Comment {
  id: string;
  userId: string;
  userName: string;
  text: string;
  timestamp: string;
  resolved: boolean;
}

export function TeamCollaborationUI() {
  const [projects, setProjects] = useState<TeamProject[]>([]);
  const [selectedProject, setSelectedProject] = useState<TeamProject | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "clips" | "members" | "activity">("overview");
  const [newComment, setNewComment] = useState("");
  const [wsConnected, setWsConnected] = useState(false);

  useEffect(() => {
    fetchProjects();
    setupWebSocket();
  }, []);

  const setupWebSocket = () => {
    const ws = new WebSocket(`wss://${window.location.host}/ws/collaboration`);
    
    ws.onopen = () => setWsConnected(true);
    ws.onclose = () => setWsConnected(false);
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      handleRealtimeUpdate(data);
    };

    return () => ws.close();
  };

  const handleRealtimeUpdate = (data: Record<string, unknown>) => {
    if (data.type === "member_joined" || data.type === "member_left") {
      fetchProjects();
    }
    if (data.type === "clip_updated") {
      fetchProjects();
    }
  };

  const fetchProjects = async () => {
    try {
      const response = await fetch("/api/collaboration/projects");
      const data = await response.json();
      setProjects(data);
    } catch (error) {
      console.error("Failed to fetch projects:", error);
    }
  };

  const createProject = async () => {
    const name = prompt("Project name:");
    if (!name) return;

    try {
      const response = await fetch("/api/collaboration/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, description: "" }),
      });
      const newProject = await response.json();
      setProjects([...projects, newProject]);
    } catch (error) {
      console.error("Failed to create project:", error);
    }
  };

  const inviteMember = async (projectId: string, email: string) => {
    try {
      await fetch(`/api/collaboration/projects/${projectId}/invite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, role: "editor" }),
      });
      fetchProjects();
    } catch (error) {
      console.error("Failed to invite member:", error);
    }
  };

  const addComment = async (clipId: string, text: string) => {
    if (!selectedProject) return;
    
    try {
      await fetch(`/api/collaboration/projects/${selectedProject.id}/clips/${clipId}/comments`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      fetchProjects();
      setNewComment("");
    } catch (error) {
      console.error("Failed to add comment:", error);
    }
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "online": return "bg-green-500";
      case "busy": return "bg-yellow-500";
      default: return "bg-gray-400";
    }
  };

  const getClipStatusBadge = (status: string) => {
    const variants: Record<string, any> = {
      draft: "secondary",
      review: "warning",
      approved: "success",
      published: "default",
    };
    return <Badge variant={variants[status] || "secondary"}>{status}</Badge>;
  };

  if (!selectedProject) {
    return (
      <div className="p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Team Projects</h1>
            <p className="text-muted-foreground">
              Collaborate with your team on video projects
            </p>
          </div>
          <Button onClick={createProject}>
            <Plus className="h-4 w-4 mr-2" />
            New Project
          </Button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {projects.map((project) => (
            <Card
              key={project.id}
              className="cursor-pointer hover:border-primary transition-colors"
              onClick={() => setSelectedProject(project)}
            >
              <CardHeader>
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="p-2 bg-primary/10 rounded-lg">
                      <Folder className="h-5 w-5 text-primary" />
                    </div>
                    <div>
                      <CardTitle className="text-lg">{project.name}</CardTitle>
                      <p className="text-sm text-muted-foreground">
                        {project.clips.length} clips
                      </p>
                    </div>
                  </div>
                  <Badge variant={project.status === "active" ? "default" : "secondary"}>
                    {project.status}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground line-clamp-2 mb-4">
                  {project.description || "No description"}
                </p>
                <div className="flex items-center justify-between">
                  <div className="flex -space-x-2">
                    {project.members.slice(0, 3).map((member) => (
                      <Avatar key={member.id} className="w-8 h-8 border-2 border-background">
                        <AvatarImage src={member.avatar} />
                        <AvatarFallback>{member.name[0]}</AvatarFallback>
                      </Avatar>
                    ))}
                    {project.members.length > 3 && (
                      <div className="w-8 h-8 rounded-full bg-muted flex items-center justify-center text-xs border-2 border-background">
                        +{project.members.length - 3}
                      </div>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    Modified {new Date(project.lastModified).toLocaleDateString()}
                  </span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <div className="border-b p-4 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="ghost" onClick={() => setSelectedProject(null)}>
            ← Back to Projects
          </Button>
          <div>
            <h1 className="text-xl font-bold">{selectedProject.name}</h1>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Badge variant="outline" className="flex items-center gap-1">
                <div className={`w-2 h-2 rounded-full ${wsConnected ? "bg-green-500" : "bg-red-500"}`} />
                {wsConnected ? "Live" : "Offline"}
              </Badge>
              <span>•</span>
              <span>{selectedProject.members.length} members</span>
              <span>•</span>
              <span>{selectedProject.clips.length} clips</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm">
            <Share2 className="h-4 w-4 mr-1" />
            Share
          </Button>
          <Button variant="outline" size="sm">
            <Settings className="h-4 w-4 mr-1" />
            Settings
          </Button>
        </div>
      </div>

      {/* Navigation */}
      <div className="border-b px-4">
        <div className="flex gap-1">
          {(["overview", "clips", "members", "activity"] as const).map((tab) => (
            <Button
              key={tab}
              variant={activeTab === tab ? "default" : "ghost"}
              onClick={() => setActiveTab(tab)}
              className="capitalize"
            >
              {tab}
            </Button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {activeTab === "overview" && (
          <div className="p-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle>Recent Clips</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-4">
                    {selectedProject.clips.slice(0, 5).map((clip) => (
                      <div
                        key={clip.id}
                        className="flex items-center gap-4 p-3 bg-muted rounded-lg"
                      >
                        <div className="w-24 h-16 bg-gray-200 rounded" />
                        <div className="flex-1">
                          <h4 className="font-medium">{clip.title}</h4>
                          <div className="flex items-center gap-2 mt-1">
                            {getClipStatusBadge(clip.status)}
                            <span className="text-xs text-muted-foreground">
                              {clip.versions} versions
                            </span>
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          {clip.assignedTo && (
                            <Avatar className="w-8 h-8">
                              <AvatarFallback>
                                {clip.assignedTo[0]}
                              </AvatarFallback>
                            </Avatar>
                          )}
                          <Button variant="ghost" size="sm">
                            <Edit3 className="h-4 w-4" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </div>

            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle>Team Members</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-3">
                    {selectedProject.members.map((member) => (
                      <div key={member.id} className="flex items-center gap-3">
                        <div className="relative">
                          <Avatar className="w-10 h-10">
                            <AvatarImage src={member.avatar} />
                            <AvatarFallback>{member.name[0]}</AvatarFallback>
                          </Avatar>
                          <div className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-white ${getStatusColor(member.status)}`} />
                        </div>
                        <div className="flex-1">
                          <p className="font-medium text-sm">{member.name}</p>
                          <p className="text-xs text-muted-foreground">
                            {member.role}
                          </p>
                        </div>
                        {member.role === "owner" && (
                          <Crown className="h-4 w-4 text-yellow-500" />
                        )}
                      </div>
                    ))}
                    <Button
                      variant="outline"
                      className="w-full"
                      onClick={() => {
                        const email = prompt("Enter email to invite:");
                        if (email) inviteMember(selectedProject.id, email);
                      }}
                    >
                      <UserPlus className="h-4 w-4 mr-2" />
                      Invite Member
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        )}

        {activeTab === "clips" && (
          <div className="p-6">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {selectedProject.clips.map((clip) => (
                <Card key={clip.id}>
                  <CardHeader className="p-4">
                    <div className="aspect-video bg-muted rounded-lg mb-3" />
                    <div className="flex items-start justify-between">
                      <div>
                        <CardTitle className="text-base">{clip.title}</CardTitle>
                        <div className="flex items-center gap-2 mt-1">
                          {getClipStatusBadge(clip.status)}
                        </div>
                      </div>
                      <Button variant="ghost" size="icon">
                        <MoreVertical className="h-4 w-4" />
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent className="p-4 pt-0">
                    <div className="space-y-3">
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">Assigned to</span>
                        {clip.assignedTo ? (
                          <Avatar className="w-6 h-6">
                            <AvatarFallback>{clip.assignedTo[0]}</AvatarFallback>
                          </Avatar>
                        ) : (
                          <span className="text-muted-foreground">Unassigned</span>
                        )}
                      </div>
                      
                      {clip.comments.length > 0 && (
                        <div className="flex items-center gap-1 text-sm text-muted-foreground">
                          <MessageSquare className="h-4 w-4" />
                          {clip.comments.length} comments
                          {clip.comments.some((c) => !c.resolved) && (
                            <AlertCircle className="h-4 w-4 text-yellow-500" />
                          )}
                        </div>
                      )}

                      {/* Comments Section */}
                      {clip.comments.length > 0 && (
                        <div className="space-y-2 max-h-32 overflow-y-auto">
                          {clip.comments.map((comment) => (
                            <div
                              key={comment.id}
                              className={`p-2 rounded text-sm ${
                                comment.resolved ? "bg-muted/50 line-through" : "bg-muted"
                              }`}
                            >
                              <div className="flex items-center justify-between">
                                <span className="font-medium">{comment.userName}</span>
                                <span className="text-xs text-muted-foreground">
                                  {new Date(comment.timestamp).toLocaleDateString()}
                                </span>
                              </div>
                              <p className="text-muted-foreground">{comment.text}</p>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Add Comment */}
                      <div className="flex gap-2">
                        <Input
                          placeholder="Add comment..."
                          value={newComment}
                          onChange={(e) => setNewComment(e.target.value)}
                          className="flex-1"
                        />
                        <Button
                          size="icon"
                          onClick={() => addComment(clip.id, newComment)}
                          disabled={!newComment.trim()}
                        >
                          <Send className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        )}

        {activeTab === "members" && (
          <div className="p-6 max-w-4xl">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center justify-between">
                  <span>Team Members</span>
                  <Button
                    onClick={() => {
                      const email = prompt("Enter email to invite:");
                      if (email) inviteMember(selectedProject.id, email);
                    }}
                  >
                    <UserPlus className="h-4 w-4 mr-2" />
                    Invite Member
                  </Button>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {selectedProject.members.map((member) => (
                    <div
                      key={member.id}
                      className="flex items-center justify-between p-4 bg-muted rounded-lg"
                    >
                      <div className="flex items-center gap-4">
                        <div className="relative">
                          <Avatar className="w-12 h-12">
                            <AvatarImage src={member.avatar} />
                            <AvatarFallback>{member.name[0]}</AvatarFallback>
                          </Avatar>
                          <div className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-white ${getStatusColor(member.status)}`} />
                        </div>
                        <div>
                          <h4 className="font-medium">{member.name}</h4>
                          <p className="text-sm text-muted-foreground">
                            {member.email}
                          </p>
                          <div className="flex items-center gap-2 mt-1">
                            <Badge variant="outline" className="capitalize">
                              {member.role}
                            </Badge>
                            {member.lastActive && (
                              <span className="text-xs text-muted-foreground">
                                Active {new Date(member.lastActive).toLocaleTimeString()}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                      {member.role !== "owner" && (
                        <Button variant="ghost" size="sm">
                          <MoreVertical className="h-4 w-4" />
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}
