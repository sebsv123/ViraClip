"use client";

import type { ReactNode, ButtonHTMLAttributes } from "react";

/* ─────────────────────────────────────────────
   Button — Linear App Design System (exact from repo)
   Source: https://github.com/nexu-io/open-design/blob/main/design-systems/linear-app/components.html
   ───────────────────────────────────────────── */

type ButtonVariant = "primary" | "ghost" | "danger";
type ButtonSize = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  loading?: boolean;
}

/* ── Inline SVG spinner (no external lib) ── */
function Spinner() {
  return (
    <svg
      width={14}
      height={14}
      viewBox="0 0 14 14"
      fill="none"
      style={{ animation: "spin 0.8s linear infinite" }}
    >
      <circle
        cx="7"
        cy="7"
        r="5.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeDasharray="25"
        strokeDashoffset="10"
        strokeLinecap="round"
        opacity={0.4}
      />
    </svg>
  );
}

const variantStyles: Record<ButtonVariant, React.CSSProperties> = {
  primary: {
    background: "var(--accent)",
    color: "#ffffff",
  },
  ghost: {
    background: "rgba(255,255,255,0.02)",
    color: "#e2e4e7",
    borderColor: "rgba(36,40,44,1)",
  },
  danger: {
    background: "rgba(220,38,38,0.15)",
    color: "var(--danger)",
    border: "1px solid rgba(220,38,38,0.3)",
  },
};

const sizeStyles: Record<ButtonSize, React.CSSProperties> = {
  sm: {
    padding: "6px 12px",
    fontSize: "var(--text-xs)",
  },
  md: {
    padding: "8px 16px",
    fontSize: "var(--text-sm)",
  },
};

export function Button({
  variant = "primary",
  size = "md",
  icon,
  loading = false,
  disabled = false,
  children,
  style,
  onMouseEnter,
  onMouseLeave,
  ...rest
}: ButtonProps) {
  const baseStyle: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: "var(--space-2)",
    borderRadius: "var(--radius-sm)",
    fontFamily: "var(--font-display)",
    fontWeight: 510,
    fontFeatureSettings: '"cv01", "ss03"',
    lineHeight: 1,
    cursor: disabled || loading ? "not-allowed" : "pointer",
    border: "1px solid transparent",
    transition: [
      "background-color var(--motion-fast) var(--ease-standard)",
      "color var(--motion-fast) var(--ease-standard)",
    ].join(","),
    opacity: disabled ? 0.45 : 1,
    ...variantStyles[variant],
    ...sizeStyles[size],
    ...style,
  };

  const handleMouseEnter = (e: React.MouseEvent<HTMLButtonElement>) => {
    if (disabled || loading) return;
    if (variant === "primary") e.currentTarget.style.background = "var(--accent-hover)";
    else if (variant === "ghost") e.currentTarget.style.background = "rgba(255,255,255,0.05)";
    else if (variant === "danger") e.currentTarget.style.background = "rgba(220,38,38,0.25)";
    onMouseEnter?.(e);
  };

  const handleMouseLeave = (e: React.MouseEvent<HTMLButtonElement>) => {
    if (disabled || loading) return;
    e.currentTarget.style.background = (variantStyles[variant].background as string) || "";
    onMouseLeave?.(e);
  };

  return (
    <button
      style={baseStyle}
      disabled={disabled || loading}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      {...rest}
    >
      {loading ? <Spinner /> : icon}
      {children}
    </button>
  );
}
