"use client";

export default function SignInError({
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
        <h1 className="text-2xl font-bold mb-3">Error al iniciar sesión</h1>
        <p className="text-gray-400 mb-6">
          No se pudo cargar la página de inicio de sesión. Es posible que el backend
          o la base de datos estén iniciándose.
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
