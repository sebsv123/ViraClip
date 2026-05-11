"use client";

import { useState, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Upload, Film, X, Check, Loader2, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

type UploadState = "idle" | "dragging" | "uploading" | "done" | "error";

export function UploadVideo({ onModeChange }: { onModeChange?: (mode: "url" | "upload") => void }) {
  const [state, setState] = useState<UploadState>("idle");
  const [progress, setProgress] = useState(0);
  const [errorMsg, setErrorMsg] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();

  const ALLOWED_TYPES = ["video/mp4", "video/quicktime", "video/webm"];
  const MAX_SIZE_MB = 500;

  const validateFile = useCallback((f: File): string | null => {
    if (!ALLOWED_TYPES.includes(f.type)) {
      return "Formato no soportado. Usa MP4, MOV o WEBM.";
    }
    if (f.size > MAX_SIZE_MB * 1024 * 1024) {
      return `Archivo demasiado grande (${(f.size / 1024 / 1024).toFixed(0)}MB, máx ${MAX_SIZE_MB}MB).`;
    }
    return null;
  }, []);

  const handleFile = useCallback(async (f: File) => {
    const error = validateFile(f);
    if (error) {
      setErrorMsg(error);
      setState("error");
      return;
    }

    setFile(f);
    setState("uploading");
    setProgress(0);

    const formData = new FormData();
    formData.append("file", f);
    formData.append("processing_mode", "fast");

    // Get user_id from cookies
    const getCookie = (name: string): string | null => {
      const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]+)`));
      return match ? match[1] : null;
    };
    const userId = getCookie("user_id") ?? "local-test-user";

    const xhr = new XMLHttpRequest();

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        setProgress(Math.round((e.loaded / e.total) * 100));
      }
    };

    xhr.onload = async () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText);
          const videoPath: string = data.video_path ?? data.videoPath ?? "";

          // Create task via POST /api/tasks
          const taskRes = await fetch("/api/tasks", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "user_id": userId,
            },
            body: JSON.stringify({
              source: { url: videoPath },
              processing_mode: "fast",
            }),
          });

          if (!taskRes.ok) {
            const errBody = await taskRes.json().catch(() => ({}));
            throw new Error(errBody.detail ?? errBody.message ?? "Error al crear la tarea");
          }

          const taskData = await taskRes.json();
          setState("done");
          setTimeout(() => {
            router.push(`/tasks/${taskData.task_id}`);
          }, 1000);
        } catch (err) {
          setErrorMsg(err instanceof Error ? err.message : "Error al procesar el video.");
          setState("error");
        }
      } else {
        try {
          const data = JSON.parse(xhr.responseText);
          setErrorMsg(data.detail || "Error al subir el video.");
        } catch {
          setErrorMsg("Error al subir el video.");
        }
        setState("error");
      }
    };

    xhr.onerror = () => {
      setErrorMsg("Error de conexión al subir el video.");
      setState("error");
    };

    xhr.open("POST", "/api/tasks/upload");
    xhr.setRequestHeader("user_id", userId);
    xhr.send(formData);
  }, [router, validateFile]);


  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setState("idle");
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  }, [handleFile]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setState("dragging");
  }, []);

  const handleDragLeave = useCallback(() => {
    setState("idle");
  }, []);

  const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) handleFile(f);
  }, [handleFile]);

  const reset = useCallback(() => {
    setState("idle");
    setProgress(0);
    setErrorMsg("");
    setFile(null);
  }, []);

  return (
    <div
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onClick={() => !file && inputRef.current?.click()}
      className={cn(
        "relative border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all duration-200",
        state === "dragging" && "border-violet-500 bg-violet-500/10 scale-[1.02]",
        state === "idle" && "border-white/20 hover:border-violet-500/50 hover:bg-white/5",
        state === "uploading" && "border-violet-500/50",
        state === "done" && "border-green-500/50",
        state === "error" && "border-red-500/50",
      )}
    >
      <input
        ref={inputRef}
        type="file"
        accept="video/mp4,video/quicktime,video/webm"
        className="hidden"
        onChange={handleInputChange}
      />

      <AnimatePresence mode="wait">
        {state === "idle" || state === "dragging" ? (
          <motion.div
            key="idle"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center gap-3"
          >
            <div className="w-16 h-16 rounded-full bg-violet-500/20 flex items-center justify-center">
              <Upload className="w-8 h-8 text-violet-400" />
            </div>
            <div>
              <p className="text-white font-medium">
                {state === "dragging" ? "Suelta el archivo aquí" : "Arrastra tu video aquí"}
              </p>
              <p className="text-sm text-white/40 mt-1">o haz clic para seleccionar</p>
            </div>
            <p className="text-xs text-white/30">MP4, MOV, WEBM &middot; máx 500MB</p>
          </motion.div>
        ) : state === "uploading" ? (
          <motion.div
            key="uploading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center gap-3"
          >
            <Loader2 className="w-10 h-10 text-violet-400 animate-spin" />
            <div className="w-full max-w-xs">
              <div className="flex justify-between text-sm mb-1">
                <span className="text-white/60">Subiendo...</span>
                <span className="text-violet-400 font-medium">{progress}%</span>
              </div>
              <div className="w-full h-2 bg-white/10 rounded-full overflow-hidden">
                <motion.div
                  className="h-full bg-gradient-to-r from-violet-500 to-fuchsia-500 rounded-full"
                  initial={{ width: 0 }}
                  animate={{ width: `${progress}%` }}
                  transition={{ duration: 0.3 }}
                />
              </div>
            </div>
            {file && (
              <p className="text-xs text-white/40 truncate max-w-[200px]">{file.name}</p>
            )}
          </motion.div>
        ) : state === "done" ? (
          <motion.div
            key="done"
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center gap-3"
          >
            <div className="w-16 h-16 rounded-full bg-green-500/20 flex items-center justify-center">
              <Check className="w-8 h-8 text-green-400" />
            </div>
            <p className="text-green-400 font-medium">Video subido correctamente</p>
            <p className="text-xs text-white/40">Redirigiendo...</p>
          </motion.div>
        ) : (
          <motion.div
            key="error"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="flex flex-col items-center gap-3"
          >
            <div className="w-16 h-16 rounded-full bg-red-500/20 flex items-center justify-center">
              <AlertCircle className="w-8 h-8 text-red-400" />
            </div>
            <p className="text-red-400 font-medium">{errorMsg}</p>
            <button
              onClick={(e) => { e.stopPropagation(); reset(); }}
              className="text-sm text-white/60 hover:text-white transition-colors"
            >
              Intentar de nuevo
            </button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
