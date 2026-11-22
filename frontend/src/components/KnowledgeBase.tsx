"use client";

import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowLeft,
  BookOpen,
  ChevronDown,
  Code2,
  FileText,
  FolderUp,
  Loader2,
  RefreshCw,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { ChunkInfo, DocumentInfo } from "@/lib/types";
import { useChat } from "@/store/chat";
import { useKnowledge } from "@/store/knowledge";

const SKIP_DIRS = new Set(["node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", ".next", "target"]);
const BATCH = 50;

function fmtSize(b: number) {
  return b < 1024 ? `${b} B` : b < 1024 ** 2 ? `${(b / 1024).toFixed(0)} KB` : `${(b / 1024 ** 2).toFixed(1)} MB`;
}

function where(c: { page: number | null; line_start: number | null; line_end: number | null }) {
  if (c.page) return `p. ${c.page}`;
  if (c.line_start) return `lines ${c.line_start}–${c.line_end}`;
  return "";
}

/** Walk dropped folders (webkitGetAsEntry) and collect files with their relative paths, skipping junk folders. */
async function filesFromDrop(items: DataTransferItemList): Promise<{ file: File; path: string }[]> {
  const out: { file: File; path: string }[] = [];
  const walk = async (entry: FileSystemEntry, prefix: string): Promise<void> => {
    if (entry.isFile) {
      const file = await new Promise<File>((res, rej) => (entry as FileSystemFileEntry).file(res, rej));
      out.push({ file, path: prefix + entry.name });
    } else if (entry.isDirectory && !SKIP_DIRS.has(entry.name)) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      let batch: FileSystemEntry[];
      do {
        batch = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej));
        for (const e of batch) await walk(e, `${prefix}${entry.name}/`);
      } while (batch.length);
    }
  };
  const entries = Array.from(items)
    .map((i) => i.webkitGetAsEntry())
    .filter((e): e is FileSystemEntry => !!e);
  for (const e of entries) await walk(e, "");
  return out;
}

function fromInput(list: FileList | null): { file: File; path: string }[] {
  return Array.from(list ?? [])
    .map((file) => ({ file, path: file.webkitRelativePath || file.name }))
    .filter(({ path }) => !path.split("/").slice(0, -1).some((p) => SKIP_DIRS.has(p)));
}

function StatusBadge({ d }: { d: DocumentInfo }) {
  const styles: Record<string, string> = {
    ready: "border-ok/30 text-ok",
    failed: "border-bad/40 text-bad",
    pending: "border-line text-dim",
    processing: "border-cyan/30 text-cyan",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-mono text-[10.5px] ${styles[d.status]}`}>
      {(d.status === "processing" || d.status === "pending") && <Loader2 size={10} className="animate-spin" />}
      {d.status}
    </span>
  );
}

function DocumentRow({ d }: { d: DocumentInfo }) {
  const { remove, reindex } = useKnowledge();
  const [open, setOpen] = useState(false);
  const [chunks, setChunks] = useState<ChunkInfo[] | null>(null);
  const Icon = d.file_type === "code" ? Code2 : FileText;

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !chunks) setChunks((await api.document(d.id)).chunks);
  }

  return (
    <li className="rounded-xl border border-line bg-deep/40">
      <div className="flex items-start gap-3 p-3">
        <Icon size={16} className="mt-0.5 shrink-0 text-cyan/80" />
        <button onClick={toggle} className="min-w-0 flex-1 text-left" aria-expanded={open}>
          <div className="truncate text-[14.5px] text-ink">{d.title}</div>
          <div className="mt-0.5 truncate font-mono text-[11px] text-faint">{d.source}</div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-faint">
            <StatusBadge d={d} />
            <span>{d.language ?? d.file_type}</span>
            <span>{fmtSize(d.size_bytes)}</span>
            {d.status === "ready" && <span>{d.chunk_count} passages</span>}
            {d.page_count != null && <span>{d.page_count} pages</span>}
          </div>
          {d.error && (
            <div className="mt-1.5 flex items-start gap-1.5 text-xs text-bad">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" /> {d.error}
            </div>
          )}
        </button>
        <div className="flex shrink-0 gap-0.5">
          <button onClick={() => reindex(d.id)} className="rounded-md p-1.5 text-faint hover:text-ink" aria-label={`Re-index ${d.title}`} title="Re-index">
            <RefreshCw size={14} />
          </button>
          <button
            onClick={() => confirm(`Remove "${d.title}" from LOKI's knowledge base? The stored file and its passages are deleted.`) && remove(d.id)}
            className="rounded-md p-1.5 text-faint hover:text-bad"
            aria-label={`Delete ${d.title}`}
            title="Delete"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      {open && (
        <div className="max-h-80 space-y-2 overflow-y-auto border-t border-line p-3">
          {!chunks && <p className="text-xs text-faint">Loading passages…</p>}
          {chunks?.length === 0 && <p className="text-xs text-faint">No passages (not indexed yet).</p>}
          {chunks?.map((c) => (
            <div key={c.id} className="rounded-lg bg-night/60 p-2.5">
              <div className="mb-1 font-mono text-[10.5px] text-faint">
                #{c.ordinal + 1} {c.heading_path ? `· ${c.heading_path}` : ""} {where(c) ? `· ${where(c)}` : ""}
              </div>
              <pre className="whitespace-pre-wrap break-words font-sans text-[12.5px] leading-relaxed text-dim">{c.content}</pre>
            </div>
          ))}
        </div>
      )}
    </li>
  );
}

export function KnowledgeBase() {
  const setView = useChat((s) => s.setView);
  const { docs, status, projects, uploading, lastUpload, hits, searching, error, load, upload, search, clearSearch } =
    useKnowledge();
  const [project, setProject] = useState("");
  const [query, setQuery] = useState("");
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    folderInput.current?.setAttribute("webkitdirectory", "");
  }, []);

  async function send(files: { file: File; path: string }[]) {
    for (let i = 0; i < files.length; i += BATCH) await upload(files.slice(i, i + BATCH), project.trim());
  }

  const groups = new Map<string, DocumentInfo[]>();
  for (const d of docs) groups.set(d.project, [...(groups.get(d.project) ?? []), d]);
  const rejected = lastUpload?.filter((r) => r.status === "rejected") ?? [];
  const rr = status?.reranker;

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-6">
        <button onClick={() => setView("assistant")} className="mb-4 flex items-center gap-1.5 text-sm text-dim hover:text-ink">
          <ArrowLeft size={15} /> Back to LOKI
        </button>
        <h1 className="flex items-center gap-2 text-2xl font-light text-ink">
          <BookOpen size={22} className="text-cyan" /> Knowledge base
        </h1>
        <p className="mt-1 max-w-xl text-sm text-dim">
          Documents LOKI can search when answering: notes, docs, PDFs, or a project&apos;s source folder. Answers that
          use them cite the passage, like [1]. Files stay on your machine; secrets files and dependency folders are skipped.
        </p>
        {status && (
          <p className="mt-2 font-mono text-[11px] text-faint">
            {status.documents} documents · {status.chunks} passages · embeddings {status.embedding_model} · reranker{" "}
            <span className={rr?.state === "ready" ? "text-ok" : rr?.state === "error" ? "text-bad" : "text-warn"}>
              {rr?.model ?? "none"} ({rr?.state})
            </span>
          </p>
        )}

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={async (e) => {
            e.preventDefault();
            setDragging(false);
            await send(await filesFromDrop(e.dataTransfer.items));
          }}
          className={`mt-5 rounded-2xl border border-dashed p-5 transition ${
            dragging ? "border-cyan/60 bg-cyan/5" : "border-line-strong bg-deep/30"
          }`}
        >
          <div className="flex flex-wrap items-center gap-2">
            <input
              list="loki-projects"
              value={project}
              onChange={(e) => setProject(e.target.value)}
              maxLength={100}
              placeholder="Project (optional), e.g. Tarka"
              className="w-56 rounded-lg border border-line bg-night px-3 py-2 text-sm text-ink placeholder:text-faint outline-none focus:border-cyan/50"
            />
            <datalist id="loki-projects">
              {projects.map((p) => (
                <option key={p} value={p} />
              ))}
            </datalist>
            <button
              onClick={() => fileInput.current?.click()}
              disabled={uploading}
              className="flex items-center gap-1.5 rounded-lg bg-cyan/90 px-3 py-2 text-sm font-medium text-void hover:bg-cyan disabled:opacity-50"
            >
              <Upload size={15} /> Add files
            </button>
            <button
              onClick={() => folderInput.current?.click()}
              disabled={uploading}
              className="flex items-center gap-1.5 rounded-lg border border-line-strong px-3 py-2 text-sm text-ink hover:border-cyan/40 disabled:opacity-50"
            >
              <FolderUp size={15} className="text-cyan" /> Add folder
            </button>
            {uploading && <Loader2 size={16} className="animate-spin text-cyan" />}
          </div>
          <p className="mt-3 text-xs text-faint">
            Or drop files or folders here. PDF, Markdown, text, HTML and source code, up to 20 MB each. Re-uploading a
            file with the same path updates it.
          </p>
          <input ref={fileInput} type="file" multiple hidden onChange={(e) => send(fromInput(e.target.files)).then(() => (e.target.value = ""))} />
          <input ref={folderInput} type="file" multiple hidden onChange={(e) => send(fromInput(e.target.files)).then(() => (e.target.value = ""))} />
        </div>

        {lastUpload && (
          <p className="mt-3 text-sm text-dim">
            {lastUpload.filter((r) => r.status === "queued").length} queued ·{" "}
            {lastUpload.filter((r) => r.status === "unchanged").length} unchanged · {rejected.length} skipped
          </p>
        )}
        {rejected.length > 0 && (
          <details className="mt-1 text-xs text-faint">
            <summary className="cursor-pointer">Show skipped files</summary>
            <ul className="mt-1 space-y-0.5">
              {rejected.map((r) => (
                <li key={r.source}>
                  <span className="font-mono">{r.source}</span>: {r.reason}
                </li>
              ))}
            </ul>
          </details>
        )}
        {error && (
          <div role="alert" className="mt-3 flex items-start gap-2 rounded-lg border border-bad/30 bg-bad/[0.07] px-3 py-2 text-sm">
            <span className="flex-1">{error}</span>
            <button onClick={() => useKnowledge.setState({ error: null })} aria-label="Dismiss">
              <X size={14} />
            </button>
          </div>
        )}

        <form
          className="mt-6 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            search(query);
          }}
        >
          <div className="relative flex-1">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                if (!e.target.value) clearSearch();
              }}
              placeholder="Test a question: see which passages LOKI would use"
              className="w-full rounded-lg border border-line bg-night/70 py-2 pl-9 pr-3 text-sm text-ink placeholder:text-faint outline-none focus:border-cyan/50"
            />
          </div>
          <button type="submit" disabled={searching || !query.trim()} className="rounded-lg border border-line-strong px-3 text-sm text-ink disabled:opacity-40">
            {searching ? <Loader2 size={15} className="animate-spin" /> : "Search"}
          </button>
        </form>
        <AnimatePresence>
          {hits && (
            <motion.ul initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="mt-3 space-y-2">
              {hits.length === 0 && <li className="text-sm text-faint">No passage is relevant enough. LOKI wouldn&apos;t use your documents for this.</li>}
              {hits.map((h, i) => (
                <li key={i} className="rounded-xl border border-cyan/20 bg-deep/40 p-3">
                  <div className="flex flex-wrap items-center gap-x-2 font-mono text-[11px] text-faint">
                    <span className="text-cyan">[{i + 1}]</span>
                    <span className="text-dim">{h.source}</span>
                    {h.heading_path && <span>· {h.heading_path}</span>}
                    {where(h) && <span>· {where(h)}</span>}
                    <span className="ml-auto">
                      relevance {h.rerank != null ? `${(h.rerank * 100).toFixed(0)}%` : "–"} · vector #{h.vector_rank ?? "–"} · keyword #{h.keyword_rank ?? "–"}
                    </span>
                  </div>
                  <p className="mt-1.5 line-clamp-4 whitespace-pre-wrap text-[13px] text-dim">{h.content}</p>
                </li>
              ))}
            </motion.ul>
          )}
        </AnimatePresence>

        <div className="mt-8 space-y-6">
          {docs.length === 0 && <p className="text-center text-sm text-faint">No documents yet.</p>}
          {[...groups.entries()].map(([proj, list]) => (
            <section key={proj}>
              <h2 className="hud-label mb-2 flex items-center gap-1">
                <ChevronDown size={12} /> {proj || "No project"} · {list.length}
              </h2>
              <ul className="space-y-2">
                {list.map((d) => (
                  <DocumentRow key={d.id} d={d} />
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
