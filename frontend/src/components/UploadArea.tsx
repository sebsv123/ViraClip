import { useState, useCallback } from 'react';
import { Upload, X, Play } from 'lucide-react';

export default function UploadArea() {
  const [files, setFiles] = useState<File[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const onDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const droppedFiles = Array.from(e.dataTransfer.files).filter(file => 
      file.type.startsWith('video/')
    );
    if (droppedFiles.length > 0) {
      setFiles(prev => [...prev, ...droppedFiles]);
    }
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const selected = Array.from(e.target.files).filter(file => 
        file.type.startsWith('video/')
      );
      setFiles(prev => [...prev, ...selected]);
    }
  };

  const removeFile = (index: number) => {
    setFiles(prev => prev.filter((_, i) => i !== index));
  };

  const startProcessing = async () => {
    if (files.length === 0) return;

    setIsUploading(true);
    
    alert(`🚀 ViraClip está procesando ${files.length} video(s) en batch...\n\n(Esto es la versión visual del Paso 2. En el Paso 3 conectaremos el backend real con procesamiento paralelo)`);

    // Simulación de proceso
    setTimeout(() => {
      setIsUploading(false);
      alert(`✅ ${files.length} videos enviados correctamente a ViraClip.\n\nLos clips virales aparecerán en "All Generations" cuando activemos los workers.`);
      setFiles([]);
    }, 2800);
  };

  return (
    <div className="max-w-5xl mx-auto">
      {/* Área de arrastre mejorada */}
      <div 
        onDrop={onDrop}
        onDragOver={(e) => e.preventDefault()}
        className="border-3 border-dashed border-zinc-700 hover:border-violet-500 rounded-3xl p-20 text-center transition-all bg-zinc-900/60 hover:bg-zinc-900"
      >
        <Upload className="w-20 h-20 mx-auto mb-8 text-violet-400" />
        <h3 className="text-4xl font-semibold mb-3">Arrastra varios videos aquí</h3>
        <p className="text-zinc-400 text-xl mb-10">Soporta hasta 20 videos a la vez • MP4, MOV, AVI, etc.</p>

        <label className="cursor-pointer inline-flex items-center gap-4 bg-violet-600 hover:bg-violet-700 px-12 py-5 rounded-2xl font-semibold text-lg transition transform hover:scale-105">
          <Upload className="w-6 h-6" />
          Seleccionar múltiples videos
          <input 
            type="file" 
            multiple 
            accept="video/*" 
            className="hidden" 
            onChange={handleFileSelect}
          />
        </label>
      </div>

      {/* Lista de videos seleccionados */}
      {files.length > 0 && (
        <div className="mt-12">
          <div className="flex items-center justify-between mb-6">
            <h4 className="text-2xl font-semibold">
              Videos listos ({files.length})
            </h4>
            <button
              onClick={() => setFiles([])}
              className="text-red-400 hover:text-red-500 text-sm flex items-center gap-2"
            >
              <X size={18} /> Limpiar todo
            </button>
          </div>

          <div className="grid gap-4">
            {files.map((file, index) => (
              <div key={index} className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 flex items-center gap-6 group">
                <div className="w-16 h-16 bg-zinc-800 rounded-2xl flex-shrink-0 flex items-center justify-center text-4xl">
                  🎬
                </div>
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-lg truncate">{file.name}</p>
                  <p className="text-zinc-500 text-sm">
                    {(file.size / (1024 * 1024)).toFixed(1)} MB
                  </p>
                </div>
                <button
                  onClick={() => removeFile(index)}
                  className="opacity-60 hover:opacity-100 text-red-400 p-2"
                >
                  <X size={24} />
                </button>
              </div>
            ))}
          </div>

          {/* Botón principal de procesar */}
          <button
            onClick={startProcessing}
            disabled={isUploading}
            className="mt-10 w-full bg-gradient-to-r from-violet-600 to-fuchsia-600 py-7 rounded-3xl font-bold text-2xl flex items-center justify-center gap-4 disabled:opacity-70 hover:brightness-110 transition-all active:scale-[0.985]"
          >
            {isUploading ? (
              <>Procesando en batch con ViraClip...</>
            ) : (
              <>
                <Play className="w-7 h-7" />
                Generar Clips Virales de los {files.length} videos
              </>
            )}
          </button>
        </div>
      )}
    </div>
  );
}