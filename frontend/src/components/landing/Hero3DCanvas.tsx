"use client";

import React, { useEffect, useRef } from "react";
import { useCanvasOptimization } from "@/hooks/useCanvasOptimization";

interface Node3D {
  x: number;
  y: number;
  z: number;
  baseX: number;
  baseY: number;
  baseZ: number;
  vx: number;
  vy: number;
  vz: number;
  size: number;
  color: string;
  glowColor: string;
  isBeacon: boolean;
  pulsePhase: number;
  energy: number;
}

interface EnergyPacket {
  fromIndex: number;
  toIndex: number;
  progress: number;
  speed: number;
  size: number;
  color: string;
}

export default function Hero3DCanvas({
  className = "",
}: {
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const { isVisibleRef, prefersReducedMotionRef } = useCanvasOptimization(canvasRef);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    let animationFrameId: number;
    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    const dpr = Math.min(typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1, 2);

    const resize = () => {
      if (!canvas || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      width = rect.width || window.innerWidth;
      height = rect.height || window.innerHeight;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.scale(dpr, dpr);
    };

    resize();
    window.addEventListener("resize", resize);

    // --- Interactive Mouse Parallax & Gravity (ThreeUI / Spring Physics) ---
    const mouse = {
      x: 0,
      y: 0,
      targetX: 0,
      targetY: 0,
      isHovered: false,
      speed: 0.045,
    };

    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      // Normalized coordinates from -1 to 1 centered on container
      const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const ny = ((e.clientY - rect.top) / rect.height) * 2 - 1;
      mouse.targetX = Math.max(-1, Math.min(1, nx));
      mouse.targetY = Math.max(-1, Math.min(1, ny));
      mouse.isHovered = true;
    };

    const handleMouseLeave = () => {
      mouse.targetX = 0;
      mouse.targetY = 0;
      mouse.isHovered = false;
    };

    window.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseleave", handleMouseLeave);

    // --- 3D Constellation Initialization ---
    const NODE_COUNT = 110;
    const nodes: Node3D[] = [];
    const fov = 380; // 3D Camera focal length

    // Palette: Shopify Emerald & Deliverability Energy Tokens
    const emeraldHues = [
      { color: "rgba(16, 185, 129, 0.95)", glow: "rgba(16, 185, 129, 0.35)" }, // Emerald-500
      { color: "rgba(52, 211, 153, 0.90)", glow: "rgba(52, 211, 153, 0.25)" }, // Emerald-400
      { color: "rgba(5, 150, 105, 0.85)", glow: "rgba(5, 150, 105, 0.20)" }, // Emerald-600
      { color: "rgba(167, 243, 208, 0.90)", glow: "rgba(16, 185, 129, 0.40)" }, // Emerald-200 (Core highlight)
      { color: "rgba(255, 255, 255, 0.65)", glow: "rgba(16, 185, 129, 0.20)" }, // White photon
    ];

    for (let i = 0; i < NODE_COUNT; i++) {
      // Cylindrical/spherical 3D distribution with density biased towards upper-center and sides
      const angle = (i / NODE_COUNT) * Math.PI * 2 + (Math.random() - 0.5) * 0.4;
      const radius = 120 + Math.random() * 380;
      const x = Math.cos(angle) * radius * (Math.random() > 0.5 ? 1.2 : 0.9);
      const y = (Math.random() - 0.5) * 360 + Math.sin(angle * 2) * 50;
      const z = (Math.random() - 0.5) * 440;

      const isBeacon = i < 7; // 7 Key Governance / IMAP Telemetry Beacon Nodes
      const palette = isBeacon
        ? emeraldHues[3]
        : emeraldHues[Math.floor(Math.random() * emeraldHues.length)];

      nodes.push({
        x,
        y,
        z,
        baseX: x,
        baseY: y,
        baseZ: z,
        vx: (Math.random() - 0.5) * 0.25,
        vy: (Math.random() - 0.5) * 0.25,
        vz: (Math.random() - 0.5) * 0.25,
        size: isBeacon ? 3.2 + Math.random() * 1.5 : 1.2 + Math.random() * 1.6,
        color: palette.color,
        glowColor: palette.glow,
        isBeacon,
        pulsePhase: Math.random() * Math.PI * 2,
        energy: isBeacon ? 1.0 : 0.3 + Math.random() * 0.7,
      });
    }

    // --- Dynamic Traveling Energy Packets (Simulating email deliverability telemetry) ---
    const packets: EnergyPacket[] = [];
    const maxPackets = 18;

    const spawnPacket = () => {
      if (packets.length >= maxPackets) return;
      const from = Math.floor(Math.random() * nodes.length);
      // Find candidate nearby node in 3D space
      let candidates: number[] = [];
      for (let j = 0; j < nodes.length; j++) {
        if (j === from) continue;
        const dx = nodes[from].x - nodes[j].x;
        const dy = nodes[from].y - nodes[j].y;
        const dz = nodes[from].z - nodes[j].z;
        const dist3d = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (dist3d < 160) {
          candidates.push(j);
        }
      }

      if (candidates.length > 0) {
        const to = candidates[Math.floor(Math.random() * candidates.length)];
        packets.push({
          fromIndex: from,
          toIndex: to,
          progress: 0,
          speed: 0.012 + Math.random() * 0.02,
          size: 1.8 + Math.random() * 1.2,
          color: "rgba(52, 211, 153, 0.95)",
        });
      }
    };

    // Pre-populate packets
    for (let p = 0; p < 8; p++) {
      spawnPacket();
    }

    // --- Main 60 FPS Render Loop ---
    let time = 0;

    const render = () => {
      if (!isVisibleRef.current) {
        animationFrameId = requestAnimationFrame(render);
        return;
      }

      time += 0.014;

      // Smooth Spring-Damper Interpolation for Mouse Parallax
      mouse.x += (mouse.targetX - mouse.x) * mouse.speed;
      mouse.y += (mouse.targetY - mouse.y) * mouse.speed;

      ctx.clearRect(0, 0, width, height);

      const cx = width / 2;
      const cy = height / 2 - 20;

      // 3D Camera Rotation Angles (Interactive Tilt + Slow Ambient Float)
      const rotY = mouse.x * 0.35 + Math.sin(time * 0.4) * 0.08;
      const rotX = -mouse.y * 0.25 + Math.cos(time * 0.3) * 0.06;
      const cosY = Math.cos(rotY);
      const sinY = Math.sin(rotY);
      const cosX = Math.cos(rotX);
      const sinX = Math.sin(rotX);

      // --- 1. Project 3D Nodes to 2D Screen Coordinates ---
      interface ProjectedNode {
        node: Node3D;
        px: number;
        py: number;
        scale: number;
        alpha: number;
        depthZ: number;
      }

      const projected: ProjectedNode[] = [];
      const nodeToProj: (ProjectedNode | null)[] = new Array(nodes.length).fill(null);

      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];

        // Soft autonomous floating oscillation
        n.x = n.baseX + Math.sin(time * 0.8 + n.pulsePhase) * 16;
        n.y = n.baseY + Math.cos(time * 0.7 + n.pulsePhase) * 14;
        n.z = n.baseZ + Math.sin(time * 0.5 + n.pulsePhase) * 18;

        // 3D Rotation Transform around center
        // Y-axis rotation (Yaw)
        const x1 = n.x * cosY - n.z * sinY;
        const z1 = n.z * cosY + n.x * sinY;

        // X-axis rotation (Pitch)
        const y2 = n.y * cosX - z1 * sinX;
        const z2 = z1 * cosX + n.y * sinX;

        // Perspective Projection Scale
        const depth = fov / (fov + z2 + 450);
        if (depth <= 0) continue;

        const px = cx + x1 * depth;
        const py = cy + y2 * depth;

        // Mouse Gravity / Spring Repulsion in Screen Space
        let screenX = px;
        let screenY = py;
        if (mouse.isHovered) {
          const mouseScreenX = cx + (mouse.targetX * width) / 2.5;
          const mouseScreenY = cy + (mouse.targetY * height) / 2.5;
          const mdx = px - mouseScreenX;
          const mdy = py - mouseScreenY;
          const mDist = Math.sqrt(mdx * mdx + mdy * mdy);
          const maxRepel = 160;
          if (mDist < maxRepel && mDist > 0) {
            const force = (1 - mDist / maxRepel) * 32 * depth;
            screenX += (mdx / mDist) * force;
            screenY += (mdy / mDist) * force;
          }
        }

        // Distance / Depth-of-Field (DOF) Falloff
        const depthAlpha = Math.max(0.12, Math.min(1.0, (z2 + 350) / 600));
        const edgeDist = Math.hypot(screenX - cx, screenY - cy);
        const edgeVignette = Math.max(0, 1 - (edgeDist / (width * 0.75)));
        const finalAlpha = depthAlpha * edgeVignette;

        const pItem: ProjectedNode = {
          node: n,
          px: screenX,
          py: screenY,
          scale: depth,
          alpha: finalAlpha,
          depthZ: z2,
        };
        nodeToProj[i] = pItem;
        projected.push(pItem);
      }

      // Sort nodes back-to-front for accurate depth rendering
      projected.sort((a, b) => b.depthZ - a.depthZ);

      // --- 2. Draw Dynamic Interconnecting Energy Beams (Constellation Mesh) ---
      const maxConnectDist = 120;
      const maxConnectDistSq = maxConnectDist * maxConnectDist;
      ctx.lineWidth = 1;

      for (let i = 0; i < projected.length; i++) {
        const p1 = projected[i];
        if (p1.alpha <= 0.05) continue;

        for (let j = i + 1; j < projected.length; j++) {
          const p2 = projected[j];
          if (p2.alpha <= 0.05) continue;

          const dx = p1.px - p2.px;
          const dy = p1.py - p2.py;
          const distSq = dx * dx + dy * dy;

          // Simplify distance check: skip Math.sqrt when beyond max distance
          if (distSq < maxConnectDistSq) {
            const dist = Math.sqrt(distSq);
            const linkAlpha = (1 - dist / maxConnectDist) * 0.28 * Math.min(p1.alpha, p2.alpha);
            if (linkAlpha <= 0.01) continue;

            const isHighEnergy = p1.node.isBeacon || p2.node.isBeacon;

            ctx.strokeStyle = isHighEnergy
              ? `rgba(16, 185, 129, ${linkAlpha * 1.8})`
              : `rgba(16, 185, 129, ${linkAlpha})`;

            ctx.beginPath();
            ctx.moveTo(p1.px, p1.py);
            ctx.lineTo(p2.px, p2.py);
            ctx.stroke();
          }
        }
      }

      // --- 3. Draw Traveling Telemetry Energy Packets ---
      if (Math.random() < 0.06) {
        spawnPacket();
      }

      // Hoisted O(1) index lookup replacing O(N) .find()
      for (let p = packets.length - 1; p >= 0; p--) {
        const packet = packets[p];
        packet.progress += packet.speed;

        if (packet.progress >= 1) {
          packets.splice(p, 1);
          continue;
        }

        const fromProj = nodeToProj[packet.fromIndex];
        const toProj = nodeToProj[packet.toIndex];

        if (fromProj && toProj && fromProj.alpha > 0.08 && toProj.alpha > 0.08) {
          const curX = fromProj.px + (toProj.px - fromProj.px) * packet.progress;
          const curY = fromProj.py + (toProj.py - fromProj.py) * packet.progress;
          const packetScale = fromProj.scale * (1 - packet.progress) + toProj.scale * packet.progress;
          const packetAlpha = Math.min(fromProj.alpha, toProj.alpha) * 0.95;

          // Glowing energy packet head
          const rad = packet.size * packetScale * 2.5;
          const packetGlow = ctx.createRadialGradient(curX, curY, 0, curX, curY, rad * 2);
          packetGlow.addColorStop(0, `rgba(167, 243, 208, ${packetAlpha})`);
          packetGlow.addColorStop(0.4, `rgba(16, 185, 129, ${packetAlpha * 0.6})`);
          packetGlow.addColorStop(1, "rgba(16, 185, 129, 0)");

          ctx.fillStyle = packetGlow;
          ctx.beginPath();
          ctx.arc(curX, curY, rad * 2, 0, Math.PI * 2);
          ctx.fill();

          ctx.fillStyle = `rgba(255, 255, 255, ${packetAlpha})`;
          ctx.beginPath();
          ctx.arc(curX, curY, packet.size * packetScale * 0.8, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      // --- 4. Render 3D Constellation Nodes & Beacon Rings ---
      for (let i = 0; i < projected.length; i++) {
        const p = projected[i];
        if (p.alpha <= 0.01) continue;

        const radius = p.node.size * p.scale * 1.4;

        // Render Beacon Resonance Rings for DNS/IMAP Anchor nodes
        if (p.node.isBeacon) {
          const pulse = (Math.sin(time * 2.5 + p.node.pulsePhase) + 1) / 2;
          const ringRad = radius * (2.8 + pulse * 2.2);
          const ringAlpha = (1 - pulse) * 0.45 * p.alpha;

          ctx.strokeStyle = `rgba(16, 185, 129, ${ringAlpha})`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(p.px, p.py, ringRad, 0, Math.PI * 2);
          ctx.stroke();

          // Outer secondary echo ring
          ctx.strokeStyle = `rgba(52, 211, 153, ${ringAlpha * 0.5})`;
          ctx.beginPath();
          ctx.arc(p.px, p.py, ringRad * 1.4, 0, Math.PI * 2);
          ctx.stroke();
        }

        // Radial Glow Corona
        const glowRadius = radius * (p.node.isBeacon ? 4.5 : 3.0);
        const nodeGlow = ctx.createRadialGradient(p.px, p.py, 0, p.px, p.py, glowRadius);
        nodeGlow.addColorStop(0, p.node.color.replace(/[\d\.]+\)$/, `${p.alpha})`));
        nodeGlow.addColorStop(0.35, p.node.glowColor.replace(/[\d\.]+\)$/, `${p.alpha * 0.5})`));
        nodeGlow.addColorStop(1, "rgba(16, 185, 129, 0)");

        ctx.fillStyle = nodeGlow;
        ctx.beginPath();
        ctx.arc(p.px, p.py, glowRadius, 0, Math.PI * 2);
        ctx.fill();

        // Solid Node Core
        ctx.fillStyle = p.node.isBeacon
          ? `rgba(255, 255, 255, ${p.alpha * 0.95})`
          : p.node.color.replace(/[\d\.]+\)$/, `${p.alpha})`);

        ctx.beginPath();
        ctx.arc(p.px, p.py, Math.max(0.8, radius), 0, Math.PI * 2);
        ctx.fill();
      }

      // --- 5. Ambient Center Depth Radial Vignette Mask ---
      // Ensures the central copy and headline have supreme contrast and readability
      const centerMask = ctx.createRadialGradient(cx, cy, 40, cx, cy, width * 0.55);
      centerMask.addColorStop(0, "rgba(8, 8, 10, 0.55)");
      centerMask.addColorStop(0.45, "rgba(8, 8, 10, 0.25)");
      centerMask.addColorStop(1, "rgba(8, 8, 10, 0.0)");

      ctx.fillStyle = centerMask;
      ctx.fillRect(0, 0, width, height);

      if (!prefersReducedMotionRef.current) {
        animationFrameId = requestAnimationFrame(render);
      }
    };

    render();

    return () => {
      window.removeEventListener("resize", resize);
      window.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseleave", handleMouseLeave);
      cancelAnimationFrame(animationFrameId);
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className={`pointer-events-none absolute inset-0 overflow-hidden select-none ${className}`}
      aria-hidden="true"
    >
      <canvas
        ref={canvasRef}
        className="w-full h-full block"
        style={{
          filter: "drop-shadow(0 0 24px rgba(16, 185, 129, 0.12))",
        }}
      />
    </div>
  );
}
