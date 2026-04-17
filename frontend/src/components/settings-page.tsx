"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
import { 
  Tabs, 
  TabsContent, 
  TabsList, 
  TabsTrigger 
} from "@/components/ui/tabs";
import { 
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { 
  User, 
  Bell, 
  Shield, 
  Palette, 
  Database, 
  Share2, 
  CreditCard,
  Globe,
  Moon,
  Sun,
  Smartphone,
  Mail,
  Key,
  ExternalLink,
  CheckCircle2,
  AlertCircle
} from "lucide-react";

interface UserSettings {
  profile: {
    name: string;
    email: string;
    avatar: string;
    bio: string;
    timezone: string;
  };
  notifications: {
    email: boolean;
    push: boolean;
    marketing: boolean;
    clipReady: boolean;
    viralAlerts: boolean;
  };
  preferences: {
    theme: "light" | "dark" | "system";
    language: string;
    defaultQuality: string;
    autoPublish: boolean;
    watermark: boolean;
  };
  integrations: {
    youtube: boolean;
    tiktok: boolean;
    instagram: boolean;
    notion: boolean;
    slack: boolean;
  };
  privacy: {
    publicProfile: boolean;
    shareAnalytics: boolean;
    allowTagging: boolean;
  };
}

export function SettingsPage() {
  const [settings, setSettings] = useState<UserSettings>({
    profile: {
      name: "John Creator",
      email: "john@example.com",
      avatar: "",
      bio: "Video creator and content strategist",
      timezone: "UTC-5"
    },
    notifications: {
      email: true,
      push: true,
      marketing: false,
      clipReady: true,
      viralAlerts: true
    },
    preferences: {
      theme: "system",
      language: "en",
      defaultQuality: "1080p",
      autoPublish: false,
      watermark: true
    },
    integrations: {
      youtube: true,
      tiktok: false,
      instagram: true,
      notion: false,
      slack: true
    },
    privacy: {
      publicProfile: true,
      shareAnalytics: true,
      allowTagging: true
    }
  });

  const [hasChanges, setHasChanges] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const updateSetting = <K extends keyof UserSettings>(
    section: K,
    key: keyof UserSettings[K],
    value: any
  ) => {
    setSettings(prev => ({
      ...prev,
      [section]: {
        ...prev[section],
        [key]: value
      }
    }));
    setHasChanges(true);
  };

  const saveSettings = async () => {
    setIsSaving(true);
    // Simulate API call
    await new Promise(resolve => setTimeout(resolve, 1000));
    setIsSaving(false);
    setHasChanges(false);
  };

  return (
    <div className="max-w-6xl mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Settings</h1>
          <p className="text-muted-foreground">
            Manage your account preferences and integrations
          </p>
        </div>
        {hasChanges && (
          <Button onClick={saveSettings} disabled={isSaving}>
            {isSaving ? "Saving..." : "Save Changes"}
          </Button>
        )}
      </div>

      <Tabs defaultValue="profile" className="space-y-6">
        <TabsList className="grid w-full grid-cols-2 lg:grid-cols-6 lg:w-auto">
          <TabsTrigger value="profile">Profile</TabsTrigger>
          <TabsTrigger value="notifications">Notifications</TabsTrigger>
          <TabsTrigger value="preferences">Preferences</TabsTrigger>
          <TabsTrigger value="integrations">Integrations</TabsTrigger>
          <TabsTrigger value="privacy">Privacy</TabsTrigger>
          <TabsTrigger value="billing">Billing</TabsTrigger>
        </TabsList>

        {/* Profile Tab */}
        <TabsContent value="profile" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <User className="h-5 w-5" />
                Profile Information
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center gap-6">
                <div className="w-24 h-24 bg-muted rounded-full flex items-center justify-center">
                  <User className="h-12 w-12 text-muted-foreground" />
                </div>
                <div className="space-y-2">
                  <Button variant="outline" size="sm">
                    Change Avatar
                  </Button>
                  <p className="text-xs text-muted-foreground">
                    JPG, PNG or GIF. Max 2MB.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="name">Display Name</Label>
                  <Input
                    id="name"
                    value={settings.profile.name}
                    onChange={(e) => updateSetting("profile", "name", e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    value={settings.profile.email}
                    onChange={(e) => updateSetting("profile", "email", e.target.value)}
                  />
                </div>
                <div className="space-y-2 md:col-span-2">
                  <Label htmlFor="bio">Bio</Label>
                  <Input
                    id="bio"
                    value={settings.profile.bio}
                    onChange={(e) => updateSetting("profile", "bio", e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="timezone">Timezone</Label>
                  <Select
                    value={settings.profile.timezone}
                    onValueChange={(value) => updateSetting("profile", "timezone", value)}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="UTC-8">Pacific Time (UTC-8)</SelectItem>
                      <SelectItem value="UTC-5">Eastern Time (UTC-5)</SelectItem>
                      <SelectItem value="UTC+0">GMT (UTC+0)</SelectItem>
                      <SelectItem value="UTC+1">Central Europe (UTC+1)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-destructive">
                <Shield className="h-5 w-5" />
                Danger Zone
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">Delete Account</p>
                  <p className="text-sm text-muted-foreground">
                    Permanently delete your account and all data
                  </p>
                </div>
                <Button variant="destructive">Delete Account</Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Notifications Tab */}
        <TabsContent value="notifications" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Bell className="h-5 w-5" />
                Notification Preferences
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              {[
                { key: "email", label: "Email Notifications", description: "Receive updates via email" },
                { key: "push", label: "Push Notifications", description: "Browser push notifications" },
                { key: "marketing", label: "Marketing Emails", description: "Product updates and tips" },
                { key: "clipReady", label: "Clip Ready Alerts", description: "When AI finishes generating clips" },
                { key: "viralAlerts", label: "Viral Alerts", description: "When your clips are trending" }
              ].map((item) => (
                <div key={item.key} className="flex items-center justify-between">
                  <div>
                    <p className="font-medium">{item.label}</p>
                    <p className="text-sm text-muted-foreground">{item.description}</p>
                  </div>
                  <Switch
                    checked={settings.notifications[item.key as keyof typeof settings.notifications]}
                    onCheckedChange={(checked) => 
                      updateSetting("notifications", item.key as any, checked)
                    }
                  />
                </div>
              ))}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Preferences Tab */}
        <TabsContent value="preferences" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Palette className="h-5 w-5" />
                Appearance & Behavior
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2">
                <Label>Theme</Label>
                <div className="flex gap-2">
                  <Button
                    variant={settings.preferences.theme === "light" ? "default" : "outline"}
                    size="sm"
                    onClick={() => updateSetting("preferences", "theme", "light")}
                  >
                    <Sun className="h-4 w-4 mr-2" />
                    Light
                  </Button>
                  <Button
                    variant={settings.preferences.theme === "dark" ? "default" : "outline"}
                    size="sm"
                    onClick={() => updateSetting("preferences", "theme", "dark")}
                  >
                    <Moon className="h-4 w-4 mr-2" />
                    Dark
                  </Button>
                  <Button
                    variant={settings.preferences.theme === "system" ? "default" : "outline"}
                    size="sm"
                    onClick={() => updateSetting("preferences", "theme", "system")}
                  >
                    <Monitor className="h-4 w-4 mr-2" />
                    System
                  </Button>
                </div>
              </div>

              <Separator />

              <div className="space-y-2">
                <Label htmlFor="language">Language</Label>
                <Select
                  value={settings.preferences.language}
                  onValueChange={(value) => updateSetting("preferences", "language", value)}
                >
                  <SelectTrigger className="w-[200px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="en">English</SelectItem>
                    <SelectItem value="es">Español</SelectItem>
                    <SelectItem value="fr">Français</SelectItem>
                    <SelectItem value="de">Deutsch</SelectItem>
                    <SelectItem value="pt">Português</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                <Label htmlFor="quality">Default Export Quality</Label>
                <Select
                  value={settings.preferences.defaultQuality}
                  onValueChange={(value) => updateSetting("preferences", "defaultQuality", value)}
                >
                  <SelectTrigger className="w-[200px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="720p">720p HD</SelectItem>
                    <SelectItem value="1080p">1080p Full HD</SelectItem>
                    <SelectItem value="4K">4K Ultra HD</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <Separator />

              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">Auto-Publish</p>
                  <p className="text-sm text-muted-foreground">
                    Automatically publish clips when ready
                  </p>
                </div>
                <Switch
                  checked={settings.preferences.autoPublish}
                  onCheckedChange={(checked) => 
                    updateSetting("preferences", "autoPublish", checked)
                  }
                />
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">ViraClip Watermark</p>
                  <p className="text-sm text-muted-foreground">
                    Add subtle branding to exported clips
                  </p>
                </div>
                <Switch
                  checked={settings.preferences.watermark}
                  onCheckedChange={(checked) => 
                    updateSetting("preferences", "watermark", checked)
                  }
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Integrations Tab */}
        <TabsContent value="integrations" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Share2 className="h-5 w-5" />
                Connected Platforms
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {[
                { key: "youtube", name: "YouTube", icon: "YT", color: "bg-red-600", connected: settings.integrations.youtube },
                { key: "tiktok", name: "TikTok", icon: "TT", color: "bg-black", connected: settings.integrations.tiktok },
                { key: "instagram", name: "Instagram", icon: "IG", color: "bg-gradient-to-br from-purple-600 to-pink-500", connected: settings.integrations.instagram },
                { key: "notion", name: "Notion", icon: "N", color: "bg-gray-800", connected: settings.integrations.notion },
                { key: "slack", name: "Slack", icon: "SL", color: "bg-purple-700", connected: settings.integrations.slack }
              ].map((platform) => (
                <div key={platform.key} className="flex items-center justify-between p-4 border rounded-lg">
                  <div className="flex items-center gap-3">
                    <div className={`w-10 h-10 ${platform.color} rounded-lg flex items-center justify-center text-white font-bold text-sm`}>
                      {platform.icon}
                    </div>
                    <div>
                      <p className="font-medium">{platform.name}</p>
                      <p className="text-sm text-muted-foreground">
                        {platform.connected ? (
                          <span className="flex items-center gap-1 text-green-600">
                            <CheckCircle2 className="h-3 w-3" />
                            Connected
                          </span>
                        ) : (
                          "Not connected"
                        )}
                      </p>
                    </div>
                  </div>
                  <Button
                    variant={platform.connected ? "outline" : "default"}
                    size="sm"
                    onClick={() => updateSetting("integrations", platform.key as any, !platform.connected)}
                  >
                    {platform.connected ? "Disconnect" : "Connect"}
                  </Button>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Key className="h-5 w-5" />
                API Keys
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between p-4 border rounded-lg">
                <div>
                  <p className="font-medium">API Access</p>
                  <p className="text-sm text-muted-foreground">
                    Generate API keys for external integrations
                  </p>
                </div>
                <Button variant="outline" size="sm">
                  <Key className="h-4 w-4 mr-2" />
                  Manage Keys
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Privacy Tab */}
        <TabsContent value="privacy" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Shield className="h-5 w-5" />
                Privacy Settings
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">Public Profile</p>
                  <p className="text-sm text-muted-foreground">
                    Allow others to see your profile and clips
                  </p>
                </div>
                <Switch
                  checked={settings.privacy.publicProfile}
                  onCheckedChange={(checked) => 
                    updateSetting("privacy", "publicProfile", checked)
                  }
                />
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">Share Analytics</p>
                  <p className="text-sm text-muted-foreground">
                    Contribute to platform analytics (anonymized)
                  </p>
                </div>
                <Switch
                  checked={settings.privacy.shareAnalytics}
                  onCheckedChange={(checked) => 
                    updateSetting("privacy", "shareAnalytics", checked)
                  }
                />
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium">Allow Tagging</p>
                  <p className="text-sm text-muted-foreground">
                    Others can tag you in collaborative projects
                  </p>
                </div>
                <Switch
                  checked={settings.privacy.allowTagging}
                  onCheckedChange={(checked) => 
                    updateSetting("privacy", "allowTagging", checked)
                  }
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Billing Tab */}
        <TabsContent value="billing" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CreditCard className="h-5 w-5" />
                Subscription
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center justify-between p-4 bg-muted rounded-lg">
                <div>
                  <p className="font-medium">Pro Plan</p>
                  <p className="text-sm text-muted-foreground">
                    $29/month • Renews Jan 15, 2024
                  </p>
                </div>
                <Badge>Active</Badge>
              </div>

              <div className="grid grid-cols-3 gap-4 text-center">
                <div className="p-4 bg-muted rounded-lg">
                  <p className="text-2xl font-bold">47</p>
                  <p className="text-xs text-muted-foreground">Videos This Month</p>
                </div>
                <div className="p-4 bg-muted rounded-lg">
                  <p className="text-2xl font-bold">∞</p>
                  <p className="text-xs text-muted-foreground">Remaining</p>
                </div>
                <div className="p-4 bg-muted rounded-lg">
                  <p className="text-2xl font-bold">12</p>
                  <p className="text-xs text-muted-foreground">Days Left</p>
                </div>
              </div>

              <div className="flex gap-2">
                <Button variant="outline">Change Plan</Button>
                <Button variant="outline">Billing History</Button>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Payment Method</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between p-4 border rounded-lg">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-8 bg-blue-600 rounded flex items-center justify-center text-white text-xs font-bold">
                    VISA
                  </div>
                  <div>
                    <p className="font-medium">•••• 4242</p>
                    <p className="text-sm text-muted-foreground">Expires 12/25</p>
                  </div>
                </div>
                <Button variant="outline" size="sm">Update</Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}

// Missing import
import { Monitor } from "lucide-react";
