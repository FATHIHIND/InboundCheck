"use client";

import React, { useEffect, useRef } from "react";
import { useCanvasOptimization } from "@/hooks/useCanvasOptimization";

export default function ParticleStreamCanvas({
  isOptimizing = false,
  className = "",
}: {
  isOptimizing?: boolean;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const { isVisibleRef, prefersReducedMotionRef } = useCanvasOptimization(canvasRef);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;
    let time = 0;
    const dpr = Math.min(typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1, 2);

    const resize = () => {
      if (!canvas || !canvas.parentElement) return;
      const rect = canvas.parentElement.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);
    };

    resize();
    window.addEventListener("resize", resize);

    const PARTICLE_COUNT = 45;
    const particles = Array.from({ length: PARTICLE_COUNT }).map(() => ({
      x: Math.random(),
      y: Math.random(),
      speed: 0.01 + Math.random() * 0.02,
      size: 1.2 + Math.random() * 1.8,
      alpha: 0.2 + Math.random() * 0.8,
    }));

    const render = () => {
      if (!isVisibleRef.current) {
        animId = requestAnimationFrame(render);
        return;
      }

      time += 0.02;
      const w = canvas.width / dpr;
      const h = canvas.height / dpr;
      ctx.clearRect(0, 0, w, h);

      particles.forEach((p) => {
        p.x += isOptimizing ? p.speed * 2.5 : p.speed * 0.5;
        if (p.x > 1) p.x = 0;

        const px = p.x * w;
        const py = p.y * h + Math.sin(time + p.x * 10) * 12;

        ctx.fillStyle = isOptimizing
          ? `rgba(52, 211, 153, ${p.alpha})`
          : `rgba(16, 185, 129, ${p.alpha * 0.4})`;

        ctx.beginPath();
        ctx.arc(px, py, p.size * (isOptimizing ? 1.5 : 1.0), 0, Math.PI * 2);
        ctx.fill();
      });

      if (!prefersReducedMotionRef.current) {
        animId = requestAnimationFrame(render);
      }
    };

    render();

    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(animId);
    };
  }, [isOptimizing]);

  return (
    <canvas
      ref={canvasRef}
      className={`pointer-events-none absolute inset-0 w-full h-full ${className}`}
    />
  );
}
