"use client";

import type { ReactNode } from "react";

/* ─────────────────────────────────────────────
   Badge (Pill) — Linear App Design System (exact from repo)
   Source: https://github.com/nexu-io/open-design/blob/main/design-systems/linear-app/components.html
   ───────────────────────────────────────────── */

type BadgeVariant = "neutral" | "processing" | "done" | "error" | "active";

interface BadgeProps {
  variant?: BadgeVariant;
  dot?: boolean;
  children: ReactNode;
}

const variantStyles: Record<BadgeVariant, React.CSSProperties> = {
  neutral: {
    border: "1px solid #23252a",
    color: "var(--fg-2)",
    background: "transparent",
  },
  processing: {
    background: "rgba(234,179,8,0.15)",
    color: "var(--warn)",
    border: "1px solid rgba(234,179,8,0.3)",
  },
  done: {
    background: "rgba(39,166,68,0.15)",
    color: "var(--success)",
    border: "1px solid rgba(39,166,68,0.3)",
  },
  error: {
    background: "rgba(220,38,38,0.15)",
    color: "var(--danger)",
    border: "1px solid rgba(220,38,38,0.3)",
  },
  active: {
    background: "rgba(94,106,210,0.15)",
    color: "var(--accent)",
    border: "1px solid rgba(94,106,210,0.35)",
  },
};

const dotColors: Record<BadgeVariant, string> = {
  neutral: "var(--fg-2)",
  processing: "var(--warn)",
  done: "var(--success)",
  error: "var(--danger)",
  active: "var(--accent)",
};

export function Badge({ variant = "neutral", dot = false, children }: BadgeProps) {
  return (
    <span
      className="inline-flex items-center"
      style={{
        padding: "0 10px 0 5px",
        borderRadius: "var(--radius-pill)",
        fontSize: "var(--text-xs)",
        fontWeight: 510,
        lineHeight: 1.8,
        fontFeatureSettings: '"cv01", "ss03"',
        ...variantStyles[variant],
      }}
    >
      {dot && (
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: dotColors[variant],
            marginRight: 6,
            flexShrink: 0,
          }}
        />
      )}
      {children}
    </span>
  );
}
