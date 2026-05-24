"use client";

import { Upload, Cpu, Video } from "lucide-react";
import { Card } from "./card";

/* ─────────────────────────────────────────────
   FeaturesGrid — "Cómo funciona ViraClip" onboarding section
   Exact layout from Linear's components.html features-grid
   Source: https://github.com/nexu-io/open-design/blob/main/design-systems/linear-app/components.html
   ───────────────────────────────────────────── */

export function FeaturesGrid() {
  return (
    <section>
      <div className="stack-3" style={{ marginBottom: "var(--space-6)" }}>
        <p className="eyebrow">Cómo funciona ViraClip</p>
        <h2 style={{ maxWidth: "28ch" }}>
          De tu grabación al clip viral en tres pasos.
        </h2>
      </div>

      <div
        className="features-grid"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: "var(--space-4)",
        }}
      >
        {/* Step 1 */}
        <Card variant="default" padding="md" as="article">
          <div className="stack-3">
            <Upload size={20} style={{ color: "var(--accent)" }} />
            <h3>Sube tu grabación</h3>
            <p className="body-sm">
              MP4, MOV o AVI. Entrevistas, webinars, podcasts sobre seguros.
            </p>
          </div>
        </Card>

        {/* Step 2 */}
        <Card variant="default" padding="md" as="article">
          <div className="stack-3">
            <Cpu size={20} style={{ color: "var(--accent)" }} />
            <h3>La IA detecta los momentos</h3>
            <p className="body-sm">
              Identifica los fragmentos con mayor retención y valor informativo.
            </p>
          </div>
        </Card>

        {/* Step 3 */}
        <Card variant="default" padding="md" as="article">
          <div className="stack-3">
            <Video size={20} style={{ color: "var(--accent)" }} />
            <h3>Exporta clips verticales</h3>
            <p className="body-sm">
              9:16 listos para TikTok, Reels y Shorts con subtítulos en español.
            </p>
          </div>
        </Card>
      </div>
    </section>
  );
}
