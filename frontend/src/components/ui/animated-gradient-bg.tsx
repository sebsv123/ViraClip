"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

interface AnimatedGradientBgProps {
  className?: string;
  variant?: "aurora" | "mesh" | "radial";
}

export function AnimatedGradientBg({ 
  className,
  variant = "aurora"
}: AnimatedGradientBgProps) {
  const variants = {
    aurora: (
      <>
        <div className="absolute top-0 left-0 w-[500px] h-[500px] bg-violet-600/20 rounded-full blur-[120px] animate-pulse" />
        <div className="absolute top-[20%] right-0 w-[400px] h-[400px] bg-fuchsia-600/15 rounded-full blur-[100px] animate-pulse delay-1000" />
        <div className="absolute bottom-0 left-[20%] w-[300px] h-[300px] bg-fuchsia-500/10 rounded-full blur-[80px] animate-pulse delay-2000" />
      </>
    ),
    mesh: (
      <>
        <div className="absolute inset-0 bg-[radial-gradient(at_0%_0%,_rgba(139,92,246,0.15)_0px,_transparent_50%),radial-gradient(at_100%_0%,_rgba(192,38,211,0.1)_0px,_transparent_50%),radial-gradient(at_100%_100%,_rgba(236,72,153,0.08)_0px,_transparent_50%),radial-gradient(at_0%_100%,_rgba(139,92,246,0.1)_0px,_transparent_50%)]" />
        <motion.div 
          className="absolute inset-0 bg-gradient-to-br from-violet-500/10 via-transparent to-fuchsia-500/10"
          animate={{ 
            backgroundPosition: ["0% 0%", "100% 100%", "0% 0%"]
          }}
          transition={{ duration: 15, repeat: Infinity, ease: "linear" }}
        />
      </>
    ),
    radial: (
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,_rgba(139,92,246,0.12)_0%,_transparent_50%)]" />
    ),
  };

  return (
    <div className={cn("fixed inset-0 -z-10 overflow-hidden", className)}>
      {variants[variant]}
    </div>
  );
}
