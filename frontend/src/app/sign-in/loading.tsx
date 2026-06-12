export default function SignInLoading() {
  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white flex items-center justify-center">
      <div className="flex items-center gap-3">
        <span className="w-2 h-2 bg-cyan-400 rounded-full animate-[pulse_1.4s_ease-in-out_infinite]" />
        <span className="w-2 h-2 bg-purple-500 rounded-full animate-[pulse_1.4s_ease-in-out_0.2s_infinite]" />
        <span className="w-2 h-2 bg-pink-500 rounded-full animate-[pulse_1.4s_ease-in-out_0.4s_infinite]" />
        <span className="text-gray-500 text-sm ml-2">Cargando...</span>
      </div>
    </div>
  );
}
