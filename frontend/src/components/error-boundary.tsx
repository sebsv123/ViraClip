"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";

/* ─────────────────────────────────────────────
   ErrorBoundary — Linear App Design System
   EmptyState pattern, no stack traces visible
   ───────────────────────────────────────────── */

export function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Error caught by error boundary:", error);
  }, [error]);

  return (
    <div
      className="flex flex-col items-center text-center"
      style={{
        minHeight: "100dvh",
        background: "var(--bg)",
        justifyContent: "center",
        padding: "var(--space-8)",
        gap: "var(--space-3)",
      }}
    >
      {/* Icon wrapper */}
      <div
        className="grid place-items-center"
        style={{
          width: 64,
          height: 64,
          borderRadius: "var(--radius-lg)",
          background: "rgba(220,38,38,0.1)",
          boxShadow: "var(--elev-ring)",
        }}
      >
        <AlertTriangle size={36} style={{ color: "var(--danger)" }} />
      </div>

      {/* Title */}
      <p
        className="font-medium"
        style={{
          fontSize: "var(--text-base)",
          fontWeight: 510,
          color: "var(--fg)",
          fontFeatureSettings: '"cv01", "ss03"',
        }}
      >
        Algo sali\u00f3 mal
      </p>

      {/* Description */}
      <p
        className="text-sm"
        style={{
          color: "var(--muted)",
          maxWidth: "36ch",
          lineHeight: "var(--leading-body)",
          fontFeatureSettings: '"cv01", "ss03"',
        }}
      >
        Ocurri\u00f3 un error inesperado. Intenta recargar la p\u00e1gina.
      </p>

      {/* Action */}
      <button
        onClick={reset}
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
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "rgba(255,255,255,0.05)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "rgba(255,255,255,0.02)";
        }}
      >
        Recargar p\u00e1gina
      </button>
    </div>
  );
}

/* ── Global error boundary for root level ── */
export function GlobalError({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="en" data-theme="dark">
      <body style={{ margin: 0 }}>
        <ErrorBoundary error={error} reset={reset} />
      </body>
    </html>
  );
}
