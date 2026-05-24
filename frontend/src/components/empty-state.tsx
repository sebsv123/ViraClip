"use client";

import type { LucideIcon } from "lucide-react";

/* ─────────────────────────────────────────────
   EmptyState — Linear App Design System
   ───────────────────────────────────────────── */

interface EmptyStateAction {
  label: string;
  onClick: () => void;
}

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: EmptyStateAction;
}

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div
      className="flex flex-col items-center text-center"
      style={{
        padding: "var(--space-12) var(--space-8)",
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
          background: "rgba(255,255,255,0.04)",
          boxShadow: "var(--elev-ring)",
        }}
      >
        <Icon size={36} style={{ color: "var(--muted)" }} />
      </div>

      {/* Title */}
      <p
        className="font-medium"
        style={{
          fontSize: "var(--text-base)",
          color: "var(--fg)",
        }}
      >
        {title}
      </p>

      {/* Description */}
      <p
        className="text-sm"
        style={{
          color: "var(--muted)",
          maxWidth: "36ch",
          lineHeight: "var(--leading-body)",
        }}
      >
        {description}
      </p>

      {/* Action button */}
      {action && (
        <button
          onClick={action.onClick}
          className="font-medium transition-all"
          style={{
            height: 32,
            padding: "0 var(--space-4)",
            background: "var(--accent)",
            borderRadius: "var(--radius-sm)",
            fontSize: "var(--text-sm)",
            color: "#fff",
          }}
          onMouseEnter={(e) =>
            (e.currentTarget.style.background = "var(--accent-hover)")
          }
          onMouseLeave={(e) =>
            (e.currentTarget.style.background = "var(--accent)")
          }
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
