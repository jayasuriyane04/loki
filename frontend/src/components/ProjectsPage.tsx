"use client";

import { ArrowLeft, FolderKanban, MessageSquare, Plus, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ProjectDetail, ProjectInfo, ProjectStatus } from "@/lib/types";
import { useChat } from "@/store/chat";

const STATUS_TONE: Record<ProjectStatus, string> = { active: "text-ok", paused: "text-warn", done: "text-faint" };
const input = "rounded-md border border-line bg-night px-2 py-1 text-sm text-ink outline-none focus:border-cyan/50";

function when(iso: string | null) {
  return iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—";
}

function Counts({ c }: { c: ProjectInfo["counts"] }) {
  const parts = [
    [c.open_tasks, "open task", "open tasks"],
    [c.notes, "note", "notes"],
    [c.documents, "file", "files"],
    [c.memories, "memory", "memories"],
    [c.conversations, "chat", "chats"],
  ] as const;
  return (
    <span className="text-xs text-dim">
      {parts
        .filter(([n]) => n > 0)
        .map(([n, one, many]) => `${n} ${n === 1 ? one : many}`)
        .join(" · ") || "Nothing yet"}
    </span>
  );
}

function Detail({ name, onBack, onChanged }: { name: string; onBack: () => void; onChanged: () => void }) {
  const openConversation = useChat((s) => s.openConversation);
  const [p, setP] = useState<ProjectDetail | null>(null);
  const [desc, setDesc] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .project(name)
      .then((d) => {
        setP(d);
        setDesc(d.description ?? "");
      })
      .catch((e: Error) => setError(e.message));
  }, [name]);

  async function patch(body: { description?: string | null; status?: ProjectStatus }) {
    setError(null);
    try {
      const info = await api.updateProject(name, body);
      setP((d) => (d ? { ...d, ...info } : d));
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function overview() {
    setBusy(true);
    setError(null);
    try {
      const info = await api.generateOverview(name);
      setP((d) => (d ? { ...d, ...info } : d));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <button onClick={onBack} className="mb-4 flex items-center gap-1.5 text-sm text-dim hover:text-ink">
        <ArrowLeft size={15} /> All projects
      </button>
      {error && <p className="mb-3 rounded-lg border border-bad/30 bg-bad/[0.07] px-3 py-2 text-sm">{error}</p>}
      {!p ? (
        !error && <p className="text-sm text-faint">Loading…</p>
      ) : (
        <div className="space-y-6">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="flex items-center gap-2 text-2xl font-light text-ink">
              <FolderKanban size={20} className="text-cyan" /> {p.name}
            </h1>
            <select
              aria-label="Project status"
              value={p.status}
              onChange={(e) => patch({ status: e.target.value as ProjectStatus })}
              className={`${input} ml-auto text-xs`}
            >
              <option value="active">Active</option>
              <option value="paused">Paused</option>
              <option value="done">Done</option>
            </select>
          </div>

          <section>
            <label htmlFor="proj-desc" className="hud-label mb-1 block">
              Description
            </label>
            <textarea
              id="proj-desc"
              value={desc}
              rows={2}
              maxLength={2000}
              onChange={(e) => setDesc(e.target.value)}
              onBlur={() => desc !== (p.description ?? "") && patch({ description: desc })}
              placeholder="What is this project? LOKI reads this whenever you talk about it."
              className={`${input} w-full resize-y`}
            />
          </section>

          <section>
            <div className="mb-1 flex items-center gap-2">
              <h2 className="hud-label">Overview</h2>
              <button
                onClick={overview}
                disabled={busy}
                className="ml-auto flex items-center gap-1 rounded-md border border-cyan/40 px-2 py-0.5 text-xs text-ink hover:bg-cyan/10 disabled:opacity-50"
              >
                <Sparkles size={12} className="text-cyan" />
                {busy ? "Writing…" : p.overview ? "Refresh" : "Write overview"}
              </button>
            </div>
            {p.overview ? (
              <>
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-dim">{p.overview}</p>
                <p className="mt-1 text-[11px] text-faint">Written by LOKI on {when(p.overview_at)} from what it knows below.</p>
              </>
            ) : (
              <p className="text-sm text-faint">LOKI can summarise everything it knows about this project. Only on request.</p>
            )}
          </section>

          <div className="grid gap-6 sm:grid-cols-2">
            <section>
              <h2 className="hud-label mb-1">Tasks</h2>
              {p.tasks.length === 0 && <p className="text-sm text-faint">None.</p>}
              <ul className="space-y-0.5 text-sm">
                {p.tasks.map((t) => (
                  <li key={t.id} className={t.status === "done" ? "text-faint line-through" : "text-dim"}>
                    {t.title}
                    {t.due_at && <span className="ml-1 text-[11px] text-faint">· due {when(t.due_at)}</span>}
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <h2 className="hud-label mb-1">Conversations</h2>
              {p.conversations.length === 0 && <p className="text-sm text-faint">None yet.</p>}
              <ul className="space-y-0.5">
                {p.conversations.map((c) => (
                  <li key={c.id}>
                    <button
                      onClick={() => openConversation(c.id)}
                      className="flex w-full items-center gap-1.5 truncate text-left text-sm text-dim hover:text-ink"
                    >
                      <MessageSquare size={12} className="shrink-0 opacity-60" />
                      <span className="truncate">{c.title}</span>
                      <span className="ml-auto shrink-0 text-[11px] text-faint">{when(c.updated_at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
            <section>
              <h2 className="hud-label mb-1">Notes</h2>
              {p.notes.length === 0 && <p className="text-sm text-faint">None.</p>}
              <ul className="space-y-0.5 text-sm text-dim">
                {p.notes.map((n) => (
                  <li key={n.id}>{n.title}</li>
                ))}
              </ul>
            </section>
            <section>
              <h2 className="hud-label mb-1">Files</h2>
              {p.documents.length === 0 && <p className="text-sm text-faint">None.</p>}
              <ul className="space-y-0.5">
                {p.documents.map((d) => (
                  <li key={d.id} className="truncate font-mono text-[12px] text-dim" title={d.source}>
                    {d.source}
                    {d.status !== "ready" && <span className="ml-1 text-faint">({d.status})</span>}
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <section>
            <h2 className="hud-label mb-1">What LOKI remembers</h2>
            {p.memories.length === 0 && <p className="text-sm text-faint">Nothing yet.</p>}
            <ul className="space-y-1 text-sm text-dim">
              {p.memories.map((m) => (
                <li key={m.id}>
                  {m.event_at && <span className="mr-1.5 font-mono text-[11px] text-faint">{when(m.event_at)}</span>}
                  {m.content}
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}

export function ProjectsPage() {
  const setView = useChat((s) => s.setView);
  const [projects, setProjects] = useState<ProjectInfo[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      api
        .projectsOverview()
        .then(setProjects)
        .catch((e: Error) => setError(e.message)),
    [],
  );
  useEffect(() => void load(), [load]);

  async function create() {
    const name = draft.trim();
    if (!name) return;
    setError(null);
    try {
      await api.createProject({ name });
      setDraft("");
      await load();
      setOpen(name);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
        {open ? (
          <Detail name={open} onBack={() => setOpen(null)} onChanged={load} />
        ) : (
          <>
            <button onClick={() => setView("assistant")} className="mb-4 flex items-center gap-1.5 text-sm text-dim hover:text-ink">
              <ArrowLeft size={15} /> Back to LOKI
            </button>
            <h1 className="flex items-center gap-2 text-2xl font-light text-ink">
              <FolderKanban size={20} className="text-cyan" /> Projects
            </h1>
            <p className="mt-1 max-w-xl text-sm text-dim">
              Everything LOKI knows per project: tasks, notes, files, memories and past conversations. Mention a project by
              name in chat (“let&apos;s continue Tarka”) and LOKI picks up where you left off.
            </p>
            {error && <p className="mt-3 rounded-lg border border-bad/30 bg-bad/[0.07] px-3 py-2 text-sm">{error}</p>}

            <form
              className="mt-5 flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                create();
              }}
            >
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="New project name"
                aria-label="New project name"
                maxLength={100}
                className={`${input} min-w-0 flex-1`}
              />
              <button type="submit" className="flex items-center gap-1 rounded-md border border-cyan/40 px-3 py-1 text-sm text-ink hover:bg-cyan/10">
                <Plus size={14} /> Add
              </button>
            </form>

            <div className="mt-5 space-y-2">
              {projects?.length === 0 && (
                <p className="text-sm text-faint">
                  No projects yet. Add one here, or tag a task, note or upload with a project name.
                </p>
              )}
              {projects?.map((p) => (
                <button
                  key={p.name}
                  onClick={() => setOpen(p.name)}
                  className="block w-full rounded-xl border border-line bg-deep/40 px-4 py-3 text-left transition hover:border-cyan/30"
                >
                  <div className="flex items-baseline gap-2">
                    <span className="text-ink">{p.name}</span>
                    <span className={`text-[11px] ${STATUS_TONE[p.status]}`}>{p.status}</span>
                    <span className="ml-auto text-[11px] text-faint">{p.last_activity ? `active ${when(p.last_activity)}` : ""}</span>
                  </div>
                  {p.description && <p className="mt-0.5 line-clamp-2 text-sm text-dim">{p.description}</p>}
                  <Counts c={p.counts} />
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
