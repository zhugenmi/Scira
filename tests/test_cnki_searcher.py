"""Tests for MCPStdioClient and CnkiSearcher.

MCP session is mocked — no real subprocess spawned. Real smoke tests
gated behind APAPER_MCP_ENABLED=1.
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

# Make paper_search_mcp discoverable as a top-level package
_MCP_DIR = Path(__file__).resolve().parents[1] / "src" / "mcp"
if str(_MCP_DIR) not in sys.path:
    sys.path.insert(0, str(_MCP_DIR))


@pytest.mark.asyncio
async def test_mcp_stdio_client_start_stop_lifecycle():
    """MCPStdioClient.start() spawns subprocess, stop() terminates it cleanly."""
    from src.mcp.paper_search_mcp.mcp_stdio_client import MCPStdioClient

    client = MCPStdioClient(command=["echo", "dummy"])
    with patch("src.mcp.paper_search_mcp.mcp_stdio_client.stdio_client") as mock_stdio, \
         patch("src.mcp.paper_search_mcp.mcp_stdio_client.ClientSession") as mock_session_cls:
        # stdio_client is an async context manager yielding (read, write)
        mock_read = AsyncMock()
        mock_write = AsyncMock()
        mock_stdio.return_value.__aenter__.return_value = (mock_read, mock_write)
        mock_stdio.return_value.__aexit__.return_value = None

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session_cls.return_value = mock_session

        await client.start()
        assert client.is_running is True
        await client.stop()
        assert client.is_running is False


@pytest.mark.asyncio
async def test_mcp_stdio_client_call_tool_returns_result():
    """call_tool should invoke the MCP session and return parsed content."""
    from src.mcp.paper_search_mcp.mcp_stdio_client import MCPStdioClient

    client = MCPStdioClient(command=["echo", "dummy"])
    with patch("src.mcp.paper_search_mcp.mcp_stdio_client.stdio_client") as mock_stdio, \
         patch("src.mcp.paper_search_mcp.mcp_stdio_client.ClientSession") as mock_session_cls:
        mock_stdio.return_value.__aenter__.return_value = (AsyncMock(), AsyncMock())
        mock_stdio.return_value.__aexit__.return_value = None

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        # call_tool returns a result with .content list of TextContent
        fake_text = MagicMock()
        fake_text.text = '{"papers": []}'
        fake_result = MagicMock()
        fake_result.content = [fake_text]
        mock_session.call_tool = AsyncMock(return_value=fake_result)
        mock_session_cls.return_value = mock_session

        await client.start()
        result = await client.call_tool("search_cnki_papers", {"query": "test"})
        assert result is not None
        await client.stop()


@pytest.mark.asyncio
async def test_mcp_stdio_client_start_failure_does_not_crash():
    """If subprocess spawn fails, start() returns False, is_running stays False."""
    from src.mcp.paper_search_mcp.mcp_stdio_client import MCPStdioClient

    client = MCPStdioClient(command=["nonexistent-binary-xyz"])
    with patch("src.mcp.paper_search_mcp.mcp_stdio_client.stdio_client") as mock_stdio:
        mock_stdio.side_effect = FileNotFoundError("no such binary")
        ok = await client.start()
    assert ok is False
    assert client.is_running is False


# ---------------------------------------------------------------------------
# CnkiSearcher tests
# ---------------------------------------------------------------------------

import json


def _fake_mcp_text_result(payload: dict):
    """Build a fake MCP call_tool result with a single TextContent block."""
    fake_text = MagicMock()
    fake_text.text = json.dumps(payload)
    fake_result = MagicMock()
    fake_result.content = [fake_text]
    return fake_result


@pytest.mark.asyncio
async def test_cnki_searcher_search_tears_down_client_per_call():
    """Each async_search call must start AND stop its own MCP client.

    Regression: previously async_search reused a long-lived self._client
    across calls, but the sync wrapper uses asyncio.run() which destroys
    the event loop each call. The MCP SDK's stdio_client uses anyio
    cancel scopes (task-bound), so leaving the session open across the
    asyncio.run boundary raised:
        RuntimeError: Attempted to exit cancel scope in a different task
        than it was entered in
    during loop.shutdown_asyncgens(). Fix: per-call lifecycle.
    """
    from src.mcp.paper_search_mcp.academic_platforms import cnki as cnki_mod

    fake_client = AsyncMock()
    fake_client.is_running = False  # so _ensure_client path starts it
    fake_client.start = AsyncMock(return_value=True)
    fake_client.call_tool = AsyncMock(return_value=_fake_mcp_text_result({"papers": []}))

    with patch.object(cnki_mod, "MCPStdioClient", return_value=fake_client):
        searcher = cnki_mod.CnkiSearcher()
        await searcher.async_search("anything", max_results=5)

    fake_client.start.assert_awaited_once()
    fake_client.call_tool.assert_awaited_once()
    fake_client.stop.assert_awaited_once()
    # No leftover client state on the searcher instance.
    assert not hasattr(searcher, "_client") or searcher._client is None


@pytest.mark.asyncio
async def test_cnki_searcher_search_tears_down_client_on_error():
    """If call_tool fails (returns None per MCPStdioClient contract), the
    per-call client is still stopped."""
    from src.mcp.paper_search_mcp.academic_platforms import cnki as cnki_mod

    fake_client = AsyncMock()
    fake_client.is_running = False
    fake_client.start = AsyncMock(return_value=True)
    fake_client.call_tool = AsyncMock(return_value=None)  # failure, no raise
    fake_client.stop = AsyncMock()

    with patch.object(cnki_mod, "MCPStdioClient", return_value=fake_client):
        searcher = cnki_mod.CnkiSearcher()
        papers = await searcher.async_search("anything", max_results=5)

    assert papers == []
    fake_client.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_cnki_searcher_search_parses_papers():
    """CnkiSearcher.search calls search_cnki_papers via MCP and parses results."""
    from src.mcp.paper_search_mcp.academic_platforms import cnki as cnki_mod

    fake_client = AsyncMock()
    fake_client.is_running = False
    fake_client.start = AsyncMock(return_value=True)
    fake_client.call_tool = AsyncMock(return_value=_fake_mcp_text_result({
        "papers": [
            {
                "title": "深度学习医学影像综述",
                "authors": "张三;李四",
                "year": "2024",
                "href": "/detail/123",
                "abstract": "综述深度学习在医学影像中的应用",
                "doi": "10.1/cnki.123",
            }
        ],
        "total": 1,
    }))
    fake_client.stop = AsyncMock()

    with patch.object(cnki_mod, "MCPStdioClient", return_value=fake_client):
        searcher = cnki_mod.CnkiSearcher()
        papers = await searcher.async_search("深度学习 医学", max_results=5)

    assert len(papers) == 1
    p = papers[0]
    assert p.title == "深度学习医学影像综述"
    assert p.authors == ["张三", "李四"]
    assert p.source == "cnki"
    assert p.pdf_url == ""  # href stored in extra, not pdf_url
    assert p.extra.get("cnki_href") == "/detail/123"
    fake_client.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_cnki_searcher_search_client_down_returns_empty():
    """If the MCP client won't start, search returns []."""
    from src.mcp.paper_search_mcp.academic_platforms import cnki as cnki_mod

    fake_client = AsyncMock()
    fake_client.is_running = False
    fake_client.start = AsyncMock(return_value=False)
    fake_client.stop = AsyncMock()

    with patch.object(cnki_mod, "MCPStdioClient", return_value=fake_client):
        searcher = cnki_mod.CnkiSearcher()
        papers = await searcher.async_search("anything", max_results=5)
    assert papers == []
    fake_client.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_cnki_searcher_search_tool_returns_none_returns_empty():
    """If call_tool returns None (session died), search returns []."""
    from src.mcp.paper_search_mcp.academic_platforms import cnki as cnki_mod

    fake_client = AsyncMock()
    fake_client.is_running = False
    fake_client.start = AsyncMock(return_value=True)
    fake_client.call_tool = AsyncMock(return_value=None)
    fake_client.stop = AsyncMock()

    with patch.object(cnki_mod, "MCPStdioClient", return_value=fake_client):
        searcher = cnki_mod.CnkiSearcher()
        papers = await searcher.async_search("anything", max_results=5)
    assert papers == []
    fake_client.stop.assert_awaited_once()


def test_cnki_searcher_not_enabled_when_env_unset():
    """CnkiSearcher.is_enabled() should be False when APAPER_MCP_ENABLED is unset/0."""
    from src.mcp.paper_search_mcp.academic_platforms.cnki import CnkiSearcher
    with patch.dict("os.environ", {"APAPER_MCP_ENABLED": "0"}, clear=False):
        assert CnkiSearcher.is_enabled() is False
    with patch.dict("os.environ", {}, clear=True):
        assert CnkiSearcher.is_enabled() is False


def test_cnki_searcher_not_enabled_without_node():
    """is_enabled() False when flag is on but npx missing from PATH."""
    from src.mcp.paper_search_mcp.academic_platforms.cnki import CnkiSearcher
    with patch.dict("os.environ", {"APAPER_MCP_ENABLED": "1"}, clear=False), \
         patch("shutil.which", return_value=None):
        assert CnkiSearcher.is_enabled() is False


def test_cnki_searcher_enabled_when_flag_and_npx_present():
    from src.mcp.paper_search_mcp.academic_platforms.cnki import CnkiSearcher
    with patch.dict("os.environ", {"APAPER_MCP_ENABLED": "1"}, clear=False), \
         patch("shutil.which", return_value="/usr/bin/npx"):
        assert CnkiSearcher.is_enabled() is True
