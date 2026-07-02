"""Thin async wrapper around the MCP stdio client SDK.

Spawns a long-lived MCP subprocess (e.g. npx @ai4paper/apaper-mcp) and
exposes call_tool() over the stdio transport. Used by CnkiSearcher to
talk to apaper-mcp without re-implementing JSON-RPC framing.

Lifecycle: start() opens the session; call_tool() reuses it; stop()
closes. If start() fails (binary missing, subprocess crash), call_tool()
returns None — callers treat that as "source unavailable".
"""
import asyncio
import logging
from typing import Any, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class MCPStdioClient:
    """Manages a long-lived MCP stdio subprocess."""

    def __init__(self, command: List[str], env: Optional[dict] = None):
        self._command = command
        self._env = env
        self._session: Optional[ClientSession] = None
        self._stdio_cm = None
        self._session_cm = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    async def start(self) -> bool:
        """Spawn the subprocess and initialize the MCP session.

        Returns:
            True on success, False on failure (logged + suppressed).
        """
        try:
            params = StdioServerParameters(
                command=self._command[0],
                args=self._command[1:],
                env=self._env,
            )
            self._stdio_cm = stdio_client(params)
            read, write = await self._stdio_cm.__aenter__()

            self._session_cm = ClientSession(read, write)
            self._session = await self._session_cm.__aenter__()
            await self._session.initialize()
            self._is_running = True
            logger.info(f"MCP stdio client started: {' '.join(self._command)}")
            return True
        except Exception as exc:
            logger.warning(f"MCP stdio client failed to start: {exc}")
            await self._cleanup()
            return False

    async def call_tool(self, name: str, arguments: dict) -> Any:
        """Call an MCP tool. Returns the raw result, or None if session is down."""
        if not self._is_running or self._session is None:
            logger.warning(f"MCP session not running; cannot call tool '{name}'")
            return None
        try:
            return await self._session.call_tool(name, arguments)
        except Exception as exc:
            logger.warning(f"MCP call_tool '{name}' failed: {exc}")
            # Mark session dead so next call won't try a broken session.
            self._is_running = False
            return None

    async def stop(self) -> None:
        """Tear down the session + subprocess."""
        await self._cleanup()

    async def _cleanup(self) -> None:
        self._is_running = False
        if self._session_cm is not None:
            try:
                await self._session_cm.__aexit__(None, None, None)
            except Exception:
                pass
            self._session_cm = None
        if self._stdio_cm is not None:
            try:
                await self._stdio_cm.__aexit__(None, None, None)
            except Exception:
                pass
            self._stdio_cm = None
        self._session = None
