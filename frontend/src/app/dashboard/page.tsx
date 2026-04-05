"use client";

import { useState } from "react";
import { 
  Zap, 
  Plus, 
  Video, 
  Settings,
  LogOut,
  Film,
  Clock,
  CheckCircle,
  Loader2,
  AlertCircle,
  ArrowRight,
  BarChart3,
  Sparkles
} from "lucide-react";
import Link from "next/link";

// Sidebar Component
function Sidebar() {
  const navItems = [
    { icon: Video, label: "Dashboard", href: "/dashboard", active: true },
    { icon: Film, label: "My Clips", href: "/list", active: false },
    { icon: BarChart3, label: "Analytics", href: "/analytics", active: false },
    { icon: Settings, label: "Settings", href: "/settings", active: false },
  ];

  return (
    <aside className="w-64 bg-[#0a0a0f] border-r border-white/5 min-h-screen flex flex-col">
      {/* Logo */}
      <div className="p-6">
        <Link href="/" className="flex items-center gap-3">
          <div className="relative w-10 h-10">
            <div className="absolute inset-0 bg-gradient-to-br from-cyan-400 via-purple-500 to-pink-500 rounded-xl" />
            <div className="absolute inset-[2px] bg-[#0a0a0f] rounded-xl flex items-center justify-center">
              <Zap className="w-5 h-5 text-cyan-400" />
            </div>
          </div>
          <span className="text-xl font-bold">
            Vira<span className="text-cyan-400">Clip</span>
          </span>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-4">
        <div className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.label}
                href={item.href}
                className={`flex items-center gap-3 px-4 py-3 rounded-xl transition-all ${
                  item.active 
                    ? "bg-cyan-500/10 text-cyan-400 border border-cyan-500/20" 
                    : "text-gray-400 hover:bg-white/5 hover:text-white"
                }`}
              >
                <Icon className="w-5 h-5" />
                <span className="font-medium">{item.label}</span>
              </Link>
            );
          })}
        </div>
      </nav>

      {/* Bottom Actions */}
      <div className="p-4 border-t border-white/5">
        <button className="flex items-center gap-3 px-4 py-3 w-full rounded-xl text-gray-400 hover:bg-white/5 hover:text-white transition-all">
          <LogOut className="w-5 h-5" />
          <span className="font-medium">Sign Out</span>
        </button>
      </div>
    </aside>
  );
}

// Task Card Component
function TaskCard({ task }: { task: any }) {
  const statusIcons = {
    completed: <CheckCircle className="w-5 h-5 text-green-400" />,
    processing: <Loader2 className="w-5 h-5 animate-spin text-cyan-400" />,
    queued: <Clock className="w-5 h-5 text-amber-400" />,
    failed: <AlertCircle className="w-5 h-5 text-red-400" />,
  };

  const statusColors = {
    completed: "bg-green-500/10 border-green-500/20",
    processing: "bg-cyan-500/10 border-cyan-500/20",
    queued: "bg-amber-500/10 border-amber-500/20",
    failed: "bg-red-500/10 border-red-500/20",
  };

  return (
    <div className={`p-5 rounded-2xl border ${statusColors[task.status as keyof typeof statusColors] || "bg-white/5 border-white/10"} hover:scale-[1.02] transition-transform cursor-pointer group`}>
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-cyan-500/20 to-purple-500/20 flex items-center justify-center">
            <Film className="w-6 h-6 text-cyan-400" />
          </div>
          <div>
            <h3 className="font-semibold text-white group-hover:text-cyan-400 transition-colors">{task.title}</h3>
            <p className="text-sm text-gray-500">{task.source_type} • {task.clips_count} clips</p>
          </div>
        </div>
        {statusIcons[task.status as keyof typeof statusIcons] || <Clock className="w-5 h-5 text-gray-400" />}
      </div>
      
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">{new Date(task.created_at).toLocaleDateString()}</span>
        <ArrowRight className="w-4 h-4 text-gray-500 group-hover:text-cyan-400 transition-colors" />
      </div>
    </div>
  );
}

// Stats Card
function StatCard({ icon: Icon, label, value, trend }: { icon: any, label: string, value: string, trend?: string }) {
  return (
    <div className="p-6 rounded-2xl bg-white/5 border border-white/10">
      <div className="flex items-center justify-between mb-4">
        <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center">
          <Icon className="w-5 h-5 text-cyan-400" />
        </div>
        {trend && <span className="text-xs text-green-400">{trend}</span>}
      </div>
      <div className="text-2xl font-bold text-white mb-1">{value}</div>
      <div className="text-sm text-gray-500">{label}</div>
    </div>
  );
}

export default function DashboardPage() {
  const [tasks] = useState([
    { id: "1", title: "Podcast Episode #42", source_type: "youtube", clips_count: 12, status: "completed", created_at: "2026-04-04" },
    { id: "2", title: "Tutorial: React Hooks", source_type: "upload", clips_count: 8, status: "processing", created_at: "2026-04-04" },
    { id: "3", title: "Product Review 2026", source_type: "youtube", clips_count: 15, status: "queued", created_at: "2026-04-03" },
    { id: "4", title: "Interview with CEO", source_type: "upload", clips_count: 6, status: "completed", created_at: "2026-04-02" },
  ]);

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white flex">
      <Sidebar />
      
      <main className="flex-1 overflow-auto">
        {/* Header */}
        <header className="sticky top-0 z-40 bg-[#0a0a0f]/80 backdrop-blur-xl border-b border-white/5 px-8 py-4">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-2xl font-bold">Dashboard</h1>
              <p className="text-sm text-gray-500">Manage your viral clip generation</p>
            </div>
            
            <Link href="/">
              <button className="flex items-center gap-2 px-6 py-3 bg-cyan-500 hover:bg-cyan-400 text-black font-semibold rounded-xl transition-all hover:shadow-[0_0_30px_-5px_rgba(34,211,238,0.5)]">
                <Plus className="w-5 h-5" />
                New Project
              </button>
            </Link>
          </div>
        </header>

        <div className="p-8">
          {/* Stats Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            <StatCard icon={Video} label="Total Clips" value="156" trend="+12%" />
            <StatCard icon={Film} label="Projects" value="23" trend="+5%" />
            <StatCard icon={Sparkles} label="Viral Score" value="87.5" trend="+8%" />
            <StatCard icon={Clock} label="Time Saved" value="48h" trend="+15%" />
          </div>

          {/* Recent Tasks */}
          <div className="mb-8">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-bold">Recent Projects</h2>
              <Link href="/list" className="text-sm text-cyan-400 hover:text-cyan-300 flex items-center gap-1">
                View All <ArrowRight className="w-4 h-4" />
              </Link>
            </div>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {tasks.map((task) => (
                <TaskCard key={task.id} task={task} />
              ))}
            </div>
          </div>

          {/* Quick Actions */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-6 rounded-2xl bg-gradient-to-br from-cyan-500/10 to-purple-500/10 border border-cyan-500/20">
              <Video className="w-8 h-8 text-cyan-400 mb-4" />
              <h3 className="font-semibold mb-2">Upload Video</h3>
              <p className="text-sm text-gray-500 mb-4">Drop in any video file or paste a YouTube URL</p>
              <Link href="/">
                <button className="text-sm text-cyan-400 hover:text-cyan-300 font-medium">Get Started ?</button>
              </Link>
            </div>
            
            <div className="p-6 rounded-2xl bg-gradient-to-br from-purple-500/10 to-pink-500/10 border border-purple-500/20">
              <Sparkles className="w-8 h-8 text-purple-400 mb-4" />
              <h3 className="font-semibold mb-2">AI Templates</h3>
              <p className="text-sm text-gray-500 mb-4">Choose from viral caption styles and effects</p>
              <button className="text-sm text-purple-400 hover:text-purple-300 font-medium">Browse Templates ?</button>
            </div>
            
            <div className="p-6 rounded-2xl bg-gradient-to-br from-pink-500/10 to-amber-500/10 border border-pink-500/20">
              <BarChart3 className="w-8 h-8 text-pink-400 mb-4" />
              <h3 className="font-semibold mb-2">Analytics</h3>
              <p className="text-sm text-gray-500 mb-4">Track your clips performance across platforms</p>
              <button className="text-sm text-pink-400 hover:text-pink-300 font-medium">View Analytics ?</button>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
