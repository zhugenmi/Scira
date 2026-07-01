"""Tests for MCPStdioClient and CnkiSearcher.

MCP session is mocked — no real subprocess spawned. Real smoke tests
gated behind APAPER_MCP_ENABLED=1.
"""
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


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
