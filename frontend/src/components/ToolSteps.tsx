"use client";

import { motion } from "framer-motion";
import {
  Ban,
  Check,
  ChevronRight,
  CircleAlert,
  Clock,
  Loader2,
  ShieldAlert,
  ShieldCheck,
  Wrench,
} from "lucide-react";
import { useState } from "react";
import type { ApprovalRequest, ToolStep } from "@/lib/types";
import { useChat } from "@/store/chat";

const LABEL: Record<string, string> = {
  web_search: "Web search", read_webpage: "Read page", get_weather: "Weather", get_datetime: "Time",
  create_task: "New task", list_tasks: "Tasks", complete_task: "Complete task", delete_task: "Delete task",
  create_reminder: "Reminder", list_reminders: "Reminders", cancel_reminder: "Cancel reminder",
  create_note: "Save note", search_notes: "Search notes", read_note: "Read note", delete_note: "Delete note",
  create_event: "New event", list_events: "Calendar", delete_event: "Delete event", notify_user: "Notify",
  search_documents: "Documents", search_code: "Code search", read_project_file: "Read file",
  search_memory: "Memory", read_app_logs: "LOKI logs", system_info: "System", run_command: "Command",
  open_url: "Open website", open_app: "Open app", run_workflow: "Workflow",
};

function StatusIcon({ s }: { s: ToolStep }) {
  if (s.status === "running") return <Loader2 size={13} className="animate-spin text-cyan" />;
  if (s.status === "ok") return <Check size={13} className="text-ok" />;
  if (s.status === "denied") return <Ban size={13} className="text-warn" />;
  if (s.status === "timeout") return <Clock size={13} className="text-bad" />;
  return <CircleAlert size={13} className="text-bad" />;
}

export function ToolSteps({ steps }: { steps: ToolStep[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!steps.length) return null;
  return (
    <ul className="mb-2 space-y-1">
      {steps.map((s) => (
        <li key={s.id}>
          <button
            onClick={() => setOpen(open === s.id ? null : s.id)}
            aria-expanded={open === s.id}
            className="flex w-full items-center gap-2 rounded-lg border border-line bg-deep/40 px-2.5 py-1.5 text-left text-[12.5px] hover:border-line-strong"
          >
            <StatusIcon s={s} />
            <span className="font-mono text-[11px] text-faint">{LABEL[s.tool] ?? s.tool}</span>
            <span className="min-w-0 flex-1 truncate text-dim">
              {s.status === "running" ? "working…" : s.summary}
            </span>
            {s.approved === true && <ShieldCheck size={12} className="text-ok" aria-label="Approved by you" />}
            {s.approved === false && <ShieldAlert size={12} className="text-warn" aria-label="Declined by you" />}
            {s.status !== "running" && <span className="font-mono text-[10px] text-faint">{s.duration_ms} ms</span>}
            <ChevronRight size={12} className={`text-faint transition ${open === s.id ? "rotate-90" : ""}`} />
          </button>
          {open === s.id && (
            <pre className="ml-6 mt-1 overflow-x-auto rounded-lg bg-night/70 p-2 font-mono text-[11px] text-faint">
              {s.tool}({JSON.stringify(s.args, null, 2)})
            </pre>
          )}
        </li>
      ))}
    </ul>
  );
}

export function ApprovalCard({ req }: { req: ApprovalRequest }) {
  const respond = useChat((s) => s.respondApproval);
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      role="alertdialog"
      aria-label="LOKI needs your approval"
      className="mx-auto mb-2 w-full max-w-3xl px-3 sm:px-6"
    >
      <div className="rounded-2xl border border-warn/40 bg-warn/[0.06] p-4 shadow-[0_10px_40px_-12px_rgba(0,0,0,0.6)]">
        <div className="flex items-start gap-3">
          <ShieldAlert size={18} className="mt-0.5 shrink-0 text-warn" />
          <div className="min-w-0 flex-1">
            <div className="hud-label !text-warn">Approval needed</div>
            <p className="mt-1 text-[15px] text-ink">{req.call}</p>
            <p className="mt-1 text-xs text-dim">
              {req.description}
              {req.always_confirm && " LOKI always asks before this kind of action."}
            </p>
          </div>
        </div>
        <div className="mt-3 flex justify-end gap-2">
          <button
            onClick={() => respond(req.approval_id, false)}
            className="rounded-lg border border-line-strong px-4 py-1.5 text-sm text-ink hover:border-bad/50"
          >
            Don&apos;t do it
          </button>
          <button
            onClick={() => respond(req.approval_id, true)}
            autoFocus
            className="rounded-lg bg-warn/90 px-4 py-1.5 text-sm font-medium text-void hover:bg-warn"
          >
            Approve
          </button>
        </div>
      </div>
    </motion.div>
  );
}

export function ToolBadge() {
  return <Wrench size={12} />;
}
