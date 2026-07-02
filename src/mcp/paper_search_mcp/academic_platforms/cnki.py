"""CNKI (中国知网) searcher via the @ai4paper/apaper-mcp MCP server.

apaper-mcp exposes search_cnki_papers / download_cnki_paper as MCP stdio
tools. This searcher wraps a long-lived MCPStdioClient subprocess
(`npx -y @ai4paper/apaper-mcp`) and translates between our Paper schema
and apaper-mcp's JSON responses.

Gating (triple, all must be true for the searcher to register):
  1. APAPER_MCP_ENABLED=1 (opt-in; default off to avoid surprising npx downloads)
  2. `npx` resolvable on PATH
  3. CNKI institutional IP — can't be checked at boot; if the first search
     returns an auth error, the tool self-reports and we return [] gracefully.

Search is async (MCP stdio is async). The paper_search_mcp server wraps it
via async_search; the top-level FastAPI layer calls it directly in tests.
"""
import asyncio
import json
import logging
import os
import shutil
from typing import List, Optional

from ..paper import Paper
from ..mcp_stdio_client import MCPStdioClient
from .base import PaperSource

logger = logging.getLogger(__name__)

APAPER_MCP_COMMAND = ["npx", "-y", "@ai4paper/apaper-mcp"]


class CnkiSearcher(PaperSource):
    """CNKI searcher backed by the apaper-mcp MCP stdio server."""

    @staticmethod
    def is_enabled() -> bool:
        """Triple gate: env flag on + npx on PATH."""
        if os.getenv("APAPER_MCP_ENABLED", "0").strip().lower() not in ("1", "true"):
            return False
        if shutil.which("npx") is None:
            logger.warning("APAPER_MCP_ENABLED=1 but npx not found on PATH; CNKI disabled")
            return False
        return True

    async def _run_with_client(self, name: str, arguments: dict):
        """Spawn a fresh apaper-mcp subprocess, call one tool, tear it down.

        The MCP SDK's stdio_client uses anyio cancel scopes, which are
        task-bound. The sync `search()` wrapper uses asyncio.run(), so
        each call gets a brand-new event loop — a long-lived client would
        be bound to a dead loop and anyio would raise 'Attempted to exit
        cancel scope in a different task' during loop.shutdown_asyncgens().
        Per-call lifecycle keeps enter/exit in the same task.
        """
        client = MCPStdioClient(command=APAPER_MCP_COMMAND)
        try:
            if not await client.start():
                return None
            return await client.call_tool(name, arguments)
        finally:
            await client.stop()

    async def async_search(self, query: str, max_results: int = 10) -> List[Paper]:
        """Async search via MCP. Returns [] on any failure."""
        result = await self._run_with_client(
            "search_cnki_papers",
            {"query": query, "page_size": max_results},
        )
        if result is None:
            return []
        return self._parse_result(result)

    def search(self, query: str, max_results: int = 10, **kwargs) -> List[Paper]:
        """Sync wrapper for the PaperSource interface. Runs the async search."""
        return asyncio.run(self.async_search(query, max_results))

    def _parse_result(self, result) -> List[Paper]:
        """Parse apaper-mcp's call_tool result into Paper objects."""
        # result.content is a list of TextContent; concatenate text fields.
        text_parts = []
        for block in getattr(result, "content", []) or []:
            t = getattr(block, "text", None)
            if t:
                text_parts.append(t)
        if not text_parts:
            return []
        try:
            payload = json.loads("".join(text_parts))
        except json.JSONDecodeError as exc:
            logger.warning(f"CNKI: failed to parse MCP response JSON: {exc}")
            return []

        raw_papers = payload.get("papers") or payload.get("results") or []
        if isinstance(raw_papers, dict):
            raw_papers = raw_papers.get("papers", [])

        papers: List[Paper] = []
        for entry in raw_papers:
            paper = self._parse_entry(entry)
            if paper is not None:
                papers.append(paper)
        return papers

    def _parse_entry(self, entry: dict) -> Optional[Paper]:
        title = (entry.get("title") or "").strip()
        if not title:
            return None

        # CNKI uses href as the identifier for download; store in extra.
        href = (entry.get("href") or "").strip()
        paper_id = href or title  # fallback to title-based id

        raw_authors = entry.get("authors")
        authors: List[str] = []
        if isinstance(raw_authors, list):
            authors = [str(a).strip() for a in raw_authors if str(a).strip()]
        elif isinstance(raw_authors, str):
            authors = [a.strip() for a in raw_authors.replace(";", ",").split(",") if a.strip()]

        abstract = (entry.get("abstract") or "").strip()
        doi = (entry.get("doi") or "").strip()
        year = entry.get("year")
        published = str(year) if year else ""

        return Paper(
            paper_id=paper_id,
            title=title,
            authors=authors,
            abstract=abstract,
            doi=doi,
            published_date=published,  # type: ignore[arg-type]
            pdf_url="",  # CNKI PDF fetched via download_pdf(href)
            url=f"https://kns.cnki.net{href}" if href else "",
            source="cnki",
            extra={"cnki_href": href} if href else {},
        )

    def download_pdf(self, paper_id: str, save_path: str) -> str:
        """Download via apaper-mcp's download_cnki_paper tool.

        paper_id here is the CNKI href (stored in extra['cnki_href']).
        """
        if not asyncio.get_event_loop().is_running():
            return asyncio.run(self.async_download(paper_id, save_path))
        # If we're already in an event loop (paper_search_mcp server context),
        # the caller must use async_download instead.
        raise RuntimeError(
            "CnkiSearcher.download_pdf called from within a running event loop; "
            "use async_download instead."
        )

    async def async_download(self, href: str, save_path: str) -> str:
        """Async download via MCP. Returns saved file path or empty string on failure."""
        result = await self._run_with_client(
            "download_cnki_paper",
            {"href": href, "save_path": save_path},
        )
        if result is None:
            return ""
        # apaper-mcp returns the saved path in a TextContent block.
        for block in getattr(result, "content", []) or []:
            t = getattr(block, "text", None)
            if t:
                try:
                    payload = json.loads(t)
                    saved = payload.get("save_path") or payload.get("path") or ""
                    if saved:
                        return saved
                except json.JSONDecodeError:
                    # Maybe the text itself is the path.
                    if "/" in t or t.endswith(".pdf"):
                        return t.strip()
        return ""
