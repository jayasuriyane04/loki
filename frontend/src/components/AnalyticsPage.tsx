"use client";

import { ArrowLeft, ChartColumn, ChevronDown, ChevronRight, RefreshCw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import type { Dist, EvalReport, MetricsSummary, TraceInfo } from "@/lib/types";
import { useChat } from "@/store/chat";
import { ColumnChart, LineChart, Waterfall } from "./Charts";

const PERIODS = [1, 7, 30] as const;

function ms(v: number | null | undefined) {
  if (v === null || v === undefined) return "—";
  return v >= 1000 ? `${(v / 1000).toFixed(v >= 10_000 ? 0 : 2)} s` : `${Math.round(v)} ms`;
}
function pct(v: number | null | undefined) {
  return v === null || v === undefined ? "—" : `${Math.round(v * 1000) / 10}%`;
}
function num(v: number | null | undefined) {
  if (v === null || v === undefined) return "—";
  return v >= 10_000 ? `${(v / 1000).toFixed(1)}K` : v.toLocaleString();
}
function p50p95(d: Dist) {
  return d.n ? `p95 ${ms(d.p95)} · ${d.n} samples` : "no samples yet";
}

function Tile({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="min-w-0 rounded-xl border border-line bg-deep/40 px-3 py-2.5">
      <div className="truncate text-xs text-dim">{label}</div>
      <div className="mt-0.5 text-xl font-semibold text-ink">{value}</div>
      {sub && <div className="mt-0.5 truncate text-[11px] text-faint">{sub}</div>}
    </div>
  );
}

function Section({ title, note, children }: { title: string; note?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <h2 className="hud-label mb-2">{title}</h2>
      {note && <p className="-mt-1 mb-2 text-xs text-dim">{note}</p>}
      {children}
    </section>
  );
}

const grid = "grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4";
const table = "w-full text-left text-[12.5px]";
const th = "px-2 py-1.5 font-normal text-dim";
const td = "px-2 py-1.5 text-ink";

function EvalCard({ suite, info }: { suite: string; info: MetricsSummary["evals"][string] }) {
  const [open, setOpen] = useState(false);
  const [report, setReport] = useState<EvalReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toggle = () => {
    setOpen(!open);
    if (!report && !open) api.evalReport(info.file).then(setReport).catch((e: Error) => setError(e.message));
  };
  const head = Object.entries(info.headline ?? {});
  const TITLE: Record<string, string> = { rag: "Knowledge retrieval & answers", agent: "Agent & tools", voice: "Voice" };
  return (
    <div className="rounded-xl border border-line bg-deep/40">
      <button onClick={toggle} className="flex w-full items-center gap-2 px-3 py-2.5 text-left" aria-expanded={open}>
        {open ? <ChevronDown size={14} className="text-dim" /> : <ChevronRight size={14} className="text-dim" />}
        <span className="text-sm text-ink">{TITLE[suite] ?? suite}</span>
        <span className="ml-auto text-[11px] text-faint">{new Date(info.ran_at).toLocaleString()}</span>
      </button>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 px-3 pb-3 text-[12px] sm:grid-cols-3">
        {head.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-2 border-b border-line/50 py-0.5">
            <dt className="truncate text-dim">{k.replaceAll("_", " ")}</dt>
            <dd className="font-mono text-ink">{typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(3)) : String(v)}</dd>
          </div>
        ))}
      </dl>
      {open && (
        <div className="border-t border-line px-3 py-3 text-[12px]">
          {error && <p className="text-bad">{error}</p>}
          {!report && !error && <p className="text-faint">Loading…</p>}
          {report && <EvalDetails report={report} />}
        </div>
      )}
    </div>
  );
}

function EvalDetails({ report }: { report: EvalReport }) {
  const d = report.details as Record<string, unknown>;
  const cfg = Object.entries(report.config).filter(([, v]) => v !== null && typeof v !== "object");
  return (
    <div className="space-y-3">
      <p className="text-faint">{cfg.map(([k, v]) => `${k.replaceAll("_", " ")}: ${String(v)}`).join(" · ")}</p>
      {report.suite === "rag" && (
        <table className={table}>
          <thead>
            <tr className="border-b border-line">
              {["Search mode", "Recall@5", "P@1", "NDCG@5", "MRR", "p50"].map((h) => (
                <th key={h} className={th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Object.entries(d.retrieval_by_mode as Record<string, Record<string, number>>).map(([mode, m]) => (
              <tr key={mode} className="border-b border-line/50">
                <td className={td}>{mode}</td>
                <td className={td}>{m["recall@5"]?.toFixed(3)}</td>
                <td className={td}>{m["p@1"]?.toFixed(3)}</td>
                <td className={td}>{m["ndcg@5"]?.toFixed(3)}</td>
                <td className={td}>{m.mrr?.toFixed(3)}</td>
                <td className={td}>{ms(m.p50_ms)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {report.suite === "agent" && (
        <table className={table}>
          <thead>
            <tr className="border-b border-line">
              {["Scenario", "Passed", "Tools called"].map((h) => (
                <th key={h} className={th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(d.runs as { id: string; run: number; passed: boolean; tools: { tool: string; status: string }[] }[]).map((r) => (
              <tr key={`${r.id}-${r.run}`} className="border-b border-line/50">
                <td className={td}>{r.id}{r.run > 1 ? ` (run ${r.run})` : ""}</td>
                <td className={td}>{r.passed ? "yes" : <span className="text-bad">no</span>}</td>
                <td className={`${td} font-mono text-[11px] text-dim`}>
                  {r.tools.map((t) => `${t.tool}${t.status === "ok" ? "" : ` (${t.status})`}`).join(" → ") || "none"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {report.suite === "voice" && (
        <table className={table}>
          <thead>
            <tr className="border-b border-line">
              {["Spoken question", "Recognition", "First audio", "Total"].map((h) => (
                <th key={h} className={th}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(d.turns as { question: string; stt_ms: number; first_audio_s: number; total_s: number }[]).map((t) => (
              <tr key={t.question} className="border-b border-line/50">
                <td className={td}>{t.question}</td>
                <td className={td}>{ms(t.stt_ms)}</td>
                <td className={td}>{ms(t.first_audio_s * 1000)}</td>
                <td className={td}>{ms(t.total_s * 1000)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function AnalyticsPage() {
  const setView = useChat((s) => s.setView);
  const [days, setDays] = useState<number>(7);
  const [m, setM] = useState<MetricsSummary | null>(null);
  const [traces, setTraces] = useState<TraceInfo[]>([]);
  const [openTrace, setOpenTrace] = useState<string | null>(null);
  const [asTable, setAsTable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback((d: number) => {
    return Promise.all([api.metricsSummary(d), api.traces(25)])
      .then(([s, t]) => {
        setM(s);
        setTraces(t);
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => void load(days), [load, days]);

  const short = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-6">
        <button onClick={() => setView("assistant")} className="mb-4 flex items-center gap-1.5 text-sm text-dim hover:text-ink">
          <ArrowLeft size={15} /> Back to LOKI
        </button>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="flex items-center gap-2 text-2xl font-light text-ink">
            <ChartColumn size={20} className="text-cyan" /> Analytics
          </h1>
          <div className="ml-auto flex items-center gap-2">
            <div role="radiogroup" aria-label="Period" className="flex rounded-md border border-line bg-night p-0.5">
              {PERIODS.map((p) => (
                <button
                  key={p}
                  role="radio"
                  aria-checked={days === p}
                  onClick={() => setDays(p)}
                  className={`rounded px-2.5 py-1 text-xs ${days === p ? "bg-cyan/15 text-ink" : "text-dim hover:text-ink"}`}
                >
                  {p === 1 ? "24 h" : `${p} days`}
                </button>
              ))}
            </div>
            <button onClick={() => {
                setLoading(true);
                load(days);
              }} className="rounded-md p-1.5 text-dim hover:text-ink" aria-label="Refresh" title="Refresh">
              <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
            </button>
          </div>
        </div>
        <p className="mt-1 max-w-2xl text-sm text-dim">
          How LOKI is performing for you, measured on every turn. Traces store timings and counts only, never what was
          said, and are kept for 30 days. Offline evaluation results are at the bottom.
        </p>
        {error && <p className="mt-3 rounded-lg border border-bad/30 bg-bad/[0.07] px-3 py-2 text-sm">{error}</p>}
        {!m && !error && <p className="mt-6 text-sm text-faint">Loading…</p>}

        {m && (
          <div className="mt-6 space-y-8">
            <Section title="Responses">
              <div className={grid}>
                <Tile label="Turns" value={num(m.responses.turns)} sub={`${m.responses.errors} errors · ${pct(m.responses.error_rate)}`} />
                <Tile label="Time to first word (p50)" value={ms(m.responses.first_token_ms.p50)} sub={p50p95(m.responses.first_token_ms)} />
                <Tile label="Full reply (p50)" value={ms(m.responses.total_ms.p50)} sub={p50p95(m.responses.total_ms)} />
                <Tile
                  label="Tokens"
                  value={num(m.responses.prompt_tokens + m.responses.completion_tokens)}
                  sub={`${num(m.responses.prompt_tokens)} in · ${num(m.responses.completion_tokens)} out`}
                />
                <Tile
                  label="Model cost"
                  value={m.responses.cost_usd === null ? "$0" : `$${m.responses.cost_usd.toFixed(4)}`}
                  sub={m.responses.cost_usd === null ? "local models only" : "configured prices"}
                />
                <Tile label="Fallbacks to the cloud model" value={num(m.responses.fallbacks)} />
              </div>
            </Section>

            <Section title="Activity">
              <div className="rounded-xl border border-line bg-deep/40 p-3">
                <div className="mb-1 flex items-center">
                  <span className="text-sm text-ink">Turns per day</span>
                  <button onClick={() => setAsTable(!asTable)} className="ml-auto text-xs text-cyan hover:underline">
                    {asTable ? "Show charts" : "Show as table"}
                  </button>
                </div>
                {asTable ? (
                  <table className={table}>
                    <thead>
                      <tr className="border-b border-line">
                        {["Day", "Turns", "Errors", "Tokens", "Time to first word (p50)"].map((h) => (
                          <th key={h} className={th}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {m.daily.map((r) => (
                        <tr key={r.date} className="border-b border-line/50">
                          <td className={td}>{short(r.date)}</td>
                          <td className={td}>{r.turns}</td>
                          <td className={td}>{r.errors}</td>
                          <td className={td}>{num(r.tokens)}</td>
                          <td className={td}>{ms(r.p50_first_token_ms)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <>
                    <ColumnChart title="Turns per day" data={m.daily.map((r) => ({ label: short(r.date), value: r.turns }))} />
                    <div className="mb-1 mt-3 text-sm text-ink">Time to first word, median per day (ms)</div>
                    <LineChart
                      title="Median time to first word per day"
                      unit="ms"
                      data={m.daily.map((r) => ({ label: short(r.date), value: r.p50_first_token_ms }))}
                    />
                  </>
                )}
              </div>
            </Section>

            <Section title="Voice">
              <div className={grid}>
                <Tile label="Voice turns" value={num(m.voice.turns)} sub={`${m.voice.no_speech} with no speech heard`} />
                <Tile label="Speech recognition (p50)" value={ms(m.voice.stt_ms.p50)} sub={p50p95(m.voice.stt_ms)} />
                <Tile label="Time to first audio (p50)" value={ms(m.voice.first_audio_ms.p50)} sub={p50p95(m.voice.first_audio_ms)} />
                <Tile label="Voice turn total (p50)" value={ms(m.voice.total_ms.p50)} sub={p50p95(m.voice.total_ms)} />
                <Tile label="Recognition errors" value={num(m.voice.stt_errors)} sub={`rate ${pct(m.voice.stt_error_rate)}`} />
                <Tile label="Interruptions" value={num(m.voice.interrupted)} sub={`${m.voice.stop_commands} spoken “stop”`} />
                <Tile label="Speech synthesis failures" value={num(m.voice.tts_failures)} />
              </div>
            </Section>

            <Section title="Knowledge & memory">
              <div className={grid}>
                <Tile label="Document search (p50)" value={ms(m.rag.retrieval_ms.p50)} sub={p50p95(m.rag.retrieval_ms)} />
                <Tile label="Turns that used documents" value={num(m.rag.turns_with_documents)} sub={`${m.rag.avg_passages ?? "—"} passages on average`} />
                <Tile label="Valid citations" value={pct(m.rag.citation_validity)} sub={`${m.rag.invented_citations} invented [n] markers`} />
                <Tile label="Passages cited" value={`${m.rag.passages_cited}/${m.rag.passages_shown}`} sub="cited / shown to the model" />
                <Tile label="Memory recall (p50)" value={ms(m.memory.recall_ms.p50)} sub={`${m.memory.recalls_with_hits} turns recalled something`} />
                <Tile label="Memory extraction (p50)" value={ms(m.memory.extraction_ms.p50)} sub={`${m.memory.extraction_errors} errors`} />
              </div>
            </Section>

            <Section title="Agent & tools" note="Failure recovery: turns where a tool failed and a later call in the same turn succeeded.">
              <div className={grid}>
                <Tile label="Tool calls" value={num(m.agent.tool_calls)} sub={`in ${m.agent.turns_with_tools} turns`} />
                <Tile label="Tool success rate" value={pct(m.agent.success_rate)} sub={`${m.agent.failed} failed · ${m.agent.denied} declined by you`} />
                <Tile label="Failure recovery" value={pct(m.agent.failure_recovery_rate)} sub={`${m.agent.turns_with_failures} turns had a failure`} />
                <Tile
                  label="Safety-net interventions"
                  value={num(Object.values(m.agent.guards).reduce((a, b) => a + b, 0))}
                  sub={Object.entries(m.agent.guards).map(([k, v]) => `${k.replaceAll("_", " ")} ${v}`).join(" · ") || "none"}
                />
              </div>
              {m.agent.per_tool.length > 0 && (
                <table className={`${table} mt-3`}>
                  <thead>
                    <tr className="border-b border-line">
                      {["Tool", "Calls", "Success", "p50"].map((h) => (
                        <th key={h} className={th}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {m.agent.per_tool.map((t) => (
                      <tr key={t.tool} className="border-b border-line/50">
                        <td className={`${td} font-mono text-[12px]`}>{t.tool}</td>
                        <td className={td}>{t.calls}</td>
                        <td className={td}>{pct(t.success_rate)}</td>
                        <td className={td}>{ms(t.p50_ms)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Section>

            <Section title="System">
              <div className={grid}>
                <Tile label="API requests" value={num(m.system.requests)} sub={`${m.system.server_errors} server errors`} />
                <Tile label="API response (p50)" value={ms(m.system.api_ms.p50)} sub={p50p95(m.system.api_ms)} />
                <Tile label="Logged errors" value={num(m.system.errors)} />
                <Tile label="Open sessions" value={num(m.system.connections_now)} sub={`peak ${m.system.connections_peak}`} />
                <Tile
                  label="Your ratings"
                  value={
                    <span className="flex items-center gap-3">
                      <span className="flex items-center gap-1"><ThumbsUp size={15} className="text-dim" />{m.system.feedback.up}</span>
                      <span className="flex items-center gap-1"><ThumbsDown size={15} className="text-dim" />{m.system.feedback.down}</span>
                    </span>
                  }
                  sub="from the thumbs under replies"
                />
              </div>
              <div className="mt-3 grid gap-4 lg:grid-cols-2">
                <div>
                  <div className="mb-1 text-xs text-dim">Slowest endpoints (p95)</div>
                  <table className={table}>
                    <tbody>
                      {m.system.slowest_routes.map((r) => (
                        <tr key={r.route} className="border-b border-line/50">
                          <td className={`${td} font-mono text-[11.5px]`}>{r.route}</td>
                          <td className={`${td} text-right text-dim`}>{r.n}×</td>
                          <td className={`${td} text-right`}>{ms(r.p95_ms)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div>
                  <div className="mb-1 text-xs text-dim">Recent errors</div>
                  {m.system.recent_errors.length === 0 && <p className="text-sm text-faint">None in this period.</p>}
                  <ul className="space-y-1 text-[12px]">
                    {m.system.recent_errors.map((e, i) => (
                      <li key={i} className="border-b border-line/50 pb-1">
                        <span className="font-mono text-[11px] text-faint">{new Date(e.at).toLocaleString()}</span>{" "}
                        <span className="text-dim">{e.source}</span>
                        <div className="truncate text-ink" title={e.message ?? ""}>{e.message}</div>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </Section>

            <Section title="Recent traces" note="One row per turn; open it to see where the time went.">
              {traces.length === 0 && <p className="text-sm text-faint">No traces yet. Talk to LOKI and they appear here.</p>}
              <ul className="divide-y divide-line rounded-xl border border-line bg-deep/40">
                {traces.map((t) => {
                  const open = openTrace === t.id;
                  const tools = (t.attrs.tools as { tool: string; status: string }[] | undefined) ?? [];
                  return (
                    <li key={t.id}>
                      <button
                        onClick={() => setOpenTrace(open ? null : t.id)}
                        className="flex w-full flex-wrap items-center gap-x-3 gap-y-0.5 px-3 py-2 text-left text-[12.5px]"
                        aria-expanded={open}
                      >
                        {open ? <ChevronDown size={13} className="text-dim" /> : <ChevronRight size={13} className="text-dim" />}
                        <span className="font-mono text-[11px] text-faint">{new Date(t.created_at).toLocaleTimeString()}</span>
                        <span className="text-ink">{t.kind.replace("_", " ")}</span>
                        <span className={t.status === "ok" ? "text-dim" : "text-warn"}>{t.status}</span>
                        <span className="text-dim">{ms(t.duration_ms)}</span>
                        {t.first_token_ms !== null && <span className="text-faint">first word {ms(t.first_token_ms)}</span>}
                        {t.first_audio_ms !== null && <span className="text-faint">first audio {ms(t.first_audio_ms)}</span>}
                        {tools.length > 0 && <span className="truncate text-faint">{tools.map((x) => x.tool).join(", ")}</span>}
                      </button>
                      {open && (
                        <div className="px-3 pb-3 pl-8">
                          <Waterfall spans={[...t.spans].sort((a, b) => a.start_ms - b.start_ms)} total={t.duration_ms ?? 0} />
                          <p className="mt-2 text-[11px] text-faint">
                            {t.model ?? "no model call"} · {t.prompt_tokens ?? 0} tokens in · {t.completion_tokens ?? 0} out
                            {t.stt_ms !== null ? ` · speech recognition ${ms(t.stt_ms)}` : ""}
                          </p>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
            </Section>

            <Section
              title="Offline evaluations"
              note={
                <>
                  Benchmarks against a fixed test set with the real models, in a separate database. Run them with{" "}
                  <code className="text-ink">python -m eval.run rag --answers</code>, <code className="text-ink">agent</code> or{" "}
                  <code className="text-ink">voice</code> from <code className="text-ink">backend/</code>.
                </>
              }
            >
              {Object.keys(m.evals).length === 0 && <p className="text-sm text-faint">No evaluation has been run yet.</p>}
              <div className="space-y-3">
                {Object.entries(m.evals).map(([suite, info]) => (
                  <EvalCard key={suite} suite={suite} info={info} />
                ))}
              </div>
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}
