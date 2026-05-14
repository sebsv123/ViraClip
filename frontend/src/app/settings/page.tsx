"use client";

import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { signOut, useSession } from "@/lib/auth-client";
import { track } from "@/lib/datafast";
import Link from "next/link";
import { Type, Palette, CheckCircle, AlertCircle, Settings, ArrowLeft, Mail } from "lucide-react";

interface UserPreferences {
  fontFamily: string;
  fontSize: number;
  fontColor: string;
  notifyOnCompletion: boolean;
}

interface BillingSummary {
  monetization_enabled: boolean;
  plan: string;
  subscription_status: string;
  usage_count: number;
  usage_limit: number | null;
  remaining: number | null;
}

export default function SettingsPage() {
  const [fontFamily, setFontFamily] = useState("TikTokSans-Regular");
  const [fontSize, setFontSize] = useState(24);
  const [fontColor, setFontColor] = useState("#FFFFFF");
  const [completionEmails, setCompletionEmails] = useState(true);
  const [availableFonts, setAvailableFonts] = useState<Array<{ name: string, display_name: string }>>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [isFetching, setIsFetching] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [billingSummary, setBillingSummary] = useState<BillingSummary | null>(null);
  const [isBillingActionLoading, setIsBillingActionLoading] = useState(false);
  const { data: session, isPending } = useSession();
  const isAdmin = Boolean((session?.user as { is_admin?: boolean } | undefined)?.is_admin);

  const proPriceMonthly = process.env.NEXT_PUBLIC_PRO_PRICE_MONTHLY || "9.99";

  // Load available fonts from backend and inject them into the page
  useEffect(() => {
    const loadFonts = async () => {
      try {
        const response = await fetch('/api/fonts', { cache: 'no-store' });
        if (response.ok) {
          const data = await response.json();
          setAvailableFonts(data.fonts || []);

          // Dynamically load fonts using @font-face
          const fontFaceStyles = data.fonts.map((font: { name: string }) => {
            return `
              @font-face {
                font-family: '${font.name}';
                src: url('/api/fonts/${font.name}') format('truetype');
                font-weight: normal;
                font-style: normal;
              }
            `;
          }).join('\n');

          // Inject font styles into the page
          const styleElement = document.createElement('style');
          styleElement.id = 'custom-fonts';
          styleElement.innerHTML = fontFaceStyles;

          // Remove existing custom fonts style if present
          const existingStyle = document.getElementById('custom-fonts');
          if (existingStyle) {
            existingStyle.remove();
          }

          document.head.appendChild(styleElement);
        }
      } catch (error) {
        console.error('Failed to load fonts:', error);
      }
    };

    loadFonts();
  }, []);

  // Load user preferences
  useEffect(() => {
    const loadPreferences = async () => {
      if (!session?.user?.id) return;

      setIsFetching(true);
      try {
        const response = await fetch('/api/preferences');
        if (response.ok) {
          const data: UserPreferences = await response.json();
          setFontFamily(data.fontFamily);
          setFontSize(data.fontSize);
          setFontColor(data.fontColor);
          setCompletionEmails(data.notifyOnCompletion ?? true);
        }
      } catch (error) {
        console.error('Failed to load preferences:', error);
      } finally {
        setIsFetching(false);
      }
    };

    loadPreferences();
  }, [session?.user?.id]);

  useEffect(() => {
    const fetchBillingSummary = async () => {
      if (!session?.user?.id) return;

      try {
        const response = await fetch("/api/tasks/billing-summary", {
          cache: "no-store",
        });

        if (!response.ok) {
          return;
        }

        const data: BillingSummary = await response.json();
        setBillingSummary(data);
      } catch (fetchError) {
        console.error("Failed to fetch billing summary:", fetchError);
      }
    };

    fetchBillingSummary();
  }, [session?.user?.id]);

  const handleBillingAction = async () => {
    if (!billingSummary?.monetization_enabled) return;

    const route = billingSummary.plan === "pro" ? "/api/billing/portal" : "/api/billing/checkout";

    try {
      setIsBillingActionLoading(true);
      const response = await fetch(route, { method: "POST" });
      const data = await response.json();

      if (!response.ok || !data.url) {
        throw new Error(data.error || "Unable to open billing");
      }

      track(billingSummary.plan === "pro" ? "billing_portal_opened" : "billing_checkout_started", {
        plan: billingSummary.plan,
      });
      window.location.href = data.url;
    } catch (billingError) {
      setError(billingError instanceof Error ? billingError.message : "Billing action failed");
    } finally {
      setIsBillingActionLoading(false);
    }
  };

  const handleSavePreferences = async () => {
    setIsLoading(true);
    setError(null);
    setSuccess(false);

    try {
      const response = await fetch('/api/preferences', {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          fontFamily,
          fontSize,
          fontColor,
          notifyOnCompletion: completionEmails,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || 'Failed to save preferences');
      }

      track("preferences_saved");
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (error) {
      console.error('Error saving preferences:', error);
      setError(error instanceof Error ? error.message : 'Failed to save preferences');
    } finally {
      setIsLoading(false);
    }
  };

  const handleSignOut = async () => {
    await signOut();
    window.location.href = "/sign-in";
  };

  if (isPending || isFetching) {
    return (
      <div className="min-h-screen bg-[#0a0a0f] flex items-center justify-center p-4">
        <div className="space-y-4">
          <Skeleton className="h-4 w-32 mx-auto bg-white/10" />
          <Skeleton className="h-4 w-48 mx-auto bg-white/10" />
          <Skeleton className="h-4 w-24 mx-auto bg-white/10" />
        </div>
      </div>
    );
  }

  if (!session?.user) {
    return (
      <div className="min-h-screen bg-[#0a0a0f]">
        <div className="max-w-4xl mx-auto px-4 py-24">
          <div className="text-center">
            <h1 className="text-3xl font-bold text-white mb-4">
              Sign In Required
            </h1>
            <p className="text-gray-400 mb-8">
              You need to sign in to access your settings
            </p>
            <Link href="/sign-in">
              <Button size="lg">Sign In</Button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white">
      {/* Header */}
      <div className="border-b border-white/5 bg-[#0a0a0f]/80 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex justify-between items-center">
            <Link href="/dashboard">
              <Button variant="ghost" size="sm" className="text-gray-400 hover:text-white">
                <ArrowLeft className="w-4 h-4" />
                Back to Dashboard
              </Button>
            </Link>

            <div className="flex items-center gap-3">
              {isAdmin && (
                <Link href="/admin">
                  <Button variant="outline" size="sm" className="border-white/10 text-gray-300 hover:text-white">
                    Admin
                  </Button>
                </Link>
              )}
              <Button variant="outline" size="sm" onClick={handleSignOut} className="border-white/10 text-gray-300 hover:text-white">
                Sign Out
              </Button>
              <Avatar className="w-8 h-8">
                <AvatarImage src={session.user.image || ""} />
                <AvatarFallback className="bg-gray-700 text-white text-sm">
                  {session.user.name?.charAt(0) || session.user.email?.charAt(0) || "U"}
                </AvatarFallback>
              </Avatar>
              <div className="hidden sm:block">
                <p className="text-sm font-medium text-white">{session.user.name}</p>
                <p className="text-xs text-gray-400">{session.user.email}</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-4xl mx-auto px-4 py-16">
        <div className="max-w-xl mx-auto">
          <div className="mb-8">
            <div className="flex items-center gap-2 mb-2">
              <Settings className="w-6 h-6 text-cyan-400" />
              <h2 className="text-2xl font-bold text-white">
                Settings
              </h2>
            </div>
            <p className="text-gray-400">
              Configure your default preferences for video clip generation
            </p>
          </div>

          <Separator className="my-8 bg-white/10" />

          <div className="space-y-8">
            {/* Font Preferences Section */}
            <div className="space-y-6">
              <div>
                <h3 className="text-lg font-semibold text-white mb-1">
                  Default Font Settings
                </h3>
                <p className="text-sm text-gray-400">
                  These settings will be applied to all new video processing tasks
                </p>
              </div>

              {/* Font Family Selector */}
              <div className="space-y-2">
                <Label className="text-sm font-medium text-gray-200 flex items-center gap-2">
                  <Type className="w-4 h-4" />
                  Font Family
                </Label>
                <Select value={fontFamily} onValueChange={setFontFamily} disabled={isLoading}>
                  <SelectTrigger className="w-full bg-white/5 border-white/10 text-white">
                    <SelectValue placeholder="Select font" />
                  </SelectTrigger>
                  <SelectContent className="bg-[#1a1a2e] border-white/10 text-white">
                    {availableFonts.map((font) => (
                      <SelectItem key={font.name} value={font.name}>
                        {font.display_name}
                      </SelectItem>
                    ))}
                    {availableFonts.length === 0 && (
                      <SelectItem value="TikTokSans-Regular">TikTok Sans Regular</SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>

              {/* Font Size Slider */}
              <div className="space-y-2">
                <Label className="text-sm font-medium text-gray-200">
                  Font Size: {fontSize}px
                </Label>
                <div className="px-2">
                  <Slider
                    value={[fontSize]}
                    onValueChange={(value) => setFontSize(value[0])}
                    max={48}
                    min={12}
                    step={2}
                    disabled={isLoading}
                    className="w-full"
                  />
                </div>
                <div className="flex justify-between text-xs text-gray-500">
                  <span>12px</span>
                  <span>48px</span>
                </div>
              </div>

              {/* Font Color Picker */}
              <div className="space-y-2">
                <Label className="text-sm font-medium text-gray-200 flex items-center gap-2">
                  <Palette className="w-4 h-4" />
                  Font Color
                </Label>
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    value={fontColor}
                    onChange={(e) => setFontColor(e.target.value)}
                    disabled={isLoading}
                    className="w-12 h-10 rounded border border-gray-600 cursor-pointer disabled:cursor-not-allowed bg-gray-800"
                  />
                  <Input
                    type="text"
                    value={fontColor}
                    onChange={(e) => setFontColor(e.target.value)}
                    disabled={isLoading}
                    placeholder="#FFFFFF"
                    className="flex-1 h-10 bg-white/5 border-white/10 text-white"
                    pattern="^#[0-9A-Fa-f]{6}$"
                  />
                </div>
                <div className="flex gap-2 mt-2">
                  {["#FFFFFF", "#000000", "#FFD700", "#FF6B6B", "#4ECDC4", "#45B7D1"].map((color) => (
                    <button
                      key={color}
                      type="button"
                      onClick={() => setFontColor(color)}
                      disabled={isLoading}
                      className="w-8 h-8 rounded border-2 border-gray-600 cursor-pointer hover:scale-110 transition-transform disabled:cursor-not-allowed"
                      style={{ backgroundColor: color }}
                      title={color}
                    />
                  ))}
                </div>
              </div>

              {/* Preview */}
              <div className="space-y-2">
                <Label className="text-sm font-medium text-gray-200">Preview</Label>
                <div className="p-6 bg-black rounded-lg flex items-center justify-center min-h-[100px] border border-white/10">
                  <p
                    style={{
                      color: fontColor,
                      fontSize: `${Math.min(fontSize, 32)}px`,
                      fontFamily: `'${fontFamily}', system-ui, -apple-system, sans-serif`,
                      textAlign: 'center',
                      lineHeight: '1.4'
                    }}
                    className="font-medium"
                  >
                    Your subtitle will look like this
                  </p>
                </div>
              </div>
            </div>

            {/* Notifications Section */}
            <div className="space-y-6">
              <div>
                <h3 className="text-lg font-semibold text-white mb-1">
                  Notifications
                </h3>
                <p className="text-sm text-gray-400">
                  Manage how you receive updates about your clips
                </p>
              </div>

              <div className="flex items-center justify-between p-4 rounded-xl border border-white/10 bg-white/5">
                <Label htmlFor="completion-emails" className="flex items-center gap-2 text-sm font-medium text-gray-200 cursor-pointer">
                  <Mail className="w-4 h-4" />
                  Completion emails
                  <span className="text-gray-500 font-normal">— get notified when clips are ready</span>
                </Label>
                <Switch
                  id="completion-emails"
                  checked={completionEmails}
                  onCheckedChange={setCompletionEmails}
                  disabled={isLoading}
                />
              </div>
            </div>

            <Separator className="mb-4 bg-white/10" />

            {/* Success/Error Messages */}
            {success && (
              <Alert className="border-green-500/30 bg-green-500/10">
                <CheckCircle className="h-4 w-4 text-green-400" />
                <AlertDescription className="text-sm text-green-300">
                  Preferences saved successfully!
                </AlertDescription>
              </Alert>
            )}

            {error && (
              <Alert className="border-red-500/30 bg-red-500/10">
                <AlertCircle className="h-4 w-4 text-red-400" />
                <AlertDescription className="text-sm text-red-300">
                  {error}
                </AlertDescription>
              </Alert>
            )}

            {/* Save Button */}
            {billingSummary?.monetization_enabled && (
              <div className="border border-white/10 rounded-xl p-4 bg-white/5 space-y-3">
                <div>
                  <h3 className="text-lg font-semibold text-white">Billing</h3>
                  {billingSummary.plan !== "pro" && (
                    <p className="text-sm text-gray-400">Pro plan: ${proPriceMonthly}/month</p>
                  )}
                  <p className="text-sm text-gray-400">
                    {billingSummary.usage_limit === null
                      ? `${billingSummary.usage_count} generations in this billing period`
                      : `${billingSummary.usage_count}/${billingSummary.usage_limit} generations used this period`}
                  </p>
                  <p className="text-sm text-gray-500 capitalize">
                    Plan: {billingSummary.plan} ({billingSummary.subscription_status})
                  </p>
                </div>

                <Button
                  type="button"
                  variant={billingSummary.plan === "pro" ? "outline" : "default"}
                  onClick={handleBillingAction}
                  disabled={isBillingActionLoading}
                  className="w-full"
                >
                  {isBillingActionLoading
                    ? "Loading..."
                    : billingSummary.plan === "pro"
                      ? "Manage Billing"
                      : `Upgrade to Pro ($${proPriceMonthly}/mo)`}
                </Button>
              </div>
            )}

            <Button
              onClick={handleSavePreferences}
              disabled={isLoading}
              className="w-full h-11 bg-cyan-500 hover:bg-cyan-400 text-black font-semibold"
            >
              {isLoading ? "Saving..." : "Save Preferences"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
