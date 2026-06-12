"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en" className="dark">
      <body className="font-sans antialiased bg-[#0a0a0f] text-white">
        <div className="min-h-screen flex items-center justify-center p-8">
          <div className="text-center max-w-md">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-red-500/20 to-orange-500/20 border border-red-500/30 flex items-center justify-center mx-auto mb-6">
              <span className="text-3xl">⚠️</span>
            </div>
            <h1 className="text-2xl font-bold mb-3">Error crítico</h1>
            <p className="text-gray-400 mb-6">
              La aplicación falló al cargar. Esto puede ocurrir justo después de reiniciar los servicios.
              Si el problema persiste, revisa los logs del contenedor frontend.
            </p>
            <button
              onClick={reset}
              className="px-6 py-3 bg-cyan-500 hover:bg-cyan-400 text-black font-semibold rounded-xl transition-all"
            >
              Reintentar
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
