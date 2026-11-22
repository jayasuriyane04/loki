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
  citations?: Citation[] | null;
  created_at: string;
};

export type MemoryKind = "profile" | "episodic" | "semantic";

export type Memory = {
  id: string;
  kind: MemoryKind;
  content: string;
  importance: number;
  project: string | null;
  source: "extracted" | "user_edited" | "summary";
  source_conversation_id: string | null;
  event_at: string | null;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
  use_count: number;
  similarity: number | null;
};

export type MemoryRef = { id: string; kind: MemoryKind; content: string };

/** A document passage LOKI was shown for a reply; `cited` = the answer referenced it as [n]. */
export type Citation = {
  n: number;
  document_id: string;
  chunk_id: string;
  title: string;
  source: string;
  project: string | null;
  heading: string | null;
  page: number | null;
  line_start: number | null;
  line_end: number | null;
  score: number;
  snippet: string;
  cited: boolean;
};

export type DocStatus = "pending" | "processing" | "ready" | "failed";

export type DocumentInfo = {
  id: string;
  project: string;
  title: string;
  source: string;
  file_type: "pdf" | "markdown" | "text" | "html" | "code";
  language: string | null;
  size_bytes: number;
  status: DocStatus;
  error: string | null;
  chunk_count: number;
  page_count: number | null;
  created_at: string;
  updated_at: string;
  indexed_at: string | null;
};

export type ChunkInfo = {
  id: string;
  ordinal: number;
  content: string;
  heading_path: string | null;
  page: number | null;
  line_start: number | null;
  line_end: number | null;
};

export type UploadResult = {
  source: string;
  status: "queued" | "unchanged" | "rejected";
  document_id: string | null;
  reason: string | null;
};

export type SearchHit = {
  document_id: string;
  title: string;
  source: string;
  project: string;
  heading_path: string | null;
  page: number | null;
  line_start: number | null;
  line_end: number | null;
  content: string;
  score: number;
  rerank: number | null;
  vector_rank: number | null;
  keyword_rank: number | null;
};

export type KnowledgeStatus = {
  documents: number;
  by_status: Partial<Record<DocStatus, number>>;
  chunks: number;
  embedding_model: string;
  reranker: { model: string | null; state: string; error: string | null };
};
export type MemoryOp = { action: "add" | "update" | "delete"; id: string; kind: MemoryKind; content: string };

/** Client-side view of a message: adds transient flags that never come from the server. */
export type UiMessage = Message & {
  streaming?: boolean;
  pending?: boolean;
  failed?: boolean;
  recalled?: MemoryRef[]; // memories LOKI was given for this reply
  saved?: MemoryOp[]; // memory changes made after this reply
};

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
  | { type: "state"; state: "transcribing" | "retrieving" | "processing" | "thinking" | "idle" }
  | { type: "memories_used"; conversation_id: string; memories: MemoryRef[] }
  | { type: "memory_updated"; conversation_id: string; operations: MemoryOp[] }
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
