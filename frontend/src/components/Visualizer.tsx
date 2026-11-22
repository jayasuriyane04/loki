"use client";

import { useEffect, useRef } from "react";
import { energy } from "@/lib/energy";
import type { AssistantState } from "@/lib/types";

type Palette = { core: [number, number, number]; ring: [number, number, number]; speed: number; arcs: boolean };

const PALETTES: Record<AssistantState, Palette> = {
  idle: { core: [94, 231, 255], ring: [59, 130, 246], speed: 0.25, arcs: false },
  listening: { core: [120, 240, 255], ring: [94, 231, 255], speed: 0.5, arcs: false },
  hearing: { core: [170, 250, 255], ring: [94, 231, 255], speed: 0.8, arcs: false },
  transcribing: { core: [120, 200, 255], ring: [56, 189, 248], speed: 1.3, arcs: true },
  processing: { core: [110, 170, 255], ring: [59, 130, 246], speed: 1.4, arcs: true },
  thinking: { core: [150, 140, 255], ring: [99, 102, 241], speed: 1.1, arcs: true },
  retrieving: { core: [110, 200, 255], ring: [56, 189, 248], speed: 1.2, arcs: true },
  executing: { core: [130, 255, 200], ring: [45, 212, 191], speed: 1.2, arcs: true },
  responding: { core: [94, 231, 255], ring: [34, 211, 238], speed: 0.7, arcs: false },
  speaking: { core: [94, 231, 255], ring: [34, 211, 238], speed: 0.7, arcs: false },
  error: { core: [248, 113, 113], ring: [239, 68, 68], speed: 0.3, arcs: false },
};

const mix = (a: number[], b: number[], t: number) => a.map((v, i) => v + (b[i] - v) * t);
const rgba = (c: number[], a: number) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;

/**
 * Central orb. Shape and colour follow the assistant state; size modulation comes only from the
 * real `energy` signal: microphone level while listening, LOKI's output level while speaking,
 * streamed tokens in text mode. No synthetic audio motion.
 */
export function Visualizer({ state, size = 280 }: { state: AssistantState; size?: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef(state);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);

    let core = [...PALETTES.idle.core];
    let ring = [...PALETTES.idle.ring];
    let phase = 0;
    let smoothEnergy = 0;
    let last = performance.now();
    let raf = 0;

    const draw = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const p = PALETTES[stateRef.current];
      core = mix(core, p.core, dt * 4);
      ring = mix(ring, p.ring, dt * 4);
      phase += dt * (reduced ? 0 : p.speed);
      smoothEnergy += (energy.read(now) - smoothEnergy) * Math.min(1, dt * 10);

      const c = size / 2;
      const base = size * 0.2;
      const r = base * (1 + smoothEnergy * 0.18);
      ctx.clearRect(0, 0, size, size);

      // Ambient glow
      const glow = ctx.createRadialGradient(c, c, r * 0.2, c, c, size * 0.5);
      glow.addColorStop(0, rgba(core, 0.22 + smoothEnergy * 0.15));
      glow.addColorStop(0.45, rgba(ring, 0.06));
      glow.addColorStop(1, rgba(ring, 0));
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, size, size);

      // Fine concentric rings
      for (let i = 1; i <= 3; i++) {
        ctx.beginPath();
        ctx.arc(c, c, r + i * size * 0.055, 0, Math.PI * 2);
        ctx.strokeStyle = rgba(ring, 0.16 / i);
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Rotating arcs while LOKI is working
      if (p.arcs) {
        for (let i = 0; i < 3; i++) {
          const start = phase * (i % 2 ? -1.6 : 1.2) + (i * Math.PI * 2) / 3;
          ctx.beginPath();
          ctx.arc(c, c, r + size * (0.07 + i * 0.045), start, start + Math.PI * 0.45);
          ctx.strokeStyle = rgba(core, 0.55 - i * 0.12);
          ctx.lineWidth = 1.6;
          ctx.lineCap = "round";
          ctx.stroke();
        }
      }

      // Core: softly deformed sphere
      ctx.beginPath();
      const steps = 96;
      for (let i = 0; i <= steps; i++) {
        const a = (i / steps) * Math.PI * 2;
        const wobble =
          Math.sin(a * 3 + phase * 2) * 0.012 + Math.sin(a * 5 - phase * 1.3) * (0.008 + smoothEnergy * 0.03);
        const rr = r * (1 + wobble);
        const x = c + Math.cos(a) * rr;
        const y = c + Math.sin(a) * rr;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      const body = ctx.createRadialGradient(c - r * 0.35, c - r * 0.4, r * 0.1, c, c, r);
      body.addColorStop(0, rgba(mix(core, [255, 255, 255], 0.55), 0.95));
      body.addColorStop(0.5, rgba(core, 0.55));
      body.addColorStop(1, rgba(ring, 0.18));
      ctx.fillStyle = body;
      ctx.fill();
      ctx.strokeStyle = rgba(core, 0.5);
      ctx.lineWidth = 1;
      ctx.stroke();

      raf = requestAnimationFrame(draw);
    };
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [size]);

  return <canvas ref={canvasRef} style={{ width: size, height: size }} aria-hidden className="pointer-events-none" />;
}

export const STATE_LABEL: Record<AssistantState, string> = {
  idle: "Standing by",
  listening: "Listening",
  hearing: "Hearing you",
  transcribing: "Transcribing",
  processing: "Processing",
  thinking: "Reasoning",
  retrieving: "Retrieving",
  executing: "Executing",
  responding: "Responding",
  speaking: "Speaking",
  error: "Error",
};
