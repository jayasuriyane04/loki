"use client";

import { ArrowLeft, Bell, CalendarDays, CheckSquare, NotebookPen, Plus, Sparkles, Square, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api } from "@/lib/api";
import type { EventItem, NoteItem, ReminderItem, TaskItem } from "@/lib/types";
import { useChat } from "@/store/chat";

type Tab = "tasks" | "reminders" | "calendar" | "notes";

const fmt = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
const field = "rounded-lg border border-line bg-night px-3 py-2 text-sm text-ink outline-none placeholder:text-faint focus:border-cyan/50";

function ByLoki({ by }: { by: string }) {
  return by === "loki" ? (
    <span title="Created by LOKI" className="inline-flex items-center gap-0.5 font-mono text-[10px] text-cyan/70">
      <Sparkles size={10} /> LOKI
    </span>
  ) : null;
}

function Tasks() {
  const [items, setItems] = useState<TaskItem[]>([]);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.tasks("all").then(setItems).catch((e) => setError(e.message)), []);
  useEffect(() => void load(), [load]);

  return (
    <div>
      <form
        className="flex flex-wrap gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!title.trim()) return;
          await api.createTask({ title: title.trim(), due_at: due ? new Date(due).toISOString() : null }).catch((x) => setError(x.message));
          setTitle("");
          setDue("");
          load();
        }}
      >
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="New task" maxLength={300} className={`${field} min-w-48 flex-1`} />
        <input type="datetime-local" value={due} onChange={(e) => setDue(e.target.value)} className={field} aria-label="Due" />
        <button className="flex items-center gap-1 rounded-lg bg-cyan/90 px-3 text-sm font-medium text-void hover:bg-cyan">
          <Plus size={15} /> Add
        </button>
      </form>
      {error && <p className="mt-2 text-sm text-bad">{error}</p>}
      <ul className="mt-4 space-y-1.5">
        {items.length === 0 && <li className="text-sm text-faint">No tasks. Add one here, or ask LOKI.</li>}
        {items.map((t) => (
          <li key={t.id} className="group flex items-center gap-3 rounded-xl border border-line bg-deep/40 px-3 py-2">
            <button
              onClick={async () => {
                await api.updateTask(t.id, { status: t.status === "open" ? "done" : "open" });
                load();
              }}
              aria-label={t.status === "open" ? `Mark “${t.title}” done` : `Reopen “${t.title}”`}
              className="text-dim hover:text-cyan"
            >
              {t.status === "done" ? <CheckSquare size={17} className="text-ok" /> : <Square size={17} />}
            </button>
            <div className="min-w-0 flex-1">
              <div className={`truncate text-sm ${t.status === "done" ? "text-faint line-through" : "text-ink"}`}>{t.title}</div>
              <div className="flex flex-wrap gap-x-2 text-[11px] text-faint">
                {t.due_at && <span>due {fmt(t.due_at)}</span>}
                {t.priority !== "normal" && <span>{t.priority} priority</span>}
                {t.project && <span>#{t.project}</span>}
                <ByLoki by={t.created_by} />
              </div>
            </div>
            <button
              onClick={async () => {
                if (confirm(`Delete “${t.title}”?`)) {
                  await api.deleteTask(t.id);
                  load();
                }
              }}
              className="text-faint opacity-0 hover:text-bad group-hover:opacity-100 focus:opacity-100"
              aria-label={`Delete “${t.title}”`}
            >
              <Trash2 size={14} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Reminders() {
  const [items, setItems] = useState<ReminderItem[]>([]);
  const [text, setText] = useState("");
  const [when, setWhen] = useState("");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => api.reminders(true).then(setItems).catch((e) => setError(e.message)), []);
  useEffect(() => void load(), [load]);
  const upcoming = items.filter((r) => r.status === "scheduled").sort((a, b) => a.remind_at.localeCompare(b.remind_at));
  const past = items.filter((r) => r.status !== "scheduled");

  return (
    <div>
      <form
        className="flex flex-wrap gap-2"
        onSubmit={async (e) => {
          e.preventDefault();
          if (!text.trim() || !when) return;
          setError(null);
          try {
            await api.createReminder({ text: text.trim(), remind_at: new Date(when).toISOString() });
            setText("");
            setWhen("");
            load();
          } catch (x) {
            setError((x as Error).message);
          }
        }}
      >
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Remind me to…" maxLength={500} className={`${field} min-w-48 flex-1`} />
        <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} required className={field} aria-label="When" />
        <button className="flex items-center gap-1 rounded-lg bg-cyan/90 px-3 text-sm font-medium text-void hover:bg-cyan">
          <Plus size={15} /> Add
        </button>
      </form>
      {error && <p className="mt-2 text-sm text-bad">{error}</p>}
      <ul className="mt-4 space-y-1.5">
        {upcoming.length === 0 && <li className="text-sm text-faint">No upcoming reminders.</li>}
        {upcoming.map((r) => (
          <li key={r.id} className="flex items-center gap-3 rounded-xl border border-line bg-deep/40 px-3 py-2">
            <Bell size={15} className="text-cyan" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-ink">{r.text}</div>
              <div className="flex gap-2 text-[11px] text-faint">
                {fmt(r.remind_at)} <ByLoki by={r.created_by} />
              </div>
            </div>
            <button
              onClick={async () => {
                await api.cancelReminder(r.id);
                load();
              }}
              className="text-xs text-faint hover:text-bad"
            >
              Cancel
            </button>
          </li>
        ))}
      </ul>
      {past.length > 0 && (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer text-faint">Past and cancelled ({past.length})</summary>
          <ul className="mt-2 space-y-1 text-dim">
            {past.map((r) => (
              <li key={r.id}>
                <span className={r.status === "cancelled" ? "line-through" : ""}>{r.text}</span>{" "}
                <span className="text-[11px] text-faint">
                  · {fmt(r.remind_at)} · {r.status}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Calendar() {
  const [items, setItems] = useState<EventItem[]>([]);
  const load = useCallback(() => api.events(new Date(Date.now() - 86_400_000).toISOString()).then(setItems).catch(() => undefined), []);
  useEffect(() => void load(), [load]);
  return (
    <ul className="space-y-1.5">
      {items.length === 0 && <li className="text-sm text-faint">No upcoming events. Ask LOKI to add one.</li>}
      {items.map((e) => (
        <li key={e.id} className="group flex items-center gap-3 rounded-xl border border-line bg-deep/40 px-3 py-2">
          <CalendarDays size={15} className="text-cyan" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm text-ink">{e.title}</div>
            <div className="flex gap-2 text-[11px] text-faint">
              {fmt(e.starts_at)}
              {e.ends_at && `–${new Date(e.ends_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`}
              {e.location && ` · ${e.location}`} <ByLoki by={e.created_by} />
            </div>
          </div>
          <button
            onClick={async () => {
              if (confirm(`Delete “${e.title}”?`)) {
                await api.deleteEvent(e.id);
                load();
              }
            }}
            className="text-faint opacity-0 hover:text-bad group-hover:opacity-100 focus:opacity-100"
            aria-label={`Delete “${e.title}”`}
          >
            <Trash2 size={14} />
          </button>
        </li>
      ))}
    </ul>
  );
}

function Notes() {
  const [items, setItems] = useState<NoteItem[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const load = useCallback(() => api.notes().then(setItems).catch(() => undefined), []);
  useEffect(() => void load(), [load]);
  return (
    <ul className="space-y-2">
      {items.length === 0 && <li className="text-sm text-faint">No notes. Ask LOKI to save a summary or report.</li>}
      {items.map((n) => (
        <li key={n.id} className="rounded-xl border border-line bg-deep/40">
          <div className="flex items-center gap-3 px-3 py-2">
            <button onClick={() => setOpen(open === n.id ? null : n.id)} className="min-w-0 flex-1 text-left" aria-expanded={open === n.id}>
              <div className="truncate text-sm text-ink">{n.title}</div>
              <div className="flex gap-2 text-[11px] text-faint">
                {fmt(n.updated_at)} {n.project && `#${n.project}`} <ByLoki by={n.created_by} />
              </div>
            </button>
            <button
              onClick={async () => {
                if (confirm(`Delete note “${n.title}”?`)) {
                  await api.deleteNote(n.id);
                  load();
                }
              }}
              className="text-faint hover:text-bad"
              aria-label={`Delete note “${n.title}”`}
            >
              <Trash2 size={14} />
            </button>
          </div>
          {open === n.id && (
            <div className="prose-loki border-t border-line px-4 py-3 text-[14px]">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{n.body}</ReactMarkdown>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

export function Planner() {
  const setView = useChat((s) => s.setView);
  const [tab, setTab] = useState<Tab>("tasks");
  const tabs: [Tab, string, typeof Bell][] = [
    ["tasks", "Tasks", CheckSquare],
    ["reminders", "Reminders", Bell],
    ["calendar", "Calendar", CalendarDays],
    ["notes", "Notes", NotebookPen],
  ];
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
        <button onClick={() => setView("assistant")} className="mb-4 flex items-center gap-1.5 text-sm text-dim hover:text-ink">
          <ArrowLeft size={15} /> Back to LOKI
        </button>
        <h1 className="text-2xl font-light text-ink">Planner</h1>
        <p className="mt-1 text-sm text-dim">Tasks, reminders, events and notes, whether you added them or LOKI did.</p>
        <div className="mt-5 flex flex-wrap gap-1.5" role="tablist">
          {tabs.map(([key, label, Icon]) => (
            <button
              key={key}
              role="tab"
              aria-selected={tab === key}
              onClick={() => setTab(key)}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm transition ${
                tab === key ? "border-cyan/40 bg-cyan/10 text-cyan" : "border-line text-dim hover:text-ink"
              }`}
            >
              <Icon size={13} /> {label}
            </button>
          ))}
        </div>
        <div className="mt-5">
          {tab === "tasks" && <Tasks />}
          {tab === "reminders" && <Reminders />}
          {tab === "calendar" && <Calendar />}
          {tab === "notes" && <Notes />}
        </div>
      </div>
    </div>
  );
}
