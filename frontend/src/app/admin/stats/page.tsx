"use client";

import { useState, useEffect, useCallback, useRef } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const SESSION_KEY = "admin_jwt";
const REFRESH_MS = 30_000;

interface Stats {
  active_workers: number;
  queued_jobs: number;
  success_rate_1h: number;
  failed_jobs_1h: number;
  alert: boolean;
  ratings: {
    good: number;
    bad: number;
    unrated: number;
    total: number;
    good_pct: number;
  };
}

export default function AdminStatsPage() {
  const [token, setToken] = useState<string | null>(null);
  const [secret, setSecret] = useState("");
  const [loginError, setLoginError] = useState("");
  const [stats, setStats] = useState<Stats | null>(null);
  const [fetchError, setFetchError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Restore token from sessionStorage on mount
  useEffect(() => {
    const stored = sessionStorage.getItem(SESSION_KEY);
    if (stored) setToken(stored);
  }, []);

  const fetchStats = useCallback(async (jwt: string) => {
    try {
      const res = await fetch(`${API_URL}/admin/stats`, {
        headers: { Authorization: `Bearer ${jwt}` },
      });
      if (res.status === 401) {
        sessionStorage.removeItem(SESSION_KEY);
        setToken(null);
        setFetchError("Session expired — please log in again.");
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStats(await res.json());
      setFetchError("");
      setLastUpdated(new Date());
    } catch (e) {
      setFetchError(e instanceof Error ? e.message : "Fetch failed");
    }
  }, []);

  // Start polling when token is available
  useEffect(() => {
    if (!token) {
      if (intervalRef.current) clearInterval(intervalRef.current);
      return;
    }
    void fetchStats(token);
    intervalRef.current = setInterval(() => void fetchStats(token), REFRESH_MS);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [token, fetchStats]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError("");
    try {
      const res = await fetch(`${API_URL}/admin/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ secret }),
      });
      if (res.status === 401) {
        setLoginError("Invalid secret.");
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const { token: jwt } = await res.json();
      sessionStorage.setItem(SESSION_KEY, jwt);
      setToken(jwt);
      setSecret("");
    } catch (e) {
      setLoginError(e instanceof Error ? e.message : "Login failed");
    }
  };

  const handleLogout = () => {
    sessionStorage.removeItem(SESSION_KEY);
    setToken(null);
    setStats(null);
  };

  if (!token) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gray-50 px-4">
        <div className="w-full max-w-sm rounded-xl border border-gray-200 bg-white p-8 shadow-sm">
          <h1 className="mb-1 text-xl font-semibold text-gray-900">Admin Stats</h1>
          <p className="mb-6 text-sm text-gray-500">Enter your ADMIN_SECRET to continue.</p>
          <form onSubmit={handleLogin} className="space-y-4">
            <input
              type="password"
              placeholder="Admin secret"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              autoFocus
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gray-500 focus:outline-none"
            />
            {loginError && (
              <p className="text-sm text-red-600">{loginError}</p>
            )}
            <button
              type="submit"
              className="w-full rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 transition-colors"
            >
              Sign in
            </button>
          </form>
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Live Stats</h1>
          <p className="mt-1 text-xs text-gray-400">
            Auto-refreshes every 30s
            {lastUpdated && ` · Last: ${lastUpdated.toLocaleTimeString()}`}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <a href="/admin" className="text-sm text-gray-500 underline">
            Full dashboard
          </a>
          <button
            onClick={handleLogout}
            className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
          >
            Sign out
          </button>
        </div>
      </div>

      {fetchError && (
        <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {fetchError}
        </div>
      )}

      {stats?.alert && (
        <div className="mb-6 rounded-lg border border-red-400 bg-red-600 px-4 py-3 text-sm font-semibold text-white">
          ⚠ Alert: elevated failure rate or queue backlog detected
        </div>
      )}

      {!stats ? (
        <div className="text-sm text-gray-400">Loading…</div>
      ) : (
        <>
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label="Active workers" value={stats.active_workers} />
            <StatCard label="Queued jobs" value={stats.queued_jobs} />
            <StatCard
              label="1h success rate"
              value={`${stats.success_rate_1h}%`}
              highlight={stats.success_rate_1h < 80 ? "red" : "green"}
            />
            <StatCard
              label="1h failed jobs"
              value={stats.failed_jobs_1h}
              highlight={stats.failed_jobs_1h > 0 ? "red" : undefined}
            />
          </section>

          <section className="mt-8 rounded-xl border border-gray-200 bg-white p-6">
            <h2 className="mb-4 text-base font-semibold text-gray-900">Clip ratings</h2>
            <div className="grid gap-4 sm:grid-cols-4">
              <StatCard label="Total clips" value={stats.ratings.total} />
              <StatCard label="Good (4–5 ★)" value={stats.ratings.good} highlight="green" />
              <StatCard label="Bad (1–2 ★)" value={stats.ratings.bad} highlight={stats.ratings.bad > 0 ? "red" : undefined} />
              <StatCard label="Unrated" value={stats.ratings.unrated} />
            </div>
            {stats.ratings.total > 0 && (
              <div className="mt-4">
                <div className="mb-1 flex justify-between text-xs text-gray-500">
                  <span>Positive rating</span>
                  <span>{stats.ratings.good_pct}%</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
                  <div
                    className="h-full rounded-full bg-green-500 transition-all"
                    style={{ width: `${stats.ratings.good_pct}%` }}
                  />
                </div>
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}

function StatCard({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string | number;
  highlight?: "green" | "red";
}) {
  const valueClass =
    highlight === "green"
      ? "text-green-600"
      : highlight === "red"
      ? "text-red-600"
      : "text-gray-900";
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <p className="text-xs uppercase tracking-wide text-gray-500">{label}</p>
      <p className={`mt-2 text-2xl font-semibold ${valueClass}`}>{value}</p>
    </div>
  );
}
