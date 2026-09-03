"use client";

import React, { useEffect, useRef, useState } from "react";
import { useCanvasOptimization } from "@/hooks/useCanvasOptimization";

export default function ScoreGauge3DCanvas({
  score = 94,
  className = "",
}: {
  score?: number;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [tilt, setTilt] = useState({ x: 0, y: 0 });
  const { isVisibleRef, prefersReducedMotionRef } = useCanvasOptimization(canvasRef);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    const ny = ((e.clientY - rect.top) / rect.height) * 2 - 1;
    setTilt({ x: ny * -8, y: nx * 8 });
  };

  const handleMouseLeave = () => {
    setTilt({ x: 0, y: 0 });
  };

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

    // 3D Ring Mesh Particles (60 spatial particles orbiting in pitch/yaw)
    const PARTICLE_COUNT = 65;
    const particles = Array.from({ length: PARTICLE_COUNT }).map((_, i) => {
      const angle = (i / PARTICLE_COUNT) * Math.PI * 2;
      return {
        angle,
        radius: 64 + (i % 4) * 4,
        size: 1.2 + Math.random() * 1.8,
        speed: 0.009 + (i % 3) * 0.003,
      };
    });

    const render = () => {
      if (!isVisibleRef.current) {
        animId = requestAnimationFrame(render);
        return;
      }

      time += 0.02;
      const w = canvas.width / dpr;
      const h = canvas.height / dpr;
      ctx.clearRect(0, 0, w, h);

      const cx = w / 2;
      const cy = h / 2;
      const radius = 68;

      // 1. Radiant Glowing Core Halo
      const pulse = (Math.sin(time * 2.5) + 1) / 2;
      const coreGlow = ctx.createRadialGradient(cx, cy, 10, cx, cy, radius + 22 + pulse * 8);
      coreGlow.addColorStop(0, "rgba(16, 185, 129, 0.25)");
      coreGlow.addColorStop(0.4, "rgba(16, 185, 129, 0.08)");
      coreGlow.addColorStop(1, "rgba(16, 185, 129, 0)");

      ctx.fillStyle = coreGlow;
      ctx.beginPath();
      ctx.arc(cx, cy, radius + 25, 0, Math.PI * 2);
      ctx.fill();

      // 2. Base Radial Gauge Track
      ctx.lineWidth = 8;
      ctx.strokeStyle = "rgba(255, 255, 255, 0.06)";
      ctx.beginPath();
      ctx.arc(cx, cy, radius, Math.PI * 0.75, Math.PI * 2.25);
      ctx.stroke();

      // 3. Illuminated Emerald Arc based on Score
      const targetPercent = Math.min(100, Math.max(0, score)) / 100;
      const startAngle = Math.PI * 0.75;
      const endAngle = startAngle + targetPercent * (Math.PI * 1.5);

      const arcGrad = ctx.createLinearGradient(cx - radius, cy, cx + radius, cy);
      arcGrad.addColorStop(0, "#059669");
      arcGrad.addColorStop(0.5, "#10B981");
      arcGrad.addColorStop(1, "#34D399");

      ctx.lineWidth = 9;
      ctx.strokeStyle = arcGrad;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.arc(cx, cy, radius, startAngle, endAngle);
      ctx.stroke();

      // 4. 3D Orbiting Mesh Particles
      particles.forEach((p) => {
        p.angle += p.speed;
        const px = cx + Math.cos(p.angle) * p.radius;
        const py = cy + Math.sin(p.angle * 0.7 + time * 0.4) * (p.radius * 0.45);
        const depthAlpha = (Math.sin(p.angle) + 1) / 2 * 0.7 + 0.3;

        ctx.fillStyle = `rgba(52, 211, 153, ${depthAlpha * 0.85})`;
        ctx.beginPath();
        ctx.arc(px, py, p.size, 0, Math.PI * 2);
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
  }, [score]);

  return (
    <div
      ref={containerRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      style={{
        transform: `perspective(1000px) rotateX(${tilt.x.toFixed(2)}deg) rotateY(${tilt.y.toFixed(2)}deg)`,
        transition: "transform 0.15s cubic-bezier(0.2, 0, 0.2, 1)",
      }}
      className={`relative flex items-center justify-center ${className}`}
    >
      <canvas ref={canvasRef} className="w-full h-full block pointer-events-none" />
      <div className="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none">
        <span className="text-3xl font-extrabold text-white font-mono tracking-tight drop-shadow-[0_0_12px_rgba(16,185,129,0.6)]">
          {score}
        </span>
        <span className="text-[10px] font-mono font-bold tracking-widest text-emerald-400 uppercase">
          / 100 HEALTH
        </span>
      </div>
    </div>
  );
}
