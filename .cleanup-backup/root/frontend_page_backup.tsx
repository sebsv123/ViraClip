"use client";

import { useState } from "react";
import { 
  Zap, 
  Sparkles, 
  Scissors, 
  Music, 
  Subtitles, 
  Play,
  Github,
  Twitter,
  CheckCircle2,
  ArrowRight,
  Video,
  Wand2,
  Upload,
  Shield,
  Cpu,
  Globe,
  Layers,
  Rocket,
  Star
} from "lucide-react";
import Link from "next/link";

// Neon Button Component
function NeonButton({ 
  children, 
  variant = "primary", 
  size = "md",
  className = "",
  glowing = false,
  ...props 
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { 
  variant?: "primary" | "secondary" | "accent" | "ghost" | "outline",
  size?: "sm" | "md" | "lg",
  glowing?: boolean
}) {
  const variants = {
    primary: "bg-[hsl(180,100%,50%)] text-[hsl(220,25%,4%)] hover:shadow-[0_0_30px_-5px_hsl(180,100%,50%,0.5)]",
    secondary: "bg-[hsl(270,100%,65%)] text-white hover:shadow-[0_0_30px_-5px_hsl(270,100%,65%,0.5)]",
    accent: "bg-[hsl(330,100%,60%)] text-white hover:shadow-[0_0_30px_-5px_hsl(330,100%,60%,0.5)]",
    ghost: "bg-transparent border border-white/20 hover:bg-white/10 text-white",
    outline: "bg-transparent border-2 border-[hsl(180,100%,50%)] text-[hsl(180,100%,50%)] hover:bg-[hsl(180,100%,50%)]/10",
  };
  const sizes = { sm: "px-4 py-2 text-sm", md: "px-6 py-3 text-base", lg: "px-8 py-4 text-lg" };
  
  return (
    <button className={`relative inline-flex items-center justify-center gap-2 font-semibold rounded-xl transition-all duration-300 ${variants[variant]} ${sizes[size]} ${glowing ? "shadow-[0_0_40px_-10px_hsl(180,100%,50%,0.5)]" : ""} ${className}`} {...props}>
      {children}
    </button>
  );
}

// Feature Card Component
function FeatureCard({ icon: Icon, title, description, color, delay }: { icon: any, title: string, description: string, color: string, delay: number }) {
  const colorMap: Record<string, string> = {
    cyan: "from-cyan-400/20 to-cyan-600/20 border-cyan-500/30",
    pink: "from-pink-400/20 to-pink-600/20 border-pink-500/30",
    purple: "from-purple-400/20 to-purple-600/20 border-purple-500/30",
    lime: "from-green-400/20 to-green-600/20 border-green-500/30",
    amber: "from-amber-400/20 to-amber-600/20 border-amber-500/30",
  };
  
  const iconColorMap: Record<string, string> = {
    cyan: "text-cyan-400 bg-cyan-400/20",
    pink: "text-pink-400 bg-pink-400/20",
    purple: "text-purple-400 bg-purple-400/20",
    lime: "text-green-400 bg-green-400/20",
    amber: "text-amber-400 bg-amber-400/20",
  };

  return (
    <div 
      className={`group relative p-6 rounded-2xl bg-gradient-to-br ${colorMap[color]} border backdrop-blur-sm hover:scale-105 transition-all duration-500`}
    >
      <div className={`w-14 h-14 rounded-xl ${iconColorMap[color]} flex items-center justify-center mb-4 group-hover:scale-110 transition-transform`}>
        <Icon className="w-7 h-7" />
      </div>
      <h3 className="text-xl font-bold mb-2 text-white">{title}</h3>
      <p className="text-sm text-gray-400 leading-relaxed">{description}</p>
    </div>
  );
}

// Stats Card
function StatCard({ value, label }: { value: string, label: string }) {
  return (
    <div className="text-center p-6 rounded-2xl bg-white/5 border border-white/10 backdrop-blur-sm hover:border-[hsl(180,100%,50%)]/50 transition-colors">
      <div className="text-3xl md:text-4xl font-bold bg-gradient-to-r from-cyan-400 via-purple-400 to-pink-400 bg-clip-text text-transparent mb-1">{value}</div>
      <div className="text-sm text-gray-500">{label}</div>
    </div>
  );
}

export default function LandingPage() {
  const features = [
    { icon: Scissors, title: "AI Clip Detection", description: "Advanced machine learning finds the most viral moments in your videos automatically", color: "cyan" },
    { icon: Subtitles, title: "Smart Subtitles", description: "Animated, emoji-enhanced captions with perfect timing and viral styling", color: "pink" },
    { icon: Music, title: "B-Roll & Music", description: "Auto-matched stock footage and trending audio from Pexels and more", color: "purple" },
    { icon: Wand2, title: "One-Click Magic", description: "Upload once, get dozens of viral-ready clips instantly with zero editing", color: "lime" },
    { icon: Shield, title: "Self-Hosted", description: "100% privacy-focused. Your videos never leave your infrastructure", color: "amber" },
    { icon: Globe, title: "Multi-Platform", description: "Optimized exports for TikTok, Reels, Shorts, and more with one click", color: "cyan" },
  ];

  const stats = [
    { value: "10x", label: "Faster Editing" },
    { value: "50+", label: "Clips Per Video" },
    { value: "100%", label: "Self-Hosted" },
    { value: "0", label: "Watermarks" },
  ];

  return (
    <div className="min-h-screen bg-[#0a0a0f] text-white overflow-x-hidden font-sans">
      {/* Animated Background */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-0 left-1/4 w-[500px] h-[500px] bg-cyan-500/10 rounded-full blur-[120px]" />
        <div className="absolute top-1/3 right-0 w-[600px] h-[600px] bg-purple-500/10 rounded-full blur-[150px]" />
        <div className="absolute bottom-0 left-1/3 w-[400px] h-[400px] bg-pink-500/10 rounded-full blur-[100px]" />
      </div>

      {/* Navigation */}
      <nav className="relative z-50 border-b border-white/5 bg-[#0a0a0f]/80 backdrop-blur-xl">
        <div className="max-w-7xl mx-auto px-6 py-4">
          <div className="flex items-center justify-between">
            <Link href="/" className="flex items-center gap-3 group">
              <div className="relative w-10 h-10">
                <div className="absolute inset-0 bg-gradient-to-br from-cyan-400 via-purple-500 to-pink-500 rounded-xl blur-sm opacity-75 group-hover:opacity-100 transition-opacity" />
                <div className="absolute inset-[2px] bg-[#0a0a0f] rounded-xl flex items-center justify-center">
                  <Zap className="w-5 h-5 text-cyan-400" />
                </div>
              </div>
              <span className="text-xl font-bold tracking-tight">
                Vira<span className="bg-gradient-to-r from-cyan-400 to-purple-400 bg-clip-text text-transparent">Clip</span>
              </span>
            </Link>

            <div className="hidden md:flex items-center gap-8">
              <Link href="#features" className="text-sm text-gray-400 hover:text-white transition-colors">Features</Link>
              <Link href="#how-it-works" className="text-sm text-gray-400 hover:text-white transition-colors">How it Works</Link>
              <Link href="#pricing" className="text-sm text-gray-400 hover:text-white transition-colors">Pricing</Link>
              <Link href="https://github.com" className="text-sm text-gray-400 hover:text-white transition-colors">
                <Github className="w-5 h-5" />
              </Link>
            </div>

            <div className="flex items-center gap-3">
              <Link href="/sign-in">
                <NeonButton variant="ghost" size="sm">Sign In</NeonButton>
              </Link>
              <Link href="/sign-up" className="hidden sm:block">
                <NeonButton size="sm">Get Started</NeonButton>
              </Link>
            </div>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="relative z-10 pt-20 pb-32">
        <div className="max-w-7xl mx-auto px-6">
          <div className="text-center max-w-4xl mx-auto">
            <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/5 border border-white/10 mb-8">
              <Rocket className="w-4 h-4 text-cyan-400" />
              <span className="text-sm text-gray-400">Now with Quantum-Inspired Viral Detection</span>
              <ArrowRight className="w-4 h-4 text-cyan-400" />
            </div>

            <h1 className="text-5xl md:text-7xl font-bold leading-[1.1] mb-6">
              Turn Long Videos into{" "}
              <span className="bg-gradient-to-r from-cyan-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">Viral Shorts</span>
              <br />
              <span className="text-gray-500">in Seconds</span>
            </h1>

            <p className="text-lg md:text-xl text-gray-400 max-w-2xl mx-auto mb-10">
              AI-powered clip generator with quantum-inspired algorithms, swarm evolution engine, and advanced engagement prediction. Self-hosted with no watermarks.
            </p>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-16">
              <Link href="/sign-up">
                <NeonButton size="lg" glowing>
                  <Play className="w-5 h-5" />
                  Start Creating Free
                </NeonButton>
              </Link>
              <NeonButton variant="outline" size="lg">
                <Video className="w-5 h-5" />
                Watch Demo
              </NeonButton>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 max-w-3xl mx-auto">
              {stats.map((stat, i) => (
                <StatCard key={i} value={stat.value} label={stat.label} />
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="relative z-10 py-24 bg-gradient-to-b from-transparent via-white/[0.02] to-transparent">
        <div className="max-w-7xl mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-5xl font-bold mb-4">
              Powered by <span className="bg-gradient-to-r from-cyan-400 to-purple-400 bg-clip-text text-transparent">Advanced AI</span>
            </h2>
            <p className="text-gray-400 max-w-xl mx-auto">
              State-of-the-art machine learning models for viral content creation
            </p>
          </div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {features.map((f, i) => (
              <FeatureCard key={i} {...f} delay={i * 100} />
            ))}
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section id="how-it-works" className="relative z-10 py-24">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-5xl font-bold mb-4">
              How It <span className="bg-gradient-to-r from-cyan-400 to-purple-400 bg-clip-text text-transparent">Works</span>
            </h2>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            {[
              { step: "01", title: "Upload", desc: "Drop in any video up to 4K. YouTube links or file uploads supported.", icon: Upload },
              { step: "02", title: "AI Analysis", desc: "Our AI finds viral moments, transcribes audio, and scores engagement.", icon: Cpu },
              { step: "03", title: "Get Clips", desc: "Download dozens of edited clips ready for all social platforms.", icon: Sparkles },
            ].map((item, i) => {
              const Icon = item.icon;
              return (
                <div key={i} className="relative text-center group">
                  <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-cyan-500/20 to-purple-500/20 border border-cyan-500/30 flex items-center justify-center relative group-hover:scale-110 transition-transform">
                    <span className="absolute -top-3 -right-3 w-8 h-8 rounded-full bg-gradient-to-br from-cyan-400 to-purple-500 text-xs font-bold flex items-center justify-center">
                      {item.step}
                    </span>
                    <Icon className="w-8 h-8 text-cyan-400" />
                  </div>
                  <h3 className="text-xl font-bold mb-2">{item.title}</h3>
                  <p className="text-gray-400">{item.desc}</p>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* Pricing Section */}
      <section id="pricing" className="relative z-10 py-24 bg-gradient-to-b from-transparent via-white/[0.02] to-transparent">
        <div className="max-w-5xl mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-5xl font-bold mb-4">
              Simple, <span className="bg-gradient-to-r from-cyan-400 to-purple-400 bg-clip-text text-transparent">Transparent</span> Pricing
            </h2>
            <p className="text-gray-400">Self-hosted freedom with optional cloud convenience</p>
          </div>

          <div className="grid md:grid-cols-2 gap-8 max-w-4xl mx-auto">
            <div className="p-8 rounded-2xl bg-white/5 border border-white/10 backdrop-blur-sm">
              <div className="flex items-center gap-3 mb-4">
                <Github className="w-6 h-6 text-gray-400" />
                <h3 className="text-xl font-bold">Open Source</h3>
              </div>
              <div className="text-4xl font-bold mb-2">Free</div>
              <p className="text-gray-400 mb-6">Self-host on your own machine</p>
              <ul className="space-y-3 mb-8">
                {["Unlimited clips", "All AI features", "Self-hosted", "No watermarks", "Community support"].map((item, i) => (
                  <li key={i} className="flex items-center gap-2 text-sm">
                    <CheckCircle2 className="w-4 h-4 text-cyan-400" />
                    {item}
                  </li>
                ))}
              </ul>
              <NeonButton variant="outline" className="w-full">
                <Github className="w-4 h-4" />
                View on GitHub
              </NeonButton>
            </div>

            <div className="relative p-8 rounded-2xl bg-gradient-to-br from-cyan-500/10 to-purple-500/10 border-2 border-cyan-500/50 backdrop-blur-sm">
              <div className="absolute -top-4 left-1/2 -translate-x-1/2 px-4 py-1 rounded-full bg-gradient-to-r from-cyan-400 to-purple-500 text-sm font-semibold">
                Recommended
              </div>
              <div className="flex items-center gap-3 mb-4">
                <Layers className="w-6 h-6 text-cyan-400" />
                <h3 className="text-xl font-bold">Cloud Hosted</h3>
              </div>
              <div className="text-4xl font-bold mb-2">$29<span className="text-lg text-gray-400">/mo</span></div>
              <p className="text-gray-400 mb-6">Fully managed, GPU-accelerated</p>
              <ul className="space-y-3 mb-8">
                {["Everything in Open Source", "GPU acceleration", "Priority processing", "Email support", "99.9% uptime SLA"].map((item, i) => (
                  <li key={i} className="flex items-center gap-2 text-sm">
                    <CheckCircle2 className="w-4 h-4 text-cyan-400" />
                    {item}
                  </li>
                ))}
              </ul>
              <NeonButton className="w-full" glowing>
                <Star className="w-4 h-4" />
                Get Started
              </NeonButton>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 py-12 border-t border-white/10">
        <div className="max-w-7xl mx-auto px-6">
          <div className="flex flex-col md:flex-row items-center justify-between gap-6">
            <div className="flex items-center gap-3">
              <div className="relative w-8 h-8">
                <div className="absolute inset-0 bg-gradient-to-br from-cyan-400 to-purple-500 rounded-lg" />
                <div className="absolute inset-[2px] bg-[#0a0a0f] rounded-lg flex items-center justify-center">
                  <Zap className="w-4 h-4 text-cyan-400" />
                </div>
              </div>
              <span className="font-bold">
                Vira<span className="text-cyan-400">Clip</span>
              </span>
            </div>
            
            <div className="flex items-center gap-6 text-sm text-gray-400">
              <Link href="/privacy" className="hover:text-white transition-colors">Privacy</Link>
              <Link href="/terms" className="hover:text-white transition-colors">Terms</Link>
              <Link href="https://github.com" className="hover:text-white transition-colors">
                <Github className="w-5 h-5" />
              </Link>
              <Link href="https://twitter.com" className="hover:text-white transition-colors">
                <Twitter className="w-5 h-5" />
              </Link>
            </div>
            
            <p className="text-sm text-gray-500">
              ® 2026 ViraClip. MIT License.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
