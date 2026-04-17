import { useState } from 'react';
import UploadArea from './components/UploadArea';

function App() {
  return (
    <div className="min-h-screen bg-zinc-950 text-white">
      {/* Header personalizado */}
      <header className="border-b border-zinc-800 bg-zinc-900">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 bg-gradient-to-br from-violet-500 via-fuchsia-500 to-rose-500 rounded-2xl flex items-center justify-center text-2xl font-bold">
              ⚡
            </div>
            <h1 className="text-3xl font-bold tracking-tighter">ViraClip</h1>
          </div>
          
          <div className="flex items-center gap-6 text-sm">
            <span className="text-zinc-400">Self-Hosted • Sin límites • Sin watermark • 100% Tuyo</span>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-12">
        <div className="text-center mb-12">
          <h2 className="text-5xl font-bold tracking-tight mb-4">
            Tu propio generador de clips virales,<br />
            <span className="bg-gradient-to-r from-violet-400 to-fuchsia-400 bg-clip-text text-transparent">mejor que OpusClip</span>
          </h2>
          <p className="text-xl text-zinc-400 max-w-2xl mx-auto">
            Sube varios videos a la vez • Detecta los momentos más virales • Subtítulos animados • Todo local en tu máquina
          </p>
        </div>

        <UploadArea />
      </main>
    </div>
  );
}

export default App;