"use client";

import { useEffect } from "react";
import { AlertCircle, RefreshCw, ArrowLeft } from "lucide-react";
import Link from "next/link";

export function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Error caught by error boundary:", error);
  }, [error]);

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white flex items-center justify-center p-8">
      <div className="max-w-md w-full text-center">
        <div className="w-20 h-20 bg-red-500/10 rounded-2xl flex items-center justify-center mx-auto mb-6">
          <AlertCircle className="w-10 h-10 text-red-400" />
        </div>
        
        <h2 className="text-2xl font-bold mb-2">Something went wrong</h2>
        <p className="text-gray-400 mb-6">
          {error.message || "An unexpected error occurred. Please try again."}
        </p>
        
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <button
            onClick={reset}
            className="flex items-center justify-center gap-2 px-6 py-3 bg-cyan-500 hover:bg-cyan-400 text-black font-semibold rounded-xl transition-all"
          >
            <RefreshCw className="w-5 h-5" />
            Try Again
          </button>
          
          <Link href="/dashboard">
            <button className="flex items-center justify-center gap-2 px-6 py-3 bg-white/5 hover:bg-white/10 border border-white/10 font-semibold rounded-xl transition-all">
              <ArrowLeft className="w-5 h-5" />
              Go to Dashboard
            </button>
          </Link>
        </div>
        
        {error.digest && (
          <p className="mt-6 text-xs text-gray-600 font-mono">
            Error ID: {error.digest}
          </p>
        )}
      </div>
    </div>
  );
}

// Global error boundary for the root level
export function GlobalError({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <html className="dark">
      <body className="min-h-screen bg-[#0a0a0f] text-white">
        <ErrorBoundary error={error} reset={reset} />
      </body>
    </html>
  );
}
