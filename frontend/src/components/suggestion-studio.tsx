"use client";

import { useState, useEffect } from "react";
import { X, Sparkles, Loader2, Lightbulb, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";

interface SuggestionStudioProps {
  isOpen: boolean;
  onClose: () => void;
  clipId: string | null;
  taskId: string;
  apiUrl: string;
  sessionToken?: string;
}

interface Suggestion {
  id: string;
  type: "caption" | "broll" | "music" | "effect" | "trim";
  label: string;
  description: string;
  action: string;
}

export function SuggestionStudio({
  isOpen,
  onClose,
  clipId,
  taskId,
  apiUrl,
  sessionToken,
}: SuggestionStudioProps) {
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [loading, setLoading] = useState(false);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (isOpen && clipId) {
      fetchSuggestions();
    }
  }, [isOpen, clipId]);

  async function fetchSuggestions() {
    setLoading(true);
    setError("");
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (sessionToken) {
        headers["Authorization"] = `Bearer ${sessionToken}`;
      }

      const res = await fetch(
        `${apiUrl}/api/tasks/${taskId}/clips/${clipId}/suggestions`,
        { headers },
      );

      if (!res.ok) {
        throw new Error(`Failed to fetch suggestions: ${res.status}`);
      }

      const data = await res.json();
      setSuggestions(data.suggestions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load suggestions");
    } finally {
      setLoading(false);
    }
  }

  async function applySuggestion(suggestion: Suggestion) {
    setApplyingId(suggestion.id);
    setError("");
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (sessionToken) {
        headers["Authorization"] = `Bearer ${sessionToken}`;
      }

      const res = await fetch(
        `${apiUrl}/api/tasks/${taskId}/clips/${clipId}/suggestions/${suggestion.id}/apply`,
        {
          method: "POST",
          headers,
        },
      );

      if (!res.ok) {
        throw new Error(`Failed to apply suggestion: ${res.status}`);
      }

      // Remove applied suggestion from list
      setSuggestions((prev) => prev.filter((s) => s.id !== suggestion.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to apply suggestion");
    } finally {
      setApplyingId(null);
    }
  }

  if (!isOpen) return null;

  const typeIcon = (type: Suggestion["type"]) => {
    switch (type) {
      case "caption":
        return <Lightbulb size={16} />;
      case "broll":
        return <Wand2 size={16} />;
      case "music":
        return <Sparkles size={16} />;
      case "effect":
        return <Sparkles size={16} />;
      case "trim":
        return <Wand2 size={16} />;
      default:
        return <Lightbulb size={16} />;
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.6)" }}
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-lg max-h-[80vh] overflow-y-auto rounded-xl border p-6 shadow-2xl"
        style={{
          background: "var(--bg)",
          borderColor: "var(--border)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <Sparkles size={20} style={{ color: "var(--accent)" }} />
            <h2 className="text-lg font-semibold" style={{ color: "var(--fg)" }}>
              AI Suggestions
            </h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 transition-colors hover:bg-white/5"
          >
            <X size={18} style={{ color: "var(--meta)" }} />
          </button>
        </div>

        {/* Error */}
        {error && (
          <div
            className="mb-4 rounded-lg border p-3 text-sm"
            style={{
              background: "rgba(239,68,68,0.1)",
              borderColor: "rgba(239,68,68,0.2)",
              color: "rgb(239,68,68)",
            }}
          >
            {error}
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <Loader2 size={24} className="animate-spin" style={{ color: "var(--accent)" }} />
            <p className="text-sm" style={{ color: "var(--meta)" }}>
              Analyzing clip for suggestions...
            </p>
          </div>
        )}

        {/* Empty state */}
        {!loading && suggestions.length === 0 && !error && (
          <div className="flex flex-col items-center justify-center py-12 gap-3">
            <Lightbulb size={32} style={{ color: "var(--meta)" }} />
            <p className="text-sm" style={{ color: "var(--meta)" }}>
              No suggestions available for this clip yet.
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={fetchSuggestions}
              style={{
                borderColor: "var(--border)",
                color: "var(--fg)",
              }}
            >
              <Sparkles size={14} className="mr-1" />
              Refresh
            </Button>
          </div>
        )}

        {/* Suggestions list */}
        {!loading && suggestions.length > 0 && (
          <div className="space-y-3">
            {suggestions.map((suggestion) => (
              <div
                key={suggestion.id}
                className="rounded-lg border p-4 transition-all hover:bg-white/[0.03]"
                style={{ borderColor: "var(--border)" }}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span style={{ color: "var(--accent)" }}>
                        {typeIcon(suggestion.type)}
                      </span>
                      <span
                        className="text-xs font-medium uppercase tracking-wider"
                        style={{ color: "var(--accent)" }}
                      >
                        {suggestion.type}
                      </span>
                    </div>
                    <p
                      className="text-sm font-medium truncate"
                      style={{ color: "var(--fg)" }}
                    >
                      {suggestion.label}
                    </p>
                    <p
                      className="text-xs mt-1 line-clamp-2"
                      style={{ color: "var(--meta)" }}
                    >
                      {suggestion.description}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    disabled={applyingId === suggestion.id}
                    onClick={() => applySuggestion(suggestion)}
                    style={{
                      background: "var(--accent)",
                      color: "white",
                      minWidth: 72,
                    }}
                  >
                    {applyingId === suggestion.id ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      "Apply"
                    )}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
