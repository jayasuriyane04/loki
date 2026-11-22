"use client";

import { Cpu, LogOut, Menu, Mic, MicOff, Settings } from "lucide-react";
import { useCallback, useState } from "react";
import { useAuth } from "@/store/auth";
import { useChat, visualState } from "@/store/chat";
import { STATE_LABEL } from "./Visualizer";
import { NotificationBell } from "./Notifications";
import { VoicePanel } from "./VoicePanel";

function Dot({ tone }: { tone: "ok" | "warn" | "bad" | "off" }) {
  const cls = { ok: "bg-ok", warn: "bg-warn", bad: "bg-bad", off: "bg-faint" }[tone];
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${cls}`} />;
}

export function TopBar({ onMenu }: { onMenu: () => void }) {
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);
  const { socketStatus, models, modelsError, lastModel, mic, voiceStatus, view, setView } = useChat();
  const shown = useChat(visualState);
  const [panel, setPanel] = useState(false);
  const closePanel = useCallback(() => setPanel(false), []);
  const vs = voiceStatus;
  const voiceTone =
    !vs ? "off" : vs.stt.state === "ready" && vs.tts.state === "ready" ? "ok" : vs.stt.state === "error" || vs.tts.state === "error" ? "bad" : "warn";

  const link = socketStatus === "open" ? "ok" : socketStatus === "connecting" ? "warn" : "bad";
  const primary = models?.primary;
  const modelTone = modelsError ? "bad" : !primary ? "off" : primary.ok ? "ok" : models?.fallback?.ok ? "warn" : "bad";
  const modelText = lastModel ?? (primary ? `${primary.provider} · ${primary.model}` : "checking…");
  const modelTitle = modelsError ?? (primary && !primary.ok ? primary.error ?? "Unavailable" : undefined);

  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line px-3 sm:px-5">
      <button onClick={onMenu} className="rounded-md p-1.5 text-dim hover:text-ink lg:hidden" aria-label="Open panel">
        <Menu size={18} />
      </button>
      <div className="font-mono text-sm tracking-[0.42em] text-ink">LOKI</div>

      <div className="ml-2 hidden items-center gap-2 sm:flex">
        <Dot tone={link} />
        <span className="hud-label">{socketStatus === "open" ? STATE_LABEL[shown] : socketStatus === "connecting" ? "Connecting" : "Offline"}</span>
      </div>

      <div className="ml-auto flex items-center gap-1 sm:gap-3">
        <div
          className="hidden items-center gap-2 rounded-full border border-line px-3 py-1 md:flex"
          title={modelTitle}
        >
          <Cpu size={13} className="text-faint" />
          <span className="font-mono text-[11.5px] text-dim">{modelText}</span>
          <Dot tone={modelTone} />
        </div>
        <div className="relative">
          <button
            onClick={() => setPanel((p) => !p)}
            className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 transition ${
              mic === "on" ? "border-bad/50 bg-bad/10" : "border-line hover:border-line-strong"
            }`}
            title={mic === "on" ? "Microphone is live" : "Voice settings"}
            aria-label="Voice settings"
            aria-expanded={panel}
          >
            {mic === "on" ? (
              <>
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-bad opacity-60 motion-reduce:hidden" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-bad" />
                </span>
                <span className="hud-label !text-[10px] !text-bad">Mic live</span>
              </>
            ) : (
              <>
                {mic === "off" || mic === "starting" ? <Mic size={13} className="text-faint" /> : <MicOff size={13} className="text-bad" />}
                <span className="hud-label !text-[10px]">Voice</span>
                <Dot tone={voiceTone} />
              </>
            )}
          </button>
          {panel && <VoicePanel onClose={closePanel} />}
        </div>
        <NotificationBell />
        <button
          onClick={() => setView(view === "settings" ? "assistant" : "settings")}
          className={`rounded-md p-1.5 hover:text-ink ${view === "settings" ? "text-cyan" : "text-dim"}`}
          title="Settings"
          aria-label="Settings"
          aria-current={view === "settings" ? "page" : undefined}
        >
          <Settings size={17} />
        </button>
        <div className="hidden h-7 w-7 items-center justify-center rounded-full border border-line-strong bg-deep text-xs font-medium text-ink sm:flex" title={user?.email}>
          {user?.display_name.slice(0, 1).toUpperCase()}
        </div>
        <button onClick={logout} className="rounded-md p-1.5 text-dim hover:text-ink" title="Sign out" aria-label="Sign out">
          <LogOut size={17} />
        </button>
      </div>
    </header>
  );
}
