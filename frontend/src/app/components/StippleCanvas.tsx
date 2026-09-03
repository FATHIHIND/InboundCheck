"use client";

import { useEffect, useRef } from "react";
import { useCanvasOptimization } from "@/hooks/useCanvasOptimization";

export default function StippleCanvas({ className = "" }: { className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const { isVisibleRef, prefersReducedMotionRef } = useCanvasOptimization(canvasRef);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animationFrameId: number;
    const dpr = Math.min(typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1, 2);
    let width = canvas.parentElement?.clientWidth || 800;
    let height = canvas.parentElement?.clientHeight || 450;

    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    const handleResize = () => {
      if (!canvas || !canvas.parentElement) return;
      width = canvas.parentElement.clientWidth;
      height = canvas.parentElement.clientHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.scale(dpr, dpr);
    };

    window.addEventListener("resize", handleResize);

    // Generate Pointillism / Stipple Dot Wave Field
    const numPoints = 280;
    const points: Array<{
      x: number;
      y: number;
      baseX: number;
      baseY: number;
      size: number;
      opacity: number;
      speed: number;
      offset: number;
    }> = [];

    for (let i = 0; i < numPoints; i++) {
      const u = (i / numPoints) * Math.PI * 2;
      const radius = 60 + Math.random() * 160;
      const x = width / 2 + Math.cos(u) * radius;
      const y = height / 2 + Math.sin(u) * (radius * 0.45);

      points.push({
        x,
        y,
        baseX: x,
        baseY: y,
        size: Math.random() < 0.2 ? 1.8 : 0.9,
        opacity: 0.15 + Math.random() * 0.7,
        speed: 0.001 + Math.random() * 0.002,
        offset: Math.random() * Math.PI * 2,
      });
    }

    let t = 0;
    const render = () => {
      if (!isVisibleRef.current) {
        animationFrameId = requestAnimationFrame(render);
        return;
      }

      t += 0.015;
      ctx.clearRect(0, 0, width, height);

      // Draw subtle orbital rings
      ctx.strokeStyle = "rgba(255, 255, 255, 0.03)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.ellipse(width / 2, height / 2, 180, 80, 0, 0, Math.PI * 2);
      ctx.stroke();

      ctx.beginPath();
      ctx.ellipse(width / 2, height / 2, 260, 110, 0, 0, Math.PI * 2);
      ctx.stroke();

      // Draw Stippled Dots with Wave Oscillations
      for (let i = 0; i < points.length; i++) {
        const p = points[i];
        const wave = Math.sin(t * 1.5 + p.offset) * 12;
        const waveX = Math.cos(t + p.offset) * 8;

        const currentX = p.baseX + waveX;
        const currentY = p.baseY + wave;

        // Radial fade towards edges
        const distFromCenter = Math.hypot(currentX - width / 2, currentY - height / 2);
        const alpha = Math.max(0, p.opacity * (1 - distFromCenter / (width * 0.6)));

        ctx.fillStyle = `rgba(255, 255, 255, ${alpha.toFixed(3)})`;
        ctx.beginPath();
        ctx.arc(currentX, currentY, p.size, 0, Math.PI * 2);
        ctx.fill();

        // Sparse connection filaments
        if (i % 7 === 0 && i < points.length - 1) {
          const next = points[i + 1];
          const dist = Math.hypot(currentX - next.baseX, currentY - next.baseY);
          if (dist < 70) {
            ctx.strokeStyle = `rgba(255, 255, 255, ${(alpha * 0.15).toFixed(3)})`;
            ctx.beginPath();
            ctx.moveTo(currentX, currentY);
            ctx.lineTo(next.baseX, next.baseY);
            ctx.stroke();
          }
        }
      }

      if (!prefersReducedMotionRef.current) {
        animationFrameId = requestAnimationFrame(render);
      }
    };

    render();

    return () => {
      window.removeEventListener("resize", handleResize);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className={`pointer-events-none absolute inset-0 w-full h-full ${className}`}
    />
  );
}
