"use client";

import { motion } from "framer-motion";
import { BookOpen, Brain, Mic, Sparkles } from "lucide-react";
import { memo, useState } from "react";
import { useChat } from "@/store/chat";
import { ToolSteps } from "./ToolSteps";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation, UiMessage } from "@/lib/types";

function Meta({ m }: { m: UiMessage }) {
  if (m.streaming || m.role !== "assistant") return null;
  const bits: string[] = [];
  if (m.model) bits.push(m.model);
  if (m.first_token_ms != null) bits.push(`first token ${(m.first_token_ms / 1000).toFixed(1)}s`);
  if (m.latency_ms != null) bits.push(`total ${(m.latency_ms / 1000).toFixed(1)}s`);
  if (m.completion_tokens != null) bits.push(`${m.completion_tokens} tok`);
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-2 font-mono text-[10.5px] text-faint">
      {m.status === "interrupted" && <span className="text-warn">interrupted</span>}
      {m.status === "error" && <span className="text-bad">failed</span>}
      <span>{bits.join(" · ")}</span>
    </div>
  );
}

function locate(c: Citation) {
  if (c.page) return `p. ${c.page}`;
  if (c.line_start) return `lines ${c.line_start}–${c.line_end}`;
  return "";
}

/** Turn valid [n] markers into links the markdown renderer shows as chips. Unknown numbers stay plain text. */
function linkCitations(m: UiMessage): string {
  const valid = new Set((m.citations ?? []).map((c) => c.n));
  if (!valid.size) return m.content;
  return m.content.replace(/\[(\d{1,2})\](?!\()/g, (whole, n) => (valid.has(Number(n)) ? `[${n}](#cite-${n})` : whole));
}

function CiteChip({ n, m }: { n: number; m: UiMessage }) {
  const c = m.citations?.find((x) => x.n === n);
  return (
    <button
      onClick={() => document.getElementById(`src-${m.id}-${n}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" })}
      title={c ? `${c.title}${c.heading ? " · " + c.heading : ""} ${locate(c)}` : undefined}
      className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded-md border border-cyan/30 bg-cyan/10 px-1 align-middle font-mono text-[10.5px] text-cyan hover:bg-cyan/20"
    >
      {n}
    </button>
  );
}

function Sources({ m }: { m: UiMessage }) {
  const [open, setOpen] = useState<number | null>(null);
  const [showAll, setShowAll] = useState(false);
  const all = m.citations ?? [];
  if (m.streaming || !all.length) return null;
  const cited = all.filter((c) => c.cited);
  const shown = showAll ? all : cited;
  return (
    <div className="mt-3 text-[12.5px]">
      <div className="hud-label mb-1.5 flex items-center gap-2">
        <BookOpen size={11} /> Sources
        {all.length > cited.length && (
          <button onClick={() => setShowAll(!showAll)} className="normal-case tracking-normal text-faint hover:text-dim">
            {showAll ? "show cited only" : `+${all.length - cited.length} consulted, not cited`}
          </button>
        )}
      </div>
      {!cited.length && !showAll && (
        <p className="text-faint">Your documents were searched, but the answer doesn&apos;t cite them.</p>
      )}
      <ul className="space-y-1">
        {shown.map((c) => (
          <li key={c.n} id={`src-${m.id}-${c.n}`}>
            <button
              onClick={() => setOpen(open === c.n ? null : c.n)}
              aria-expanded={open === c.n}
              className={`flex w-full items-baseline gap-2 text-left ${c.cited ? "text-dim" : "text-faint"} hover:text-ink`}
            >
              <span className="font-mono text-cyan/80">[{c.n}]</span>
              <span className="min-w-0 truncate">
                {c.title}
                {c.heading && <span className="text-faint"> · {c.heading}</span>}
                <span className="font-mono text-faint"> {locate(c)}</span>
              </span>
            </button>
            {open === c.n && (
              <div className="mb-2 ml-7 mt-1 rounded-lg border border-line bg-night/60 p-2.5">
                <div className="mb-1 font-mono text-[10.5px] text-faint">
                  {c.source} · relevance {(c.score * 100).toFixed(0)}%
                </div>
                <pre className="whitespace-pre-wrap break-words font-sans text-[12px] leading-relaxed text-dim">{c.snippet}</pre>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function MemoryTrail({ m }: { m: UiMessage }) {
  const [open, setOpen] = useState(false);
  const setView = useChat((s) => s.setView);
  const recalled = m.recalled ?? [];
  const saved = m.saved ?? [];
  if (!recalled.length && !saved.length) return null;
  const verb = { add: "Saved", update: "Updated", delete: "Forgot" } as const;
  return (
    <div className="mt-2 text-[12px]">
      <div className="flex flex-wrap gap-1.5">
        {recalled.length > 0 && (
          <button
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            className="flex items-center gap-1.5 rounded-full border border-line px-2.5 py-0.5 text-dim hover:text-ink"
          >
            <Brain size={12} className="text-cyan/80" />
            Used {recalled.length} {recalled.length === 1 ? "memory" : "memories"}
          </button>
        )}
        {saved.map((op) => (
          <button
            key={op.id + op.action}
            onClick={() => setView("memories")}
            title="Open Memory"
            className={`flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-left ${
              op.action === "delete" ? "border-warn/30 text-warn" : "border-cyan/25 text-cyan/90"
            }`}
          >
            <Sparkles size={11} className="shrink-0" />
            <span className="truncate">
              {verb[op.action]}: {op.content}
            </span>
          </button>
        ))}
      </div>
      {open && (
        <ul className="mt-2 space-y-1 border-l border-line pl-3 text-dim">
          {recalled.map((r) => (
            <li key={r.id}>{r.content}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export const MessageView = memo(function MessageView({ m }: { m: UiMessage }) {
  if (m.role === "user") {
    return (
      <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex justify-end">
        <div
          className={`max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md border px-4 py-2.5 text-[15px] leading-relaxed ${
            m.failed ? "border-bad/40 bg-bad/5 text-dim" : "border-line-strong bg-deep/80 text-ink"
          }`}
        >
          {m.input_mode === "voice" && (
            <Mic size={12} className="mr-1.5 inline -translate-y-px text-cyan/70" aria-label="Spoken" />
          )}
          {m.content}
          {m.failed && <div className="mt-1 text-xs text-bad">Not delivered</div>}
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex gap-3">
      <div className="mt-2 h-2 w-2 shrink-0 rounded-full bg-cyan/80 shadow-[0_0_12px_rgba(94,231,255,0.6)]" />
      <div className="min-w-0 flex-1">
        {m.tool_steps && m.tool_steps.length > 0 && <ToolSteps steps={m.tool_steps} />}
        <div className={`prose-loki text-ink/95 ${m.streaming ? "caret" : ""}`}>
          {m.content ? (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children, ...rest }) =>
                  href?.startsWith("#cite-") ? (
                    <CiteChip n={Number(href.slice(6))} m={m} />
                  ) : (
                    <a href={href} target="_blank" rel="noreferrer noopener" {...rest}>
                      {children}
                    </a>
                  ),
              }}
            >
              {linkCitations(m)}
            </ReactMarkdown>
          ) : m.streaming ? null : (
            <span className="text-faint">(no answer)</span>
          )}
        </div>
        <Sources m={m} />
        <Meta m={m} />
        <MemoryTrail m={m} />
      </div>
    </motion.div>
  );
});
