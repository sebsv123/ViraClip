"use client";

import {
  useState,
  useCallback,
  createContext,
  useContext,
  type ReactNode,
} from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  CheckCircle,
  AlertCircle,
  XCircle,
  Info,
  X,
} from "lucide-react";

/* ─────────────────────────────────────────────
   Types
   ───────────────────────────────────────────── */

type ToastType = "success" | "warning" | "error" | "info";

interface Toast {
  id: string;
  type: ToastType;
  message: string;
}

interface ToastContextValue {
  toast: (type: ToastType, message: string) => void;
}

/* ─────────────────────────────────────────────
   Config
   ───────────────────────────────────────────── */

const ICONS = {
  success: CheckCircle,
  warning: AlertCircle,
  error: XCircle,
  info: Info,
} as const;

const COLORS = {
  success: "var(--success)",
  warning: "var(--warn)",
  error: "var(--danger)",
  info: "var(--accent)",
} as const;

const AUTO_DISMISS_MS: Record<ToastType, number | null> = {
  success: 4000,
  warning: 4000,
  info: 4000,
  error: null, // must dismiss manually
};

const MAX_VISIBLE = 3;

/* ─────────────────────────────────────────────
   Context
   ───────────────────────────────────────────── */

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>");
  return ctx;
}

/* ─────────────────────────────────────────────
   Provider
   ───────────────────────────────────────────── */

let toastIdCounter = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((type: ToastType, message: string) => {
    const id = `toast-${++toastIdCounter}`;
    const toast: Toast = { id, type, message };

    setToasts((prev) => {
      const next = [...prev, toast];
      // Keep only MAX_VISIBLE
      return next.length > MAX_VISIBLE
        ? next.slice(next.length - MAX_VISIBLE)
        : next;
    });

    // Auto-dismiss
    const ms = AUTO_DISMISS_MS[type];
    if (ms !== null) {
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, ms);
    }
  }, []);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toast: addToast }}>
      {children}

      {/* Toast stack — fixed bottom-right */}
      <div
        className="fixed flex flex-col-reverse gap-2 pointer-events-none z-[9999]"
        style={{
          bottom: "var(--space-5)",
          right: "var(--space-5)",
        }}
      >
        <AnimatePresence mode="popLayout">
          {toasts.map((t) => {
            const Icon = ICONS[t.type];
            const color = COLORS[t.type];

            return (
              <motion.div
                key={t.id}
                layout
                initial={{ opacity: 0, x: 100 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0 }}
                transition={{
                  duration: 0.2,
                  ease: [0.2, 0, 0, 1],
                }}
                className="pointer-events-auto flex items-center gap-3"
                style={{
                  minWidth: 300,
                  maxWidth: 380,
                  background: "var(--surface)",
                  boxShadow: "var(--elev-raised)",
                  border: "var(--elev-ring)",
                  borderRadius: "var(--radius-md)",
                  padding: "var(--space-3) var(--space-4)",
                }}
              >
                <Icon size={16} style={{ color, flexShrink: 0 }} />
                <span
                  className="text-sm flex-1"
                  style={{ color: "var(--fg-2)" }}
                >
                  {t.message}
                </span>
                <button
                  onClick={() => dismissToast(t.id)}
                  className="p-0.5 rounded-sm transition-all ml-auto"
                  style={{ color: "var(--meta)" }}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.color = "var(--fg)")
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.color = "var(--meta)")
                  }
                >
                  <X size={14} />
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}
