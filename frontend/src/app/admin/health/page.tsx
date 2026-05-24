'use client'

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import { useSession } from '@/lib/auth-client'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Loader2, RefreshCw, ArrowLeft } from 'lucide-react'

interface EffectStats {
  effect: string
  p50_ms: number
  p95_ms: number
  p99_ms: number
  count: number
  avg_ms: number
  slow_count: number
  threshold_s: number
}

interface SystemStatus {
  redis: { connected: boolean; queue_length: number }
  sam: { available: boolean; model_type: string | null }
  render3d: { available: boolean; gpu: boolean }
  worker: { last_heartbeat: string | null; tasks_processed_today: number }
}

interface FeedbackStats {
  total_corrections: number
  total_saves: number
  override_rate: number
  most_corrected: { auto_choice: string; count: number } | null
  correction_matrix: Record<string, number>
  recommendations: string[]
}

function StatusDot({ ok, color }: { ok: boolean; color?: string }) {
  return (
    <span
      className="inline-block w-2.5 h-2.5 rounded-full mr-1.5"
      style={{
        backgroundColor: ok ? (color || '#22c55e') : '#ef4444',
      }}
    />
  )
}

function formatMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)}s`
  return `${ms.toFixed(1)}ms`
}

export default function AdminHealthPage() {
  const { data: session } = useSession()
  const [effects, setEffects] = useState<Record<string, EffectStats>>({})
  const [system, setSystem] = useState<SystemStatus | null>(null)
  const [feedback, setFeedback] = useState<FeedbackStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [accessDenied, setAccessDenied] = useState(false)

  const isAdmin = Boolean((session?.user as { is_admin?: boolean })?.is_admin)

  // Leer ADMIN_SECRET del frontend (NEXT_PUBLIC_ADMIN_SECRET en .env.local)
  const adminSecret = typeof window !== 'undefined'
    ? (window as unknown as Record<string, string>)['__NEXT_PUBLIC_ADMIN_SECRET__']
    : process.env.NEXT_PUBLIC_ADMIN_SECRET || ''

  const fetchWithAuth = useCallback(async (url: string) => {
    const headers: Record<string, string> = {}
    if (adminSecret) {
      headers['X-Admin-Secret'] = adminSecret
    }
    const res = await fetch(url, { headers })
    if (res.status === 401 || res.status === 403) {
      setAccessDenied(true)
      return null
    }
    return res
  }, [adminSecret])

  const fetchData = useCallback(async () => {
    try {
      setAccessDenied(false)
      const [effectsRes, systemRes, feedbackRes] = await Promise.all([
        fetchWithAuth('/api/admin/metrics/effects'),
        fetchWithAuth('/api/admin/metrics/system'),
        fetchWithAuth('/api/admin/metrics/effects/feedback'),
      ])

      if (effectsRes && effectsRes.ok) {
        const data = await effectsRes.json()
        setEffects(data.effects || {})
      }
      if (systemRes && systemRes.ok) {
        setSystem(await systemRes.json())
      }
      if (feedbackRes && feedbackRes.ok) {
        setFeedback(await feedbackRes.json())
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch data')
    } finally {
      setLoading(false)
    }
  }, [fetchWithAuth])

  useEffect(() => {
    fetchData()
    // Auto-refresh cada 30s
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [fetchData])

  if (!session?.user) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-16">
        <h1 className="text-2xl font-semibold">System Health</h1>
        <p className="mt-3 text-sm text-gray-600">You need to sign in to view this page.</p>
        <Link href="/sign-in" className="mt-6 inline-block text-sm font-medium text-black underline">
          Go to sign in
        </Link>
      </main>
    )
  }

  if (!isAdmin) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-16">
        <h1 className="text-2xl font-semibold">System Health</h1>
        <p className="mt-3 text-sm text-gray-600">You do not have admin access.</p>
        <Link href="/" className="mt-6 inline-block text-sm font-medium text-black underline">
          Back to app
        </Link>
      </main>
    )
  }

  if (loading) {
    return (
      <main className="mx-auto max-w-6xl px-6 py-16">
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <Loader2 className="w-4 h-4 animate-spin" />
          Loading system health...
        </div>
      </main>
    )
  }

  // Sort effects by p95 DESC
  const sortedEffects = Object.entries(effects).sort(
    ([, a], [, b]) => b.p95_ms - a.p95_ms,
  )

  return (
    <main className="mx-auto max-w-6xl px-6 py-10 space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 text-sm text-gray-500 mb-1">
            <Link href="/admin" className="hover:text-black transition-colors">
              Admin
            </Link>
            <span>/</span>
            <span className="text-black">System Health</span>
          </div>
          <h1 className="text-3xl font-semibold">System Health</h1>
          <p className="mt-1 text-sm text-gray-600">
            Effect performance, system status, and transition feedback.
          </p>
        </div>
        <button
          onClick={fetchData}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {accessDenied && (
        <Alert className="border-red-200 bg-red-50">
          <AlertDescription className="text-red-700 text-sm">
            Acceso denegado. Verifica que NEXT_PUBLIC_ADMIN_SECRET esté configurado en .env.local.
          </AlertDescription>
        </Alert>
      )}

      {error && (
        <Alert className="border-red-200 bg-red-50">
          <AlertDescription className="text-red-700 text-sm">{error}</AlertDescription>
        </Alert>
      )}

      {/* Section 1: System Status Cards */}
      <section>
        <h2 className="text-lg font-medium mb-4">System Status</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {/* Redis */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium flex items-center">
                <StatusDot ok={system?.redis.connected ?? false} />
                Redis
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-gray-500">
                {system?.redis.connected ? 'Connected' : 'Disconnected'}
              </p>
              <p className="text-xs text-gray-500 mt-1">
                Queue: {system?.redis.queue_length ?? '?'} tasks
              </p>
            </CardContent>
          </Card>

          {/* SAM */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium flex items-center">
                <StatusDot
                  ok={system?.sam.available ?? false}
                  color={system?.sam.available ? '#22c55e' : '#eab308'}
                />
                SAM
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-gray-500">
                {system?.sam.available
                  ? `Loaded (${system.sam.model_type || 'unknown'})`
                  : 'Not available'}
              </p>
            </CardContent>
          </Card>

          {/* render3d */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium flex items-center">
                <StatusDot ok={system?.render3d.available ?? false} />
                render3d
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-gray-500">
                {system?.render3d.available ? 'Available' : 'Unavailable'}
              </p>
              {system?.render3d.gpu && (
                <p className="text-xs text-gray-500 mt-1">GPU: Yes</p>
              )}
            </CardContent>
          </Card>

          {/* Worker */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium flex items-center">
                <StatusDot ok={(system?.worker.tasks_processed_today ?? 0) > 0} />
                Worker
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-gray-500">
                {system?.worker.tasks_processed_today ?? 0} tasks today
              </p>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* Section 2: Effect Performance Table */}
      <section>
        <h2 className="text-lg font-medium mb-4">Effect Performance</h2>
        <div className="rounded-lg border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500">Effect</th>
                  <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500">Calls</th>
                  <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500">Avg</th>
                  <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500">P50</th>
                  <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500">P95</th>
                  <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500">P99</th>
                  <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-gray-500">Slow</th>
                  <th className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wide text-gray-500">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 bg-white">
                {sortedEffects.length === 0 ? (
                  <tr>
                    <td className="px-4 py-8 text-sm text-gray-500 text-center" colSpan={8}>
                      No effect data recorded yet.
                    </td>
                  </tr>
                ) : (
                  sortedEffects.map(([name, stats]) => {
                    const thresholdMs = stats.threshold_s * 1000
                    let status: 'ok' | 'warning' | 'critical'
                    if (stats.p99_ms > thresholdMs * 2) {
                      status = 'critical'
                    } else if (stats.p95_ms > thresholdMs) {
                      status = 'warning'
                    } else {
                      status = 'ok'
                    }

                    const statusLabel =
                      status === 'ok' ? '✅ Normal' :
                      status === 'warning' ? '⚠️ Slow' : '❌ Critical'

                    return (
                      <tr key={name}>
                        <td className="px-4 py-3 text-sm font-medium text-gray-900">
                          {name.replace(/_/g, ' ')}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-700 text-right tabular-nums">
                          {stats.count}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-700 text-right tabular-nums">
                          {formatMs(stats.avg_ms)}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-700 text-right tabular-nums">
                          {formatMs(stats.p50_ms)}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-700 text-right tabular-nums">
                          {formatMs(stats.p95_ms)}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-700 text-right tabular-nums">
                          {formatMs(stats.p99_ms)}
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-700 text-right tabular-nums">
                          {stats.slow_count}
                        </td>
                        <td className="px-4 py-3 text-center">
                          <Badge
                            className={
                              status === 'ok' ? 'bg-green-100 text-green-800' :
                              status === 'warning' ? 'bg-yellow-100 text-yellow-800' :
                              'bg-red-100 text-red-800'
                            }
                          >
                            {statusLabel}
                          </Badge>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* Section 3: Feedback Stats */}
      <section>
        <h2 className="text-lg font-medium mb-4">Transition Selector Feedback</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Total Corrections</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">{feedback?.total_corrections ?? 0}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Override Rate</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">
                {((feedback?.override_rate ?? 0) * 100).toFixed(1)}%
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Total Saves</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">{feedback?.total_saves ?? 0}</p>
            </CardContent>
          </Card>
        </div>

        {/* Most corrected */}
        {feedback?.most_corrected && (
          <Card className="mt-4">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Most Corrected</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm">
                <span className="font-medium">{feedback.most_corrected.auto_choice}</span>
                {' → '}
                <span className="text-gray-600">{feedback.most_corrected.count} corrections</span>
              </p>
            </CardContent>
          </Card>
        )}

        {/* Correction matrix */}
        {feedback?.correction_matrix && Object.keys(feedback.correction_matrix).length > 0 && (
          <Card className="mt-4">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Top Corrections</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1">
                {Object.entries(feedback.correction_matrix)
                  .sort(([, a], [, b]) => b - a)
                  .slice(0, 5)
                  .map(([pair, count]) => (
                    <div key={pair} className="flex justify-between text-sm">
                      <span className="text-gray-700">{pair}</span>
                      <span className="font-medium tabular-nums">{count}</span>
                    </div>
                  ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Recommendations */}
        {feedback?.recommendations && feedback.recommendations.length > 0 && (
          <Alert className="mt-4 border-yellow-200 bg-yellow-50">
            <AlertDescription className="text-yellow-800 text-sm">
              <p className="font-medium mb-1">Threshold Adjustment Recommendations</p>
              <ul className="list-disc pl-4 space-y-1">
                {feedback.recommendations.map((rec, i) => (
                  <li key={i}>{rec}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}
      </section>
    </main>
  )
}
