"use client";

import { useState, useEffect, useCallback } from "react";

interface ProviderUsage {
  tokens_today: number;
  cost_today: number;
  cost_30d: number;
}

interface UsageData {
  date: string;
  deepseek: ProviderUsage;
  groq: ProviderUsage;
  elevenlabs: ProviderUsage & { chars_today: number };
  total_cost_today: number;
  total_cost_30d: number;
  alert_level: "ok" | "moderate" | "high";
}

export default function AdminUsagePage() {
  const [data, setData] = useState<UsageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<string>("");

  const fetchUsage = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/usage");
      if (res.ok) {
        const json = await res.json();
        setData(json);
        setLastUpdated(new Date().toLocaleTimeString());
      }
    } catch (err) {
      console.error("Failed to fetch usage:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUsage();
  }, [fetchUsage]);

  const alertBanner = () => {
    if (!data) return null;
    if (data.alert_level === "high") {
      return (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-400 text-sm font-medium">
          ⚠ Coste alto hoy: ${data.total_cost_today.toFixed(4)}
        </div>
      );
    }
    if (data.alert_level === "moderate") {
      return (
        <div className="p-4 rounded-xl bg-amber-500/10 border border-amber-500/30 text-amber-400 text-sm font-medium">
          ⚡ Coste moderado: ${data.total_cost_today.toFixed(4)}
        </div>
      );
    }
    return (
      <div className="p-4 rounded-xl bg-green-500/10 border border-green-500/30 text-green-400 text-sm font-medium">
        ✓ Coste nominal: ${data.total_cost_today.toFixed(4)}
      </div>
    );
  };

  return (
    <div className="p-6 lg:p-8 max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold text-white mb-1">Usage & Costes</h1>
          <p className="text-white/40 text-sm">
            Consumo de APIs de LLM y TTS
            {lastUpdated && <span className="ml-2">· Última actualización: {lastUpdated}</span>}
          </p>
        </div>
        <button
          onClick={fetchUsage}
          className="px-4 py-2 rounded-xl bg-violet-500/20 text-violet-300 text-sm font-medium hover:bg-violet-500/30 transition-colors"
        >
          Actualizar
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : data ? (
        <>
          <div className="overflow-x-auto mb-6">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10">
                  <th className="text-left py-3 px-4 text-white/50 font-medium">Proveedor</th>
                  <th className="text-right py-3 px-4 text-white/50 font-medium">Tokens/Chars hoy</th>
                  <th className="text-right py-3 px-4 text-white/50 font-medium">Coste estimado hoy</th>
                  <th className="text-right py-3 px-4 text-white/50 font-medium">Acumulado 30d</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-b border-white/5 hover:bg-white/[0.02]">
                  <td className="py-3 px-4 text-white font-medium">DeepSeek</td>
                  <td className="py-3 px-4 text-right text-white/70">{data.deepseek.tokens_today.toLocaleString()}</td>
                  <td className="py-3 px-4 text-right text-white/70">${data.deepseek.cost_today.toFixed(4)}</td>
                  <td className="py-3 px-4 text-right text-white/70">${data.deepseek.cost_30d.toFixed(4)}</td>
                </tr>
                <tr className="border-b border-white/5 hover:bg-white/[0.02]">
                  <td className="py-3 px-4 text-white font-medium">Groq</td>
                  <td className="py-3 px-4 text-right text-white/70">{data.groq.tokens_today.toLocaleString()}</td>
                  <td className="py-3 px-4 text-right text-white/70">${data.groq.cost_today.toFixed(4)}</td>
                  <td className="py-3 px-4 text-right text-white/70">${data.groq.cost_30d.toFixed(4)}</td>
                </tr>
                <tr className="border-b border-white/5 hover:bg-white/[0.02]">
                  <td className="py-3 px-4 text-white font-medium">ElevenLabs</td>
                  <td className="py-3 px-4 text-right text-white/70">{data.elevenlabs.chars_today.toLocaleString()} chars</td>
                  <td className="py-3 px-4 text-right text-white/70">${data.elevenlabs.cost_today.toFixed(4)}</td>
                  <td className="py-3 px-4 text-right text-white/70">${data.elevenlabs.cost_30d.toFixed(4)}</td>
                </tr>
                <tr className="bg-white/[0.03] font-semibold">
                  <td className="py-3 px-4 text-white">TOTAL</td>
                  <td className="py-3 px-4 text-right text-white">—</td>
                  <td className="py-3 px-4 text-right text-white">${data.total_cost_today.toFixed(4)}</td>
                  <td className="py-3 px-4 text-right text-white">${data.total_cost_30d.toFixed(4)}</td>
                </tr>
              </tbody>
            </table>
          </div>

          {alertBanner()}
        </>
      ) : (
        <div className="text-center py-20 text-white/40">
          No se pudieron cargar los datos de uso. Verifica que Redis esté disponible.
        </div>
      )}
    </div>
  );
}
