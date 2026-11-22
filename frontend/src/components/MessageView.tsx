"use client";

import { motion } from "framer-motion";
import { Brain, Mic, Sparkles } from "lucide-react";
import { memo, useState } from "react";
import { useChat } from "@/store/chat";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { UiMessage } from "@/lib/types";

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
        <div className={`prose-loki text-ink/95 ${m.streaming ? "caret" : ""}`}>
          {m.content ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
          ) : m.streaming ? null : (
            <span className="text-faint">(no answer)</span>
          )}
        </div>
        <Meta m={m} />
        <MemoryTrail m={m} />
      </div>
    </motion.div>
  );
});
