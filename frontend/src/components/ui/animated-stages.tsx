"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";
import { Check, Loader2 } from "lucide-react";

interface Stage {
  id: string;
  label: string;
  description?: string;
  status: "pending" | "in-progress" | "completed" | "error";
}

interface AnimatedStagesProps {
  stages: Stage[];
  className?: string;
  currentStageId?: string;
}

export function AnimatedStages({ stages, className, currentStageId }: AnimatedStagesProps) {
  return (
    <div className={cn("space-y-0", className)}>
      {stages.map((stage, index) => {
        const isLast = index === stages.length - 1;
        const isActive = stage.status === "in-progress";
        const isCompleted = stage.status === "completed";
        
        return (
          <div key={stage.id} className="relative flex gap-4">
            {/* Connector line */}
            {!isLast && (
              <div className="absolute left-[19px] top-[40px] w-[2px] h-[calc(100%-24px)] bg-white/10">
                {isCompleted && (
                  <motion.div
                    className="w-full bg-gradient-to-b from-violet-500 to-fuchsia-500"
                    initial={{ height: "0%" }}
                    animate={{ height: "100%" }}
                    transition={{ duration: 0.5 }}
                  />
                )}
              </div>
            )}
            
            {/* Stage indicator */}
            <div className="relative z-10 flex-shrink-0">
              <motion.div
                className={cn(
                  "w-10 h-10 rounded-full flex items-center justify-center border-2 transition-colors",
                  isCompleted && "bg-violet-500 border-violet-500",
                  isActive && "border-violet-500 bg-violet-500/20",
                  !isCompleted && !isActive && "border-white/20 bg-white/5"
                )}
                animate={isActive ? { scale: [1, 1.1, 1] } : {}}
                transition={{ duration: 1.5, repeat: Infinity }}
              >
                {isCompleted ? (
                  <Check className="w-5 h-5 text-white" />
                ) : isActive ? (
                  <Loader2 className="w-5 h-5 text-violet-400 animate-spin" />
                ) : (
                  <span className="text-sm text-white/40">{index + 1}</span>
                )}
              </motion.div>
            </div>
            
            {/* Content */}
            <div className={cn("pb-8", isLast && "pb-0")}>
              <h4 className={cn(
                "font-medium",
                isActive ? "text-white" : isCompleted ? "text-white/80" : "text-white/40"
              )}>
                {stage.label}
              </h4>
              {stage.description && (
                <p className={cn(
                  "text-sm mt-1",
                  isActive ? "text-white/60" : "text-white/30"
                )}>
                  {stage.description}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
