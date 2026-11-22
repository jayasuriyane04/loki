import { create } from "zustand";
import { api } from "@/lib/api";
import type { Memory, MemoryKind } from "@/lib/types";

type Filter = MemoryKind | "all";

type MemoryState = {
  items: Memory[];
  total: number;
  byKind: Record<MemoryKind, number>;
  enabled: boolean | null;
  query: string;
  filter: Filter;
  loading: boolean;
  error: string | null;
  load: () => Promise<void>;
  setQuery: (q: string) => void;
  setFilter: (f: Filter) => void;
  add: (content: string, kind: MemoryKind, importance: number, project: string | null) => Promise<boolean>;
  update: (id: string, patch: Partial<Pick<Memory, "content" | "kind" | "importance" | "project">>) => Promise<boolean>;
  remove: (id: string) => Promise<void>;
  removeAll: () => Promise<void>;
  setEnabled: (on: boolean) => Promise<void>;
};

let searchTimer: ReturnType<typeof setTimeout> | null = null;
let seq = 0;

export const useMemory = create<MemoryState>((set, get) => {
  const fail = (e: unknown) => set({ error: (e as Error).message, loading: false });

  return {
    items: [],
    total: 0,
    byKind: { profile: 0, semantic: 0, episodic: 0 },
    enabled: null,
    query: "",
    filter: "all",
    loading: false,
    error: null,

    load: async () => {
      const mine = ++seq; // ignore responses to superseded searches
      const { query, filter } = get();
      set({ loading: true, error: null });
      try {
        const [items, stats, settings] = await Promise.all([
          api.memories({ q: query.trim() || undefined, kind: filter === "all" ? undefined : filter }),
          api.memoryStats(),
          api.settings(),
        ]);
        if (mine === seq) {
          set({ items, total: stats.total, byKind: stats.by_kind, enabled: settings.memory_enabled, loading: false });
        }
      } catch (e) {
        if (mine === seq) fail(e);
      }
    },

    setQuery: (q) => {
      set({ query: q });
      if (searchTimer) clearTimeout(searchTimer);
      searchTimer = setTimeout(() => get().load(), 300);
    },

    setFilter: (f) => {
      set({ filter: f });
      get().load();
    },

    add: async (content, kind, importance, project) => {
      try {
        await api.addMemory({ content, kind, importance, project });
        await get().load();
        return true;
      } catch (e) {
        set({ error: (e as Error).message });
        return false;
      }
    },

    update: async (id, patch) => {
      try {
        const updated = await api.updateMemory(id, patch);
        set((s) => ({ items: s.items.map((m) => (m.id === id ? { ...updated, similarity: m.similarity } : m)) }));
        return true;
      } catch (e) {
        set({ error: (e as Error).message });
        return false;
      }
    },

    remove: async (id) => {
      try {
        await api.deleteMemory(id);
        await get().load();
      } catch (e) {
        set({ error: (e as Error).message });
      }
    },

    removeAll: async () => {
      try {
        await api.deleteAllMemories();
        await get().load();
      } catch (e) {
        set({ error: (e as Error).message });
      }
    },

    setEnabled: async (on) => {
      try {
        set({ enabled: (await api.updateSettings({ memory_enabled: on })).memory_enabled });
      } catch (e) {
        set({ error: (e as Error).message });
      }
    },
  };
});
