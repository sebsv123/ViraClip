"use client";

import Link from "next/link";

export default function TaskError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white flex items-center justify-center p-8">
      <div className="text-center max-w-md">
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-red-500/20 to-orange-500/20 border border-red-500/30 flex items-center justify-center mx-auto mb-6">
          <span className="text-3xl">⚠️</span>
        </div>
        <h1 className="text-2xl font-bold mb-3">Error al cargar la tarea</h1>
        <p className="text-gray-400 mb-6">
          No se pudo cargar esta tarea. Es posible que el backend esté iniciándose
          o que la tarea ya no exista.
        </p>
        <div className="flex gap-3 justify-center">
          <button
            onClick={reset}
            className="px-6 py-3 bg-cyan-500 hover:bg-cyan-400 text-black font-semibold rounded-xl transition-all"
          >
            Reintentar
          </button>
          <Link
            href="/dashboard"
            className="px-6 py-3 bg-white/10 hover:bg-white/20 text-white font-semibold rounded-xl transition-all"
          >
            Volver al panel
          </Link>
        </div>
      </div>
    </div>
  );
}
