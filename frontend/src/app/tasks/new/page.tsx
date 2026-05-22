"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import { ArrowLeft, Sparkles, Loader2, Link2 } from "lucide-react";
import Link from "next/link";

const CAPTION_TEMPLATES = [
  { id: "default", name: "Default", description: "Clean white text with black outline" },
  { id: "hormozi", name: "Hormozi", description: "Bold green highlights like Alex Hormozi" },
  { id: "mrbeast", name: "MrBeast", description: "Large yellow text with red highlights" },
  { id: "minimal", name: "Minimal", description: "Clean, subtle captions" },
  { id: "tiktok", name: "TikTok", description: "TikTok-style with pink highlights" },
  { id: "neon", name: "Neon", description: "Glowing neon effect with cyan highlights" },
  { id: "podcast", name: "Podcast", description: "Professional podcast-style captions" },
  { id: "viral_pro", name: "Viral Pro", description: "Ultra-bold, yellow highlights" },
  { id: "minimal_box", name: "Minimal Box", description: "Clean text with background box" },
  { id: "bounce", name: "Bounce", description: "Each word springs in with pop animation" },
  { id: "fire", name: "Fire", description: "Intense orange-red bouncing captions" },
  { id: "subtitles", name: "Subtitles", description: "Clean accessible subtitle style" },
  { id: "tiktok_word", name: "TikTok Word", description: "Active word highlighted in yellow" },
  { id: "bold", name: "Bold", description: "Uppercase black text on white background" },
  { id: "clean_podcast", name: "Clean Podcast", description: "Montserrat, white on dark box" },
  { id: "tiktok_loud", name: "TikTok Loud", description: "Poppins Bold, yellow highlights, bounce" },
];

export default function NewTaskPage() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [captionTemplate, setCaptionTemplate] = useState("default");
  const [includeBroll, setIncludeBroll] = useState(true);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url.trim()) return;

    setIsLoading(true);
    try {
      const res = await fetch("/api/tasks/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          caption_template: captionTemplate,
          include_broll: includeBroll,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        router.push(`/tasks/${data.task_id}`);
      } else {
        const err = await res.json().catch(() => ({ error: "Unknown error" }));
        alert(err.error || "Failed to create task");
      }
    } catch {
      alert("Network error. Please check your connection.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white">
      <div className="max-w-lg mx-auto px-4 py-8">
        {/* Back button */}
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-2 text-sm text-white/50 hover:text-white mb-8 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Dashboard
        </Link>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <h1 className="text-2xl font-semibold mb-2">New Task</h1>
          <p className="text-white/50 text-sm mb-8">
            Paste a YouTube URL and choose your caption style.
          </p>

          <form onSubmit={handleSubmit} className="space-y-6">
            {/* URL input */}
            <div>
              <label className="block text-sm text-white/60 mb-2">
                Video URL
              </label>
              <div className="relative">
                <Link2 className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/30" />
                <input
                  type="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://youtube.com/watch?v=..."
                  className="w-full pl-12 pr-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white placeholder:text-white/30 focus:outline-none focus:border-violet-500/50 transition-colors"
                />
              </div>
            </div>

            {/* Caption template dropdown */}
            <div>
              <label className="block text-sm text-white/60 mb-2">
                Caption Template
              </label>
              <select
                value={captionTemplate}
                onChange={(e) => setCaptionTemplate(e.target.value)}
                className="w-full px-4 py-3 rounded-xl bg-white/5 border border-white/10 text-white text-sm focus:outline-none focus:border-violet-500/50 transition-colors"
              >
                {CAPTION_TEMPLATES.map((tpl) => (
                  <option key={tpl.id} value={tpl.id} className="bg-[#1a1a25]">
                    {tpl.name} — {tpl.description}
                  </option>
                ))}
              </select>
              <p className="text-xs text-white/40 mt-1.5">
                18 templates available. Default: clean white text with black outline.
              </p>
            </div>

            {/* B-roll toggle */}
            <div>
              <label className="flex items-center gap-3 cursor-pointer">
                <button
                  type="button"
                  role="switch"
                  aria-checked={includeBroll}
                  onClick={() => setIncludeBroll(!includeBroll)}
                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                    includeBroll ? "bg-violet-500" : "bg-white/10"
                  }`}
                >
                  <span
                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                      includeBroll ? "translate-x-6" : "translate-x-1"
                    }`}
                  />
                </button>
                <div>
                  <span className="text-sm text-white font-medium">Añadir B-roll</span>
                  <p className="text-xs text-white/40">
                    Inserta clips visuales de apoyo entre tus momentos clave
                  </p>
                </div>
              </label>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={!url.trim() || isLoading}
              className="w-full px-4 py-3 rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white font-medium hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {isLoading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <>
                  <Sparkles className="w-5 h-5" />
                  Generate Clips
                </>
              )}
            </button>
          </form>
        </motion.div>
      </div>
    </div>
  );
}
