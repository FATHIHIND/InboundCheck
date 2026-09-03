"use client";

import React, { useEffect, useRef } from "react";
import { useCanvasOptimization } from "@/hooks/useCanvasOptimization";

export default function Sparkline3DCanvas({ className = "" }: { className?: string }) {
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

    // Sparkline points trajectory (low risk < 5%)
    const basePoints = [12, 9, 7, 5, 4, 3, 2];

    const render = () => {
      if (!isVisibleRef.current) {
        animId = requestAnimationFrame(render);
        return;
      }

      time += 0.03;
      const w = canvas.width / dpr;
      const h = canvas.height / dpr;
      ctx.clearRect(0, 0, w, h);

      const paddingX = 12;
      const paddingY = 8;
      const stepX = (w - paddingX * 2) / (basePoints.length - 1);

      ctx.beginPath();
      basePoints.forEach((val, i) => {
        const osc = Math.sin(time * 2 + i) * 1.5;
        const x = paddingX + i * stepX;
        const y = h - paddingY - ((val + osc) / 15) * (h - paddingY * 2);

        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });

      // Gradient stroke
      const grad = ctx.createLinearGradient(0, 0, w, 0);
      grad.addColorStop(0, "#10B981");
      grad.addColorStop(1, "#34D399");

      ctx.strokeStyle = grad;
      ctx.lineWidth = 2;
      ctx.stroke();

      // Pulsing head node at the end
      const lastVal = basePoints[basePoints.length - 1];
      const lastX = paddingX + (basePoints.length - 1) * stepX;
      const lastY = h - paddingY - ((lastVal + Math.sin(time * 2 + basePoints.length - 1) * 1.5) / 15) * (h - paddingY * 2);

      const pulse = (Math.sin(time * 4) + 1) / 2;
      ctx.fillStyle = "rgba(16, 185, 129, 0.4)";
      ctx.beginPath();
      ctx.arc(lastX, lastY, 4 + pulse * 4, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = "#34D399";
      ctx.beginPath();
      ctx.arc(lastX, lastY, 3, 0, Math.PI * 2);
      ctx.fill();

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
      className={`pointer-events-none absolute inset-0 w-full h-full ${className}`}
    />
  );
}
