"""Tools over the user's own knowledge: documents (incl. source code) and memories."""

from pydantic import Field
from sqlalchemy import select

from app.db.models import Chunk, Document
from app.memory import store as memory_store
from app.tools.base import ToolContext, ToolError, ToolInput, ToolResult
from app.tools.registry import tool


class SearchDocsIn(ToolInput):
    query: str = Field(min_length=2, max_length=300)
    project: str | None = Field(None, description="Limit to one project")


def _fmt_hits(hits) -> str:
    out = []
    for i, h in enumerate(hits, start=1):
        c, d = h.chunk, h.chunk.document
        loc = f"page {c.page}" if c.page else (f"lines {c.line_start}-{c.line_end}" if c.line_start else "")
        out.append(f"[{i}] {d.source} {('> ' + c.heading_path) if c.heading_path else ''} {loc}\n{c.content}")
    return "\n\n".join(out)


@tool("search_documents", "Search the user's uploaded documents and project files. Documents are also searched "
      "automatically before each reply; use this for a different or more specific query.", SearchDocsIn,
      permission="read", category="knowledge")
async def search_documents(ctx: ToolContext, a: SearchDocsIn) -> ToolResult:
    async with ctx.sessions() as db:
        hits = await ctx.services["knowledge"].search(db, ctx.user_id, a.query, project=a.project)
    if not hits:
        return ToolResult("No relevant passages in the user's documents.", f"Searched documents for “{a.query}”: nothing relevant")
    return ToolResult(_fmt_hits(hits), f"Searched documents for “{a.query}” ({len(hits)} passages)")


@tool("search_code", "Search source code files the user uploaded (e.g. to find where something is implemented).",
      SearchDocsIn, permission="read", category="development")
async def search_code(ctx: ToolContext, a: SearchDocsIn) -> ToolResult:
    async with ctx.sessions() as db:
        hits = await ctx.services["knowledge"].search(db, ctx.user_id, a.query, project=a.project, top_k=12)
    hits = [h for h in hits if h.chunk.document.file_type == "code"][:6]
    if not hits:
        return ToolResult("No matching code in the uploaded projects.", f"Searched code for “{a.query}”: nothing")
    return ToolResult(_fmt_hits(hits), f"Searched code for “{a.query}” ({len(hits)} matches)")


class ReadFileIn(ToolInput):
    path: str = Field(description="File path as shown in search results, e.g. tarka/app/auth.py")
    project: str | None = None


@tool("read_project_file", "Read a whole file the user uploaded to the knowledge base (only uploaded files; LOKI "
      "has no other file system access).", ReadFileIn, permission="read", category="development")
async def read_project_file(ctx: ToolContext, a: ReadFileIn) -> ToolResult:
    async with ctx.sessions() as db:
        q = select(Document).where(Document.user_id == ctx.user_id, Document.status == "ready",
                                   Document.source.like(f"%{a.path.strip().lstrip('/')}"))
        if a.project is not None:
            q = q.where(Document.project == a.project)
        docs = list(await db.scalars(q.limit(3)))
        if not docs:
            raise ToolError(f"No uploaded file matches {a.path!r}.")
        if len(docs) > 1:
            raise ToolError("Several files match: " + ", ".join(d.source for d in docs) + ". Use the full path.")
        doc = docs[0]
        chunks = list(await db.scalars(select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.ordinal)))
    # Chunks overlap slightly; for reading, the line-numbered view is what matters.
    text = "\n".join(
        (f"--- lines {c.line_start}-{c.line_end} ---\n" if c.line_start else (f"--- page {c.page} ---\n" if c.page else ""))
        + c.content for c in chunks
    )
    return ToolResult(f"{doc.source} ({doc.language or doc.file_type})\n{text[:15000]}", f"Read {doc.source}")


class SearchMemoryIn(ToolInput):
    query: str = Field(min_length=2, max_length=300)


@tool("search_memory", "Search what LOKI remembers about the user (memories are also recalled automatically).",
      SearchMemoryIn, permission="read", category="knowledge")
async def search_memory(ctx: ToolContext, a: SearchMemoryIn) -> ToolResult:
    emb = ctx.services["embeddings"]
    async with ctx.sessions() as db:
        if not await memory_store.memory_enabled(db, ctx.user_id):
            return ToolResult("Memory is switched off by the user.", "Memory is off")
        hits = await memory_store.search(db, ctx.user_id, await emb.embed_query(a.query), k=8, min_similarity=0.3)
    if not hits:
        return ToolResult("No related memories.", f"Searched memory for “{a.query}”: nothing")
    return ToolResult("\n".join(f"- ({h.memory.kind}) {h.memory.content}" for h in hits),
                      f"Searched memory for “{a.query}” ({len(hits)} found)")
