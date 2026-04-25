"use client";

import { useState, useRef } from "react";
import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

interface Tab {
  id: string;
  label: string;
  content: React.ReactNode;
}

interface AnimatedTabsProps {
  tabs: Tab[];
  className?: string;
  defaultTab?: string;
}

export function AnimatedTabs({ tabs, className, defaultTab }: AnimatedTabsProps) {
  const [activeTab, setActiveTab] = useState(defaultTab || tabs[0]?.id);
  const [hoveredTab, setHoveredTab] = useState<string | null>(null);
  const tabRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  const activeTabData = tabs.find(t => t.id === activeTab);

  return (
    <div className={cn("w-full", className)}>
      <div className="relative flex items-center gap-1 rounded-full bg-white/5 p-1 backdrop-blur-sm">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            ref={(el) => {
              if (el) tabRefs.current.set(tab.id, el);
            }}
            onClick={() => setActiveTab(tab.id)}
            onMouseEnter={() => setHoveredTab(tab.id)}
            onMouseLeave={() => setHoveredTab(null)}
            className={cn(
              "relative z-10 flex-1 px-4 py-2 text-sm font-medium transition-colors",
              activeTab === tab.id ? "text-white" : "text-white/60 hover:text-white/80"
            )}
          >
            {tab.label}
          </button>
        ))}
        
        <motion.div
          className="absolute inset-y-1 rounded-full bg-white/10"
          layoutId="activeTab"
          transition={{ type: "spring", bounce: 0.2, duration: 0.6 }}
          style={{
            left: tabRefs.current.get(activeTab)?.offsetLeft || 0,
            width: tabRefs.current.get(activeTab)?.offsetWidth || 0,
          }}
        />
      </div>
      
      <div className="mt-6">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -10 }}
          transition={{ duration: 0.3 }}
        >
          {activeTabData?.content}
        </motion.div>
      </div>
    </div>
  );
}
