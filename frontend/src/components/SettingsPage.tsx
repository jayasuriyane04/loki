"use client";

import { ArrowLeft, FolderSync, Plus, RefreshCw, Settings, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { FolderScan, Learned, Preferences, PreferencesPatch } from "@/lib/types";
import { useChat } from "@/store/chat";

function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className={`relative h-5 w-9 shrink-0 rounded-full border transition ${
        on ? "border-cyan/50 bg-cyan/30" : "border-line-strong bg-night"
      }`}
    >
      <span
        className={`absolute top-0.5 h-3.5 w-3.5 rounded-full transition-all ${on ? "left-[18px] bg-cyan" : "left-0.5 bg-faint"}`}
      />
    </button>
  );
}

function Row({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-3 px-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="text-sm text-ink">{title}</div>
        {hint && <div className="text-xs text-dim">{hint}</div>}
      </div>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  );
}

function Section({ title, children, note }: { title: string; children: ReactNode; note?: ReactNode }) {
  return (
    <section>
      <h2 className="hud-label mb-2">{title}</h2>
      {note && <p className="mb-2 text-xs text-dim">{note}</p>}
      <div className="divide-y divide-line rounded-xl border border-line bg-deep/40">{children}</div>
    </section>
  );
}

const input = "rounded-md border border-line bg-night px-2 py-1 text-sm text-ink outline-none focus:border-cyan/50";

function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T;
  options: [T, string][];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex rounded-md border border-line bg-night p-0.5">
      {options.map(([v, text]) => (
        <button
          key={v}
          role="radio"
          aria-checked={value === v}
          onClick={() => onChange(v)}
          className={`rounded px-2.5 py-1 text-xs transition ${value === v ? "bg-cyan/15 text-ink" : "text-dim hover:text-ink"}`}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

/** Text field that saves when it loses focus (or on Enter). */
function Field({ value, onSave, ...rest }: { value: string; onSave: (v: string) => void } & Omit<
  React.InputHTMLAttributes<HTMLInputElement>,
  "value" | "onChange"
>) {
  const [draft, setDraft] = useState(value);
  const [prev, setPrev] = useState(value);
  if (value !== prev) {
    setPrev(value);
    setDraft(value);
  }
  return (
    <input
      {...rest}
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => draft !== value && onSave(draft)}
      onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
      className={`${input} ${rest.className ?? ""}`}
    />
  );
}

export function SettingsPage() {
  const setView = useChat((s) => s.setView);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [memoryOn, setMemoryOn] = useState<boolean | null>(null);
  const [learned, setLearned] = useState<Learned | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [folder, setFolder] = useState({ path: "", project: "", interval_min: 30 });
  const [scan, setScan] = useState<Record<string, FolderScan | string>>({});

  const load = useCallback(
    () =>
      Promise.all([api.preferences(), api.settings(), api.learned()])
        .then(([p, s, l]) => {
          setPrefs(p);
          setInstructions(p.style.custom_instructions);
          setMemoryOn(s.memory_enabled);
          setLearned(l);
        })
        .catch((e: Error) => setError(e.message)),
    [],
  );
  useEffect(() => void load(), [load]);

  async function save(patch: PreferencesPatch) {
    setError(null);
    try {
      const p = await api.updatePreferences(patch);
      setPrefs(p);
      setSaved(true);
      setTimeout(() => setSaved(false), 1200);
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    }
  }

  async function setMemory(v: boolean) {
    setError(null);
    try {
      setMemoryOn((await api.updateSettings({ memory_enabled: v })).memory_enabled);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function addFolder() {
    if (!prefs) return;
    const path = folder.path.trim();
    const project = folder.project.trim();
    if (!path || !project) return setError("A watched folder needs a full path and a project name.");
    const ok = await save({ proactive: { watched_folders: [...prefs.proactive.watched_folders, { ...folder, path, project }] } });
    if (ok) {
      setFolder({ path: "", project: "", interval_min: 30 });
      scanNow(path);
    }
  }

  async function scanNow(path: string) {
    setScan((s) => ({ ...s, [path]: "Scanning…" }));
    try {
      const r = await api.scanFolder(path);
      setScan((s) => ({ ...s, [path]: r }));
    } catch (e) {
      setScan((s) => ({ ...s, [path]: (e as Error).message }));
    }
  }

  const p = prefs;
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
        <button onClick={() => setView("assistant")} className="mb-4 flex items-center gap-1.5 text-sm text-dim hover:text-ink">
          <ArrowLeft size={15} /> Back to LOKI
        </button>
        <h1 className="flex items-center gap-2 text-2xl font-light text-ink">
          <Settings size={20} className="text-cyan" /> Settings
          <span className={`ml-2 text-xs text-ok transition-opacity ${saved ? "opacity-100" : "opacity-0"}`} aria-live="polite">
            Saved
          </span>
        </h1>
        <p className="mt-1 max-w-xl text-sm text-dim">
          How LOKI talks to you and what it may do in the background. Changes save as you make them.
        </p>
        {error && <p className="mt-3 rounded-lg border border-bad/30 bg-bad/[0.07] px-3 py-2 text-sm">{error}</p>}
        {!p && !error && <p className="mt-6 text-sm text-faint">Loading…</p>}

        {p && (
          <div className="mt-6 space-y-8">
            <Section title="Replies">
              <Row title="Length">
                <Segmented
                  label="Reply length"
                  value={p.style.response_length}
                  options={[["brief", "Brief"], ["balanced", "Balanced"], ["detailed", "Detailed"]]}
                  onChange={(v) => save({ style: { response_length: v } })}
                />
              </Row>
              <Row title="Tone">
                <Segmented
                  label="Tone"
                  value={p.style.tone}
                  options={[["casual", "Casual"], ["neutral", "Neutral"], ["formal", "Formal"]]}
                  onChange={(v) => save({ style: { tone: v } })}
                />
              </Row>
              <Row title="Language" hint="“auto” answers in whatever language you write in.">
                <Field
                  value={p.style.language}
                  maxLength={40}
                  aria-label="Reply language"
                  className="w-36"
                  onSave={(v) => save({ style: { language: v.trim() || "auto" } })}
                />
              </Row>
              <Row title="Formatting" hint="Headings, bold text and tables in typed replies.">
                <Toggle label="Use Markdown" on={p.style.markdown} onChange={(v) => save({ style: { markdown: v } })} />
              </Row>
              <div className="px-3 py-2.5">
                <label htmlFor="custom-instructions" className="text-sm text-ink">
                  Your instructions for LOKI
                </label>
                <p className="text-xs text-dim">
                  Anything LOKI should always keep in mind. It follows these unless they conflict with its rules on honesty,
                  safety and approvals.
                </p>
                <textarea
                  id="custom-instructions"
                  value={instructions}
                  maxLength={1000}
                  rows={3}
                  onChange={(e) => setInstructions(e.target.value)}
                  onBlur={() => instructions !== p.style.custom_instructions && save({ style: { custom_instructions: instructions } })}
                  placeholder="e.g. I'm a backend developer; skip beginner explanations. Use metric units."
                  className={`${input} mt-2 w-full resize-y`}
                />
                <div className="text-right text-[11px] text-faint">{instructions.length}/1000</div>
              </div>
            </Section>

            <Section title="Voice & memory">
              <Row title="Voice" hint="Voice, speed and spoken replies are set from the Voice button in the top bar and saved to your account.">
                <span className="text-xs text-dim">
                  {p.voice.voice ?? "default"} · {p.voice.speed.toFixed(2)}×
                </span>
              </Row>
              <Row title="Memory" hint="Let LOKI remember facts and conversations across chats.">
                {memoryOn !== null && <Toggle label="Memory" on={memoryOn} onChange={setMemory} />}
                <button onClick={() => setView("memories")} className="text-xs text-cyan hover:underline">
                  Manage
                </button>
              </Row>
            </Section>

            <Section
              title="Background"
              note="Proactive features run on a timer, never by keeping the model busy. Only conversation summaries use the model."
            >
              <Row title="Background processing" hint="Master switch. Off = no alerts, briefings, summaries or folder scans. Your own reminders still arrive.">
                <Toggle label="Background processing" on={p.background_processing} onChange={(v) => save({ background_processing: v })} />
              </Row>
              <div className={p.background_processing ? "" : "pointer-events-none opacity-40"} aria-disabled={!p.background_processing}>
                <Row title="Deadline alerts" hint="A heads-up before a task is due, and when it becomes overdue.">
                  <select
                    aria-label="Deadline lead time"
                    value={p.proactive.deadline_lead_min}
                    onChange={(e) => save({ proactive: { deadline_lead_min: Number(e.target.value) } })}
                    className={input}
                  >
                    {[15, 30, 60, 120, 240, 1440].map((m) => (
                      <option key={m} value={m}>
                        {m < 60 ? `${m} min` : m === 1440 ? "1 day" : `${m / 60} h`} before
                      </option>
                    ))}
                  </select>
                  <Toggle label="Deadline alerts" on={p.proactive.deadline_alerts} onChange={(v) => save({ proactive: { deadline_alerts: v } })} />
                </Row>
                <Row title="Event heads-up" hint="Before calendar events, with related notes and documents.">
                  <select
                    aria-label="Event lead time"
                    value={p.proactive.event_lead_min}
                    onChange={(e) => save({ proactive: { event_lead_min: Number(e.target.value) } })}
                    className={input}
                  >
                    {[5, 10, 15, 30, 60, 120].map((m) => (
                      <option key={m} value={m}>
                        {m < 60 ? `${m} min` : `${m / 60} h`} before
                      </option>
                    ))}
                  </select>
                  <Toggle label="Event heads-up" on={p.proactive.event_headsup} onChange={(v) => save({ proactive: { event_headsup: v } })} />
                </Row>
                <Row title="Daily briefing" hint="Today's calendar, due tasks and reminders (and weather, if you add a place).">
                  <input
                    type="time"
                    aria-label="Briefing time"
                    value={p.proactive.briefing_time}
                    onChange={(e) => e.target.value && save({ proactive: { briefing_time: e.target.value } })}
                    className={input}
                  />
                  <Field
                    value={p.proactive.briefing_location}
                    placeholder="City (optional)"
                    maxLength={100}
                    aria-label="Briefing weather location"
                    className="w-36"
                    onSave={(v) => save({ proactive: { briefing_location: v.trim() } })}
                  />
                  <Toggle label="Daily briefing" on={p.proactive.daily_briefing} onChange={(v) => save({ proactive: { daily_briefing: v } })} />
                </Row>
                <Row
                  title="Conversation summaries"
                  hint="After a conversation goes quiet, LOKI saves a short dated summary to memory, so “what we discussed yesterday” works."
                >
                  <Toggle
                    label="Conversation summaries"
                    on={p.proactive.conversation_digests}
                    onChange={(v) => save({ proactive: { conversation_digests: v } })}
                  />
                </Row>
              </div>
            </Section>

            <Section title="Quiet hours" note="Alerts and briefings wait until quiet hours end. Reminders you set still arrive on time.">
              <Row title="Quiet hours">
                <input
                  type="time"
                  aria-label="Quiet hours start"
                  value={p.quiet_hours.start}
                  onChange={(e) => e.target.value && save({ quiet_hours: { start: e.target.value } })}
                  className={input}
                />
                <span className="text-xs text-faint">to</span>
                <input
                  type="time"
                  aria-label="Quiet hours end"
                  value={p.quiet_hours.end}
                  onChange={(e) => e.target.value && save({ quiet_hours: { end: e.target.value } })}
                  className={input}
                />
                <Toggle label="Quiet hours" on={p.quiet_hours.enabled} onChange={(v) => save({ quiet_hours: { enabled: v } })} />
              </Row>
            </Section>

            <Section
              title="Watched folders"
              note="LOKI keeps these folders indexed in your knowledge base under a project and tells you what changed. It only reads supported text, code and PDF files, skips .env and key files, and never writes to the folder."
            >
              {p.proactive.watched_folders.length === 0 && (
                <p className="px-3 py-2.5 text-sm text-faint">No folders yet.</p>
              )}
              {p.proactive.watched_folders.map((f) => {
                const r = scan[f.path];
                return (
                  <div key={f.path} className="px-3 py-2.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <FolderSync size={14} className="text-cyan" />
                      <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-ink" title={f.path}>
                        {f.path}
                      </span>
                      <span className="rounded bg-cyan/10 px-1.5 py-0.5 text-[11px] text-cyan">{f.project}</span>
                      <span className="text-[11px] text-faint">every {f.interval_min} min</span>
                      <button onClick={() => scanNow(f.path)} className="p-1 text-dim hover:text-ink" aria-label={`Scan ${f.path} now`} title="Scan now">
                        <RefreshCw size={13} />
                      </button>
                      <button
                        onClick={() =>
                          save({ proactive: { watched_folders: p.proactive.watched_folders.filter((x) => x.path !== f.path) } })
                        }
                        className="p-1 text-dim hover:text-bad"
                        aria-label={`Stop watching ${f.path}`}
                        title="Stop watching (indexed files stay in the knowledge base)"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                    {r && (
                      <p className="mt-1 pl-6 text-xs text-dim">
                        {typeof r === "string"
                          ? r
                          : `${r.added.length} new, ${r.updated.length} updated, ${r.removed.length} removed` +
                            (r.skipped ? `, ${r.skipped} skipped (unsupported or too large)` : "") +
                            ". Indexing continues in the knowledge base."}
                      </p>
                    )}
                  </div>
                );
              })}
              <form
                className="flex flex-wrap items-center gap-2 px-3 py-2.5"
                onSubmit={(e) => {
                  e.preventDefault();
                  addFolder();
                }}
              >
                <input
                  value={folder.path}
                  onChange={(e) => setFolder({ ...folder, path: e.target.value })}
                  placeholder="Full folder path, e.g. C:\Users\you\code\tarka"
                  aria-label="Folder path"
                  maxLength={500}
                  className={`${input} min-w-0 flex-[3]`}
                />
                <input
                  value={folder.project}
                  onChange={(e) => setFolder({ ...folder, project: e.target.value })}
                  placeholder="Project"
                  aria-label="Project name"
                  maxLength={100}
                  className={`${input} min-w-0 flex-1`}
                />
                <select
                  aria-label="Scan interval"
                  value={folder.interval_min}
                  onChange={(e) => setFolder({ ...folder, interval_min: Number(e.target.value) })}
                  className={input}
                >
                  {[5, 15, 30, 60, 240, 1440].map((m) => (
                    <option key={m} value={m}>
                      {m < 60 ? `${m} min` : m === 1440 ? "daily" : `${m / 60} h`}
                    </option>
                  ))}
                </select>
                <button type="submit" className="flex items-center gap-1 rounded-md border border-cyan/40 px-2.5 py-1 text-xs text-ink hover:bg-cyan/10">
                  <Plus size={13} /> Watch
                </button>
              </form>
            </Section>

            {learned && (
              <Section
                title="What LOKI has picked up"
                note="Learned from your conversations and how you use LOKI. Edit or delete these on the Memory page."
              >
                <div className="px-3 py-2.5">
                  {learned.preference_memories.length === 0 ? (
                    <p className="text-sm text-faint">No preferences noticed yet.</p>
                  ) : (
                    <ul className="list-disc space-y-0.5 pl-5 text-sm text-dim">
                      {learned.preference_memories.map((m) => (
                        <li key={m.id}>{m.content}</li>
                      ))}
                    </ul>
                  )}
                </div>
                {learned.top_tools.length > 0 && (
                  <div className="px-3 py-2.5">
                    <div className="mb-1 text-xs text-dim">Tools you use most (30 days)</div>
                    <div className="flex flex-wrap gap-1.5">
                      {learned.top_tools.map((t) => (
                        <span key={t.tool} className="rounded bg-white/[0.04] px-1.5 py-0.5 font-mono text-[11px] text-dim">
                          {t.tool} · {t.count}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </Section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
