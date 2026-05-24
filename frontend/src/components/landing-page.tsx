"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Check,
  Github,
  ExternalLink,
  Menu,
  X,
} from "lucide-react";

/* --- Types --- */





/* --- Data --- */

const FEATURES: Feature[] = [];

const STEPS: Step[] = [];

const authEnabled = !isLandingOnlyModeEnabled;

function getPlans() {
  const proPriceMonthly = process.env.NEXT_PUBLIC_PRO_PRICE_MONTHLY || "9.99";
  const freeLimit = parseInt(process.env.NEXT_PUBLIC_FREE_PLAN_TASK_LIMIT || "10", 10);
  const proLimit = parseInt(process.env.NEXT_PUBLIC_PRO_PLAN_TASK_LIMIT || "0", 10);

  const proGenerationsLabel =
    proLimit === 0 ? "Unlimited generations" : `${proLimit} generations per month`;

  return [
    {
      name: "Self-Hosted",
      price: "$0",
      period: "forever",
      description: "Run on your own infrastructure with full control.",
      features: [
        "Face-centered cropping",
        "Word-synced subtitles",
        "Virality scoring",
        "All export presets",
        "Full source code access",
      ],
      cta: "View on GitHub",
      ctaHref: "https://github.com/FujiwaraChoki/viraclip",
      highlighted: false,
      isUnlimited: false,
    },
    {
      name: "Pro",
      price: `$${proPriceMonthly}`,
      period: "/month",
      description: "For power users who clip daily and need more generations.",
      features: [
        proGenerationsLabel,
        "Everything in Free",
        "B-Roll overlays",
        "Caption templates",
        "Platform export presets",
        "Priority processing",
        "Early access to new features",
      ],
      cta: "Upgrade to Pro",
      ctaHref: "",
      highlighted: true,
      isUnlimited: proLimit === 0,
    },
  ];
}

/* --- Landing Page --- */

export function LandingPage() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  return (
    <div style={{ background: "var(--bg)", minHeight: "100dvh" }}>
      {/* Nav */}
      <header className="sticky top-0 z-50" style={{ background: "var(--bg)", borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-center justify-between h-12 px-6" style={{ maxWidth: "var(--container-max)", margin: "0 auto" }}>
          <div className="flex items-center gap-2">
            <svg width="20" height="20" viewBox="0 0 28 28" fill="none" aria-hidden="true">
              <rect x="2" y="4" width="24" height="20" rx="5" stroke="#5e6ad2" strokeWidth="2" fill="none" />
              <path d="M11 10.5v7l6-3.5-6-3.5z" fill="#5e6ad2" />
            </svg>
            <span className="text-sm font-semibold" style={{ color: "var(--fg)" }}>ViraClip</span>
          </div>
          <nav className="hidden md:flex items-center gap-6">
            <a href="#features" className="text-sm" style={{ color: "var(--fg-2)" }}>Features</a>
            <a href="#pricing" className="text-sm" style={{ color: "var(--fg-2)" }}>Pricing</a>
            <Link href="/sign-in" className="text-sm" style={{ color: "var(--fg-2)" }}>Sign in</Link>
            <Link href="/sign-up" className="btn btn-primary" style={{ display: "inline-flex", alignItems: "center", gap: "var(--space-2)", padding: "6px 14px", borderRadius: "var(--radius-sm)", fontFamily: "var(--font-display)", fontSize: "var(--text-sm)", fontWeight: 510, fontFeatureSettings: '"cv01", "ss03"', lineHeight: 1, cursor: "pointer", border: "1px solid transparent", background: "var(--accent)", color: "#ffffff", textDecoration: "none", transition: "background-color var(--motion-fast) var(--ease-standard)" }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "var(--accent-hover)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "var(--accent)"; }}
            >Empezar gratis</Link>
          </nav>
          <button onClick={() => setMobileMenuOpen(!mobileMenuOpen)} className="md:hidden p-1.5 rounded-sm" style={{ color: "var(--fg-2)" }}>
            {mobileMenuOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>
        {mobileMenuOpen && (
          <div className="md:hidden px-6 py-4 space-y-3" style={{ borderTop: "1px solid var(--border)" }}>
            <a href="#features" className="block text-sm" style={{ color: "var(--fg-2)" }}>Features</a>
            <a href="#pricing" className="block text-sm" style={{ color: "var(--fg-2)" }}>Pricing</a>
            <Link href="/sign-in" className="block text-sm" style={{ color: "var(--fg-2)" }}>Sign in</Link>
            <Link href="/sign-up" className="block text-sm font-medium" style={{ color: "var(--accent)" }}>Empezar gratis</Link>
          </div>
        )}
      </header>

      <main>
        {/* HERO */}
        <section>
          <div className="hero-grid" style={{ maxWidth: "var(--container-max)", margin: "0 auto", padding: "var(--space-12) var(--gutter)", display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: "var(--space-12)", alignItems: "center" }}>
            <div className="stack-4">
              <p className="eyebrow">Para profesionales de seguros \u00b7 Espa\u00f1a</p>
              <h1>Convierte tus v\u00eddeos en clips virales.</h1>
              <p className="lead" style={{ maxWidth: "50ch" }}>
                ViraClip usa IA para transformar entrevistas, webinars y podcasts en clips verticales listos para TikTok, Reels y Shorts.
              </p>
              <div className="hero-actions" style={{ display: "flex", gap: "var(--space-3)", marginBlockStart: "var(--space-6)" }}>
                <Link href="/sign-up" className="btn btn-primary" style={{ display: "inline-flex", alignItems: "center", gap: "var(--space-2)", padding: "10px 20px", borderRadius: "var(--radius-sm)", fontFamily: "var(--font-display)", fontSize: "var(--text-sm)", fontWeight: 510, fontFeatureSettings: '"cv01", "ss03"', lineHeight: 1, cursor: "pointer", border: "1px solid transparent", background: "var(--accent)", color: "#ffffff", textDecoration: "none", transition: "background-color var(--motion-fast) var(--ease-standard)" }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = "var(--accent-hover)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "var(--accent)"; }}
                >Empezar gratis</Link>
                <a href="#features" className="btn btn-ghost" style={{ display: "inline-flex", alignItems: "center", gap: "var(--space-2)", padding: "10px 20px", borderRadius: "var(--radius-sm)", fontFamily: "var(--font-display)", fontSize: "var(--text-sm)", fontWeight: 510, fontFeatureSettings: '"cv01", "ss03"', lineHeight: 1, cursor: "pointer", border: "1px solid rgba(36,40,44,1)", background: "rgba(255,255,255,0.02)", color: "#e2e4e7", textDecoration: "none", transition: "background-color var(--motion-fast) var(--ease-standard)" }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.05)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.02)"; }}
                >Ver demo</a>
              </div>
            </div>
            <aside style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
              <div className="card" style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "var(--space-6)" }}>
                <p className="eyebrow" style={{ marginBottom: "var(--space-3)" }}>\u00daltimos clips generados</p>
                <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                  {[
                    { label: "C\u00f3mo optimizar tu p\u00f3liza de hogar", status: "done" },
                    { label: "Los 5 errores fiscales m\u00e1s comunes", status: "processing" },
                    { label: "Entrevista con experto en previsi\u00f3n social", status: "pending" },
                  ].map((item) => (
                    <div key={item.label} style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", fontSize: "var(--text-sm)", color: item.status === "done" ? "var(--fg-2)" : item.status === "processing" ? "var(--fg)" : "var(--meta)" }}>
                      <span style={{ width: 8, height: 8, borderRadius: item.status === "pending" ? 2 : "50%", background: item.status === "done" ? "#27a644" : item.status === "processing" ? "var(--accent)" : "rgba(255,255,255,0.1)", flexShrink: 0, animation: item.status === "processing" ? "pulse 1.8s ease-in-out infinite" : undefined }} />
                      {item.label}
                    </div>
                  ))}
                </div>
              </div>
            </aside>
          </div>
        </section>

        {/* SOCIAL PROOF */}
        <section style={{ borderTop: "1px solid var(--border)" }}>
          <div className="container" style={{ maxWidth: "var(--container-max)", margin: "0 auto", padding: "var(--space-8) var(--gutter)", textAlign: "center" }}>
            <p className="eyebrow" style={{ marginBottom: "var(--space-4)" }}>Usado por equipos de</p>
            <div style={{ display: "flex", justifyContent: "center", gap: "var(--space-6)", flexWrap: "wrap", color: "var(--meta)", fontSize: "var(--text-sm)" }}>
              <span>Mapfre</span><span>\u00b7</span><span>Allianz</span><span>\u00b7</span><span>Santander Seguros</span><span>\u00b7</span><span>AXA</span><span>\u00b7</span><span>Mutua Madrile\u00f1a</span>
            </div>
          </div>
        </section>

        {/* FEATURES */}
        <section id="features" style={{ borderTop: "1px solid var(--border)" }}>
          <div className="container" style={{ maxWidth: "var(--container-max)", margin: "0 auto", padding: "var(--space-12) var(--gutter)" }}>
            <div className="stack-3" style={{ marginBottom: "var(--space-6)" }}>
              <p className="eyebrow">Features</p>
              <h2 style={{ maxWidth: "28ch" }}>Everything you need to go viral</h2>
              <p className="lead" style={{ maxWidth: "44ch" }}>Professional-grade video clipping with AI intelligence at every step of the pipeline.</p>
            </div>
            <div className="features-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "var(--space-4)" }}>
              {FEATURES.map((feature) => (
                <article key={feature.title} className="card stack-3" style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "var(--space-6)", transition: "background-color var(--motion-base) var(--ease-standard)" }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.04)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.02)"; }}
                >
                  <feature.icon size={20} style={{ color: "var(--accent)" }} />
                  <h3>{feature.title}</h3>
                  <p className="body-sm">{feature.description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* PRICING */}
        <section id="pricing" style={{ borderTop: "1px solid var(--border)" }}>
          <div className="container" style={{ maxWidth: "var(--container-max)", margin: "0 auto", padding: "var(--space-12) var(--gutter)" }}>
            <div className="stack-3" style={{ marginBottom: "var(--space-8)", textAlign: "center" }}>
              <p className="eyebrow">Pricing</p>
              <h2>Simple pricing, no surprises</h2>
              <p className="lead" style={{ maxWidth: "44ch", margin: "0 auto" }}>Start free. Upgrade when you need unlimited power. Self-hosters get everything free, always.</p>
            </div>
            <div className="grid gap-6" style={{ gridTemplateColumns: "repeat(3, 1fr)", maxWidth: 900, margin: "0 auto" }}>
              {getPlans().map((plan) => (
                <div key={plan.name} className="card" style={{ background: "rgba(255,255,255,0.02)", border: plan.highlighted ? "1px solid var(--accent)" : "1px solid var(--border)", borderRadius: "var(--radius-md)", padding: "var(--space-6)", position: "relative", display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
                  {plan.highlighted && (
                    <span className="eyebrow" style={{ alignSelf: "flex-start", padding: "2px 10px", borderRadius: "var(--radius-pill)", background: "rgba(94,106,210,0.15)", color: "var(--accent)", border: "1px solid rgba(94,106,210,0.35)" }}>
                      M\u00e1s popular
                    </span>
                  )}
                  <div>
                    <p className="text-sm font-medium" style={{ color: "var(--fg)" }}>{plan.name}</p>
                    <p className="body-sm">{plan.description}</p>
                  </div>
                  <div className="flex items-baseline gap-1">
                    <span className="text-2xl font-semibold" style={{ color: "var(--fg)", fontWeight: 510, fontVariantNumeric: "tabular-nums" }}>{plan.price}</span>
                    <span className="text-sm" style={{ color: "var(--meta)" }}>{plan.period}</span>
                  </div>
                  <ul className="space-y-2" style={{ flex: 1 }}>
                    {plan.features.map((feature) => (
                      <li key={feature} className="flex items-start gap-2 text-sm" style={{ color: "var(--fg-2)" }}>
                        <Check size={14} style={{ color: "var(--success)", marginTop: 2, flexShrink: 0 }} />
                        <span>{feature}</span>
                      </li>
                    ))}
                  </ul>
                  {plan.ctaHref ? (
                    <a href={plan.ctaHref} target="_blank" rel="noopener noreferrer" style={{ textDecoration: "none" }}>
                      <button className="btn btn-ghost" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", gap: "var(--space-2)", padding: "8px 16px", borderRadius: "var(--radius-sm)", fontFamily: "var(--font-display)", fontSize: "var(--text-sm)", fontWeight: 510, fontFeatureSettings: '"cv01", "ss03"', lineHeight: 1, cursor: "pointer", border: "1px solid rgba(36,40,44,1)", background: "rgba(255,255,255,0.02)", color: "#e2e4e7", width: "100%", transition: "background-color var(--motion-fast) var(--ease-standard)" }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.05)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.02)"; }}
                      >
                        <Github size={14} /> {plan.cta} <ExternalLink size={12} style={{ opacity: 0.5 }} />
                      </button>
                    </a>
                  ) : (
                    <Link href={plan.highlighted ? "/sign-up" : "/sign-up"} style={{ textDecoration: "none" }}>
                      <button className={plan.highlighted ? "btn btn-primary" : "btn btn-ghost"} style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", gap: "var(--space-2)", padding: "8px 16px", borderRadius: "var(--radius-sm)", fontFamily: "var(--font-display)", fontSize: "var(--text-sm)", fontWeight: 510, fontFeatureSettings: '"cv01", "ss03"', lineHeight: 1, cursor: "pointer", border: plan.highlighted ? "1px solid transparent" : "1px solid rgba(36,40,44,1)", background: plan.highlighted ? "var(--accent)" : "rgba(255,255,255,0.02)", color: plan.highlighted ? "#ffffff" : "#e2e4e7", width: "100%", transition: "background-color var(--motion-fast) var(--ease-standard)" }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = plan.highlighted ? "var(--accent-hover)" : "rgba(255,255,255,0.05)"; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = plan.highlighted ? "var(--accent)" : "rgba(255,255,255,0.02)"; }}
                      >
                        {plan.cta}
                      </button>
                    </Link>
                  )}
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>

      {/* FOOTER */}
      <footer style={{ borderTop: "1px solid var(--border)", padding: "var(--space-8) 0" }}>
        <div className="container" style={{ maxWidth: "var(--container-max)", margin: "0 auto", padding: "0 var(--gutter)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div className="flex items-center gap-2">
            <svg width="16" height="16" viewBox="0 0 28 28" fill="none" aria-hidden="true">
              <rect x="2" y="4" width="24" height="20" rx="5" stroke="#5e6ad2" strokeWidth="2" fill="none" />
              <path d="M11 10.5v7l6-3.5-6-3.5z" fill="#5e6ad2" />
            </svg>
            <span className="text-xs" style={{ color: "var(--meta)" }}>ViraClip</span>
          </div>
          <div className="flex items-center gap-6">
            <a href="#features" className="text-sm" style={{ color: "var(--muted)", textDecoration: "none" }}
               onMouseEnter={(e) => { e.currentTarget.style.color = "var(--fg-2)"; }}
               onMouseLeave={(e) => { e.currentTarget.style.color = "var(--muted)"; }}
            >Features</a>
            <a href="#pricing" className="text-sm" style={{ color: "var(--muted)", textDecoration: "none" }}
               onMouseEnter={(e) => { e.currentTarget.style.color = "var(--fg-2)"; }}
               onMouseLeave={(e) => { e.currentTarget.style.color = "var(--muted)"; }}
            >Pricing</a>
            <span className="text-xs" style={{ color: "var(--meta)" }}>\u00a9 2026 ViraClip. All rights reserved.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
