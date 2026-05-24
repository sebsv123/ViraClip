"use client";

/* ─────────────────────────────────────────────
   Skeleton — Linear App Design System
   Luminance stepping, no shimmer colors
   ───────────────────────────────────────────── */

interface SkeletonProps {
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Base skeleton block. Apply `.skeleton` class from skeleton.css.
 */
export function Skeleton({ className, style }: SkeletonProps) {
  return (
    <div
      className={["skeleton", className].filter(Boolean).join(" ")}
      style={style}
      aria-hidden="true"
    />
  );
}

/* ── Variants ── */

interface SkeletonTextProps {
  width?: string | number;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Text line skeleton. Default height 14px, full width.
 * Last line of a block should get width="60%".
 */
export function SkeletonText({ width = "100%", className, style }: SkeletonTextProps) {
  return (
    <Skeleton
      className={className}
      style={{
        height: 14,
        width,
        marginBottom: "var(--space-2)",
        ...style,
      }}
    />
  );
}

interface SkeletonHeadingProps {
  width?: string | number;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Heading skeleton. Default height 20px, width 40%.
 */
export function SkeletonHeading({ width = "40%", className, style }: SkeletonHeadingProps) {
  return (
    <Skeleton
      className={className}
      style={{
        height: 20,
        width,
        marginBottom: "var(--space-3)",
        ...style,
      }}
    />
  );
}

interface SkeletonAvatarProps {
  size?: number;
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Avatar skeleton. Default 28x28, circular.
 */
export function SkeletonAvatar({ size = 28, className, style }: SkeletonAvatarProps) {
  return (
    <Skeleton
      className={className}
      style={{
        width: size,
        height: size,
        borderRadius: "50%",
        ...style,
      }}
    />
  );
}

interface SkeletonCardProps {
  className?: string;
  style?: React.CSSProperties;
}

/**
 * Clip thumbnail skeleton. aspect-ratio 9/16, radius-md.
 */
export function SkeletonCard({ className, style }: SkeletonCardProps) {
  return (
    <Skeleton
      className={className}
      style={{
        width: "100%",
        aspectRatio: "9/16",
        borderRadius: "var(--radius-md)",
        ...style,
      }}
    />
  );
}

interface SkeletonKpiProps {
  className?: string;
  style?: React.CSSProperties;
}

/**
 * KPI card skeleton. height 80px, radius-md.
 */
export function SkeletonKpi({ className, style }: SkeletonKpiProps) {
  return (
    <Skeleton
      className={className}
      style={{
        height: 80,
        width: "100%",
        borderRadius: "var(--radius-md)",
        ...style,
      }}
    />
  );
}

/* ── Composed layouts ── */

/**
 * Full dashboard skeleton: 4 KPI cards + 6 table rows.
 */
export function SkeletonDashboard() {
  return (
    <div aria-label="Loading dashboard" role="status">
      {/* KPI row */}
      <div
        className="grid gap-4 mb-10"
        style={{
          gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
        }}
      >
        <SkeletonKpi />
        <SkeletonKpi />
        <SkeletonKpi />
        <SkeletonKpi />
      </div>

      {/* Table rows */}
      <div
        className="rounded-lg overflow-hidden p-5"
        style={{
          background: "var(--surface)",
          boxShadow: "var(--elev-ring)",
        }}
      >
        {/* Table header */}
        <div className="flex items-center gap-4 mb-6">
          <SkeletonHeading width={120} style={{ marginBottom: 0 }} />
          <SkeletonText width={60} style={{ marginBottom: 0 }} />
          <SkeletonText width={80} style={{ marginBottom: 0 }} />
        </div>

        {/* 6 table rows */}
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="flex items-center gap-4 py-3"
            style={{ borderTop: "1px solid var(--border-soft)" }}
          >
            <SkeletonAvatar />
            <div className="flex-1 grid grid-cols-3 gap-4">
              <SkeletonText width="80%" />
              <SkeletonText width="60%" />
              <SkeletonText width="40%" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
