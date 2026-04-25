"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { ArrowRight, Play, Video } from "lucide-react";
import { StarField } from "@/components/ui/star-field";
import { ShimmerButton } from "@/components/ui/shimmer-button";

export default function LandingPage() {
  return (
    <main className="relative min-h-screen bg-[#0A0A0F] overflow-x-hidden">
      <StarField count={50} />
      
      {/* Background gradients */}
      <div className="fixed inset-0 -z-10">
        <div className="absolute top-0 left-1/4 w-[600px] h-[600px] bg-violet-600/10 rounded-full blur-[150px]" />
        <div className="absolute top-1/3 right-0 w-[500px] h-[500px] bg-fuchsia-600/10 rounded-full blur-[150px]" />
      </div>

      {/* Navigation */}
      <nav className="fixed top-0 left-0 right-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16 mt-4 px-6 rounded-full bg-white/5 backdrop-blur-xl border border-white/10">
            <Link href="/" className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-500 flex items-center justify-center">
                <Video className="w-4 h-4 text-white" />
              </div>
              <span className="text-lg font-semibold text-white">ViraClip</span>
            </Link>
            
            <div className="hidden md:flex items-center gap-8">
              <Link href="#features" className="text-sm text-white/60 hover:text-white transition-colors">Features</Link>
              <Link href="/dashboard" className="text-sm text-white/60 hover:text-white transition-colors">Dashboard</Link>
            </div>
            
            <div className="flex items-center gap-4">
              <Link href="/sign-in" className="text-sm text-white/60 hover:text-white transition-colors hidden sm:block">
                Sign In
              </Link>
              <Link href="/dashboard">
                <ShimmerButton>Get Started</ShimmerButton>
              </Link>
            </div>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="relative z-10 pt-32 pb-20 lg:pt-40 lg:pb-32">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            className="text-center"
          >
            <motion.div 
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/5 border border-white/10 mb-8"
            >
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-violet-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-violet-500"></span>
              </span>
              <span className="text-sm text-white/70">Now with AI B-Roll Generation</span>
            </motion.div>

            <motion.h1 
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-semibold text-white leading-[1.1] mb-6"
            >
              Turn Long Videos into{" "}
              <span className="bg-gradient-to-r from-violet-400 via-fuchsia-400 to-pink-400 bg-clip-text text-transparent">
                Viral Shorts
              </span>
            </motion.h1>

            <motion.p 
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
              className="text-lg md:text-xl text-white/50 max-w-2xl mx-auto mb-10"
            >
              AI-powered clip generator that automatically finds viral moments, 
              adds B-roll, captions, and music. No editing skills required.
            </motion.p>

            <motion.div 
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 }}
              className="flex flex-col sm:flex-row items-center justify-center gap-4"
            >
              <Link href="/dashboard">
                <ShimmerButton className="w-full sm:w-auto">
                  <Play className="w-4 h-4" />
                  Start Creating Free
                </ShimmerButton>
              </Link>
              <ShimmerButton variant="outline" className="w-full sm:w-auto">
                Watch Demo
              </ShimmerButton>
            </motion.div>
          </motion.div>
        </div>
      </section>

      {/* Stats Section */}
      <section className="relative z-10 py-12 border-y border-white/5">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
            {[
              { value: "500K+", label: "Clips Generated" },
              { value: "10K+", label: "Active Creators" },
              { value: "99%", label: "Uptime" },
              { value: "4.9/5", label: "User Rating" },
            ].map((stat, i) => (
              <motion.div
                key={stat.label}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.1 }}
                className="text-center"
              >
                <div className="text-2xl md:text-3xl font-bold text-white mb-1">{stat.value}</div>
                <div className="text-sm text-white/40">{stat.label}</div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="relative z-10 py-24 lg:py-32">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-center mb-16"
          >
            <h2 className="text-3xl md:text-4xl lg:text-5xl font-semibold text-white mb-4">
              Powered by{" "}
              <span className="bg-gradient-to-r from-violet-400 to-fuchsia-400 bg-clip-text text-transparent">
                Advanced AI
              </span>
            </h2>
            <p className="text-lg text-white/40 max-w-2xl mx-auto">
              State-of-the-art machine learning models for viral content creation
            </p>
          </motion.div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[
              { title: "AI Clip Extraction", desc: "Automatically detects and extracts the most viral moments from long videos." },
              { title: "B-Roll Generation", desc: "Generate cinematic B-roll footage with AI to enhance your content." },
              { title: "Auto-Captions", desc: "AI-powered captions with perfect timing and stylish fonts." },
              { title: "Color Grading", desc: "Professional color grading LUTs applied automatically." },
              { title: "Multi-Format Export", desc: "Export in 9:16 for TikTok/Reels, 16:9 for YouTube." },
              { title: "Auto-Translation", desc: "Translate captions and generate voiceovers in 50+ languages." },
            ].map((feature, i) => (
              <motion.div
                key={feature.title}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: i * 0.1 }}
                className="p-6 rounded-2xl bg-white/[0.02] border border-white/10 hover:border-violet-500/30 transition-colors"
              >
                <h3 className="text-lg font-semibold text-white mb-2">{feature.title}</h3>
                <p className="text-sm text-white/50">{feature.desc}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="relative z-10 py-24">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="relative p-12 md:p-16 rounded-3xl bg-white/[0.02] border border-white/10 text-center overflow-hidden">
            <div className="absolute inset-0 bg-gradient-to-r from-violet-600/20 to-fuchsia-600/20 blur-3xl" />
            <div className="relative z-10">
              <h2 className="text-3xl md:text-4xl lg:text-5xl font-semibold text-white mb-6">
                Ready to go viral?
              </h2>
              <p className="text-lg text-white/50 mb-8 max-w-xl mx-auto">
                Join thousands of creators who are already saving hours of editing time.
              </p>
              <Link href="/dashboard">
                <ShimmerButton size="lg">
                  Start Creating Free
                  <ArrowRight className="w-5 h-5" />
                </ShimmerButton>
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 py-12 border-t border-white/5">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex flex-col md:flex-row items-center justify-between gap-4">
            <Link href="/" className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-500 flex items-center justify-center">
                <Video className="w-4 h-4 text-white" />
              </div>
              <span className="text-lg font-semibold text-white">ViraClip</span>
            </Link>
            <p className="text-sm text-white/30">
              © {new Date().getFullYear()} ViraClip. All rights reserved.
            </p>
          </div>
        </div>
      </footer>
    </main>
  );
}

