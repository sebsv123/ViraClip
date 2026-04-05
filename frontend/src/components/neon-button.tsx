"use client";

import { cn } from "@/lib/utils";
import { ReactNode } from "react";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "accent" | "ghost" | "outline";
  size?: "sm" | "md" | "lg";
  children: ReactNode;
  glowing?: boolean;
}

export function NeonButton({
  variant = "primary",
  size = "md",
  children,
  className,
  glowing = false,
  ...props
}: ButtonProps) {
  const baseStyles = "relative inline-flex items-center justify-center font-semibold transition-all duration-300 ease-out rounded-xl overflow-hidden group disabled:opacity-50 disabled:cursor-not-allowed";
  
  const variants = {
    primary: "bg-[hsl(180,100%,50%)] text-[hsl(220,25%,4%)] hover:bg-[hsl(180,100%,45%)] hover:shadow-[0_0_30px_-5px_hsl(180,100%,50%,0.5)]",
    secondary: "bg-[hsl(270,100%,65%)] text-white hover:bg-[hsl(270,100%,60%)] hover:shadow-[0_0_30px_-5px_hsl(270,100%,65%,0.5)]",
    accent: "bg-[hsl(330,100%,60%)] text-white hover:bg-[hsl(330,100%,55%)] hover:shadow-[0_0_30px_-5px_hsl(330,100%,60%,0.5)]",
    ghost: "bg-transparent text-[hsl(0,0%,98%)] hover:bg-white/10 border border-[hsl(220,15%,25%)]",
    outline: "bg-transparent border-2 border-[hsl(180,100%,50%)] text-[hsl(180,100%,50%)] hover:bg-[hsl(180,100%,50%)]/10",
  };
  
  const sizes = {
    sm: "px-4 py-2 text-sm",
    md: "px-6 py-3 text-base",
    lg: "px-8 py-4 text-lg",
  };

  return (
    <button
      className={cn(
        baseStyles,
        variants[variant],
        sizes[size],
        glowing && "animate-pulse-glow",
        className
      )}
      {...props}
    >
      <span className="relative z-10 flex items-center gap-2">{children}</span>
      <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent -translate-x-full group-hover:translate-x-full transition-transform duration-700" />
    </button>
  );
}
