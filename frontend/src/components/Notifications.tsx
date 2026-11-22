"use client";

import { AnimatePresence, motion } from "framer-motion";
import { Bell, BellRing, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useChat } from "@/store/chat";

function ago(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

export function NotificationBell() {
  const { notifications, markAllRead } = useChat();
  const [open, setOpen] = useState(false);
  const [perm, setPerm] = useState<string>(() =>
    typeof Notification !== "undefined" ? Notification.permission : "unsupported",
  );
  const ref = useRef<HTMLDivElement>(null);
  const unread = notifications.filter((n) => !n.read_at).length;

  useEffect(() => {
    const onDown = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => {
          setOpen(!open);
          if (!open && unread) markAllRead();
        }}
        className="relative rounded-md p-1.5 text-dim hover:text-ink"
        aria-label={unread ? `${unread} unread notifications` : "Notifications"}
        aria-expanded={open}
      >
        {unread ? <BellRing size={17} className="text-cyan" /> : <Bell size={17} />}
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-cyan px-1 text-[10px] font-semibold text-void">
            {unread}
          </span>
        )}
      </button>
      {open && (
        <div className="glass absolute right-0 top-10 z-50 w-[min(92vw,340px)] rounded-xl p-2 shadow-2xl" role="dialog" aria-label="Notifications">
          <div className="hud-label px-2 py-1">Notifications</div>
          {notifications.length === 0 && <p className="px-2 py-3 text-sm text-faint">Nothing yet.</p>}
          <ul className="max-h-80 overflow-y-auto">
            {notifications.slice(0, 30).map((n) => (
              <li key={n.id} className="rounded-lg px-2 py-2 hover:bg-white/[0.03]">
                <div className="text-sm text-ink">{n.title}</div>
                {n.body && <div className="mt-0.5 text-xs text-dim">{n.body}</div>}
                <div className="mt-0.5 font-mono text-[10.5px] text-faint">{ago(n.created_at)}</div>
              </li>
            ))}
          </ul>
          {perm === "default" && (
            <button
              onClick={async () => setPerm(await Notification.requestPermission())}
              className="mt-1 w-full rounded-lg border border-line px-2 py-1.5 text-xs text-dim hover:text-ink"
            >
              Also show desktop notifications when LOKI is in the background
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export function Toasts() {
  const { toasts, dismissToast } = useChat();
  return (
    <div className="pointer-events-none fixed bottom-24 right-4 z-50 flex w-[min(92vw,360px)] flex-col gap-2" aria-live="polite">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, x: 30 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 30 }}
            className="glass pointer-events-auto flex items-start gap-3 rounded-xl border-cyan/30 p-3 shadow-2xl"
          >
            <BellRing size={16} className="mt-0.5 shrink-0 text-cyan" />
            <div className="min-w-0 flex-1">
              <div className="text-sm text-ink">{t.title}</div>
              {t.body && <div className="mt-0.5 text-xs text-dim">{t.body}</div>}
            </div>
            <button onClick={() => dismissToast(t.id)} className="text-faint hover:text-ink" aria-label="Dismiss">
              <X size={14} />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
