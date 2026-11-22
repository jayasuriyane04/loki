import type {
  ConversationDetail,
  ConversationSummary,
  Memory,
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
  settings: () => request<{ memory_enabled: boolean }>("/api/settings"),
  updateSettings: (body: { memory_enabled: boolean }) =>
    request<{ memory_enabled: boolean }>("/api/settings", { method: "PATCH", body: json(body) }),
};
