"use client";

import { useRef, useCallback } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

interface MagicCardProps {
  children: React.ReactNode;
  className?: string;
}

export function MagicCard({ children, className }: MagicCardProps) {
  const ref = useRef<HTMLDivElement>(null);
  const glowRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number>(0);

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLDivElement>) => {
    if (!ref.current || !glowRef.current) return;

    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => {
      if (!ref.current || !glowRef.current) return;
      const rect = ref.current.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      glowRef.current.style.background = `radial-gradient(400px circle at ${x}px ${y}px, rgba(139, 92, 246, 0.15), transparent 40%)`;
    });
  }, []);

  const handleMouseEnter = useCallback(() => {
    if (glowRef.current) glowRef.current.style.opacity = "1";
  }, []);

  const handleMouseLeave = useCallback(() => {
    if (glowRef.current) glowRef.current.style.opacity = "0";
  }, []);

  return (
    <motion.div
      ref={ref}
      className={cn(
        "relative overflow-hidden rounded-2xl border border-white/10 bg-white/[0.02] p-6",
        className
      )}
      onMouseMove={handleMouseMove}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      whileHover={{ y: -2 }}
      transition={{ duration: 0.3 }}
    >
      <div
        ref={glowRef}
        className="pointer-events-none absolute -inset-px rounded-2xl opacity-0 transition-opacity duration-300"
      />
      <div className="relative z-10">{children}</div>
    </motion.div>
  );
}
