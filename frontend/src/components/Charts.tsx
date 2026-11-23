"use client";

import { useState } from "react";

/** Series colour for chart marks (validated on LOKI's dark surface #0b1220). Text never uses it. */
export const SERIES = "#18a3c4";
const SURFACE = "#0b1220";

type Point = { label: string; value: number | null };

function niceMax(v: number, integer = false): number {
  if (v <= 0) return integer ? 2 : 1;
  const p = 10 ** Math.floor(Math.log10(v));
  const n = v / p;
  const max = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
  // Counts get whole-number ticks: 0 / half / max must all be integers.
  return integer && max % 2 ? Math.max(2, Math.ceil(v / 2) * 2) : max;
}

function fmt(v: number, unit?: string) {
  const s = v >= 10_000 ? `${(v / 1000).toFixed(v >= 100_000 ? 0 : 1)}K` : v.toLocaleString();
  return unit ? `${s} ${unit}` : s;
}

const W = 640;
const H = 180;
const PAD = { l: 44, r: 12, t: 12, b: 26 };

function Frame({ max, labels, children }: { max: number; labels: string[]; children: React.ReactNode }) {
  const ticks = [0, max / 2, max];
  const ih = H - PAD.t - PAD.b;
  const show = labels.length <= 8 ? labels.map((_, i) => i) : [0, Math.floor((labels.length - 1) / 2), labels.length - 1];
  const step = (W - PAD.l - PAD.r) / labels.length;
  return (
    <>
      {ticks.map((t) => {
        const y = PAD.t + ih - (t / max) * ih;
        return (
          <g key={t}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y} y2={y} stroke="rgb(120 170 220 / 0.12)" strokeWidth={1} />
            <text x={PAD.l - 6} y={y + 4} textAnchor="end" className="fill-faint text-[10px]">
              {fmt(Math.round(t * 10) / 10)}
            </text>
          </g>
        );
      })}
      {show.map((i) => (
        <text key={i} x={PAD.l + step * (i + 0.5)} y={H - 8} textAnchor="middle" className="fill-faint text-[10px]">
          {labels[i]}
        </text>
      ))}
      {children}
    </>
  );
}

function Tip({ x, y, title, value }: { x: number; y: number; title: string; value: string }) {
  const left = x > W * 0.7;
  return (
    <foreignObject x={left ? x - 150 : x + 10} y={Math.max(0, y - 46)} width={140} height={44} pointerEvents="none">
      <div className="rounded-md border border-line-strong bg-night px-2 py-1 text-[11px] leading-tight text-ink shadow-lg">
        <div className="text-dim">{title}</div>
        <div className="font-medium">{value}</div>
      </div>
    </foreignObject>
  );
}

/** One series of columns from a single baseline; hover shows the exact value. */
export function ColumnChart({ data, unit, title, empty = "No data yet" }: { data: Point[]; unit?: string; title: string; empty?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const vals = data.map((d) => d.value ?? 0);
  if (!vals.some((v) => v > 0)) return <p className="py-8 text-center text-sm text-faint">{empty}</p>;
  const max = niceMax(Math.max(...vals), vals.every(Number.isInteger));
  const ih = H - PAD.t - PAD.b;
  const step = (W - PAD.l - PAD.r) / data.length;
  const bw = Math.min(24, step - 2);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={title} onMouseLeave={() => setHover(null)}>
      <Frame max={max} labels={data.map((d) => d.label)}>
        {data.map((d, i) => {
          const v = d.value ?? 0;
          const h = (v / max) * ih;
          const x = PAD.l + step * i + (step - bw) / 2;
          const y = PAD.t + ih - h;
          const r = Math.min(4, h / 2, bw / 2);
          return (
            <g key={d.label} onMouseEnter={() => setHover(i)}>
              <rect x={PAD.l + step * i} y={PAD.t} width={step} height={ih} fill="transparent" />
              {h > 0 && (
                <path
                  d={`M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + bw - r} Q${x + bw},${y} ${x + bw},${y + r} V${y + h} Z`}
                  fill={SERIES}
                  opacity={hover === null || hover === i ? 1 : 0.55}
                />
              )}
            </g>
          );
        })}
        {hover !== null && (
          <Tip
            x={PAD.l + step * (hover + 0.5)}
            y={PAD.t + ih - ((data[hover].value ?? 0) / max) * ih}
            title={data[hover].label}
            value={fmt(data[hover].value ?? 0, unit)}
          />
        )}
      </Frame>
    </svg>
  );
}

/** One series as a 2px line; gaps where there is no value; crosshair + tooltip on hover. */
export function LineChart({ data, unit, title, empty = "No data yet" }: { data: Point[]; unit?: string; title: string; empty?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const present = data.filter((d) => d.value !== null);
  if (!present.length) return <p className="py-8 text-center text-sm text-faint">{empty}</p>;
  const max = niceMax(Math.max(...present.map((d) => d.value as number)));
  const ih = H - PAD.t - PAD.b;
  const step = (W - PAD.l - PAD.r) / data.length;
  const pt = (i: number, v: number) => [PAD.l + step * (i + 0.5), PAD.t + ih - (v / max) * ih] as const;
  const segments: string[] = [];
  let cur = "";
  data.forEach((d, i) => {
    if (d.value === null) {
      if (cur) segments.push(cur);
      cur = "";
      return;
    }
    const [x, y] = pt(i, d.value);
    cur += `${cur ? "L" : "M"}${x},${y} `;
  });
  if (cur) segments.push(cur);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={title} onMouseLeave={() => setHover(null)}>
      <Frame max={max} labels={data.map((d) => d.label)}>
        {segments.map((s) => (
          <path key={s} d={s} fill="none" stroke={SERIES} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {data.map((d, i) =>
          d.value === null ? null : (
            <circle key={d.label} cx={pt(i, d.value)[0]} cy={pt(i, d.value)[1]} r={hover === i ? 5 : 4} fill={SERIES} stroke={SURFACE} strokeWidth={2} />
          ),
        )}
        {data.map((d, i) => (
          <rect key={`hit-${d.label}`} x={PAD.l + step * i} y={PAD.t} width={step} height={ih} fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
        {hover !== null && (
          <>
            <line x1={pt(hover, 0)[0]} x2={pt(hover, 0)[0]} y1={PAD.t} y2={PAD.t + ih} stroke="rgb(120 190 255 / 0.24)" strokeWidth={1} pointerEvents="none" />
            <Tip
              x={pt(hover, 0)[0]}
              y={data[hover].value === null ? PAD.t + 40 : pt(hover, data[hover].value as number)[1]}
              title={data[hover].label}
              value={data[hover].value === null ? "No data" : fmt(data[hover].value as number, unit)}
            />
          </>
        )}
      </Frame>
    </svg>
  );
}

/** Horizontal waterfall of a trace's spans (offset + duration against the total). */
export function Waterfall({ spans, total }: { spans: { name: string; start_ms: number; duration_ms: number }[]; total: number }) {
  const t = Math.max(total, 1);
  return (
    <ul className="space-y-1">
      {spans.map((s, i) => (
        <li key={`${s.name}-${i}`} className="grid grid-cols-[9rem_1fr_4.5rem] items-center gap-2 text-[11px]">
          <span className="truncate text-dim" title={s.name}>
            {s.name}
          </span>
          <span className="relative h-2 rounded-sm bg-white/[0.04]">
            {s.duration_ms > 0 ? (
              <span
                className="absolute top-0 h-2 rounded-sm"
                style={{ left: `${(s.start_ms / t) * 100}%`, width: `${Math.max(0.6, (s.duration_ms / t) * 100)}%`, background: SERIES }}
              />
            ) : (
              <span className="absolute -top-0.5 h-3 w-0.5 bg-warn" style={{ left: `${(s.start_ms / t) * 100}%` }} title="event" />
            )}
          </span>
          <span className="text-right font-mono text-faint">{s.duration_ms > 0 ? `${s.duration_ms} ms` : "event"}</span>
        </li>
      ))}
    </ul>
  );
}
