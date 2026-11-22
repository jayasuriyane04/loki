import { create } from "zustand";
import { api } from "@/lib/api";
import { floatToPcm16, SpeechPlayer } from "@/lib/audio";
import { energy } from "@/lib/energy";
import { describeMicError, MicInput } from "@/lib/mic";
import { LokiSocket, type SocketStatus } from "@/lib/socket";
import { useMemory } from "@/store/memory";
import type {
  AppNotification,
  ApprovalRequest,
  AssistantState,
  ConversationSummary,
  MemoryRef,
  ModelsStatus,
  ServerEvent,
  UiMessage,
  VoiceSettings,
  VoiceStatus,
} from "@/lib/types";

type MicState = "off" | "starting" | "on" | "error";

type ChatState = {
  socketStatus: SocketStatus;
  assistantState: AssistantState;
  busy: boolean;
  conversations: ConversationSummary[];
  activeId: string | null;
  activeIsTemporary: boolean;
  messages: UiMessage[];
  loadingConversation: boolean;
  temporaryMode: boolean;
  error: string | null;
  models: ModelsStatus | null;
  modelsError: string | null;
  lastModel: string | null;

  // voice
  mic: MicState;
  hearing: boolean;
  playing: boolean;
  voiceStatus: VoiceStatus | null;
  voiceSettings: VoiceSettings;
  lastVoiceMetrics: { stt_ms: number | null; first_audio_ms: number | null };
  view: View;
  approvals: ApprovalRequest[];
  notifications: AppNotification[];
  toasts: AppNotification[];

  setView: (v: View) => void;
  respondApproval: (id: string, approved: boolean) => void;
  loadNotifications: () => Promise<void>;
  markAllRead: () => Promise<void>;
  dismissToast: (id: string) => void;
  connect: (onUnauthorized: () => void) => void;
  disconnect: () => void;
  refreshConversations: () => Promise<void>;
  refreshModels: () => Promise<void>;
  refreshVoice: () => Promise<void>;
  openConversation: (id: string) => Promise<void>;
  newConversation: () => void;
  send: (content: string) => void;
  cancel: () => void;
  rename: (id: string, title: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
  setTemporaryMode: (on: boolean) => void;
  toggleMic: () => Promise<void>;
  setVoiceSettings: (patch: Partial<VoiceSettings>) => void;
  clearError: () => void;
  reset: () => void;
};

const VOICE_KEY = "loki.voice";
export type View = "assistant" | "memories" | "knowledge" | "planner" | "tools" | "projects" | "settings";

const DEFAULT_VOICE: VoiceSettings = { voice: null, speed: 1, speakTextReplies: false };

function loadVoiceSettings(): VoiceSettings {
  try {
    const raw = localStorage.getItem(VOICE_KEY);
    return raw ? { ...DEFAULT_VOICE, ...JSON.parse(raw) } : DEFAULT_VOICE;
  } catch {
    return DEFAULT_VOICE;
  }
}

function storeVoice(v: VoiceSettings) {
  try {
    localStorage.setItem(VOICE_KEY, JSON.stringify(v));
  } catch {
    /* storage unavailable: settings last for this session only */
  }
}

let voiceSaveTimer: ReturnType<typeof setTimeout> | null = null;
let socket: LokiSocket | null = null;
let errorTimer: ReturnType<typeof setTimeout> | null = null;
let player: SpeechPlayer | null = null;
let mic: MicInput | null = null;
let pendingTts: { sample_rate: number } | null = null;
let dropAudio = false; // set on barge-in / stop until the next reply starts
let pendingRecall: MemoryRef[] | null = null; // memories announced for the reply that is about to start

const initial = {
  socketStatus: "closed" as SocketStatus,
  assistantState: "idle" as AssistantState,
  busy: false,
  conversations: [],
  activeId: null,
  activeIsTemporary: false,
  messages: [],
  loadingConversation: false,
  temporaryMode: false,
  error: null,
  models: null,
  modelsError: null,
  lastModel: null,
  mic: "off" as MicState,
  hearing: false,
  playing: false,
  voiceStatus: null,
  lastVoiceMetrics: { stt_ms: null, first_audio_ms: null },
  approvals: [] as ApprovalRequest[],
  notifications: [] as AppNotification[],
  toasts: [] as AppNotification[],
  view: "assistant" as View,
};

/** Desktop notification (only if the user granted permission; LOKI never asks on its own). */
function showDesktopNotification(n: AppNotification) {
  try {
    if (typeof Notification !== "undefined" && Notification.permission === "granted" && document.hidden) {
      new Notification(n.title, { body: n.body ?? undefined, tag: n.id });
    }
  } catch {
    /* unsupported */
  }
}

/** What the visualiser and status labels show, derived from all the moving parts. */
export function visualState(s: ChatState): AssistantState {
  if (s.assistantState === "error") return "error";
  if (s.playing) return "speaking";
  if (s.busy) return s.assistantState;
  if (s.hearing) return "hearing";
  if (s.mic === "on") return "listening";
  return "idle";
}

export const useChat = create<ChatState>((set, get) => {
  const showError = (message: string, visual = true) => {
    set({ error: message, ...(visual ? { assistantState: "error" as AssistantState } : {}) });
    if (errorTimer) clearTimeout(errorTimer);
    errorTimer = setTimeout(() => {
      if (get().assistantState === "error") set({ assistantState: "idle" });
      if (!visual && get().error === message) set({ error: null });
    }, 4000);
  };

  const sendVoiceConfig = () => {
    const v = get().voiceSettings;
    socket?.send({
      type: "voice_config",
      speak_replies: true,
      speak_text_replies: v.speakTextReplies,
      voice: v.voice,
      speed: v.speed,
    });
  };

  const stopSpeech = () => {
    dropAudio = true;
    pendingTts = null;
    player?.stop();
  };

  const handle = (ev: ServerEvent) => {
    switch (ev.type) {
      case "conversation": {
        const c = ev.conversation;
        set((s) => ({
          activeId: c.id,
          activeIsTemporary: c.is_temporary,
          conversations: c.is_temporary ? s.conversations : [c, ...s.conversations.filter((x) => x.id !== c.id)],
        }));
        break;
      }
      case "project":
        set((s) => ({
          conversations: s.conversations.map((c) => (c.id === ev.conversation_id ? { ...c, project: ev.project } : c)),
        }));
        break;
      case "message_saved": {
        if (ev.conversation_id !== get().activeId) break;
        set((s) => {
          const idx = s.messages.findIndex((m) => m.pending);
          const msgs = [...s.messages];
          if (idx >= 0) msgs[idx] = ev.message;
          else msgs.push(ev.message);
          return { messages: msgs };
        });
        break;
      }
      case "state":
        if (ev.state === "idle") {
          set((s) => ({
            busy: false,
            assistantState: s.assistantState === "error" ? "error" : "idle",
            messages: s.messages.map((m) => (m.pending ? { ...m, pending: false, failed: true } : m)),
          }));
          get().refreshConversations();
        } else {
          set({ busy: true, assistantState: ev.state });
        }
        break;
      case "tool_call":
        set((s) => {
          const idx = s.messages.findLastIndex((m) => m.role === "assistant" && m.streaming);
          if (idx < 0) return {};
          const msgs = [...s.messages];
          const step = { id: ev.id, tool: ev.tool, args: ev.args, status: "running" as const, summary: "", approved: null, duration_ms: 0 };
          msgs[idx] = { ...msgs[idx], tool_steps: [...(msgs[idx].tool_steps ?? []), step] };
          return { messages: msgs };
        });
        break;
      case "tool_result": {
        const { type: _t, ...step } = ev;
        void _t;
        set((s) => {
          const idx = s.messages.findLastIndex((m) => m.role === "assistant" && m.streaming);
          if (idx < 0) return {};
          const msgs = [...s.messages];
          const steps = msgs[idx].tool_steps ?? [];
          msgs[idx] = {
            ...msgs[idx],
            tool_steps: steps.some((x) => x.id === step.id) ? steps.map((x) => (x.id === step.id ? step : x)) : [...steps, step],
          };
          return { messages: msgs };
        });
        break;
      }
      case "approval_required": {
        const { type: _t, ...req } = ev;
        void _t;
        set((s) => ({ approvals: [...s.approvals.filter((a) => a.approval_id !== req.approval_id), req] }));
        break;
      }
      case "approval_resolved":
        set((s) => ({ approvals: s.approvals.filter((a) => a.approval_id !== ev.approval_id) }));
        break;
      case "notification": {
        const n = ev.notification;
        set((s) => ({ notifications: [n, ...s.notifications], toasts: [...s.toasts, n] }));
        showDesktopNotification(n);
        setTimeout(() => get().dismissToast(n.id), 12_000);
        break;
      }
      case "memories_used":
        if (ev.conversation_id === get().activeId) pendingRecall = ev.memories;
        break;
      case "memory_updated":
        if (ev.conversation_id === get().activeId) {
          set((s) => {
            const idx = s.messages.findLastIndex((m) => m.role === "assistant");
            if (idx < 0) return {};
            const msgs = [...s.messages];
            msgs[idx] = { ...msgs[idx], saved: [...(msgs[idx].saved ?? []), ...ev.operations] };
            return { messages: msgs };
          });
        }
        if (get().view === "memories") useMemory.getState().load();
        break;
      case "stt_command":
        stopSpeech();
        break;
      case "stt_final":
        set((s) => ({ lastVoiceMetrics: { ...s.lastVoiceMetrics, stt_ms: ev.latency_ms } }));
        break;
      case "assistant_start": {
        dropAudio = false;
        const recalled = pendingRecall ?? undefined;
        pendingRecall = null;
        if (ev.conversation_id !== get().activeId) break;
        set((s) => ({
          lastModel: `${ev.provider} · ${ev.model}`,
          messages: [
            ...s.messages,
            {
              id: ev.message_id,
              role: "assistant",
              content: "",
              status: "complete",
              input_mode: "text",
              provider: ev.provider,
              model: ev.model,
              prompt_tokens: null,
              completion_tokens: null,
              latency_ms: null,
              first_token_ms: null,
              created_at: new Date().toISOString(),
              streaming: true,
              recalled,
            },
          ],
        }));
        break;
      }
      case "token":
        if (!player?.playing) energy.bump();
        set((s) => ({
          assistantState: "responding",
          messages: s.messages.map((m) => (m.id === ev.message_id ? { ...m, content: m.content + ev.delta } : m)),
        }));
        break;
      case "assistant_end":
        set((s) => ({
          // merge, so client-only details (recalled memories) survive the final server copy
          messages: s.messages.map((m) => (m.id === ev.message.id ? { ...m, ...ev.message, streaming: false } : m)),
        }));
        break;
      case "tts_chunk":
        pendingTts = dropAudio ? null : { sample_rate: ev.sample_rate };
        break;
      case "tts_end":
        set((s) => ({ lastVoiceMetrics: { ...s.lastVoiceMetrics, first_audio_ms: ev.first_audio_ms } }));
        break;
      case "error":
        if (ev.code === "busy") showError(ev.message, false);
        else if (ev.code === "no_speech") showError(ev.message, false);
        else showError(ev.message);
        break;
    }
  };

  const onBinary = (data: ArrayBuffer) => {
    if (pendingTts && !dropAudio) player?.enqueue(data, pendingTts.sample_rate);
    pendingTts = null;
  };

  const sendUtterance = (audio: Float32Array) => {
    const s = get();
    const ok = socket?.sendWithBinary(
      {
        type: "audio_utterance",
        conversation_id: s.activeId,
        temporary: s.activeId ? s.activeIsTemporary : s.temporaryMode,
        sample_rate: 16000,
      },
      floatToPcm16(audio),
    );
    if (!ok) showError("Not connected to LOKI. Reconnecting…");
    else set({ busy: true, assistantState: "transcribing", error: null });
  };

  /** The user started talking: if LOKI is speaking or still working, stop it (barge-in). */
  const bargeIn = () => {
    const s = get();
    if (s.playing || s.busy) {
      stopSpeech();
      if (s.busy) socket?.send({ type: "cancel" });
    }
  };

  return {
    ...initial,
    voiceSettings: DEFAULT_VOICE,

    setView: (view) => set({ view }),

    respondApproval: (id, approved) => {
      socket?.send({ type: "approval", approval_id: id, approved });
      set((s) => ({ approvals: s.approvals.filter((a) => a.approval_id !== id) }));
    },

    loadNotifications: async () => {
      try {
        set({ notifications: await api.notifications() });
      } catch {
        /* non-fatal */
      }
    },

    markAllRead: async () => {
      await api.markNotificationsRead().catch(() => undefined);
      const now = new Date().toISOString();
      set((s) => ({ notifications: s.notifications.map((n) => ({ ...n, read_at: n.read_at ?? now })) }));
    },

    dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

    connect: (onUnauthorized) => {
      if (socket) return;
      set({ voiceSettings: loadVoiceSettings() });
      // The account's saved voice settings win over this browser's copy.
      api
        .preferences()
        .then((p) => {
          const v = { voice: p.voice.voice, speed: p.voice.speed, speakTextReplies: p.voice.speak_text_replies };
          set({ voiceSettings: v });
          storeVoice(v);
          sendVoiceConfig();
        })
        .catch(() => undefined);
      player = new SpeechPlayer((playing) => set({ playing }));
      socket = new LokiSocket({
        onEvent: handle,
        onBinary,
        onStatus: (socketStatus) => {
          set((s) => ({
            socketStatus,
            // A dropped socket ends any in-flight turn on the client side.
            ...(socketStatus === "closed" && s.busy ? { busy: false, assistantState: "idle" } : {}),
          }));
          if (socketStatus === "open") {
            sendVoiceConfig();
            socket?.send({ type: "client_info", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
          }
        },
        onUnauthorized,
      });
      socket.connect();
    },

    disconnect: () => {
      socket?.close();
      socket = null;
    },

    refreshConversations: async () => {
      try {
        set({ conversations: await api.listConversations() });
      } catch {
        /* surfaced elsewhere via socket status */
      }
    },

    refreshModels: async () => {
      try {
        set({ models: await api.models(), modelsError: null });
      } catch (e) {
        set({ modelsError: (e as Error).message });
      }
    },

    refreshVoice: async () => {
      try {
        set({ voiceStatus: await api.voice() });
      } catch {
        /* non-fatal; the panel shows unknown */
      }
    },

    openConversation: async (id) => {
      if (get().busy) get().cancel();
      stopSpeech();
      set({ activeId: id, loadingConversation: true, messages: [], error: null, view: "assistant" });
      try {
        const conv = await api.getConversation(id);
        if (get().activeId === id) {
          set({ messages: conv.messages, activeIsTemporary: conv.is_temporary, loadingConversation: false });
        }
      } catch (e) {
        set({ error: (e as Error).message, loadingConversation: false, activeId: null });
      }
    },

    newConversation: () => {
      if (get().busy) get().cancel();
      stopSpeech();
      set({
        activeId: null,
        activeIsTemporary: false,
        messages: [],
        error: null,
        assistantState: "idle",
        view: "assistant",
      });
    },

    send: (content) => {
      const text = content.trim();
      const s = get();
      if (!text || s.busy) return;
      stopSpeech();
      const ok = socket?.send({
        type: "user_message",
        conversation_id: s.activeId,
        content: text,
        temporary: s.activeId ? s.activeIsTemporary : s.temporaryMode,
        input_mode: "text",
      });
      if (!ok) {
        set({ error: "Not connected to LOKI. Reconnecting…" });
        return;
      }
      if (s.voiceSettings.speakTextReplies) player?.unlock();
      set({
        busy: true,
        error: null,
        assistantState: "processing",
        messages: [
          ...s.messages,
          {
            id: `pending-${Date.now()}`,
            role: "user",
            content: text,
            status: "complete",
            input_mode: "text",
            provider: null,
            model: null,
            prompt_tokens: null,
            completion_tokens: null,
            latency_ms: null,
            first_token_ms: null,
            created_at: new Date().toISOString(),
            pending: true,
          },
        ],
      });
    },

    cancel: () => {
      stopSpeech();
      if (get().busy) socket?.send({ type: "cancel" });
    },

    rename: async (id, title) => {
      const updated = await api.renameConversation(id, title);
      set((s) => ({ conversations: s.conversations.map((c) => (c.id === id ? updated : c)) }));
    },

    remove: async (id) => {
      await api.deleteConversation(id);
      set((s) => ({ conversations: s.conversations.filter((c) => c.id !== id) }));
      if (get().activeId === id) get().newConversation();
    },

    setTemporaryMode: (on) => set({ temporaryMode: on }),

    toggleMic: async () => {
      const state = get().mic;
      if (state === "on" || state === "starting") {
        await mic?.pause();
        set({ mic: "off", hearing: false });
        return;
      }
      set({ mic: "starting", error: null });
      try {
        await player?.unlock(); // inside the click gesture, so replies can play
        mic ??= new MicInput({
          onSpeechStart: bargeIn,
          onUtterance: sendUtterance,
          onHearing: (hearing) => set({ hearing }),
        });
        await mic.start();
        set({ mic: "on" });
      } catch (e) {
        set({ mic: "error" });
        showError(describeMicError(e));
      }
    },

    setVoiceSettings: (patch) => {
      const next = { ...get().voiceSettings, ...patch };
      set({ voiceSettings: next });
      storeVoice(next);
      sendVoiceConfig();
      if (voiceSaveTimer) clearTimeout(voiceSaveTimer);
      voiceSaveTimer = setTimeout(() => {
        api
          .updatePreferences({ voice: { voice: next.voice, speed: next.speed, speak_text_replies: next.speakTextReplies } })
          .catch(() => undefined);
      }, 600);
    },

    clearError: () => set({ error: null }),
    reset: () => {
      socket?.close();
      socket = null;
      player?.stop();
      player = null;
      mic?.destroy();
      mic = null;
      set({ ...initial });
    },
  };
});
