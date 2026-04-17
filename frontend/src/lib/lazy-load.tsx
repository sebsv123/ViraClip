"use client";

import { Suspense, lazy, ComponentType } from "react";
import { Loader2 } from "lucide-react";

// Loading fallback component
function LoadingFallback() {
  return (
    <div className="flex items-center justify-center min-h-[200px]">
      <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
    </div>
  );
}

// Lazy load components with proper typing
export function lazyLoad<T extends ComponentType<any>>(
  importFn: () => Promise<{ default: T }>
) {
  const LazyComponent = lazy(importFn);
  
  return function LazyLoadedComponent(props: React.ComponentProps<T>) {
    return (
      <Suspense fallback={<LoadingFallback />}>
        <LazyComponent {...props} />
      </Suspense>
    );
  };
}

// Preload function for critical components
export function preloadComponent<T extends ComponentType<any>>(
  importFn: () => Promise<{ default: T }>
) {
  const component = importFn();
  return component;
}
