"use client";

import React, { useEffect, useRef } from "react";
import { useCanvasOptimization } from "@/hooks/useCanvasOptimization";

export default function WireframeGridCanvas({ className = "" }: { className?: string }) {
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

    const render = () => {
      if (!isVisibleRef.current) {
        animId = requestAnimationFrame(render);
        return;
      }

      time += 0.015;
      const w = canvas.width / dpr;
      const h = canvas.height / dpr;
      ctx.clearRect(0, 0, w, h);

      // Draw 3D perspective wireframe grid
      const cols = 14;
      const rows = 10;
      const fov = 200;
      const cx = w / 2;
      const cy = h / 2 + 10;

      ctx.lineWidth = 1;

      for (let r = 0; r <= rows; r++) {
        const z = 80 + r * 25 - (time * 20) % 25;
        const scale = fov / (fov + z);
        const y = cy + (r * 18 - 40) * scale;
        const alpha = Math.max(0.05, Math.min(0.4, 1 - z / 320));

        ctx.strokeStyle = `rgba(16, 185, 129, ${alpha})`;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
        ctx.stroke();
      }

      for (let c = 0; c <= cols; c++) {
        const xOffset = (c - cols / 2) * 32;
        ctx.beginPath();

        for (let r = 0; r <= rows; r++) {
          const z = 80 + r * 25 - (time * 20) % 25;
          const scale = fov / (fov + z);
          const x = cx + xOffset * scale;
          const y = cy + (r * 18 - 40) * scale;
          const alpha = Math.max(0.05, Math.min(0.35, 1 - z / 320));

          if (r === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);

          ctx.strokeStyle = `rgba(16, 185, 129, ${alpha})`;
        }
        ctx.stroke();
      }

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
      className={`absolute inset-0 w-full h-full pointer-events-none opacity-40 ${className}`}
    />
  );
}
