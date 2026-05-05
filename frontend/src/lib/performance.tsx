"use client";

import { useEffect, useState } from "react";

interface PerformanceMetrics {
  fcp: number | null;
  lcp: number | null;
  fid: number | null;
  cls: number | null;
  ttfb: number | null;
}

export function usePerformanceMonitor() {
  const [metrics, setMetrics] = useState<PerformanceMetrics>({
    fcp: null,
    lcp: null,
    fid: null,
    cls: null,
    ttfb: null,
  });

  useEffect(() => {
    if (typeof window === "undefined" || !("PerformanceObserver" in window)) {
      return;
    }

    // First Contentful Paint
    const fcpObserver = new PerformanceObserver((list) => {
      const entries = list.getEntries();
      if (entries.length > 0) {
        setMetrics((prev) => ({ ...prev, fcp: entries[0].startTime }));
      }
    });
    fcpObserver.observe({ entryTypes: ["paint"] });

    // Largest Contentful Paint
    const lcpObserver = new PerformanceObserver((list) => {
      const entries = list.getEntries();
      if (entries.length > 0) {
        const lastEntry = entries[entries.length - 1];
        setMetrics((prev) => ({ ...prev, lcp: lastEntry.startTime }));
      }
    });
    lcpObserver.observe({ entryTypes: ["largest-contentful-paint"] });

    // First Input Delay
    const fidObserver = new PerformanceObserver((list) => {
      const entries = list.getEntries();
      if (entries.length > 0) {
        const firstEntry = entries[0] as PerformanceEventTiming;
        setMetrics((prev) => ({ ...prev, fid: firstEntry.processingStart - firstEntry.startTime }));
      }
    });
    fidObserver.observe({ entryTypes: ["first-input"] });

    // Cumulative Layout Shift
    let clsValue = 0;
    const clsObserver = new PerformanceObserver((list) => {
      const entries = list.getEntries();
      entries.forEach((entry) => {
        const ls = entry as unknown as { hadRecentInput?: boolean; value: number };
        if (!ls.hadRecentInput) {
          clsValue += ls.value;
        }
      });
      setMetrics((prev) => ({ ...prev, cls: clsValue }));
    });
    clsObserver.observe({ entryTypes: ["layout-shift"] });

    // Time to First Byte
    const navigation = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming;
    if (navigation) {
      setMetrics((prev) => ({ ...prev, ttfb: navigation.responseStart - navigation.startTime }));
    }

    return () => {
      fcpObserver.disconnect();
      lcpObserver.disconnect();
      fidObserver.disconnect();
      clsObserver.disconnect();
    };
  }, []);

  return metrics;
}

export function PerformanceDisplay() {
  const metrics = usePerformanceMonitor();
  const [isVisible, setIsVisible] = useState(false);

  if (process.env.NODE_ENV !== "development") {
    return null;
  }

  return (
    <div className="fixed bottom-4 right-4 z-50">
      <button
        onClick={() => setIsVisible(!isVisible)}
        className="px-3 py-2 bg-cyan-500/20 border border-cyan-500/50 rounded-lg text-xs text-cyan-400 font-mono"
      >
        {isVisible ? "Hide" : "Perf"}
      </button>
      
      {isVisible && (
        <div className="mt-2 p-4 bg-[#0a0a0f]/95 border border-white/10 rounded-xl backdrop-blur-xl text-xs font-mono">
          <div className="space-y-2">
            <div className="flex justify-between gap-8">
              <span className="text-gray-400">FCP:</span>
              <span className={metrics.fcp && metrics.fcp < 1800 ? "text-green-400" : "text-amber-400"}>
                {metrics.fcp ? `${Math.round(metrics.fcp)}ms` : "..."}
              </span>
            </div>
            <div className="flex justify-between gap-8">
              <span className="text-gray-400">LCP:</span>
              <span className={metrics.lcp && metrics.lcp < 2500 ? "text-green-400" : "text-amber-400"}>
                {metrics.lcp ? `${Math.round(metrics.lcp)}ms` : "..."}
              </span>
            </div>
            <div className="flex justify-between gap-8">
              <span className="text-gray-400">FID:</span>
              <span className={metrics.fid && metrics.fid < 100 ? "text-green-400" : "text-amber-400"}>
                {metrics.fid ? `${Math.round(metrics.fid)}ms` : "..."}
              </span>
            </div>
            <div className="flex justify-between gap-8">
              <span className="text-gray-400">CLS:</span>
              <span className={metrics.cls && metrics.cls < 0.1 ? "text-green-400" : "text-amber-400"}>
                {metrics.cls ? metrics.cls.toFixed(3) : "..."}
              </span>
            </div>
            <div className="flex justify-between gap-8">
              <span className="text-gray-400">TTFB:</span>
              <span className={metrics.ttfb && metrics.ttfb < 800 ? "text-green-400" : "text-amber-400"}>
                {metrics.ttfb ? `${Math.round(metrics.ttfb)}ms` : "..."}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function ReportWebVitals() {
  useEffect(() => {
    if (typeof window === "undefined") return;

    // Send metrics to analytics in production
    const sendToAnalytics = (metric: { name: string; value: number; id: string }) => {
      // In production, send to your analytics endpoint
      if (process.env.NODE_ENV === "production") {
        // fetch('/api/analytics', { method: 'POST', body: JSON.stringify(metric) });
      }
      
      // Log to console in development
      if (process.env.NODE_ENV === "development") {
        console.log(`[Web Vitals] ${metric.name}:`, Math.round(metric.value * 100) / 100);
      }
    };

    // Use web-vitals library pattern with native API
    const observeWebVitals = () => {
      try {
        const observer = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            if (entry.entryType === "web-vital") {
              sendToAnalytics({
                name: (entry as any).name,
                value: (entry as any).value,
                id: entry.id,
              });
            }
          }
        });
        observer.observe({ entryTypes: ["measure"] });
      } catch (e) {
        // Fallback for browsers without web-vitals support
      }
    };

    observeWebVitals();
  }, []);

  return null;
}
