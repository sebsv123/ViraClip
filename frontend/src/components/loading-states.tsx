"use client";

/* ─────────────────────────────────────────────
   Loading States — Linear App Design System
   Shimmer: luminance stepping, no shimmer colors
   ───────────────────────────────────────────── */

/* ── LoadingSpinner ── */
export function LoadingSpinner({ size = 20 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      style={{ animation: "spin 0.8s linear infinite" }}
    >
      <circle
        cx="10"
        cy="10"
        r="8"
        stroke="var(--accent)"
        strokeWidth="2"
        strokeDasharray="38"
        strokeDashoffset="12"
        strokeLinecap="round"
        opacity={0.6}
      />
    </svg>
  );
}

/* ── LoadingBar ── */
export function LoadingBar() {
  return (
    <div
      style={{
        width: "100%",
        height: 3,
        background: "rgba(255,255,255,0.06)",
        borderRadius: 2,
        overflow: "hidden",
      }}
    >
      <div
        style={{
          width: "30%",
          height: "100%",
          background: "var(--accent)",
          borderRadius: 2,
          animation: "loadingBar 1.2s ease-in-out infinite",
        }}
      />
    </div>
  );
}

/* ── LoadingPage ── */
export function LoadingPage({ message = "Cargando..." }: { message?: string }) {
  return (
    <div
      className="flex flex-col items-center justify-center"
      style={{
        minHeight: "100dvh",
        background: "var(--bg)",
        gap: "var(--space-3)",
      }}
    >
      <LoadingSpinner size={24} />
      <span
        style={{
          fontSize: "var(--text-sm)",
          color: "var(--muted)",
          fontFeatureSettings: '"cv01", "ss03"',
        }}
      >
        {message}
      </span>
    </div>
  );
}
