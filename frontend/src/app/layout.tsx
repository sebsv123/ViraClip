import type { Metadata } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import "./globals.css";
import { PerformanceDisplay, ReportWebVitals } from "@/lib/performance";

const inter = Inter({ 
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap", // Optimize font loading
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-space-grotesk",
  display: "swap", // Optimize font loading
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
      <body className={`${inter.variable} ${spaceGrotesk.variable} font-sans antialiased`}>
        <ReportWebVitals />
        {children}
        <PerformanceDisplay />
      </body>
    </html>
  );
}
