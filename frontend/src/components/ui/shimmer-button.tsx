"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

interface ShimmerButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  children: React.ReactNode;
  className?: string;
  variant?: "default" | "secondary" | "outline";
}

export function ShimmerButton({ 
  children, 
  className,
  variant = "default",
  ...props 
}: ShimmerButtonProps) {
  const sizes = {
    sm: "px-3 sm:px-4 py-2 text-xs sm:text-sm",
    md: "px-4 sm:px-6 py-2.5 sm:py-3 text-sm sm:text-base",
    lg: "px-6 sm:px-8 py-3 sm:py-4 text-base sm:text-lg",
  };

  const baseStyles = `relative overflow-hidden ${sizes.md} transition-all duration-300 touch-manipulation`;
  
  const variants = {
    default: "bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white hover:from-violet-500 hover:to-fuchsia-500",
    secondary: "bg-white/10 text-white hover:bg-white/20 border border-white/20",
    outline: "border border-violet-500/50 text-violet-400 hover:bg-violet-500/10 hover:border-violet-500",
  };

  return (
    <motion.button
      className={cn(baseStyles, variants[variant], className)}
      whileHover={{ scale: 1.02 }}
      whileTap={{ scale: 0.98 }}
      {...props}
    >
      <span className="relative z-10 flex items-center justify-center gap-2">
        {children}
      </span>
      {variant === "default" && (
        <motion.span
          className="absolute inset-0 -translate-x-full bg-gradient-to-r from-transparent via-white/20 to-transparent"
          animate={{ translateX: ["-100%", "100%"] }}
          transition={{ duration: 2, repeat: Infinity, repeatDelay: 1 }}
        />
      )}
    </motion.button>
  );
}
