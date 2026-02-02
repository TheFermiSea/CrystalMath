"""JSON-RPC 2.0 server over Unix domain sockets.

This module provides the Python-side of the IPC boundary that replaces PyO3
embedded Python. The server uses asyncio for non-blocking I/O and delegates
to CrystalController.dispatch() for most requests.

Usage:
    # Start server from CLI
    crystalmath-server --foreground

    # Or programmatically
    from crystalmath.server import JsonRpcServer
    server = JsonRpcServer()
    await server.serve_forever()

Protocol:
    - Transport: Unix domain socket
    - Framing: HTTP-style Content-Length headers (same as LSP)
    - Protocol: JSON-RPC 2.0

Wire format:
    Content-Length: 47\\r\\n
    \\r\\n
    {"jsonrpc":"2.0","method":"system.ping","id":1}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .handlers import HANDLER_REGISTRY

__all__ = ["JsonRpcServer", "main", "get_default_socket_path"]

# JSON-RPC 2.0 error codes
JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

# Maximum message size (100MB, matching lsp.rs)
MAX_MESSAGE_SIZE = 100 * 1024 * 1024

# Configure logging
logger = logging.getLogger("crystalmath.server")


def get_default_socket_path() -> Path:
    """Get the default socket path.

    Priority:
    1. $XDG_RUNTIME_DIR/crystalmath.sock (Linux)
    2. ~/Library/Caches/crystalmath.sock (macOS)
    3. /tmp/crystalmath-{uid}.sock (fallback)
    """
    # Check XDG_RUNTIME_DIR first (Linux)
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR")
    if xdg_runtime:
        return Path(xdg_runtime) / "crystalmath.sock"

    # macOS cache directory
    if sys.platform == "darwin":
        cache_dir = Path.home() / "Library" / "Caches"
        if cache_dir.exists():
            return cache_dir / "crystalmath.sock"

    # Fallback to /tmp with uid for security
    uid = os.getuid()
    return Path(f"/tmp/crystalmath-{uid}.sock")


def _jsonrpc_error(
    code: int,
    message: str,
    request_id: int | str | None = None,
    data: Any = None,
) -> str:
    """Create a JSON-RPC 2.0 error response."""
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return json.dumps({"jsonrpc": "2.0", "error": error, "id": request_id})


def _jsonrpc_result(result: Any, request_id: int | str | None) -> str:
    """Create a JSON-RPC 2.0 success response."""
    return json.dumps({"jsonrpc": "2.0", "result": result, "id": request_id})


class JsonRpcServer:
    """JSON-RPC 2.0 server over Unix domain socket.

    Uses Content-Length framing (same as LSP protocol) for message boundaries.
    Delegates to CrystalController.dispatch() for most requests, with special
    handling for system.* namespace methods.

    Attributes:
        socket_path: Path to the Unix domain socket.
        inactivity_timeout: Seconds of inactivity before shutdown (0 = disabled).
        controller: CrystalController instance for dispatch.
    """

    def __init__(
        self,
        socket_path: Path | None = None,
        inactivity_timeout: int = 300,
        controller: Any | None = None,
    ) -> None:
        """Initialize the server.

        Args:
            socket_path: Unix socket path. If None, uses get_default_socket_path().
            inactivity_timeout: Seconds to wait before auto-shutdown (0 = disabled).
            controller: CrystalController instance. If None, creates one on first request.
        """
        self.socket_path = socket_path or get_default_socket_path()
        self.inactivity_timeout = inactivity_timeout
        self._controller = controller
        self._server: asyncio.Server | None = None
        self._shutdown_event = asyncio.Event()
        self._last_activity = datetime.now(timezone.utc)
        self._active_connections = 0

    @property
    def controller(self) -> Any:
        """Lazy-load CrystalController on first access."""
        if self._controller is None:
            try:
                from crystalmath.api import CrystalController

                self._controller = CrystalController()
                logger.info("CrystalController initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize CrystalController: {e}")
                # Return None - handlers will need to handle this
                return None
        return self._controller

    async def _read_content_length(
        self,
        reader: asyncio.StreamReader,
    ) -> int | None:
        """Read HTTP-style headers and return Content-Length.

        Returns:
            Content-Length value, or None if client disconnected.

        Raises:
            ValueError: If Content-Length is missing or invalid.
        """
        content_length: int | None = None

        while True:
            try:
                line = await reader.readline()
            except asyncio.IncompleteReadError:
                return None

            if not line:
                # EOF - client disconnected
                return None

            decoded = line.decode("utf-8", errors="replace").strip()

            if not decoded:
                # Empty line signals end of headers
                break

            # Parse Content-Length header (case-insensitive)
            if ":" in decoded:
                key, _, value = decoded.partition(":")
                if key.strip().lower() == "content-length":
                    try:
                        content_length = int(value.strip())
                    except ValueError:
                        raise ValueError(f"Invalid Content-Length: {value}")

        if content_length is None:
            raise ValueError("Missing Content-Length header")

        if content_length <= 0:
            raise ValueError(f"Invalid Content-Length: {content_length}")

        if content_length > MAX_MESSAGE_SIZE:
            raise ValueError(
                f"Message too large: {content_length} bytes (max {MAX_MESSAGE_SIZE})"
            )

        return content_length

    async def _dispatch(self, request_json: str) -> str:
        """Dispatch a JSON-RPC request to the appropriate handler.

        For system.* methods, uses HANDLER_REGISTRY directly.
        For other methods, delegates to CrystalController.dispatch().

        Args:
            request_json: JSON-RPC 2.0 request string.

        Returns:
            JSON-RPC 2.0 response string.
        """
        request_id: int | str | None = None

        try:
            # Parse request
            try:
                request = json.loads(request_json)
            except json.JSONDecodeError as e:
                return _jsonrpc_error(JSONRPC_PARSE_ERROR, f"Parse error: {e}")

            request_id = request.get("id")

            # Validate JSON-RPC version
            if request.get("jsonrpc") != "2.0":
                return _jsonrpc_error(
                    JSONRPC_INVALID_REQUEST,
                    "Invalid Request: missing or invalid 'jsonrpc' field",
                    request_id=request_id,
                )

            # Extract method
            method_name = request.get("method")
            if not method_name or not isinstance(method_name, str):
                return _jsonrpc_error(
                    JSONRPC_INVALID_REQUEST,
                    "Invalid Request: missing or invalid 'method' field",
                    request_id=request_id,
                )

            params = request.get("params", {})
            if not isinstance(params, dict):
                params = {}

            # Check for system.* handlers first
            if method_name in HANDLER_REGISTRY:
                handler = HANDLER_REGISTRY[method_name]
                result = await handler(self.controller, params)
                return _jsonrpc_result(result, request_id)

            # Delegate to CrystalController.dispatch() for other methods
            if self.controller is not None:
                # CrystalController.dispatch() is synchronous, run in executor
                loop = asyncio.get_event_loop()
                response_json = await loop.run_in_executor(
                    None,
                    self.controller.dispatch,
                    request_json,
                )
                return response_json

            # No controller available
            return _jsonrpc_error(
                JSONRPC_METHOD_NOT_FOUND,
                f"Method not found: {method_name}",
                request_id=request_id,
            )

        except Exception as e:
            logger.exception(f"Dispatch error: {e}")
            return _jsonrpc_error(
                JSONRPC_INTERNAL_ERROR,
                f"Internal error: {e}",
                request_id=request_id,
            )

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single client connection.

        Reads JSON-RPC requests, dispatches them, and writes responses.
        Continues until client disconnects or server shuts down.
        """
        peer = writer.get_extra_info("peername") or "unknown"
        logger.debug(f"Client connected: {peer}")
        self._active_connections += 1

        try:
            while not self._shutdown_event.is_set():
                # Update activity timestamp
                self._last_activity = datetime.now(timezone.utc)

                # Read Content-Length header
                try:
                    content_length = await asyncio.wait_for(
                        self._read_content_length(reader),
                        timeout=60.0,  # 60s timeout for header read
                    )
                except asyncio.TimeoutError:
                    # Keep connection alive, just no data yet
                    continue
                except ValueError as e:
                    logger.warning(f"Header error: {e}")
                    # Send error response
                    error_response = _jsonrpc_error(
                        JSONRPC_PARSE_ERROR,
                        str(e),
                    )
                    await self._write_response(writer, error_response)
                    continue

                if content_length is None:
                    # Client disconnected
                    break

                # Read message body
                try:
                    body = await reader.readexactly(content_length)
                    request_json = body.decode("utf-8")
                except asyncio.IncompleteReadError:
                    logger.debug("Client disconnected mid-message")
                    break
                except UnicodeDecodeError as e:
                    logger.warning(f"Invalid UTF-8: {e}")
                    error_response = _jsonrpc_error(
                        JSONRPC_PARSE_ERROR,
                        f"Invalid UTF-8: {e}",
                    )
                    await self._write_response(writer, error_response)
                    continue

                # Dispatch and respond
                logger.debug(f"Request: {request_json[:200]}...")
                response_json = await self._dispatch(request_json)
                logger.debug(f"Response: {response_json[:200]}...")

                await self._write_response(writer, response_json)

                # Check for shutdown request
                try:
                    response = json.loads(response_json)
                    result = response.get("result", {})
                    if isinstance(result, dict) and result.get("action") == "shutdown":
                        logger.info("Shutdown requested via RPC")
                        self._shutdown_event.set()
                except json.JSONDecodeError:
                    pass

        except ConnectionResetError:
            logger.debug(f"Client {peer} reset connection")
        except Exception as e:
            logger.exception(f"Client handler error: {e}")
        finally:
            self._active_connections -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            logger.debug(f"Client disconnected: {peer}")

    async def _write_response(
        self,
        writer: asyncio.StreamWriter,
        response_json: str,
    ) -> None:
        """Write a JSON-RPC response with Content-Length framing."""
        response_bytes = response_json.encode("utf-8")
        header = f"Content-Length: {len(response_bytes)}\r\n\r\n"
        writer.write(header.encode("utf-8"))
        writer.write(response_bytes)
        await writer.drain()

    async def _inactivity_monitor(self) -> None:
        """Monitor for inactivity and trigger shutdown if timeout exceeded."""
        if self.inactivity_timeout <= 0:
            return

        while not self._shutdown_event.is_set():
            await asyncio.sleep(30)  # Check every 30 seconds

            if self._active_connections > 0:
                continue

            elapsed = (
                datetime.now(timezone.utc) - self._last_activity
            ).total_seconds()
            if elapsed >= self.inactivity_timeout:
                logger.info(
                    f"Inactivity timeout ({self.inactivity_timeout}s) - shutting down"
                )
                self._shutdown_event.set()
                break

    def _cleanup_stale_socket(self) -> None:
        """Remove stale socket file if present.

        Tries to connect first - if connection succeeds, another server is running.
        If connection fails (refused), the socket is stale and can be removed.
        """
        if not self.socket_path.exists():
            return

        import socket

        try:
            # Try to connect - if it works, server is running
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(str(self.socket_path))
            sock.close()
            raise RuntimeError(
                f"Server already running at {self.socket_path}"
            )
        except socket.error:
            # Connection failed - stale socket, safe to remove
            logger.info(f"Removing stale socket: {self.socket_path}")
            self.socket_path.unlink()

    async def serve_forever(self) -> None:
        """Start the server and run until shutdown.

        Creates the Unix socket, starts accepting connections, and runs
        until SIGTERM/SIGINT or inactivity timeout.
        """
        # Clean up stale socket
        self._cleanup_stale_socket()

        # Ensure parent directory exists
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)

        # Start server
        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=str(self.socket_path),
        )

        # Set socket permissions (owner only)
        os.chmod(self.socket_path, 0o600)

        logger.info(f"Listening on {self.socket_path}")

        # Start inactivity monitor
        inactivity_task = asyncio.create_task(self._inactivity_monitor())

        try:
            async with self._server:
                # Wait for shutdown event
                await self._shutdown_event.wait()
        finally:
            logger.info("Server shutting down...")
            inactivity_task.cancel()
            try:
                await inactivity_task
            except asyncio.CancelledError:
                pass

            # Clean up socket file
            if self.socket_path.exists():
                self.socket_path.unlink()
                logger.debug(f"Removed socket: {self.socket_path}")

    def shutdown(self) -> None:
        """Request graceful shutdown."""
        self._shutdown_event.set()


def _setup_logging(verbose: bool = False) -> None:
    """Configure logging to stderr with timestamp."""
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logging.getLogger("crystalmath").setLevel(level)
    logging.getLogger("crystalmath").addHandler(handler)


def main() -> int:
    """CLI entry point for crystalmath-server."""
    parser = argparse.ArgumentParser(
        prog="crystalmath-server",
        description="JSON-RPC 2.0 server for CrystalMath (IPC bridge for Rust TUI)",
    )
    parser.add_argument(
        "--socket",
        type=Path,
        default=None,
        help=f"Unix socket path (default: {get_default_socket_path()})",
    )
    parser.add_argument(
        "--foreground",
        action="store_true",
        default=True,
        help="Run in foreground (default)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        metavar="SECONDS",
        help="Inactivity timeout in seconds (default: 300, 0 to disable)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    _setup_logging(args.verbose)

    # Create server
    server = JsonRpcServer(
        socket_path=args.socket,
        inactivity_timeout=args.timeout,
    )

    # Set up signal handlers
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def handle_signal(signum: int, frame: Any) -> None:
        signame = signal.Signals(signum).name
        logger.info(f"Received {signame}, shutting down...")
        server.shutdown()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Run server
    try:
        loop.run_until_complete(server.serve_forever())
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted")
        return 130  # Standard exit code for SIGINT
    except Exception as e:
        logger.error(f"Server error: {e}")
        return 1
    finally:
        loop.close()


if __name__ == "__main__":
    sys.exit(main())
