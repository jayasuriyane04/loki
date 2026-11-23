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
  project?: string | null;
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
  tool_steps?: ToolStep[] | null;
  feedback?: number | null;
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

export type ToolStep = {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  status: "running" | "ok" | "error" | "denied" | "timeout" | "invalid" | "disabled";
  summary: string;
  approved: boolean | null;
  duration_ms: number;
  data?: Record<string, unknown> | null;
};

export type ApprovalRequest = {
  approval_id: string;
  tool: string;
  args: Record<string, unknown>;
  description: string;
  call: string;
  always_confirm: boolean;
};

export type AppNotification = {
  id: string;
  kind: "reminder" | "agent" | "system" | "deadline" | "event" | "briefing" | "folder";
  title: string;
  body: string | null;
  data?: Record<string, unknown> | null;
  read_at?: string | null;
  created_at: string;
};

export type TaskItem = {
  id: string;
  title: string;
  notes: string | null;
  project: string | null;
  priority: "low" | "normal" | "high";
  status: "open" | "done";
  due_at: string | null;
  completed_at: string | null;
  created_by: "user" | "loki";
  created_at: string;
};

export type ReminderItem = {
  id: string;
  text: string;
  remind_at: string;
  status: "scheduled" | "delivered" | "cancelled";
  delivered_at: string | null;
  created_by: string;
};

export type NoteItem = { id: string; title: string; body: string; project: string | null; created_by: string; updated_at: string };

export type EventItem = {
  id: string;
  title: string;
  starts_at: string;
  ends_at: string | null;
  location: string | null;
  notes: string | null;
  created_by: string;
};

export type ToolInfo = {
  name: string;
  description: string;
  category: string;
  permission: "read" | "reversible" | "confirm";
  always_confirm: boolean;
  setting: "auto" | "confirm" | "off";
  parameters: Record<string, unknown>;
};

export type ToolExecution = {
  id: string;
  conversation_id: string | null;
  tool: string;
  arguments: Record<string, unknown>;
  permission: string;
  status: string;
  approved: boolean | null;
  summary: string | null;
  error: string | null;
  duration_ms: number;
  created_at: string;
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
  | { type: "state"; state: "transcribing" | "retrieving" | "processing" | "thinking" | "executing" | "idle" }
  | { type: "tool_call"; id: string; tool: string; args: Record<string, unknown> }
  | ({ type: "tool_result" } & ToolStep)
  | ({ type: "approval_required" } & ApprovalRequest)
  | { type: "approval_resolved"; approval_id: string; approved: boolean }
  | { type: "notification"; notification: AppNotification }
  | { type: "project"; conversation_id: string; project: string }
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

// ---------- Phase 6: preferences + projects ----------
export type WatchedFolder = { path: string; project: string; interval_min: number };

export type Preferences = {
  style: {
    response_length: "brief" | "balanced" | "detailed";
    tone: "casual" | "neutral" | "formal";
    language: string;
    markdown: boolean;
    custom_instructions: string;
  };
  voice: { voice: string | null; speed: number; speak_text_replies: boolean };
  proactive: {
    deadline_alerts: boolean;
    deadline_lead_min: number;
    event_headsup: boolean;
    event_lead_min: number;
    daily_briefing: boolean;
    briefing_time: string;
    briefing_location: string;
    conversation_digests: boolean;
    watched_folders: WatchedFolder[];
  };
  quiet_hours: { enabled: boolean; start: string; end: string };
  background_processing: boolean;
};

/** Partial update: nested objects are merged by the server. */
export type PreferencesPatch = { [K in keyof Preferences]?: Preferences[K] extends object ? Partial<Preferences[K]> : Preferences[K] };

export type Learned = {
  preference_memories: { id: string; content: string }[];
  top_tools: { tool: string; count: number }[];
};

export type ProjectStatus = "active" | "paused" | "done";

export type ProjectInfo = {
  name: string;
  description: string | null;
  status: ProjectStatus;
  overview: string | null;
  overview_at: string | null;
  counts: { open_tasks: number; notes: number; memories: number; documents: number; conversations: number };
  last_activity: string | null;
};

export type ProjectDetail = ProjectInfo & {
  tasks: { id: string; title: string; status: string; due_at: string | null }[];
  notes: { id: string; title: string; updated_at: string }[];
  memories: { id: string; kind: string; content: string; event_at: string | null }[];
  documents: { id: string; source: string; status: string }[];
  conversations: { id: string; title: string; updated_at: string }[];
};

export type FolderScan = { added: string[]; updated: string[]; removed: string[]; skipped: number };

// ---------- Phase 7: observability ----------
export type Dist = { n: number; p50: number | null; p95: number | null; max: number | null };

export type MetricsSummary = {
  days: number;
  voice: {
    turns: number; stt_ms: Dist; first_audio_ms: Dist; total_ms: Dist; stt_errors: number; stt_error_rate: number | null;
    no_speech: number; stop_commands: number; interrupted: number; tts_failures: number;
  };
  responses: {
    turns: number; first_token_ms: Dist; total_ms: Dist; errors: number; error_rate: number | null; fallbacks: number;
    prompt_tokens: number; completion_tokens: number; cost_usd: number | null;
    by_model: Record<string, { turns: number; prompt_tokens: number; completion_tokens: number; cost_usd: number | null }>;
  };
  rag: {
    retrieval_ms: Dist; turns_with_documents: number; avg_passages: number | null; turns_citing: number;
    passages_shown: number; passages_cited: number; invented_citations: number; citation_validity: number | null;
  };
  memory: { recall_ms: Dist; recalls_with_hits: number; extraction_ms: Dist; extraction_errors: number };
  agent: {
    turns_with_tools: number; tool_calls: number; success_rate: number | null; denied: number; failed: number;
    failure_recovery_rate: number | null; turns_with_failures: number; model_steps: Dist; guards: Record<string, number>;
    per_tool: { tool: string; calls: number; success_rate: number | null; p50_ms: number | null }[];
  };
  system: {
    requests: number; api_ms: Dist; server_errors: number;
    slowest_routes: { route: string; n: number; p50_ms: number | null; p95_ms: number | null }[];
    errors: number; errors_by_source: [string, number][];
    recent_errors: { at: string; source: string; message: string | null }[];
    connections_now: number; connections_peak: number; feedback: { up: number; down: number }; dropped_metrics: number;
  };
  daily: { date: string; turns: number; errors: number; tokens: number; p50_first_token_ms: number | null }[];
  evals: Record<string, { file: string; ran_at: string; headline: Record<string, unknown>; config: Record<string, unknown> }>;
};

export type TraceSpan = { name: string; start_ms: number; duration_ms: number; attrs?: Record<string, unknown> };

export type TraceInfo = {
  id: string; kind: string; status: string; input_mode: string; created_at: string; conversation_id: string | null;
  model: string | null; duration_ms: number | null; first_token_ms: number | null; first_audio_ms: number | null;
  stt_ms: number | null; prompt_tokens: number | null; completion_tokens: number | null;
  spans: TraceSpan[]; attrs: Record<string, unknown>;
};

export type EvalReport = {
  suite: string; ran_at: string; config: Record<string, unknown>; headline: Record<string, unknown>;
  details: Record<string, unknown>;
};
