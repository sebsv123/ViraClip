import type { Metadata } from "next";
import "@/styles/base.css";
import "@/styles/typography.css";
import "@/styles/skeleton.css";
import "./globals.css";
import { PerformanceDisplay, ReportWebVitals } from "@/lib/performance";

export const metadata: Metadata = {
  title: "ViraClip - AI-Powered Viral Clip Generator",
  description: "Turn long videos into viral shorts with AI. Self-hosted, no watermarks, unlimited clips.",
  keywords: ["viral clips", "video editing", "AI", "TikTok", "Reels", "Shorts"],
  authors: [{ name: "ViraClip" }],
  openGraph: {
    title: "ViraClip - AI-Powered Viral Clip Generator",
    description: "Turn long videos into viral shorts with AI",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="dark" className="dark">
      <body>
        <ReportWebVitals />
        {children}
        <PerformanceDisplay />
      </body>
    </html>
  );
}
