"use client";

import { ArrowLeft, Lock, Wrench } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ToolExecution, ToolInfo } from "@/lib/types";
import { useChat } from "@/store/chat";

const CATEGORY: Record<string, string> = {
  information: "Information",
  productivity: "Productivity",
  knowledge: "Your knowledge",
  development: "Development",
  system: "System",
};
const PERMISSION: Record<string, string> = {
  read: "Reads only",
  reversible: "Makes changes you can undo",
  confirm: "Always asks first",
};
const STATUS_TONE: Record<string, string> = {
  ok: "text-ok",
  denied: "text-warn",
  error: "text-bad",
  timeout: "text-bad",
  invalid: "text-bad",
  disabled: "text-faint",
};

export function ToolsPage() {
  const setView = useChat((s) => s.setView);
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [log, setLog] = useState<ToolExecution[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      Promise.all([api.tools(), api.toolExecutions(40)])
        .then(([t, l]) => {
          setTools(t);
          setLog(l);
        })
        .catch((e: Error) => setError(e.message)),
    [],
  );
  useEffect(() => void load(), [load]);

  async function change(t: ToolInfo, setting: ToolInfo["setting"]) {
    setError(null);
    try {
      const updated = await api.setToolSetting(t.name, setting);
      setTools((all) => all.map((x) => (x.name === t.name ? updated : x)));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const groups = new Map<string, ToolInfo[]>();
  for (const t of tools) groups.set(t.category, [...(groups.get(t.category) ?? []), t]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
        <button onClick={() => setView("assistant")} className="mb-4 flex items-center gap-1.5 text-sm text-dim hover:text-ink">
          <ArrowLeft size={15} /> Back to LOKI
        </button>
        <h1 className="flex items-center gap-2 text-2xl font-light text-ink">
          <Wrench size={20} className="text-cyan" /> Tools
        </h1>
        <p className="mt-1 max-w-xl text-sm text-dim">
          What LOKI can do for you, and how much it may do on its own. Deleting things, running commands and opening
          websites always need your approval. Commands, apps and workflows come from <code>backend/config/automation.json</code>.
        </p>
        {error && <p className="mt-3 rounded-lg border border-bad/30 bg-bad/[0.07] px-3 py-2 text-sm">{error}</p>}

        <div className="mt-6 space-y-6">
          {[...groups.entries()].map(([cat, list]) => (
            <section key={cat}>
              <h2 className="hud-label mb-2">{CATEGORY[cat] ?? cat}</h2>
              <ul className="divide-y divide-line rounded-xl border border-line bg-deep/40">
                {list.map((t) => {
                  const locked = t.always_confirm || t.permission === "confirm";
                  return (
                    <li key={t.name} className="flex flex-wrap items-center gap-3 px-3 py-2.5">
                      <div className="min-w-0 flex-1">
                        <div className="font-mono text-[12.5px] text-ink">{t.name}</div>
                        <div className="text-xs text-dim">{t.description}</div>
                        <div className="mt-0.5 text-[11px] text-faint">{PERMISSION[t.permission]}</div>
                      </div>
                      <label className="flex items-center gap-1.5 text-xs text-dim">
                        {locked && <Lock size={11} className="text-warn" aria-label="Approval required" />}
                        <select
                          value={t.setting}
                          onChange={(e) => change(t, e.target.value as ToolInfo["setting"])}
                          aria-label={`${t.name} setting`}
                          className="rounded-md border border-line bg-night px-2 py-1 text-xs text-ink outline-none"
                        >
                          {!locked && <option value="auto">Automatic</option>}
                          <option value="confirm">Ask me first</option>
                          <option value="off">Off</option>
                        </select>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>

        <section className="mt-10">
          <h2 className="hud-label mb-2">Recent activity</h2>
          {log.length === 0 && <p className="text-sm text-faint">LOKI hasn&apos;t used any tools yet.</p>}
          <ul className="space-y-1">
            {log.map((x) => (
              <li key={x.id} className="flex flex-wrap items-baseline gap-x-3 text-[12.5px]">
                <span className="font-mono text-[11px] text-faint">{new Date(x.created_at).toLocaleString()}</span>
                <span className={`font-mono text-[11px] ${STATUS_TONE[x.status] ?? "text-dim"}`}>{x.status}</span>
                {x.approved !== null && (
                  <span className="text-[11px] text-faint">{x.approved ? "approved" : "declined"} by you</span>
                )}
                <span className="min-w-0 flex-1 truncate text-dim">{x.summary ?? x.tool}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
