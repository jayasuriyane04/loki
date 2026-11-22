"use client";

import {
  BookOpen,
  Brain,
  ChartColumn,
  Check,
  FolderKanban,
  ListTodo,
  MessageSquare,
  Pencil,
  Plus,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { useState } from "react";
import { useChat } from "@/store/chat";

const UPCOMING = [{ icon: ChartColumn, label: "Analytics", phase: 7 }];

function groupLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const days = Math.floor((today.setHours(0, 0, 0, 0) - new Date(d).setHours(0, 0, 0, 0)) / 86_400_000);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return "This week";
  return "Earlier";
}

export function SidePanel({ onNavigate }: { onNavigate?: () => void }) {
  const { conversations, activeId, openConversation, newConversation, rename, remove, view, setView } = useChat();
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const groups: [string, typeof conversations][] = [];
  for (const c of conversations) {
    const label = groupLabel(c.updated_at);
    const g = groups.find(([l]) => l === label);
    if (g) g[1].push(c);
    else groups.push([label, [c]]);
  }

  async function commitRename(id: string) {
    const title = draft.trim();
    setEditing(null);
    if (title) await rename(id, title).catch(() => undefined);
  }

  return (
    <nav className="flex h-full flex-col">
      <div className="p-3">
        <button
          onClick={() => {
            newConversation();
            onNavigate?.();
          }}
          className="flex w-full items-center gap-2 rounded-lg border border-line-strong bg-deep/60 px-3 py-2 text-sm text-ink transition hover:border-cyan/40 hover:bg-deep"
        >
          <Plus size={15} className="text-cyan" />
          New conversation
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
        {conversations.length === 0 && (
          <p className="px-3 py-2 text-sm text-faint">Conversations you have with LOKI appear here.</p>
        )}
        {groups.map(([label, items]) => (
          <div key={label} className="mb-3">
            <div className="hud-label px-3 pb-1 pt-2">{label}</div>
            {items.map((c) => (
              <div
                key={c.id}
                className={`group flex items-center gap-1 rounded-lg pr-1 transition ${
                  c.id === activeId ? "bg-cyan/[0.08] text-ink" : "text-dim hover:bg-white/[0.03] hover:text-ink"
                }`}
              >
                {editing === c.id ? (
                  <form
                    className="flex flex-1 items-center gap-1 px-2 py-1"
                    onSubmit={(e) => {
                      e.preventDefault();
                      commitRename(c.id);
                    }}
                  >
                    <input
                      autoFocus
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => e.key === "Escape" && setEditing(null)}
                      maxLength={200}
                      className="min-w-0 flex-1 rounded border border-line-strong bg-night px-2 py-1 text-sm text-ink outline-none"
                    />
                    <button type="submit" className="p-1 text-dim hover:text-ok" aria-label="Save title">
                      <Check size={14} />
                    </button>
                    <button type="button" onClick={() => setEditing(null)} className="p-1 text-dim hover:text-ink" aria-label="Cancel">
                      <X size={14} />
                    </button>
                  </form>
                ) : (
                  <>
                    <button
                      onClick={() => {
                        openConversation(c.id);
                        onNavigate?.();
                      }}
                      className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2 text-left text-sm"
                    >
                      <MessageSquare size={14} className="shrink-0 opacity-60" />
                      <span className="truncate">{c.title}</span>
                    </button>
                    <button
                      onClick={() => {
                        setEditing(c.id);
                        setDraft(c.title);
                      }}
                      className="p-1 text-faint opacity-0 transition hover:text-ink group-hover:opacity-100 focus:opacity-100"
                      aria-label={`Rename ${c.title}`}
                    >
                      <Pencil size={13} />
                    </button>
                    <button
                      onClick={() => {
                        if (confirm(`Delete "${c.title}"? This cannot be undone.`)) remove(c.id).catch(() => undefined);
                      }}
                      className="p-1 text-faint opacity-0 transition hover:text-bad group-hover:opacity-100 focus:opacity-100"
                      aria-label={`Delete ${c.title}`}
                    >
                      <Trash2 size={13} />
                    </button>
                  </>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="border-t border-line p-2">
        {(
          [
            ["projects", FolderKanban, "Projects"],
            ["planner", ListTodo, "Planner"],
            ["memories", Brain, "Memory"],
            ["knowledge", BookOpen, "Knowledge base"],
            ["tools", Wrench, "Tools"],
          ] as const
        ).map(([key, Icon, label]) => (
          <button
            key={key}
            onClick={() => {
              setView(view === key ? "assistant" : key);
              onNavigate?.();
            }}
            aria-current={view === key ? "page" : undefined}
            className={`mb-1 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm transition ${
              view === key ? "bg-cyan/[0.08] text-ink" : "text-dim hover:bg-white/[0.03] hover:text-ink"
            }`}
          >
            <Icon size={14} className="text-cyan" />
            {label}
          </button>
        ))}
        <div className="hud-label px-3 pb-1 pt-1">Coming next</div>
        {UPCOMING.map(({ icon: Icon, label, phase }) => (
          <div
            key={label}
            className="flex cursor-not-allowed items-center gap-2 px-3 py-1.5 text-sm text-faint"
            title={`Not built yet — Phase ${phase}`}
          >
            <Icon size={14} />
            <span>{label}</span>
            <span className="ml-auto font-mono text-[10px] text-faint/70">P{phase}</span>
          </div>
        ))}
      </div>
    </nav>
  );
}
