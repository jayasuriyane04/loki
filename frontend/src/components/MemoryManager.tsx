"use client";

import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, Brain, Check, Loader2, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { Memory, MemoryKind } from "@/lib/types";
import { useChat } from "@/store/chat";
import { useMemory } from "@/store/memory";

const KIND_LABEL: Record<MemoryKind, string> = { profile: "About you", semantic: "Projects & facts", episodic: "Events" };
const KIND_STYLE: Record<MemoryKind, string> = {
  profile: "border-cyan/30 text-cyan",
  semantic: "border-azure/40 text-[#8fb4ff]",
  episodic: "border-warn/30 text-warn",
};

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function Editor({
  initial,
  onSave,
  onCancel,
  submitLabel,
}: {
  initial: Pick<Memory, "content" | "kind" | "importance" | "project">;
  onSave: (v: Pick<Memory, "content" | "kind" | "importance" | "project">) => Promise<boolean>;
  onCancel: () => void;
  submitLabel: string;
}) {
  const [v, setV] = useState(initial);
  const [busy, setBusy] = useState(false);
  const field = "rounded-lg border border-line bg-night px-2.5 py-1.5 text-sm text-ink outline-none focus:border-cyan/50";
  return (
    <form
      className="space-y-2"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        const ok = await onSave({ ...v, content: v.content.trim(), project: v.project?.trim() || null });
        setBusy(false);
        if (ok) onCancel();
      }}
    >
      <textarea
        autoFocus
        value={v.content}
        onChange={(e) => setV({ ...v, content: e.target.value })}
        rows={2}
        maxLength={400}
        required
        minLength={3}
        placeholder="e.g. I prefer short answers with code examples."
        className={`${field} block w-full resize-y`}
      />
      <div className="flex flex-wrap items-center gap-2">
        <select value={v.kind} onChange={(e) => setV({ ...v, kind: e.target.value as MemoryKind })} className={field}>
          {(Object.keys(KIND_LABEL) as MemoryKind[]).map((k) => (
            <option key={k} value={k}>
              {KIND_LABEL[k]}
            </option>
          ))}
        </select>
        <input
          value={v.project ?? ""}
          onChange={(e) => setV({ ...v, project: e.target.value })}
          placeholder="Project (optional)"
          maxLength={100}
          className={`${field} w-40`}
        />
        <label className="flex items-center gap-2 text-xs text-dim">
          Importance
          <input
            type="range"
            min={0}
            max={1}
            step={0.1}
            value={v.importance}
            onChange={(e) => setV({ ...v, importance: Number(e.target.value) })}
            className="w-24 accent-cyan"
          />
        </label>
        <div className="ml-auto flex gap-1">
          <button type="button" onClick={onCancel} className="rounded-md px-3 py-1.5 text-sm text-dim hover:text-ink">
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="flex items-center gap-1.5 rounded-md bg-cyan/90 px-3 py-1.5 text-sm font-medium text-void hover:bg-cyan disabled:opacity-50"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
            {submitLabel}
          </button>
        </div>
      </div>
    </form>
  );
}

function MemoryRow({ m }: { m: Memory }) {
  const { update, remove } = useMemory();
  const [editing, setEditing] = useState(false);
  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      className="group rounded-xl border border-line bg-deep/40 p-3.5"
    >
      {editing ? (
        <Editor initial={m} onSave={(v) => update(m.id, v)} onCancel={() => setEditing(false)} submitLabel="Save" />
      ) : (
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-[15px] leading-relaxed text-ink">{m.content}</p>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-faint">
              <span className={`rounded-full border px-2 py-0.5 font-mono ${KIND_STYLE[m.kind]}`}>{KIND_LABEL[m.kind]}</span>
              {m.project && <span className="rounded-full border border-line px-2 py-0.5 text-dim">{m.project}</span>}
              <span title="Importance">{"●".repeat(Math.max(1, Math.round(m.importance * 3)))}</span>
              <span>{m.kind === "episodic" && m.event_at ? `happened ${fmtDate(m.event_at)}` : `saved ${fmtDate(m.created_at)}`}</span>
              <span>{m.source === "user_edited" ? "edited by you" : "learned in conversation"}</span>
              {m.use_count > 0 && <span>used {m.use_count}×</span>}
              {m.similarity != null && <span className="text-cyan/80">match {(m.similarity * 100).toFixed(0)}%</span>}
            </div>
          </div>
          <div className="flex shrink-0 gap-0.5 opacity-60 transition group-hover:opacity-100">
            <button onClick={() => setEditing(true)} className="rounded-md p-1.5 text-dim hover:text-ink" aria-label="Edit memory">
              <Pencil size={14} />
            </button>
            <button
              onClick={() => confirm("Delete this memory? This cannot be undone.") && remove(m.id)}
              className="rounded-md p-1.5 text-dim hover:text-bad"
              aria-label="Delete memory"
            >
              <Trash2 size={14} />
            </button>
          </div>
        </div>
      )}
    </motion.li>
  );
}

export function MemoryManager() {
  const setView = useChat((s) => s.setView);
  const { items, total, byKind, enabled, query, filter, loading, error, load, setQuery, setFilter, add, removeAll, setEnabled } =
    useMemory();
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    load();
  }, [load]);

  const tabs: [typeof filter, string, number][] = [
    ["all", "All", total],
    ["profile", KIND_LABEL.profile, byKind.profile],
    ["semantic", KIND_LABEL.semantic, byKind.semantic],
    ["episodic", KIND_LABEL.episodic, byKind.episodic],
  ];

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
        <button onClick={() => setView("assistant")} className="mb-4 flex items-center gap-1.5 text-sm text-dim hover:text-ink">
          <ArrowLeft size={15} /> Back to LOKI
        </button>

        <div className="flex flex-wrap items-start gap-4">
          <div className="flex-1">
            <h1 className="flex items-center gap-2 text-2xl font-light text-ink">
              <Brain size={22} className="text-cyan" /> Memory
            </h1>
            <p className="mt-1 max-w-lg text-sm text-dim">
              What LOKI has learned about you. It saves useful facts after a reply and recalls them when they&apos;re
              relevant. Everything here is yours to correct or delete. Temporary chats never use memory.
            </p>
          </div>
          <label className="flex cursor-pointer items-center gap-3 rounded-xl border border-line px-3.5 py-2.5">
            <span className="text-sm text-ink">{enabled ? "Memory on" : enabled === false ? "Memory off" : "…"}</span>
            <button
              role="switch"
              aria-checked={!!enabled}
              aria-label="Use and save memories"
              disabled={enabled === null}
              onClick={() => setEnabled(!enabled)}
              className={`relative h-5 w-9 rounded-full transition ${enabled ? "bg-cyan/80" : "bg-white/10"}`}
            >
              <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all ${enabled ? "left-[18px]" : "left-0.5"}`} />
            </button>
          </label>
        </div>
        {enabled === false && (
          <p className="mt-3 rounded-lg border border-warn/30 bg-warn/5 px-3 py-2 text-sm text-warn">
            Memory is off: LOKI won&apos;t use these memories or save new ones until you turn it back on.
          </p>
        )}

        <div className="mt-6 flex flex-wrap items-center gap-2">
          <div className="relative min-w-56 flex-1">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by meaning — e.g. “what stack does Tarka use”"
              className="w-full rounded-lg border border-line bg-night/70 py-2 pl-9 pr-3 text-sm text-ink placeholder:text-faint outline-none focus:border-cyan/50"
            />
          </div>
          <button
            onClick={() => setAdding(true)}
            className="flex items-center gap-1.5 rounded-lg border border-line-strong px-3 py-2 text-sm text-ink hover:border-cyan/40"
          >
            <Plus size={15} className="text-cyan" /> Add memory
          </button>
        </div>

        <div className="mt-3 flex flex-wrap gap-1.5" role="tablist">
          {tabs.map(([key, label, n]) => (
            <button
              key={key}
              role="tab"
              aria-selected={filter === key}
              onClick={() => setFilter(key)}
              className={`rounded-full border px-3 py-1 text-xs transition ${
                filter === key ? "border-cyan/40 bg-cyan/10 text-cyan" : "border-line text-dim hover:text-ink"
              }`}
            >
              {label} <span className="opacity-60">{n}</span>
            </button>
          ))}
        </div>

        {error && (
          <div role="alert" className="mt-4 flex items-start gap-2 rounded-lg border border-bad/30 bg-bad/[0.07] px-3 py-2 text-sm">
            <span className="flex-1">{error}</span>
            <button onClick={() => useMemory.setState({ error: null })} aria-label="Dismiss">
              <X size={14} />
            </button>
          </div>
        )}

        <AnimatePresence>
          {adding && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-4 overflow-hidden rounded-xl border border-cyan/30 bg-deep/60 p-3.5"
            >
              <Editor
                initial={{ content: "", kind: "profile", importance: 0.8, project: null }}
                onSave={(v) => add(v.content, v.kind, v.importance, v.project)}
                onCancel={() => setAdding(false)}
                submitLabel="Save memory"
              />
            </motion.div>
          )}
        </AnimatePresence>

        <ul className="mt-4 space-y-2.5">
          <AnimatePresence initial={false}>
            {items.map((m) => (
              <MemoryRow key={m.id} m={m} />
            ))}
          </AnimatePresence>
        </ul>
        {loading && items.length === 0 && <p className="mt-6 text-center text-sm text-faint">Loading…</p>}
        {!loading && items.length === 0 && (
          <p className="mt-10 text-center text-sm text-faint">
            {query ? "No memories match that." : "Nothing saved yet. Tell LOKI about yourself and it will remember."}
          </p>
        )}

        {total > 0 && (
          <div className="mt-10 border-t border-line pt-4">
            <button
              onClick={() => {
                const typed = prompt(`This permanently deletes all ${total} memories. Type DELETE to confirm.`);
                if (typed === "DELETE") removeAll();
              }}
              className="text-sm text-faint hover:text-bad"
            >
              Delete all memories…
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
