import { create } from "zustand";
import { api } from "@/lib/api";
import type { DocumentInfo, KnowledgeStatus, SearchHit, UploadResult } from "@/lib/types";

type KnowledgeState = {
  docs: DocumentInfo[];
  status: KnowledgeStatus | null;
  projects: string[];
  uploading: boolean;
  lastUpload: UploadResult[] | null;
  hits: SearchHit[] | null;
  searching: boolean;
  error: string | null;
  load: () => Promise<void>;
  upload: (files: { file: File; path: string }[], project: string) => Promise<void>;
  remove: (id: string) => Promise<void>;
  reindex: (id: string) => Promise<void>;
  search: (q: string, project?: string) => Promise<void>;
  clearSearch: () => void;
};

let poll: ReturnType<typeof setTimeout> | null = null;

export const useKnowledge = create<KnowledgeState>((set, get) => {
  const fail = (e: unknown) => set({ error: (e as Error).message });

  /** While anything is being indexed, refresh every 1.5 s so statuses update without a reload. */
  const schedule = () => {
    if (poll) clearTimeout(poll);
    if (get().docs.some((d) => d.status === "pending" || d.status === "processing")) {
      poll = setTimeout(() => get().load(), 1500);
    }
  };

  return {
    docs: [],
    status: null,
    projects: [],
    uploading: false,
    lastUpload: null,
    hits: null,
    searching: false,
    error: null,

    load: async () => {
      try {
        const [docs, status, projects] = await Promise.all([api.documents(), api.knowledgeStatus(), api.projects()]);
        set({ docs, status, projects });
        schedule();
      } catch (e) {
        fail(e);
      }
    },

    upload: async (files, project) => {
      if (!files.length) return;
      set({ uploading: true, error: null, lastUpload: null });
      try {
        set({ lastUpload: await api.uploadDocuments(files, project) });
        await get().load();
      } catch (e) {
        fail(e);
      } finally {
        set({ uploading: false });
      }
    },

    remove: async (id) => {
      try {
        await api.deleteDocument(id);
        await get().load();
      } catch (e) {
        fail(e);
      }
    },

    reindex: async (id) => {
      try {
        await api.reindexDocument(id);
        await get().load();
      } catch (e) {
        fail(e);
      }
    },

    search: async (q, project) => {
      if (!q.trim()) return;
      set({ searching: true, error: null });
      try {
        set({ hits: await api.searchKnowledge(q.trim(), project) });
      } catch (e) {
        fail(e);
      } finally {
        set({ searching: false });
      }
    },

    clearSearch: () => set({ hits: null }),
  };
});
