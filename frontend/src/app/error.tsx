"use client";

export default function RootError({
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
        <h1 className="text-2xl font-bold mb-3">Algo salió mal</h1>
        <p className="text-gray-400 mb-6">
          Hubo un error inesperado. Esto puede ocurrir justo después de reiniciar los servicios.
          Intenta recargar la página.
        </p>
        <button
          onClick={reset}
          className="px-6 py-3 bg-cyan-500 hover:bg-cyan-400 text-black font-semibold rounded-xl transition-all"
        >
          Reintentar
        </button>
      </div>
    </div>
  );
}
