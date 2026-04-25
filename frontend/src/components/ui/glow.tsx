"use client";

import { cn } from "@/lib/utils";

interface GlowProps {
  children: React.ReactNode;
  className?: string;
  size?: "sm" | "md" | "lg";
  color?: "violet" | "fuchsia" | "mixed";
}

export function Glow({ 
  children, 
  className,
  size = "md",
  color = "mixed"
}: GlowProps) {
  const sizes = {
    sm: "blur-[60px]",
    md: "blur-[100px]",
    lg: "blur-[150px]",
  };

  const colors = {
    violet: "from-violet-600/40 to-violet-400/20",
    fuchsia: "from-fuchsia-600/40 to-fuchsia-400/20",
    mixed: "from-violet-600/30 via-fuchsia-500/30 to-fuchsia-400/20",
  };

  return (
    <div className={cn("relative", className)}>
      <div 
        className={cn(
          "absolute -inset-4 rounded-full bg-gradient-to-r opacity-50",
          sizes[size],
          colors[color]
        )}
      />
      <div className="relative z-10">{children}</div>
    </div>
  );
}
