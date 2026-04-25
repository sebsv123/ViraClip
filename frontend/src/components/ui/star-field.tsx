"use client";

import { useEffect, useRef } from "react";
import { motion } from "framer-motion";

interface Star {
  x: number;
  y: number;
  size: number;
  opacity: number;
  speed: number;
  phase: number;
}

export function StarField({
  count = 30,
  className = ""
}: {
  count?: number;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d", { alpha: true, willReadFrequently: false });
    if (!ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const resize = () => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    const stars: Star[] = [];
    const w = window.innerWidth;
    const h = window.innerHeight;
    for (let i = 0; i < count; i++) {
      stars.push({
        x: Math.random() * w,
        y: Math.random() * h,
        size: Math.random() * 1.5 + 0.5,
        opacity: Math.random() * 0.4 + 0.2,
        speed: Math.random() * 0.015 + 0.005,
        phase: Math.random() * Math.PI * 2,
      });
    }

    let animationId: number;
    let lastFrame = 0;
    const FRAME_INTERVAL = 1000 / 24; // cap at ~24fps for background

    const animate = (time: number) => {
      animationId = requestAnimationFrame(animate);
      if (time - lastFrame < FRAME_INTERVAL) return;
      lastFrame = time;

      const W = window.innerWidth;
      const H = window.innerHeight;
      ctx.clearRect(0, 0, W, H);

      const now = time * 0.001;

      // batch draw same-size stars
      ctx.fillStyle = "#ffffff";
      for (const star of stars) {
        star.y -= star.speed;
        if (star.y < -2) {
          star.y = H + 2;
          star.x = Math.random() * W;
        }

        const twinkle = Math.sin(now * star.speed * 0.5 + star.phase) * 0.3 + 0.7;
        const alpha = star.opacity * twinkle;
        const x = star.x;
        const y = star.y;
        const s = star.size;

        ctx.globalAlpha = alpha;
        ctx.beginPath();
        ctx.arc(x, y, s, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;
    };

    animationId = requestAnimationFrame(animate);

    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(animationId);
    };
  }, [count]);

  return (
    <motion.canvas
      ref={canvasRef}
      className={`fixed inset-0 pointer-events-none ${className}`}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 1.5 }}
    />
  );
}
