"use client";

/* ─────────────────────────────────────────────
   VideoJobRow — Linear App Design System (exact from repo)
   Adapted from the issue-tracker pattern in components.html
   Source: https://github.com/nexu-io/open-design/blob/main/design-systems/linear-app/components.html
   ───────────────────────────────────────────── */

type JobStatus = "done" | "processing" | "pending" | "error";

interface VideoJobRowProps {
  status: JobStatus;
  label: string;
  onClick?: () => void;
}

const statusConfig: Record<JobStatus, { dotStyle: React.CSSProperties; textColor: string }> = {
  done: {
    dotStyle: {
      width: 8,
      height: 8,
      borderRadius: "50%",
      background: "#27a644",
      flexShrink: 0,
    },
    textColor: "var(--fg-2)",
  },
  processing: {
    dotStyle: {
      width: 8,
      height: 8,
      borderRadius: "50%",
      background: "var(--accent)",
      flexShrink: 0,
      animation: "pulse 1.8s ease-in-out infinite",
    },
    textColor: "var(--fg)",
  },
  pending: {
    dotStyle: {
      width: 8,
      height: 8,
      borderRadius: 2,
      background: "rgba(255,255,255,0.1)",
      flexShrink: 0,
    },
    textColor: "var(--muted)",
  },
  error: {
    dotStyle: {
      width: 8,
      height: 8,
      borderRadius: "50%",
      background: "var(--danger)",
      flexShrink: 0,
    },
    textColor: "var(--danger)",
  },
};

export function VideoJobRow({ status, label, onClick }: VideoJobRowProps) {
  const config = statusConfig[status];

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--space-3)",
        height: 44,
        fontSize: "var(--text-sm)",
        color: config.textColor,
        fontFeatureSettings: '"cv01", "ss03"',
        cursor: onClick ? "pointer" : undefined,
        transition: "background-color var(--motion-fast) var(--ease-standard)",
        borderRadius: "var(--radius-sm)",
        padding: "0 var(--space-2)",
      }}
      onClick={onClick}
      onMouseEnter={(e) => {
        if (onClick) e.currentTarget.style.background = "rgba(255,255,255,0.04)";
      }}
      onMouseLeave={(e) => {
        if (onClick) e.currentTarget.style.background = "transparent";
      }}
    >
      <span style={config.dotStyle} />
      <span>{label}</span>
    </div>
  );
}
