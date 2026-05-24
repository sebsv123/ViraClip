"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard,
  Film,
  Settings,
  LogOut,
  Menu,
  X,
  Sun,
  Moon,
  CreditCard,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { signOut } from "@/lib/auth-client";
import { useRouter } from "next/navigation";

/* ─────────────────────────────────────────────
   Navigation config
   ───────────────────────────────────────────── */
interface NavSection {
  label: string;
  items: NavItem[];
}

interface NavItem {
  icon: React.ElementType;
  label: string;
  href: string;
}

const navSections: NavSection[] = [
  {
    label: "Menu",
    items: [
      { icon: LayoutDashboard, label: "Dashboard", href: "/dashboard" },
      { icon: Film, label: "My Clips", href: "/list" },
    ],
  },
  {
    label: "Account",
    items: [
      { icon: CreditCard, label: "Billing", href: "/dashboard/settings" },
      { icon: Settings, label: "Settings", href: "/dashboard/settings" },
    ],
  },
];

/* ─────────────────────────────────────────────
   Inline SVG logo — geometric play + clip shape
   ───────────────────────────────────────────── */
function ViraClipLogo({ collapsed }: { collapsed?: boolean }) {
  return (
    <svg
      width={collapsed ? 24 : 28}
      height={collapsed ? 24 : 28}
      viewBox="0 0 28 28"
      fill="none"
      aria-hidden="true"
    >
      {/* Clip / rounded-rect body */}
      <rect
        x="2"
        y="4"
        width="24"
        height="20"
        rx="5"
        stroke="#5e6ad2"
        strokeWidth="2"
        fill="none"
      />
      {/* Play triangle */}
      <path d="M11 10.5v7l6-3.5-6-3.5z" fill="#5e6ad2" />
    </svg>
  );
}

/* ─────────────────────────────────────────────
   Props
   ───────────────────────────────────────────── */
interface AppShellProps {
  children: React.ReactNode;
  user?: {
    name?: string | null;
    email?: string | null;
    image?: string | null;
  };
  credits?: number;
}

/* ─────────────────────────────────────────────
   Component
   ───────────────────────────────────────────── */
export function AppShell({ children, user, credits = 0 }: AppShellProps) {
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isDark, setIsDark] = useState(true);
  const pathname = usePathname();
  const router = useRouter();

  /* ── Dark mode: init from localStorage, default dark ── */
  useEffect(() => {
    const stored = localStorage.getItem("vc-theme");
    const dark = stored ? stored === "dark" : true;
    setIsDark(dark);
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  }, []);

  const toggleTheme = useCallback(() => {
    setIsDark((prev) => {
      const next = !prev;
      const theme = next ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", theme);
      localStorage.setItem("vc-theme", theme);
      return next;
    });
  }, []);

  const initials = user?.name
    ? user.name.split(" ").map((n) => n[0]).join("").slice(0, 2).toUpperCase()
    : user?.email?.[0]?.toUpperCase() ?? "?";

  const handleSignOut = async () => {
    await signOut();
    router.push("/sign-in");
  };

  /* ── Build breadcrumb from pathname ── */
  const segments = pathname.split("/").filter(Boolean);
  const breadcrumb = segments
    .map((s) => s.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()))
    .join(" / ");

  /* ── Shared nav item renderer ── */
  const renderNavItem = (item: NavItem, closeMobile?: () => void) => {
    const Icon = item.icon;
    const isActive = pathname === item.href;

    return (
      <Link
        key={item.label}
        href={item.href}
        onClick={closeMobile}
        className={cn(
          "flex items-center gap-2 h-8 px-3 rounded-sm transition-all",
          "text-sm",
          isActive
            ? "bg-[rgba(94,106,210,0.15)] text-[var(--fg)]"
            : "text-[var(--fg-2)] hover:bg-[rgba(255,255,255,0.06)]"
        )}
        style={{ transitionDuration: "var(--motion-fast)", transitionTimingFunction: "var(--ease-standard)" }}
      >
        <Icon
          className="shrink-0"
          size={16}
          style={{ color: isActive ? "var(--accent)" : undefined }}
        />
        <span>{item.label}</span>
      </Link>
    );
  };

  /* ── Sidebar content (shared between desktop & mobile) ── */
  const sidebarContent = (closeMobile?: () => void) => (
    <>
      {/* Logo */}
      <div className="flex items-center gap-2 px-3 py-4">
        <ViraClipLogo />
        <span className="text-base font-semibold" style={{ color: "var(--fg)" }}>
          ViraClip
        </span>
      </div>

      {/* Navigation sections */}
      <nav className="flex-1 px-2 py-2 space-y-4">
        {navSections.map((section) => (
          <div key={section.label}>
            <p
              className="px-3 py-1 text-xs uppercase tracking-wider"
              style={{
                color: "var(--muted)",
                letterSpacing: "0.08em",
              }}
            >
              {section.label}
            </p>
            <div className="mt-1 space-y-0.5">
              {section.items.map((item) => renderNavItem(item, closeMobile))}
            </div>
          </div>
        ))}
      </nav>

      {/* Bottom: user + sign out */}
      <div className="px-2 py-3 space-y-2" style={{ borderTop: "1px solid var(--border)" }}>
        {user && (
          <div
            className="flex items-center gap-2 px-3 py-2 rounded-sm"
            style={{ background: "var(--surface)" }}
          >
            <div
              className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold shrink-0"
              style={{ background: "var(--surface)", color: "var(--fg-2)" }}
            >
              {initials}
            </div>
            <div className="min-w-0 flex-1">
              <p
                className="text-sm font-medium truncate"
                style={{ color: "var(--fg)" }}
              >
                {user.name || "User"}
              </p>
              <p
                className="text-xs truncate"
                style={{ color: "var(--meta)" }}
              >
                {credits} credits
              </p>
            </div>
          </div>
        )}
        <button
          onClick={handleSignOut}
          className="flex items-center gap-2 w-full h-8 px-3 rounded-sm text-sm transition-all"
          style={{
            color: "var(--fg-2)",
            transitionDuration: "var(--motion-fast)",
            transitionTimingFunction: "var(--ease-standard)",
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.06)")}
          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
        >
          <LogOut size={16} />
          <span>Sign Out</span>
        </button>
      </div>
    </>
  );

  return (
    <div
      className="min-h-screen flex"
      style={{ background: "var(--bg)" }}
    >
      {/* ── Desktop Sidebar ── */}
      <aside
        className="hidden lg:flex flex-col shrink-0"
        style={{
          width: 220,
          borderRight: "1px solid var(--border)",
          background: "var(--bg)",
        }}
      >
        {sidebarContent()}
      </aside>

      {/* ── Main Column ── */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* ── Sticky Header ── */}
        <header
          className="sticky top-0 z-40 flex items-center justify-between h-12 px-4 lg:px-6"
          style={{
            background: "var(--bg)",
            borderBottom: "1px solid var(--border)",
          }}
        >
          {/* Left: mobile hamburger + breadcrumb */}
          <div className="flex items-center gap-3">
            <button
              onClick={() => setIsMobileMenuOpen(true)}
              className="lg:hidden p-1.5 rounded-sm"
              style={{ color: "var(--fg-2)" }}
              onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.06)")}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <Menu size={16} />
            </button>
            <span style={{ color: "var(--fg-2)", fontSize: "var(--text-sm)" }}>
              {breadcrumb || "Dashboard"}
            </span>
          </div>

          {/* Right: theme toggle + avatar */}
          <div className="flex items-center gap-3">
            <div className="relative group">
              <button
                onClick={toggleTheme}
                className="p-1.5 rounded-sm transition-all"
                style={{
                  color: "var(--fg-2)",
                  transitionDuration: "var(--motion-fast)",
                  transitionTimingFunction: "var(--ease-standard)",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.06)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                aria-label={isDark ? "Cambiar a modo claro" : "Cambiar a modo oscuro"}
              >
                {isDark ? <Moon size={16} /> : <Sun size={16} />}
              </button>
              {/* Tooltip */}
              <div
                className="absolute top-full left-1/2 -translate-x-1/2 mt-1.5 px-2 py-1 rounded-sm text-xs whitespace-nowrap pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity"
                style={{
                  background: "var(--surface)",
                  color: "var(--fg-2)",
                  boxShadow: "var(--elev-raised)",
                }}
              >
                {isDark ? "Cambiar a modo claro" : "Cambiar a modo oscuro"}
              </div>
            </div>

            <div
              className="w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold"
              style={{ background: "var(--surface)", color: "var(--fg-2)" }}
            >
              {initials}
            </div>
          </div>
        </header>

        {/* ── Page Content ── */}
        <main className="flex-1 overflow-auto">{children}</main>
      </div>

      {/* ── Mobile Drawer ── */}
      <AnimatePresence>
        {isMobileMenuOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-50 lg:hidden"
              style={{ background: "rgba(0,0,0,0.6)" }}
              onClick={() => setIsMobileMenuOpen(false)}
            />
            <motion.aside
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "spring", damping: 25, stiffness: 200 }}
              className="fixed left-0 top-0 bottom-0 z-50 flex flex-col lg:hidden"
              style={{
                width: 220,
                background: "var(--bg)",
                borderRight: "1px solid var(--border)",
              }}
            >
              <div className="flex items-center justify-between px-3 py-4">
                <ViraClipLogo />
                <button
                  onClick={() => setIsMobileMenuOpen(false)}
                  className="p-1.5 rounded-sm"
                  style={{ color: "var(--fg-2)" }}
                >
                  <X size={16} />
                </button>
              </div>
              {sidebarContent(() => setIsMobileMenuOpen(false))}
            </motion.aside>
          </>
        )}
      </AnimatePresence>
    </div>
  );
}
