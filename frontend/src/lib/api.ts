import type {
  AppNotification,
  EventItem,
  NoteItem,
  ReminderItem,
  TaskItem,
  ToolExecution,
  ToolInfo,
  ChunkInfo,
  ConversationDetail,
  ConversationSummary,
  DocumentInfo,
  KnowledgeStatus,
  Memory,
  SearchHit,
  UploadResult,
  MemoryKind,
  ModelsStatus,
  User,
  VoiceStatus,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
export const WS_URL = API_URL.replace(/^http/, "ws") + "/ws";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      credentials: "include",
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch {
    throw new ApiError(0, "Can't reach the LOKI backend. Is it running?");
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = body?.detail;
    const message = Array.isArray(detail)
      ? detail.map((d: { msg?: string }) => d.msg).join("; ")
      : typeof detail === "string"
        ? detail
        : `Request failed (${res.status})`;
    throw new ApiError(res.status, message);
  }
  return body as T;
}

const json = (data: unknown) => JSON.stringify(data);

export const api = {
  me: () => request<User>("/api/auth/me"),
  login: (email: string, password: string) =>
    request<User>("/api/auth/login", { method: "POST", body: json({ email, password }) }),
  register: (email: string, password: string, display_name: string) =>
    request<User>("/api/auth/register", { method: "POST", body: json({ email, password, display_name }) }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),

  listConversations: () => request<ConversationSummary[]>("/api/conversations?limit=100"),
  getConversation: (id: string) => request<ConversationDetail>(`/api/conversations/${id}`),
  renameConversation: (id: string, title: string) =>
    request<ConversationSummary>(`/api/conversations/${id}`, { method: "PATCH", body: json({ title }) }),
  deleteConversation: (id: string) => request<void>(`/api/conversations/${id}`, { method: "DELETE" }),

  models: () => request<ModelsStatus>("/api/models"),
  voice: () => request<VoiceStatus>("/api/voice"),

  memories: (opts: { q?: string; kind?: MemoryKind } = {}) => {
    const p = new URLSearchParams();
    if (opts.q) p.set("q", opts.q);
    if (opts.kind) p.set("kind", opts.kind);
    return request<Memory[]>(`/api/memories${p.size ? `?${p}` : ""}`);
  },
  memoryStats: () => request<{ total: number; by_kind: Record<MemoryKind, number> }>("/api/memories/stats"),
  addMemory: (body: { content: string; kind: MemoryKind; importance: number; project?: string | null }) =>
    request<Memory>("/api/memories", { method: "POST", body: json(body) }),
  updateMemory: (id: string, body: Partial<Pick<Memory, "content" | "kind" | "importance" | "project">>) =>
    request<Memory>(`/api/memories/${id}`, { method: "PATCH", body: json(body) }),
  deleteMemory: (id: string) => request<void>(`/api/memories/${id}`, { method: "DELETE" }),
  deleteAllMemories: () => request<{ deleted: number }>("/api/memories?confirm=true", { method: "DELETE" }),
  documents: () => request<DocumentInfo[]>("/api/documents"),
  document: (id: string) => request<DocumentInfo & { chunks: ChunkInfo[] }>(`/api/documents/${id}`),
  deleteDocument: (id: string) => request<void>(`/api/documents/${id}`, { method: "DELETE" }),
  reindexDocument: (id: string) => request<DocumentInfo>(`/api/documents/${id}/reindex`, { method: "POST" }),
  uploadDocuments: async (files: { file: File; path: string }[], project: string): Promise<UploadResult[]> => {
    const form = new FormData();
    for (const f of files) {
      form.append("files", f.file);
      form.append("paths", f.path);
    }
    form.append("project", project);
    let res: Response;
    try {
      res = await fetch(`${API_URL}/api/documents`, { method: "POST", body: form, credentials: "include" });
    } catch {
      throw new ApiError(0, "Can't reach the LOKI backend. Is it running?");
    }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(res.status, typeof body?.detail === "string" ? body.detail : `Upload failed (${res.status})`);
    return body as UploadResult[];
  },
  searchKnowledge: (q: string, project?: string) => {
    const p = new URLSearchParams({ q });
    if (project) p.set("project", project);
    return request<SearchHit[]>(`/api/knowledge/search?${p}`);
  },
  knowledgeStatus: () => request<KnowledgeStatus>("/api/knowledge/status"),
  projects: () => request<string[]>("/api/projects"),
  tasks: (status: "open" | "done" | "all" = "all") => request<TaskItem[]>(`/api/tasks?status=${status}`),
  createTask: (body: { title: string; due_at?: string | null; priority?: string; project?: string | null }) =>
    request<TaskItem>("/api/tasks", { method: "POST", body: json(body) }),
  updateTask: (id: string, body: Partial<Pick<TaskItem, "title" | "status" | "priority" | "due_at" | "project">>) =>
    request<TaskItem>(`/api/tasks/${id}`, { method: "PATCH", body: json(body) }),
  deleteTask: (id: string) => request<void>(`/api/tasks/${id}`, { method: "DELETE" }),
  reminders: (includePast = false) => request<ReminderItem[]>(`/api/reminders?include_past=${includePast}`),
  createReminder: (body: { text: string; remind_at: string }) =>
    request<ReminderItem>("/api/reminders", { method: "POST", body: json(body) }),
  cancelReminder: (id: string) => request<ReminderItem>(`/api/reminders/${id}/cancel`, { method: "POST" }),
  notes: () => request<NoteItem[]>("/api/notes"),
  deleteNote: (id: string) => request<void>(`/api/notes/${id}`, { method: "DELETE" }),
  events: (start?: string) => request<EventItem[]>(`/api/events${start ? `?start=${encodeURIComponent(start)}` : ""}`),
  deleteEvent: (id: string) => request<void>(`/api/events/${id}`, { method: "DELETE" }),
  notifications: (unread = false) => request<AppNotification[]>(`/api/notifications?unread=${unread}`),
  markNotificationsRead: (ids?: string[]) =>
    request<void>("/api/notifications/read", { method: "POST", body: json({ ids: ids ?? null }) }),
  tools: () => request<ToolInfo[]>("/api/tools"),
  setToolSetting: (name: string, setting: ToolInfo["setting"]) =>
    request<ToolInfo>(`/api/tools/${name}`, { method: "PATCH", body: json({ setting }) }),
  toolExecutions: (limit = 50) => request<ToolExecution[]>(`/api/tool-executions?limit=${limit}`),
  settings: () => request<{ memory_enabled: boolean }>("/api/settings"),
  updateSettings: (body: { memory_enabled: boolean }) =>
    request<{ memory_enabled: boolean }>("/api/settings", { method: "PATCH", body: json(body) }),
};
