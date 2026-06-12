import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Only use standalone output for production builds (next build + next start).
  // In development (next dev), standalone output is incompatible and can cause
  // erratic behavior or startup failures.
  ...(process.env.NODE_ENV === "production" ? { output: "standalone" as const } : {}),

  // Skip ESLint during builds (generated Prisma code causes lint errors)
  eslint: {
    ignoreDuringBuilds: true,
  },

  // TypeScript error handling.
  // Bun's TypeScript cannot resolve ESM barrel exports from lucide-react
  // ("Cannot find name 'Zap'"). This is a Bun limitation, not a real code error.
  // Set VIRACLIP_FRONTEND_IGNORE_TS_ERRORS=true to suppress (local dev only).
  // In CI/production, keep this false to catch real type errors.
  typescript: {
    ignoreBuildErrors:
      process.env.VIRACLIP_FRONTEND_IGNORE_TS_ERRORS === "true",
  },

  // The worker writes large render files into ./outputs which is volume-mounted
  // INSIDE the Next project root (/app/outputs). Without this exclusion the dev
  // watcher ingests every chunk written during a render, stalling requests and
  // bloating memory.
  webpack: (config, { dev }) => {
    if (dev) {
      config.watchOptions = {
        ...config.watchOptions,
        ignored: [
          "**/node_modules/**",
          "**/.git/**",
          "**/outputs/**",
          "**/.next/**",
        ],
      };
    }
    return config;
  },

  async rewrites() {
    return [
      {
        source: "/js/script.js",
        destination: "https://datafa.st/js/script.js",
      },
      {
        source: "/api/events",
        destination: "https://datafa.st/api/events",
      },
    ];
  },
};

export default nextConfig;
