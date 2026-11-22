"use client";

import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect, useRef } from "react";
import { useAuth } from "@/store/auth";
import { useChat, visualState } from "@/store/chat";
import { Composer } from "./Composer";
import { MessageView } from "./MessageView";
import { ApprovalCard } from "./ToolSteps";
import { STATE_LABEL, Visualizer } from "./Visualizer";

function greeting(name: string) {
  const h = new Date().getHours();
  const part = h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  return `${part}, ${name}.`;
}

export function AssistantView() {
  const name = useAuth((s) => s.user?.display_name ?? "");
  const { messages, loadingConversation, error, clearError, activeIsTemporary, activeId, temporaryMode, mic } =
    useChat();
  const assistantState = useChat(visualState);
  const approvals = useChat((s) => s.approvals);
  const project = useChat((s) => s.conversations.find((c) => c.id === s.activeId)?.project ?? null);
  const setView = useChat((s) => s.setView);
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  const empty = messages.length === 0 && !loadingConversation;
  const lastContent = messages.at(-1)?.content.length ?? 0;

  useEffect(() => {
    const el = scroller.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [messages.length, lastContent]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget;
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
        className="min-h-0 flex-1 overflow-y-auto"
      >
        <AnimatePresence mode="popLayout" initial={false}>
          {empty ? (
            <motion.section
              key="hero"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0, scale: 0.96 }}
              className="flex min-h-full flex-col items-center justify-center px-4 py-8 text-center"
            >
              <Visualizer state={assistantState} size={260} />
              <h2 className="mt-2 text-2xl font-light tracking-tight text-ink sm:text-3xl">{greeting(name)}</h2>
              <p className="mt-2 max-w-md text-sm text-dim">
                {activeId === null && temporaryMode
                  ? "Temporary conversation — it won't appear in history."
                  : mic === "on"
                    ? "I'm listening."
                    : "What are we working on?"}
              </p>
              <div className="hud-label mt-5">{STATE_LABEL[assistantState]}</div>
            </motion.section>
          ) : (
            <motion.section key="thread" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="relative">
              <div className="sticky top-0 z-10 flex flex-col items-center bg-gradient-to-b from-void via-void/85 to-transparent pb-4 pt-2">
                <Visualizer state={assistantState} size={92} />
                <div className="hud-label -mt-1">
                  {STATE_LABEL[assistantState]}
                  {activeIsTemporary && " · temporary"}
                </div>
                {project && (
                  <button
                    onClick={() => setView("projects")}
                    className="mt-1 rounded-full border border-cyan/30 bg-cyan/[0.06] px-2 py-0.5 text-[11px] text-cyan hover:bg-cyan/10"
                    title="LOKI is using this project's context"
                  >
                    Project · {project}
                  </button>
                )}
              </div>
              <div className="mx-auto w-full max-w-3xl space-y-6 px-4 pb-6 sm:px-6">
                {loadingConversation && <p className="text-center text-sm text-faint">Loading…</p>}
                {messages.map((m) => (
                  <MessageView key={m.id} m={m} />
                ))}
              </div>
            </motion.section>
          )}
        </AnimatePresence>
      </div>

      <AnimatePresence>
        {approvals.map((a) => (
          <ApprovalCard key={a.approval_id} req={a} />
        ))}
      </AnimatePresence>

      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            role="alert"
            className="mx-auto mb-2 flex w-full max-w-3xl items-start gap-2 px-3 sm:px-6"
          >
            <div className="flex flex-1 items-start gap-2 rounded-lg border border-bad/30 bg-bad/[0.07] px-3 py-2 text-sm text-ink">
              <span className="flex-1">{error}</span>
              <button onClick={clearError} className="text-dim hover:text-ink" aria-label="Dismiss error">
                <X size={15} />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <Composer />
    </div>
  );
}
