"use client";

import { cn } from "@/lib/utils";

interface MarqueeProps {
  children: React.ReactNode;
  className?: string;
  speed?: "slow" | "normal" | "fast";
  pauseOnHover?: boolean;
  direction?: "left" | "right";
}

export function Marquee({ 
  children, 
  className,
  speed = "normal",
  pauseOnHover = false,
  direction = "left"
}: MarqueeProps) {
  const speeds = {
    slow: "40s",
    normal: "25s",
    fast: "15s",
  };

  return (
    <div 
      className={cn(
        "flex overflow-hidden",
        pauseOnHover && "[&:hover_.marquee-content]:pause",
        className
      )}
    >
      <div 
        className="marquee-content flex shrink-0 animate-marquee"
        style={{ 
          animationDuration: speeds[speed],
          animationDirection: direction === "right" ? "reverse" : "normal"
        }}
      >
        {children}
      </div>
      <div 
        className="marquee-content flex shrink-0 animate-marquee"
        style={{ 
          animationDuration: speeds[speed],
          animationDirection: direction === "right" ? "reverse" : "normal"
        }}
        aria-hidden
      >
        {children}
      </div>
    </div>
  );
}
