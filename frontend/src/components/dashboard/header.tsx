"use client";

import { Bell, LogOut, Settings, User } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

interface HeaderProps {
  user: {
    name?: string;
    email?: string;
    image?: string;
  };
}

export function DashboardHeader({ user }: HeaderProps) {
  const [showDropdown, setShowDropdown] = useState(false);

  const handleSignOut = async () => {
    // TODO: Implement better-auth signout
    window.location.href = "/api/auth/sign-out";
  };

  const initials = user.name
    ? user.name.split(' ').map(n => n[0]).join('').toUpperCase()
    : 'U';

  return (
    <header className="h-16 border-b border-gray-800 bg-gray-900 flex items-center justify-between px-6">
      {/* Left: Page title (can be dynamically set) */}
      <div>
        <h1 className="text-xl font-semibold text-white">Dashboard</h1>
      </div>

      {/* Right: Notifications & User menu */}
      <div className="flex items-center gap-4">
        {/* Notifications (placeholder) */}
        <button className="relative p-2 text-gray-400 hover:text-white hover:bg-gray-800 rounded-lg transition-colors">
          <Bell className="w-5 h-5" />
          {/* Notification badge */}
          <span className="absolute top-1 right-1 w-2 h-2 bg-cyan-400 rounded-full" />
        </button>

        {/* User menu */}
        <div className="relative">
          <button
            onClick={() => setShowDropdown(!showDropdown)}
            className="flex items-center gap-3 p-2 hover:bg-gray-800 rounded-lg transition-colors"
          >
            {/* Avatar */}
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-cyan-400 to-purple-500 flex items-center justify-center text-white font-bold text-sm">
              {user.image ? (
                <img src={user.image} alt={user.name || 'User'} className="w-full h-full rounded-full" />
              ) : (
                initials
              )}
            </div>
            <span className="text-sm font-medium text-white hidden md:block">
              {user.name || 'User'}
            </span>
          </button>

          {/* Dropdown menu */}
          {showDropdown && (
            <>
              {/* Backdrop */}
              <div
                className="fixed inset-0 z-10"
                onClick={() => setShowDropdown(false)}
              />
              
              {/* Menu */}
              <div className="absolute right-0 mt-2 w-56 bg-gray-800 rounded-lg shadow-xl border border-gray-700 py-2 z-20">
                <div className="px-4 py-3 border-b border-gray-700">
                  <p className="text-sm font-medium text-white">{user.name}</p>
                  <p className="text-xs text-gray-400">{user.email}</p>
                </div>

                <Link
                  href="/dashboard/settings"
                  className="flex items-center gap-3 px-4 py-2 text-sm text-gray-300 hover:bg-gray-700 hover:text-white"
                  onClick={() => setShowDropdown(false)}
                >
                  <Settings className="w-4 h-4" />
                  Settings
                </Link>

                <Link
                  href="/dashboard/settings"
                  className="flex items-center gap-3 px-4 py-2 text-sm text-gray-300 hover:bg-gray-700 hover:text-white"
                  onClick={() => setShowDropdown(false)}
                >
                  <User className="w-4 h-4" />
                  Profile
                </Link>

                <div className="border-t border-gray-700 my-2" />

                <button
                  onClick={handleSignOut}
                  className="w-full flex items-center gap-3 px-4 py-2 text-sm text-red-400 hover:bg-gray-700"
                >
                  <LogOut className="w-4 h-4" />
                  Sign Out
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
