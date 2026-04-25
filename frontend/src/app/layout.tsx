import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { PerformanceDisplay, ReportWebVitals } from "@/lib/performance";

const geistSans = Geist({ 
  subsets: ["latin"],
  variable: "--font-geist-sans",
  display: "swap",
});

const geistMono = Geist_Mono({
  subsets: ["latin"],
  variable: "--font-geist-mono",
  display: "swap",
});

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
    <html lang="en" className="dark">
      <body className={`${geistSans.variable} ${geistMono.variable} font-sans antialiased`}>
        <ReportWebVitals />
        {children}
        <PerformanceDisplay />
      </body>
    </html>
  );
}
