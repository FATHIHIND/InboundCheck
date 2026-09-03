"use client";

import React, { useEffect, useRef } from "react";
import { useCanvasOptimization } from "@/hooks/useCanvasOptimization";

export default function RadarPulseCanvas({ className = "" }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const { isVisibleRef, prefersReducedMotionRef } = useCanvasOptimization(canvasRef);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animId: number;
    let angle = 0;
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

    // 10 RBL Server nodes placed radially around center
    const blips = Array.from({ length: 10 }).map((_, i) => {
      const a = (i / 10) * Math.PI * 2 + 0.3;
      const dist = 35 + (i % 3) * 22;
      return {
        angle: a,
        dist,
        name: `RBL_${i + 1}`,
      };
    });

    const render = () => {
      if (!isVisibleRef.current) {
        animId = requestAnimationFrame(render);
        return;
      }

      angle += 0.03;
      const w = canvas.width / dpr;
      const h = canvas.height / dpr;
      ctx.clearRect(0, 0, w, h);

      const cx = w / 2;
      const cy = h / 2;
      const maxR = Math.min(w, h) * 0.42;

      // Draw concentric radar rings
      ctx.lineWidth = 1;
      for (let r = 1; r <= 3; r++) {
        const rad = (maxR / 3) * r;
        ctx.strokeStyle = "rgba(16, 185, 129, 0.15)";
        ctx.beginPath();
        ctx.arc(cx, cy, rad, 0, Math.PI * 2);
        ctx.stroke();
      }

      // Draw crosshairs
      ctx.strokeStyle = "rgba(16, 185, 129, 0.12)";
      ctx.beginPath();
      ctx.moveTo(cx - maxR, cy);
      ctx.lineTo(cx + maxR, cy);
      ctx.moveTo(cx, cy - maxR);
      ctx.lineTo(cx, cy + maxR);
      ctx.stroke();

      // Sweeping radar beam gradient
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(angle);

      const grad = ctx.createConicGradient(0, 0, 0);
      grad.addColorStop(0, "rgba(16, 185, 129, 0.3)");
      grad.addColorStop(0.15, "rgba(16, 185, 129, 0.05)");
      grad.addColorStop(0.3, "rgba(16, 185, 129, 0)");

      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.arc(0, 0, maxR, -0.5, 0);
      ctx.closePath();
      ctx.fill();
      ctx.restore();

      // Render 10 RBL Blips
      blips.forEach((blip) => {
        const bx = cx + Math.cos(blip.angle) * blip.dist;
        const by = cy + Math.sin(blip.angle) * blip.dist;

        // Angle difference relative to sweep
        const diff = (angle - blip.angle + Math.PI * 4) % (Math.PI * 2);
        const intensity = diff < 0.8 ? 1 - diff / 0.8 : 0.2;

        ctx.fillStyle = `rgba(52, 211, 153, ${intensity})`;
        ctx.beginPath();
        ctx.arc(bx, by, 2.5, 0, Math.PI * 2);
        ctx.fill();

        ctx.strokeStyle = `rgba(16, 185, 129, ${intensity * 0.4})`;
        ctx.beginPath();
        ctx.arc(bx, by, 5, 0, Math.PI * 2);
        ctx.stroke();
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
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className={`absolute inset-0 w-full h-full pointer-events-none ${className}`}
    />
  );
}
