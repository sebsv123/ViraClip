"use client";

import { useState } from "react";
import {
  User,
  Bell,
  Shield,
  Palette,
  Share2,
  CreditCard,
  Globe,
  Moon,
  Sun,
  Smartphone,
  Key,
  CheckCircle2,
  AlertCircle,
  Monitor,
} from "lucide-react";

/* ─────────────────────────────────────────────
   Types
   ───────────────────────────────────────────── */

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

/* ─────────────────────────────────────────────
   Nav items
   ───────────────────────────────────────────── */

const navItems = [
  { id: "profile", label: "Perfil", icon: User },
  { id: "notifications", label: "Notificaciones", icon: Bell },
  { id: "preferences", label: "Preferencias", icon: Palette },
  { id: "integrations", label: "Integraciones", icon: Share2 },
  { id: "privacy", label: "Privacidad", icon: Shield },
  { id: "billing", label: "Plan", icon: CreditCard },
] as const;

type SectionId = (typeof navItems)[number]["id"];

/* ─────────────────────────────────────────────
   Toggle Switch — Linear style
   ───────────────────────────────────────────── */

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <div
      className="relative rounded-full transition-all cursor-pointer shrink-0"
      style={{
        width: 28,
        height: 16,
        background: checked ? "var(--accent)" : "rgba(255,255,255,0.15)",
      }}
      onClick={() => onChange(!checked)}
    >
      <div
        className="absolute top-0.5 rounded-full transition-all"
        style={{
          width: 12,
          height: 12,
          background: "var(--fg)",
          left: checked ? 14 : 2,
        }}
      />
    </div>
  );
}

/* ─────────────────────────────────────────────
   Component
   ───────────────────────────────────────────── */

export function SettingsPage() {
  const [activeSection, setActiveSection] = useState<SectionId>("profile");
  const [settings, setSettings] = useState<UserSettings>({
    profile: {
      name: "John Creator",
      email: "john@example.com",
      avatar: "",
      bio: "Video creator and content strategist",
      timezone: "UTC-5",
    },
    notifications: {
      email: true,
      push: true,
      marketing: false,
      clipReady: true,
      viralAlerts: true,
    },
    preferences: {
      theme: "system",
      language: "en",
      defaultQuality: "1080p",
      autoPublish: false,
      watermark: true,
    },
    integrations: {
      youtube: true,
      tiktok: false,
      instagram: true,
      notion: false,
      slack: true,
    },
    privacy: {
      publicProfile: true,
      shareAnalytics: true,
      allowTagging: true,
    },
  });

  const [hasChanges, setHasChanges] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const updateSetting = <K extends keyof UserSettings>(
    section: K,
    key: keyof UserSettings[K],
    value: unknown,
  ) => {
    setSettings((prev) => ({
      ...prev,
      [section]: {
        ...prev[section],
        [key]: value,
      },
    }));
    setHasChanges(true);
  };

  const saveSettings = async () => {
    setIsSaving(true);
    await new Promise((resolve) => setTimeout(resolve, 1000));
    setIsSaving(false);
    setHasChanges(false);
  };

  /* ── Shared input style ── */
  const inputStyle: React.CSSProperties = {
    background: "rgba(255,255,255,0.02)",
    color: "var(--fg-2)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-sm)",
    padding: "12px 14px",
    fontFamily: "var(--font-body)",
    fontSize: "var(--text-base)",
    fontFeatureSettings: '"cv01", "ss03"',
    outline: "none",
    transition: "border-color var(--motion-fast) var(--ease-standard)",
    width: "100%",
  };

  const labelStyle: React.CSSProperties = {
    fontSize: "var(--text-sm)",
    fontWeight: 510,
    color: "var(--fg-2)",
    fontFeatureSettings: '"cv01", "ss03"',
  };

  /* ── Card wrapper ── */
  const cardStyle: React.CSSProperties = {
    background: "rgba(255,255,255,0.02)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-md)",
    padding: "var(--space-6)",
  };

  return (
    <div
      className="flex gap-6"
      style={{ maxWidth: "var(--container-max)", margin: "0 auto", padding: "var(--space-6)" }}
    >
      {/* ── Sidebar nav ── */}
      <nav className="shrink-0 flex flex-col gap-1" style={{ width: 200 }}>
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeSection === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveSection(item.id)}
              className="flex items-center gap-2 rounded-sm transition-all text-sm"
              style={{
                height: 32,
                padding: "0 var(--space-3)",
                background: isActive ? "rgba(94,106,210,0.15)" : "transparent",
                color: isActive ? "var(--fg)" : "var(--fg-2)",
                fontFeatureSettings: '"cv01", "ss03"',
                transitionDuration: "var(--motion-fast)",
                transitionTimingFunction: "var(--ease-standard)",
              }}
              onMouseEnter={(e) => {
                if (!isActive) e.currentTarget.style.background = "rgba(255,255,255,0.06)";
              }}
              onMouseLeave={(e) => {
                if (!isActive) e.currentTarget.style.background = "transparent";
              }}
            >
              <Icon size={16} style={{ color: isActive ? "var(--accent)" : undefined }} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* ── Content ── */}
      <div className="flex-1 min-w-0 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-2">
          <div>
            <h1 className="text-xl font-semibold" style={{ color: "var(--fg)" }}>
              Settings
            </h1>
            <p className="lead" style={{ marginTop: 2 }}>
              Manage your account preferences and integrations
            </p>
          </div>
          {hasChanges && (
            <button
              onClick={saveSettings}
              disabled={isSaving}
              className="btn btn-primary"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "var(--space-2)",
                padding: "8px 16px",
                borderRadius: "var(--radius-sm)",
                fontFamily: "var(--font-display)",
                fontSize: "var(--text-sm)",
                fontWeight: 510,
                fontFeatureSettings: '"cv01", "ss03"',
                lineHeight: 1,
                cursor: isSaving ? "not-allowed" : "pointer",
                border: "1px solid transparent",
                background: "var(--accent)",
                color: "#ffffff",
                opacity: isSaving ? 0.45 : 1,
                transition: "background-color var(--motion-fast) var(--ease-standard)",
              }}
              onMouseEnter={(e) => {
                if (!isSaving) e.currentTarget.style.background = "var(--accent-hover)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = "var(--accent)";
              }}
            >
              {isSaving ? "Saving..." : "Save Changes"}
            </button>
          )}
        </div>

        {/* ── Profile ── */}
        {activeSection === "profile" && (
          <>
            <div style={cardStyle}>
              <h3 style={{ marginBottom: 4 }}>Profile Information</h3>
              <p className="lead" style={{ marginBottom: "var(--space-6)" }}>
                Update your personal details and public profile.
              </p>

              <div className="flex items-center gap-4 mb-6">
                <div
                  className="w-16 h-16 rounded-full flex items-center justify-center"
                  style={{ background: "rgba(255,255,255,0.06)" }}
                >
                  <User size={28} style={{ color: "var(--meta)" }} />
                </div>
                <div>
                  <button
                    className="btn btn-ghost"
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: "var(--space-2)",
                      padding: "6px 12px",
                      borderRadius: "var(--radius-sm)",
                      fontFamily: "var(--font-display)",
                      fontSize: "var(--text-xs)",
                      fontWeight: 510,
                      fontFeatureSettings: '"cv01", "ss03"',
                      lineHeight: 1,
                      cursor: "pointer",
                      border: "1px solid rgba(36,40,44,1)",
                      background: "rgba(255,255,255,0.02)",
                      color: "#e2e4e7",
                      transition: "background-color var(--motion-fast) var(--ease-standard)",
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.05)"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.02)"; }}
                  >
                    Change Avatar
                  </button>
                  <p className="text-xs" style={{ color: "var(--meta)", marginTop: 4 }}>
                    JPG, PNG or GIF. Max 2MB.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="field">
                  <label style={labelStyle}>Display Name</label>
                  <input
                    style={inputStyle}
                    value={settings.profile.name}
                    onChange={(e) => updateSetting("profile", "name", e.target.value)}
                    onFocus={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
                    onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
                  />
                </div>
                <div className="field">
                  <label style={labelStyle}>Email</label>
                  <input
                    style={inputStyle}
                    type="email"
                    value={settings.profile.email}
                    onChange={(e) => updateSetting("profile", "email", e.target.value)}
                    onFocus={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
                    onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
                  />
                </div>
                <div className="field md:col-span-2">
                  <label style={labelStyle}>Bio</label>
                  <input
                    style={inputStyle}
                    value={settings.profile.bio}
                    onChange={(e) => updateSetting("profile", "bio", e.target.value)}
                    onFocus={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
                    onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
                  />
                </div>
                <div className="field">
                  <label style={labelStyle}>Timezone</label>
                  <select
                    style={inputStyle}
                    value={settings.profile.timezone}
                    onChange={(e) => updateSetting("profile", "timezone", e.target.value)}
                    onFocus={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
                    onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
                  >
                    <option value="UTC-8">Pacific Time (UTC-8)</option>
                    <option value="UTC-5">Eastern Time (UTC-5)</option>
                    <option value="UTC+0">GMT (UTC+0)</option>
                    <option value="UTC+1">Central Europe (UTC+1)</option>
                  </select>
                </div>
              </div>
            </div>

            {/* Danger Zone */}
            <div
              style={{
                ...cardStyle,
                border: "1px solid rgba(220,38,38,0.3)",
                background: "rgba(220,38,38,0.05)",
              }}
            >
              <p
                className="text-sm font-medium mb-1"
                style={{
                  fontWeight: 510,
                  color: "var(--danger)",
                  fontFeatureSettings: '"cv01", "ss03"',
                }}
              >
                Zona de peligro
              </p>
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm" style={{ color: "var(--fg-2)" }}>
                    Delete Account
                  </p>
                  <p className="text-xs" style={{ color: "var(--meta)" }}>
                    Permanently delete your account and all data
                  </p>
                </div>
                <button
                  className="btn btn-danger"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "var(--space-2)",
                    padding: "6px 12px",
                    borderRadius: "var(--radius-sm)",
                    fontFamily: "var(--font-display)",
                    fontSize: "var(--text-xs)",
                    fontWeight: 510,
                    fontFeatureSettings: '"cv01", "ss03"',
                    lineHeight: 1,
                    cursor: "pointer",
                    border: "1px solid rgba(220,38,38,0.3)",
                    background: "rgba(220,38,38,0.15)",
                    color: "var(--danger)",
                    transition: "background-color var(--motion-fast) var(--ease-standard)",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(220,38,38,0.25)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(220,38,38,0.15)"; }}
                >
                  Delete Account
                </button>
              </div>
            </div>
          </>
        )}

        {/* ── Notifications ── */}
        {activeSection === "notifications" && (
          <div style={cardStyle}>
            <h3 style={{ marginBottom: 4 }}>Notification Preferences</h3>
            <p className="lead" style={{ marginBottom: "var(--space-6)" }}>
              Choose what updates you receive.
            </p>
            <div className="space-y-4">
              {[
                { key: "email", label: "Email Notifications", desc: "Receive updates via email" },
                { key: "push", label: "Push Notifications", desc: "Browser push notifications" },
                { key: "marketing", label: "Marketing Emails", desc: "Product updates and tips" },
                { key: "clipReady", label: "Clip Ready Alerts", desc: "When AI finishes generating clips" },
                { key: "viralAlerts", label: "Viral Alerts", desc: "When your clips are trending" },
              ].map((item) => (
                <div key={item.key} className="flex items-center justify-between">
                  <div>
                    <p className="text-sm" style={{ color: "var(--fg-2)" }}>{item.label}</p>
                    <p className="text-xs" style={{ color: "var(--meta)" }}>{item.desc}</p>
                  </div>
                  <Toggle
                    checked={settings.notifications[item.key as keyof typeof settings.notifications]}
                    onChange={(v) => updateSetting("notifications", item.key as any, v)}
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Preferences ── */}
        {activeSection === "preferences" && (
          <div style={cardStyle}>
            <h3 style={{ marginBottom: 4 }}>Appearance & Behavior</h3>
            <p className="lead" style={{ marginBottom: "var(--space-6)" }}>
              Customize your experience.
            </p>

            <div className="space-y-6">
              <div className="field">
                <label style={labelStyle}>Theme</label>
                <div className="flex gap-2">
                  {[
                    { value: "light", label: "Light", icon: Sun },
                    { value: "dark", label: "Dark", icon: Moon },
                    { value: "system", label: "System", icon: Monitor },
                  ].map(({ value, label, icon: Icon }) => (
                    <button
                      key={value}
                      onClick={() => updateSetting("preferences", "theme", value)}
                      className="flex items-center gap-1.5 px-3 py-2 rounded-md text-xs font-medium transition-all"
                      style={
                        settings.preferences.theme === value
                          ? {
                              background: "rgba(94,106,210,0.12)",
                              color: "var(--accent)",
                              border: "1px solid rgba(94,106,210,0.2)",
                            }
                          : {
                              background: "rgba(255,255,255,0.02)",
                              color: "var(--muted)",
                              border: "1px solid var(--border)",
                            }
                      }
                    >
                      <Icon size={14} />
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="field">
                <label style={labelStyle}>Language</label>
                <select
                  style={inputStyle}
                  value={settings.preferences.language}
                  onChange={(e) => updateSetting("preferences", "language", e.target.value)}
                  onFocus={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
                  onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
                >
                  <option value="en">English</option>
                  <option value="es">Español</option>
                  <option value="fr">Français</option>
                  <option value="de">Deutsch</option>
                  <option value="pt">Português</option>
                </select>
              </div>

              <div className="field">
                <label style={labelStyle}>Default Export Quality</label>
                <select
                  style={inputStyle}
                  value={settings.preferences.defaultQuality}
                  onChange={(e) => updateSetting("preferences", "defaultQuality", e.target.value)}
                  onFocus={(e) => (e.currentTarget.style.borderColor = "var(--accent)")}
                  onBlur={(e) => (e.currentTarget.style.borderColor = "var(--border)")}
                >
                  <option value="720p">720p HD</option>
                  <option value="1080p">1080p Full HD</option>
                  <option value="4K">4K Ultra HD</option>
                </select>
              </div>

              <div style={{ borderTop: "1px solid var(--border-soft)" }} />

              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm" style={{ color: "var(--fg-2)" }}>Auto-Publish</p>
                  <p className="text-xs" style={{ color: "var(--meta)" }}>Automatically publish clips when ready</p>
                </div>
                <Toggle
                  checked={settings.preferences.autoPublish}
                  onChange={(v) => updateSetting("preferences", "autoPublish", v)}
                />
              </div>

              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm" style={{ color: "var(--fg-2)" }}>ViraClip Watermark</p>
                  <p className="text-xs" style={{ color: "var(--meta)" }}>Add subtle branding to exported clips</p>
                </div>
                <Toggle
                  checked={settings.preferences.watermark}
                  onChange={(v) => updateSetting("preferences", "watermark", v)}
                />
              </div>
            </div>
          </div>
        )}

        {/* ── Integrations ── */}
        {activeSection === "integrations" && (
          <>
            <div style={cardStyle}>
              <h3 style={{ marginBottom: 4 }}>Connected Platforms</h3>
              <p className="lead" style={{ marginBottom: "var(--space-6)" }}>
                Link your social media accounts.
              </p>
              <div className="space-y-3">
                {[
                  { key: "youtube", name: "YouTube", icon: "YT" },
                  { key: "tiktok", name: "TikTok", icon: "TT" },
                  { key: "instagram", name: "Instagram", icon: "IG" },
                  { key: "notion", name: "Notion", icon: "N" },
                  { key: "slack", name: "Slack", icon: "SL" },
                ].map((platform) => {
                  const connected = settings.integrations[platform.key as keyof typeof settings.integrations];
                  return (
                    <div
                      key={platform.key}
                      className="flex items-center justify-between px-4 py-3 rounded-sm"
                      style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--border-soft)" }}
                    >
                      <div className="flex items-center gap-3">
                        <div
                          className="w-8 h-8 rounded-md flex items-center justify-center text-xs font-bold"
                          style={{ background: "rgba(255,255,255,0.06)", color: "var(--fg-2)" }}
                        >
                          {platform.icon}
                        </div>
                        <div>
                          <p className="text-sm" style={{ color: "var(--fg-2)" }}>{platform.name}</p>
                          <p className="text-xs" style={{ color: "var(--meta)" }}>
                            {connected ? (
                              <span className="flex items-center gap-1" style={{ color: "var(--success)" }}>
                                <CheckCircle2 size={10} />
                                Connected
                              </span>
                            ) : (
                              "Not connected"
                            )}
                          </p>
                        </div>
                      </div>
                      <button
                        onClick={() => updateSetting("integrations", platform.key as any, !connected)}
                        className="btn btn-ghost"
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "var(--space-2)",
                          padding: "6px 12px",
                          borderRadius: "var(--radius-sm)",
                          fontFamily: "var(--font-display)",
                          fontSize: "var(--text-xs)",
                          fontWeight: 510,
                          fontFeatureSettings: '"cv01", "ss03"',
                          lineHeight: 1,
                          cursor: "pointer",
                          border: "1px solid rgba(36,40,44,1)",
                          background: "rgba(255,255,255,0.02)",
                          color: "#e2e4e7",
                          transition: "background-color var(--motion-fast) var(--ease-standard)",
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.05)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.02)"; }}
                      >
                        {connected ? "Disconnect" : "Connect"}
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>

            <div style={cardStyle}>
              <h3 style={{ marginBottom: 4 }}>API Keys</h3>
              <p className="lead" style={{ marginBottom: "var(--space-4)" }}>
                Generate API keys for external integrations.
              </p>
              <div
                className="flex items-center justify-between px-4 py-3 rounded-sm"
                style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--border-soft)" }}
              >
                <div>
                  <p className="text-sm" style={{ color: "var(--fg-2)" }}>API Access</p>
                  <p className="text-xs" style={{ color: "var(--meta)" }}>Generate API keys for external integrations</p>
                </div>
                <button
                  className="btn btn-ghost"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "var(--space-2)",
                    padding: "6px 12px",
                    borderRadius: "var(--radius-sm)",
                    fontFamily: "var(--font-display)",
                    fontSize: "var(--text-xs)",
                    fontWeight: 510,
                    fontFeatureSettings: '"cv01", "ss03"',
                    lineHeight: 1,
                    cursor: "pointer",
                    border: "1px solid rgba(36,40,44,1)",
                    background: "rgba(255,255,255,0.02)",
                    color: "#e2e4e7",
                    transition: "background-color var(--motion-fast) var(--ease-standard)",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.05)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.02)"; }}
                >
                  <Key size={12} />
                  Manage Keys
                </button>
              </div>
            </div>
          </>
        )}

        {/* ── Privacy ── */}
        {activeSection === "privacy" && (
          <div style={cardStyle}>
            <h3 style={{ marginBottom: 4 }}>Privacy Settings</h3>
            <p className="lead" style={{ marginBottom: "var(--space-6)" }}>
              Control your privacy preferences.
            </p>
            <div className="space-y-4">
              {[
                { key: "publicProfile", label: "Public Profile", desc: "Allow others to see your profile and clips" },
                { key: "shareAnalytics", label: "Share Analytics", desc: "Contribute to platform analytics (anonymized)" },
                { key: "allowTagging", label: "Allow Tagging", desc: "Others can tag you in collaborative projects" },
              ].map((item) => (
                <div key={item.key} className="flex items-center justify-between">
                  <div>
                    <p className="text-sm" style={{ color: "var(--fg-2)" }}>{item.label}</p>
                    <p className="text-xs" style={{ color: "var(--meta)" }}>{item.desc}</p>
                  </div>
                  <Toggle
                    checked={settings.privacy[item.key as keyof typeof settings.privacy]}
                    onChange={(v) => updateSetting("privacy", item.key as any, v)}
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Billing / Plan ── */}
        {activeSection === "billing" && (
          <>
            <div style={cardStyle}>
              <h3 style={{ marginBottom: 4 }}>Subscription</h3>
              <p className="lead" style={{ marginBottom: "var(--space-6)" }}>
                Manage your plan and billing.
              </p>

              {/* Pricing grid */}
              <div className="grid grid-cols-3 gap-4 mb-6">
                {[
                  { name: "Free", price: "$0", desc: "3 clips/mes", active: false },
                  { name: "Pro", price: "$29", desc: "Clips ilimitados", active: true },
                  { name: "Enterprise", price: "$99", desc: "API + equipo", active: false },
                ].map((plan) => (
                  <div
                    key={plan.name}
                    className="flex flex-col gap-2 p-4 rounded-md"
                    style={{
                      background: "rgba(255,255,255,0.02)",
                      border: plan.active
                        ? "1px solid var(--accent)"
                        : "1px solid var(--border)",
                      boxShadow: plan.active ? "0 0 0 3px rgba(94,106,210,0.2)" : undefined,
                    }}
                  >
                    <p className="text-sm font-medium" style={{ color: "var(--fg)" }}>{plan.name}</p>
                    <p className="text-2xl font-semibold" style={{ color: "var(--fg)", fontWeight: 510, fontVariantNumeric: "tabular-nums" }}>
                      {plan.price}
                      <span className="text-sm" style={{ color: "var(--meta)" }}>/mes</span>
                    </p>
                    <p className="text-xs" style={{ color: "var(--meta)" }}>{plan.desc}</p>
                    {plan.active && (
                      <span
                        className="inline-flex self-start items-center px-2 py-0.5 rounded-full text-xs font-medium"
                        style={{
                          background: "rgba(94,106,210,0.15)",
                          color: "var(--accent)",
                          border: "1px solid rgba(94,106,210,0.35)",
                        }}
                      >
                        Actual
                      </span>
                    )}
                  </div>
                ))}
              </div>

              {/* Usage stats */}
              <div className="grid grid-cols-3 gap-4 text-center mb-6">
                {[
                  { value: "47", label: "Videos This Month" },
                  { value: "\u221e", label: "Remaining" },
                  { value: "12", label: "Days Left" },
                ].map((stat) => (
                  <div
                    key={stat.label}
                    className="p-4 rounded-sm"
                    style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--border-soft)" }}
                  >
                    <p className="text-2xl font-semibold" style={{ color: "var(--fg)", fontVariantNumeric: "tabular-nums" }}>
                      {stat.value}
                    </p>
                    <p className="text-xs" style={{ color: "var(--meta)" }}>{stat.label}</p>
                  </div>
                ))}
              </div>

              <div className="flex gap-2">
                <button
                  className="btn btn-ghost"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "var(--space-2)",
                    padding: "8px 16px",
                    borderRadius: "var(--radius-sm)",
                    fontFamily: "var(--font-display)",
                    fontSize: "var(--text-sm)",
                    fontWeight: 510,
                    fontFeatureSettings: '"cv01", "ss03"',
                    lineHeight: 1,
                    cursor: "pointer",
                    border: "1px solid rgba(36,40,44,1)",
                    background: "rgba(255,255,255,0.02)",
                    color: "#e2e4e7",
                    transition: "background-color var(--motion-fast) var(--ease-standard)",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.05)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.02)"; }}
                >
                  Change Plan
                </button>
                <button
                  className="btn btn-ghost"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "var(--space-2)",
                    padding: "8px 16px",
                    borderRadius: "var(--radius-sm)",
                    fontFamily: "var(--font-display)",
                    fontSize: "var(--text-sm)",
                    fontWeight: 510,
                    fontFeatureSettings: '"cv01", "ss03"',
                    lineHeight: 1,
                    cursor: "pointer",
                    border: "1px solid rgba(36,40,44,1)",
                    background: "rgba(255,255,255,0.02)",
                    color: "#e2e4e7",
                    transition: "background-color var(--motion-fast) var(--ease-standard)",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.05)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.02)"; }}
                >
                  Billing History
                </button>
              </div>
            </div>

            {/* Payment Method */}
            <div style={cardStyle}>
              <h3 style={{ marginBottom: 4 }}>Payment Method</h3>
              <p className="lead" style={{ marginBottom: "var(--space-4)" }}>
                Manage your payment details.
              </p>
              <div
                className="flex items-center justify-between px-4 py-3 rounded-sm"
                style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--border-soft)" }}
              >
                <div className="flex items-center gap-3">
                  <div
                    className="w-10 h-7 rounded flex items-center justify-center text-xs font-bold"
                    style={{ background: "rgba(255,255,255,0.06)", color: "var(--fg-2)" }}
                  >
                    VISA
                  </div>
                  <div>
                    <p className="text-sm" style={{ color: "var(--fg-2)" }}>{"\u2022\u2022\u2022\u2022"} 4242</p>
                    <p className="text-xs" style={{ color: "var(--meta)" }}>Expires 12/25</p>
                  </div>
                </div>
                <button
                  className="btn btn-ghost"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: "var(--space-2)",
                    padding: "6px 12px",
                    borderRadius: "var(--radius-sm)",
                    fontFamily: "var(--font-display)",
                    fontSize: "var(--text-xs)",
                    fontWeight: 510,
                    fontFeatureSettings: '"cv01", "ss03"',
                    lineHeight: 1,
                    cursor: "pointer",
                    border: "1px solid rgba(36,40,44,1)",
                    background: "rgba(255,255,255,0.02)",
                    color: "#e2e4e7",
                    transition: "background-color 0.2s ease"
                  }}
                >
                  Update
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
