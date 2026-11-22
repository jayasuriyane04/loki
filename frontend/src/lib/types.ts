export type User = {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
};

export type ConversationSummary = {
  id: string;
  title: string;
  is_temporary: boolean;
  created_at: string;
  updated_at: string;
};

export type MessageStatus = "complete" | "interrupted" | "error";

export type Message = {
  id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  status: MessageStatus;
  input_mode: "text" | "voice";
  provider: string | null;
  model: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  latency_ms: number | null;
  first_token_ms: number | null;
  created_at: string;
};

/** Client-side view of a message: adds transient flags that never come from the server. */
export type UiMessage = Message & { streaming?: boolean; pending?: boolean; failed?: boolean };

export type ConversationDetail = ConversationSummary & { messages: Message[] };

export type ProviderStatus = {
  provider: string;
  model: string;
  ok: boolean;
  latency_ms: number | null;
  error: string | null;
};

export type ModelsStatus = { primary: ProviderStatus; fallback: ProviderStatus | null };

type LoadState = "disabled" | "loading" | "ready" | "error";
export type VoiceStatus = {
  stt: { provider: string | null; model: string | null; state: LoadState; error: string | null };
  tts: {
    provider: string | null;
    state: LoadState;
    error: string | null;
    voices: string[];
    default_voice: string;
    default_speed: number;
  };
};

export type VoiceSettings = { voice: string | null; speed: number; speakTextReplies: boolean };

/** Every visual state LOKI can be in. Phase 1 produces idle / processing / thinking / responding / error. */
export type AssistantState =
  | "idle"
  | "listening"
  | "hearing"
  | "transcribing"
  | "processing"
  | "thinking"
  | "retrieving"
  | "executing"
  | "responding"
  | "speaking"
  | "error";

export type ServerEvent =
  | { type: "conversation"; conversation: ConversationSummary }
  | { type: "message_saved"; conversation_id: string; message: Message }
  | { type: "state"; state: "transcribing" | "processing" | "thinking" | "idle" }
  | { type: "stt_final"; text: string; language: string | null; latency_ms: number; audio_s: number }
  | {
      type: "tts_chunk";
      message_id: string;
      seq: number;
      sample_rate: number;
      duration_s: number;
      text: string;
    }
  | { type: "tts_end"; message_id: string; first_audio_ms: number | null }
  | { type: "stt_command"; command: "stop" }
  | {
      type: "assistant_start";
      conversation_id: string;
      message_id: string;
      provider: string;
      model: string;
      fell_back: boolean;
    }
  | { type: "token"; message_id: string; delta: string }
  | { type: "assistant_end"; message: Message }
  | { type: "error"; code: string; message: string }
  | { type: "pong" };
