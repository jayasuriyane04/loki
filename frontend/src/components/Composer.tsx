"use client";

import { ArrowUp, Ghost, Loader2, Mic, MicOff, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useChat } from "@/store/chat";

export function Composer() {
  const {
    send,
    cancel,
    busy,
    playing,
    socketStatus,
    activeId,
    activeIsTemporary,
    temporaryMode,
    setTemporaryMode,
    mic,
    toggleMic,
    voiceStatus,
  } = useChat();
  const sttReady = voiceStatus?.stt.state === "ready";
  const working = busy || playing;
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 220) + "px";
  }, [text]);

  useEffect(() => {
    ref.current?.focus();
  }, [activeId]);

  const offline = socketStatus !== "open";
  const temporary = activeId ? activeIsTemporary : temporaryMode;

  function submit() {
    if (!text.trim() || busy || offline) return;
    send(text);
    setText("");
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-3 pb-[max(12px,env(safe-area-inset-bottom))] sm:px-6">
      <div className="glass rounded-2xl p-2 shadow-[0_10px_40px_-12px_rgba(0,0,0,0.6)] focus-within:border-line-strong">
        <textarea
          ref={ref}
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
            if (e.key === "Escape" && working) cancel();
          }}
          maxLength={8000}
          placeholder={offline ? "Reconnecting to LOKI…" : mic === "on" ? "Listening — just talk, or type here" : "Message LOKI"}
          className="block max-h-[220px] w-full resize-none bg-transparent px-3 py-2 text-[15px] text-ink placeholder:text-faint outline-none"
        />
        <div className="flex items-center gap-2 px-1 pt-1">
          <button
            type="button"
            disabled={!!activeId}
            onClick={() => setTemporaryMode(!temporaryMode)}
            className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition ${
              temporary ? "border-cyan/40 bg-cyan/10 text-cyan" : "border-line text-faint hover:text-dim"
            } disabled:cursor-default`}
            title={
              activeId
                ? temporary
                  ? "This is a temporary conversation"
                  : "Start a new conversation to change this"
                : "Temporary conversations are hidden from history and will never be used for memory"
            }
          >
            <Ghost size={13} />
            Temporary
          </button>
          <span className="hidden text-[11px] text-faint sm:inline">
            {mic === "on" ? "Speak to interrupt LOKI at any time" : "Enter to send · Shift+Enter for a new line"}
          </span>
          <button
            type="button"
            onClick={toggleMic}
            disabled={offline || (!sttReady && mic !== "on") || mic === "starting"}
            className={`ml-auto flex h-9 w-9 items-center justify-center rounded-full border transition disabled:opacity-40 ${
              mic === "on"
                ? "border-bad/60 bg-bad/15 text-bad hover:bg-bad/25"
                : "border-line-strong text-dim hover:border-cyan/40 hover:text-cyan"
            }`}
            aria-label={mic === "on" ? "Turn microphone off" : "Talk to LOKI"}
            aria-pressed={mic === "on"}
            title={
              mic === "on"
                ? "Microphone is live — click to turn off"
                : !sttReady
                  ? voiceStatus?.stt.state === "loading"
                    ? "Speech recognition is starting up…"
                    : voiceStatus?.stt.error ?? "Speech recognition unavailable"
                  : "Talk to LOKI (hands-free)"
            }
          >
            {mic === "starting" ? <Loader2 size={16} className="animate-spin" /> : mic === "on" ? <MicOff size={16} /> : <Mic size={16} />}
          </button>
          {working ? (
            <button
              onClick={cancel}
              className="flex h-9 w-9 items-center justify-center rounded-full border border-line-strong text-ink transition hover:border-bad/50 hover:text-bad"
              aria-label="Stop responding"
              title="Stop (Esc)"
            >
              <Square size={13} fill="currentColor" />
            </button>
          ) : (
            <button
              onClick={submit}
              disabled={!text.trim() || offline}
              className="flex h-9 w-9 items-center justify-center rounded-full bg-cyan/90 text-void transition hover:bg-cyan disabled:bg-white/5 disabled:text-faint"
              aria-label="Send"
            >
              <ArrowUp size={17} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
