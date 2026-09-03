"use client";

import React, { useEffect, useRef } from "react";
import { useCanvasOptimization } from "@/hooks/useCanvasOptimization";

interface RblNode {
  name: string;
  host: string;
  status: "clean" | "listed" | "checking";
  latency_ms: number;
}

export default function RblTopology3DCanvas({
  rbls = [],
  className = "",
}: {
  rbls?: RblNode[];
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

    const render = () => {
      if (!isVisibleRef.current) {
        animId = requestAnimationFrame(render);
        return;
      }

      time += 0.015;
      const w = canvas.width / dpr;
      const h = canvas.height / dpr;
      ctx.clearRect(0, 0, w, h);

      const cx = w / 2;
      const cy = h / 2;
      const nodeCount = Math.max(10, rbls.length);

      // Render Central Apex Monitored Domain Node
      const centerPulse = (Math.sin(time * 3) + 1) / 2;
      ctx.fillStyle = "rgba(16, 185, 129, 0.2)";
      ctx.beginPath();
      ctx.arc(cx, cy, 28 + centerPulse * 6, 0, Math.PI * 2);
      ctx.fill();

      ctx.fillStyle = "#10B981";
      ctx.beginPath();
      ctx.arc(cx, cy, 8, 0, Math.PI * 2);
      ctx.fill();

      // Render 10 RBL Satellite Nodes in 3D Orbital Plane
      for (let i = 0; i < nodeCount; i++) {
        const item = rbls[i] || { name: `RBL Node ${i + 1}`, status: "clean", latency_ms: 24 };
        const angle = (i / nodeCount) * Math.PI * 2 + time * 0.15;
        const rx = 140; // elliptical x radius
        const ry = 65;  // elliptical y radius (3D perspective pitch)

        const x = cx + Math.cos(angle) * rx;
        const y = cy + Math.sin(angle) * ry;
        const depthScale = (Math.sin(angle) + 1) / 2 * 0.4 + 0.8;
        const isListed = item.status === "listed";

        // Connecting Beam to Center
        ctx.lineWidth = 1 * depthScale;
        ctx.strokeStyle = isListed
          ? `rgba(239, 68, 68, ${0.4 * depthScale})`
          : `rgba(16, 185, 129, ${0.25 * depthScale})`;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(x, y);
        ctx.stroke();

        // Traveling Energy Packet along Beam
        const pktProgress = ((time * 0.8 + i * 0.1) % 1);
        const pkX = cx + (x - cx) * pktProgress;
        const pkY = cy + (y - cy) * pktProgress;
        ctx.fillStyle = isListed ? "rgba(248, 113, 113, 0.9)" : "rgba(52, 211, 153, 0.9)";
        ctx.beginPath();
        ctx.arc(pkX, pkY, 2.5 * depthScale, 0, Math.PI * 2);
        ctx.fill();

        // Satellite Node Glow & Dot
        ctx.fillStyle = isListed ? "rgba(239, 68, 68, 0.3)" : "rgba(16, 185, 129, 0.25)";
        ctx.beginPath();
        ctx.arc(x, y, (isListed ? 10 : 7) * depthScale, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = isListed ? "#EF4444" : "#10B981";
        ctx.beginPath();
        ctx.arc(x, y, 4 * depthScale, 0, Math.PI * 2);
        ctx.fill();

        // Label
        ctx.fillStyle = isListed ? "#F87171" : "#A1A1AA";
        ctx.font = `${Math.round(10 * depthScale)}px monospace`;
        ctx.fillText(item.name || `RBL ${i + 1}`, x + 8, y + 3);
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
  }, [rbls]);

  return (
    <div className={`relative ${className}`}>
      <canvas ref={canvasRef} className="w-full h-full block" />
    </div>
  );
}
