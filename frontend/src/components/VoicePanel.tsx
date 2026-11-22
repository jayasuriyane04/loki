"use client";

import { motion } from "framer-motion";
import { useEffect, useRef } from "react";
import { useChat } from "@/store/chat";

const ACCENT: Record<string, string> = { a: "American", b: "British", e: "Spanish", f: "French", h: "Hindi", i: "Italian", j: "Japanese", p: "Portuguese", z: "Chinese" };

function voiceLabel(id: string) {
  const [prefix, name] = id.split("_");
  const accent = ACCENT[prefix[0]] ?? prefix[0];
  const gender = prefix[1] === "f" ? "female" : prefix[1] === "m" ? "male" : "";
  return `${name[0].toUpperCase()}${name.slice(1)} — ${accent} ${gender}`.trim();
}

function StatusRow({ label, state, detail, error }: { label: string; state?: string; detail?: string | null; error?: string | null }) {
  const tone = state === "ready" ? "bg-ok" : state === "loading" ? "bg-warn" : state === "error" ? "bg-bad" : "bg-faint";
  return (
    <div className="flex items-start gap-2 text-sm">
      <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${tone}`} />
      <div className="min-w-0">
        <div className="text-ink">
          {label} <span className="text-dim">{detail}</span>
        </div>
        <div className="text-xs text-faint">{error ?? state ?? "unknown"}</div>
      </div>
    </div>
  );
}

export function VoicePanel({ onClose }: { onClose: () => void }) {
  const { voiceStatus, voiceSettings, setVoiceSettings, lastVoiceMetrics, refreshVoice } = useChat();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    refreshVoice();
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose, refreshVoice]);

  const stt = voiceStatus?.stt;
  const tts = voiceStatus?.tts;
  const voices = (tts?.voices ?? []).filter((v) => v[0] === "a" || v[0] === "b");
  const current = voiceSettings.voice ?? tts?.default_voice ?? "";

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass absolute right-0 top-11 z-50 w-[min(92vw,340px)] space-y-4 rounded-xl p-4 shadow-2xl"
      role="dialog"
      aria-label="Voice settings"
    >
      <div className="hud-label">Voice engine</div>
      <div className="space-y-2">
        <StatusRow label="Speech recognition" state={stt?.state} detail={stt?.model ? `whisper ${stt.model}` : null} error={stt?.error} />
        <StatusRow label="Speech synthesis" state={tts?.state} detail={tts?.provider} error={tts?.error} />
      </div>

      <label className="block space-y-1.5">
        <span className="hud-label">Voice</span>
        <select
          value={current}
          disabled={!voices.length}
          onChange={(e) => setVoiceSettings({ voice: e.target.value })}
          className="w-full rounded-lg border border-line bg-night px-2.5 py-2 text-sm text-ink outline-none focus:border-cyan/50"
        >
          {!voices.length && <option>{tts?.state === "loading" ? "Loading voices…" : "No voices available"}</option>}
          {voices.map((v) => (
            <option key={v} value={v}>
              {voiceLabel(v)}
            </option>
          ))}
        </select>
      </label>

      <label className="block space-y-1.5">
        <span className="hud-label flex justify-between">
          <span>Speaking speed</span>
          <span className="text-dim">{voiceSettings.speed.toFixed(2)}×</span>
        </span>
        <input
          type="range"
          min={0.7}
          max={1.5}
          step={0.05}
          value={voiceSettings.speed}
          onChange={(e) => setVoiceSettings({ speed: Number(e.target.value) })}
          className="w-full accent-cyan"
        />
      </label>

      <label className="flex cursor-pointer items-center justify-between gap-3 text-sm text-ink">
        Read typed replies aloud too
        <input
          type="checkbox"
          checked={voiceSettings.speakTextReplies}
          onChange={(e) => setVoiceSettings({ speakTextReplies: e.target.checked })}
          className="h-4 w-4 accent-cyan"
        />
      </label>

      {(lastVoiceMetrics.stt_ms != null || lastVoiceMetrics.first_audio_ms != null) && (
        <div className="border-t border-line pt-3 font-mono text-[11px] text-faint">
          last turn · transcription {lastVoiceMetrics.stt_ms ?? "–"} ms · first audio{" "}
          {lastVoiceMetrics.first_audio_ms != null ? `${(lastVoiceMetrics.first_audio_ms / 1000).toFixed(1)} s` : "–"}
        </div>
      )}
      <p className="text-xs leading-relaxed text-faint">
        Speech is detected in your browser; only what you say is sent to your LOKI server, and it is transcribed
        locally. Headphones avoid LOKI hearing itself.
      </p>
    </motion.div>
  );
}
