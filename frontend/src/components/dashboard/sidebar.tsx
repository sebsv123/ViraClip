"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { 
  Home, 
  PlusCircle, 
  Film, 
  Settings, 
  HelpCircle,
  Zap
} from "lucide-react";

interface SidebarProps {
  user: {
    name?: string;
    clips_this_month?: number;
  };
}

const navigation = [
  { name: "Dashboard", href: "/dashboard", icon: Home },
  { name: "Create Clip", href: "/dashboard", icon: PlusCircle },
  { name: "My Clips", href: "/list", icon: Film },
  { name: "Settings", href: "/dashboard/settings", icon: Settings },
  { name: "Help", href: "/dashboard/settings", icon: HelpCircle },
];

export function DashboardSidebar({ user }: SidebarProps) {
  const pathname = usePathname();

  const clipsUsed = user.clips_this_month || 0;
  const clipsLimit = 10;
  const usagePercentage = (clipsUsed / clipsLimit) * 100;

  return (
    <div className="w-64 bg-gray-900 border-r border-gray-800 flex flex-col">
      {/* Logo */}
      <div className="p-6 border-b border-gray-800">
        <Link href="/dashboard" className="flex items-center gap-2">
          <Zap className="w-8 h-8 text-cyan-400" />
          <span className="text-xl font-bold text-white">ViraClip</span>
        </Link>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-1">
        {navigation.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;

          return (
            <Link
              key={item.name}
              href={item.href}
              className={`
                flex items-center gap-3 px-4 py-3 rounded-lg transition-colors
                ${isActive 
                  ? 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20' 
                  : 'text-gray-400 hover:text-white hover:bg-gray-800'
                }
              `}
            >
              <Icon className="w-5 h-5" />
              <span className="font-medium">{item.name}</span>
            </Link>
          );
        })}
      </nav>

      {/* Usage Stats */}
      <div className="p-4 border-t border-gray-800">
        <div className="bg-gray-800 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-gray-400">Usage This Month</span>
            <span className="text-sm font-bold text-white">
              {clipsUsed}/{clipsLimit}
            </span>
          </div>
          
          {/* Progress bar */}
          <div className="w-full bg-gray-700 rounded-full h-2 overflow-hidden">
            <div 
              className="bg-gradient-to-r from-cyan-400 to-purple-500 h-full transition-all duration-300"
              style={{ width: `${Math.min(usagePercentage, 100)}%` }}
            />
          </div>

          <p className="text-xs text-gray-500 mt-2">
            Beta: Unlimited clips 🎉
          </p>
        </div>
      </div>
    </div>
  );
}
