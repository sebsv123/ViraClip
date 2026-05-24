"use client";

import type { ReactNode, ElementType } from "react";

/* ─────────────────────────────────────────────
   Card — Linear App Design System (exact from repo)
   Source: https://github.com/nexu-io/open-design/blob/main/design-systems/linear-app/components.html
   ───────────────────────────────────────────── */

type CardVariant = "default" | "raised" | "ghost";
type CardPadding = "sm" | "md" | "lg";

interface CardProps {
  variant?: CardVariant;
  padding?: CardPadding;
  as?: ElementType;
  onClick?: () => void;
  children: ReactNode;
  style?: React.CSSProperties;
}

const variantStyles: Record<CardVariant, React.CSSProperties> = {
  default: {
    background: "rgba(255,255,255,0.02)",
    border: "1px solid var(--border)",
  },
  raised: {
    background: "rgba(255,255,255,0.02)",
    border: "1px solid var(--border)",
    boxShadow: "var(--elev-raised)",
  },
  ghost: {
    background: "transparent",
    border: "1px solid var(--border)",
  },
};

const paddingStyles: Record<CardPadding, React.CSSProperties> = {
  sm: { padding: "var(--space-4)" },
  md: { padding: "var(--space-6)" },
  lg: { padding: "var(--space-8)" },
};

export function Card({
  variant = "default",
  padding = "md",
  as: Tag = "div",
  onClick,
  children,
  style,
}: CardProps) {
  const baseStyle: React.CSSProperties = {
    borderRadius: "var(--radius-md)",
    transition: "background-color var(--motion-base) var(--ease-standard)",
    fontFeatureSettings: '"cv01", "ss03"',
    ...variantStyles[variant],
    ...paddingStyles[padding],
    ...(onClick ? { cursor: "pointer" } : {}),
    ...style,
  };

  const handleMouseEnter = (e: React.MouseEvent<HTMLElement>) => {
    if (!onClick) return;
    e.currentTarget.style.background = "rgba(255,255,255,0.04)";
  };

  const handleMouseLeave = (e: React.MouseEvent<HTMLElement>) => {
    if (!onClick) return;
    e.currentTarget.style.background = variantStyles[variant].background as string || "rgba(255,255,255,0.02)";
  };

  return (
    <Tag
      style={baseStyle}
      onClick={onClick}
      onMouseEnter={onClick ? handleMouseEnter : undefined}
      onMouseLeave={onClick ? handleMouseLeave : undefined}
    >
      {children}
    </Tag>
  );
}
