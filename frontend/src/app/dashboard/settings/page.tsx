"use client";

import { useState } from "react";
import { useSession } from "@/lib/auth-client";
import { 
  User, 
  Mail, 
  Shield, 
  Bell,
  Trash2,
  Save,
  Camera,
  Loader2,
  Check
} from "lucide-react";

export default function SettingsPage() {
  const { data: session } = useSession();
  const user = session?.user;

  const [activeTab, setActiveTab] = useState<'profile' | 'account' | 'notifications'>('profile');
  const [name, setName] = useState(user?.name || '');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  // Notification preferences
  const [emailNotifications, setEmailNotifications] = useState(true);
  const [completionNotifications, setCompletionNotifications] = useState(true);

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    
    try {
      // TODO: Implement profile update API call
      await new Promise(resolve => setTimeout(resolve, 1000)); // Simulated delay
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (error) {
      console.error('Failed to save profile:', error);
    } finally {
      setSaving(false);
    }
  };

  const tabs = [
    { id: 'profile', label: 'Profile', icon: User },
    { id: 'account', label: 'Account', icon: Shield },
    { id: 'notifications', label: 'Notifications', icon: Bell },
  ] as const;

  const initials = user?.name
    ? user.name.split(' ').map(n => n[0]).join('').toUpperCase()
    : 'U';

  return (
    <div className="max-w-5xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">Settings</h1>
        <p className="text-gray-400">Manage your account settings and preferences</p>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6 border-b border-gray-800">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex items-center gap-2 px-4 py-3 font-medium transition-colors relative ${
                activeTab === tab.id
                  ? 'text-cyan-400'
                  : 'text-gray-400 hover:text-white'
              }`}
            >
              <Icon className="w-4 h-4" />
              {tab.label}
              {activeTab === tab.id && (
                <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-cyan-400" />
              )}
            </button>
          );
        })}
      </div>

      {/* Profile Tab */}
      {activeTab === 'profile' && (
        <div className="space-y-6">
          {/* Profile Card */}
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
            <h2 className="text-xl font-semibold text-white mb-6">Profile Information</h2>

            <form onSubmit={handleSaveProfile} className="space-y-6">
              {/* Avatar */}
              <div className="flex items-center gap-6">
                <div className="relative">
                  <div className="w-20 h-20 rounded-full bg-gradient-to-br from-cyan-400 to-purple-500 flex items-center justify-center text-white font-bold text-2xl">
                    {user?.image ? (
                      <img src={user.image} alt={user.name || 'User'} className="w-full h-full rounded-full" />
                    ) : (
                      initials
                    )}
                  </div>
                  <button
                    type="button"
                    className="absolute bottom-0 right-0 w-8 h-8 bg-cyan-500 hover:bg-cyan-400 rounded-full flex items-center justify-center text-black transition-colors"
                  >
                    <Camera className="w-4 h-4" />
                  </button>
                </div>
                <div>
                  <h3 className="text-white font-medium">{user?.name || 'User'}</h3>
                  <p className="text-sm text-gray-400">{user?.email}</p>
                </div>
              </div>

              {/* Name */}
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Full Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-xl text-white focus:outline-none focus:border-cyan-500 transition-colors"
                  placeholder="Enter your name"
                />
              </div>

              {/* Email (read-only) */}
              <div>
                <label className="block text-sm font-medium text-gray-300 mb-2">
                  Email
                </label>
                <div className="relative">
                  <Mail className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
                  <input
                    type="email"
                    value={user?.email || ''}
                    disabled
                    className="w-full pl-12 pr-4 py-3 bg-gray-800 border border-gray-700 rounded-xl text-gray-500 cursor-not-allowed"
                  />
                </div>
                <p className="text-xs text-gray-500 mt-1">Email cannot be changed</p>
              </div>

              {/* Save Button */}
              <div className="flex items-center gap-3">
                <button
                  type="submit"
                  disabled={saving || saved}
                  className="flex items-center gap-2 px-6 py-3 bg-cyan-500 hover:bg-cyan-400 disabled:bg-gray-700 disabled:cursor-not-allowed text-black font-semibold rounded-xl transition-colors"
                >
                  {saving ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Saving...
                    </>
                  ) : saved ? (
                    <>
                      <Check className="w-4 h-4" />
                      Saved!
                    </>
                  ) : (
                    <>
                      <Save className="w-4 h-4" />
                      Save Changes
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Account Tab */}
      {activeTab === 'account' && (
        <div className="space-y-6">
          {/* Beta Status */}
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
            <h2 className="text-xl font-semibold text-white mb-4">Beta Access</h2>
            
            <div className="flex items-center justify-between p-4 bg-green-500/10 border border-green-500/20 rounded-xl">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-green-500/20 flex items-center justify-center">
                  <Check className="w-5 h-5 text-green-400" />
                </div>
                <div>
                  <div className="text-white font-medium">Active Beta User</div>
                  <div className="text-sm text-gray-400">Unlimited clips during beta period</div>
                </div>
              </div>
              <div className="px-4 py-2 bg-green-500/20 text-green-400 rounded-lg text-sm font-medium">
                Active
              </div>
            </div>
          </div>

          {/* Usage Stats */}
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
            <h2 className="text-xl font-semibold text-white mb-4">Usage This Month</h2>
            
            <div className="grid grid-cols-3 gap-4">
              <div className="text-center p-4 bg-gray-800 rounded-xl">
                <div className="text-3xl font-bold text-cyan-400">{user?.clips_this_month || 0}</div>
                <div className="text-sm text-gray-400 mt-1">Clips Created</div>
              </div>
              <div className="text-center p-4 bg-gray-800 rounded-xl">
                <div className="text-3xl font-bold text-purple-400">∞</div>
                <div className="text-sm text-gray-400 mt-1">Remaining</div>
              </div>
              <div className="text-center p-4 bg-gray-800 rounded-xl">
                <div className="text-3xl font-bold text-pink-400">Beta</div>
                <div className="text-sm text-gray-400 mt-1">Plan</div>
              </div>
            </div>
          </div>

          {/* Danger Zone */}
          <div className="bg-gray-900 border border-red-500/30 rounded-2xl p-6">
            <h2 className="text-xl font-semibold text-red-400 mb-4">Danger Zone</h2>
            
            <div className="space-y-4">
              <div className="flex items-center justify-between p-4 border border-gray-800 rounded-xl">
                <div>
                  <div className="text-white font-medium">Delete Account</div>
                  <div className="text-sm text-gray-400">Permanently delete your account and all data</div>
                </div>
                <button className="flex items-center gap-2 px-4 py-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/30 rounded-lg transition-colors">
                  <Trash2 className="w-4 h-4" />
                  Delete
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Notifications Tab */}
      {activeTab === 'notifications' && (
        <div className="space-y-6">
          <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6">
            <h2 className="text-xl font-semibold text-white mb-6">Notification Preferences</h2>

            <div className="space-y-4">
              {/* Email Notifications */}
              <div className="flex items-center justify-between p-4 bg-gray-800 rounded-xl">
                <div>
                  <div className="text-white font-medium">Email Notifications</div>
                  <div className="text-sm text-gray-400">Receive updates via email</div>
                </div>
                <button
                  onClick={() => setEmailNotifications(!emailNotifications)}
                  className={`relative w-12 h-6 rounded-full transition-colors ${
                    emailNotifications ? 'bg-cyan-500' : 'bg-gray-700'
                  }`}
                >
                  <div
                    className={`absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition-transform ${
                      emailNotifications ? 'translate-x-6' : 'translate-x-0'
                    }`}
                  />
                </button>
              </div>

              {/* Completion Notifications */}
              <div className="flex items-center justify-between p-4 bg-gray-800 rounded-xl">
                <div>
                  <div className="text-white font-medium">Clip Completion Alerts</div>
                  <div className="text-sm text-gray-400">Get notified when clips are ready</div>
                </div>
                <button
                  onClick={() => setCompletionNotifications(!completionNotifications)}
                  className={`relative w-12 h-6 rounded-full transition-colors ${
                    completionNotifications ? 'bg-cyan-500' : 'bg-gray-700'
                  }`}
                >
                  <div
                    className={`absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition-transform ${
                      completionNotifications ? 'translate-x-6' : 'translate-x-0'
                    }`}
                  />
                </button>
              </div>
            </div>

            <div className="mt-6 p-4 bg-cyan-500/10 border border-cyan-500/20 rounded-xl">
              <p className="text-sm text-cyan-300">
                💡 <strong>Tip:</strong> Enable completion alerts to get notified as soon as your viral clips are ready to download!
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
