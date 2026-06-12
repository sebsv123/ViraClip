export default function TaskLoading() {
  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white flex">
      <aside className="w-64 bg-[#0a0a0f] border-r border-white/5 min-h-screen flex flex-col p-6">
        <div className="flex items-center gap-3">
          <div className="relative w-10 h-10">
            <div className="absolute inset-0 bg-gradient-to-br from-cyan-400 via-purple-500 to-pink-500 rounded-xl" />
            <div className="absolute inset-[2px] bg-[#0a0a0f] rounded-xl flex items-center justify-center">
              <span className="w-5 h-5 text-cyan-400">⚡</span>
            </div>
          </div>
          <span className="text-xl font-bold">
            Vira<span className="text-cyan-400">Clip</span>
          </span>
        </div>
      </aside>
      <main className="flex-1 flex items-center justify-center">
        <div className="flex items-center gap-3">
          <span className="w-2 h-2 bg-cyan-400 rounded-full animate-[pulse_1.4s_ease-in-out_infinite]" />
          <span className="w-2 h-2 bg-purple-500 rounded-full animate-[pulse_1.4s_ease-in-out_0.2s_infinite]" />
          <span className="w-2 h-2 bg-pink-500 rounded-full animate-[pulse_1.4s_ease-in-out_0.4s_infinite]" />
          <span className="text-gray-500 text-sm ml-2">Cargando tarea...</span>
        </div>
      </main>
    </div>
  );
}
