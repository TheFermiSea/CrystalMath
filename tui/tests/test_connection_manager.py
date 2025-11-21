"""
Tests for the Connection Manager.

Tests connection pooling, authentication, health monitoring, and error handling.
"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import time

from src.core.connection_manager import (
    ConnectionManager,
    ConnectionConfig,
    PooledConnection,
)


@pytest.fixture
def connection_manager():
    """Create a connection manager for testing."""
    return ConnectionManager(pool_size=3)


@pytest.fixture
def started_manager():
    """Create a connection manager for testing."""
    return ConnectionManager(pool_size=3)


def mock_ssh_connection():
    """Create a mock SSH connection."""
    conn = MagicMock()

    # Make run() return an awaitable
    async def mock_run(*args, **kwargs):
        result = AsyncMock()
        result.exit_status = 0
        result.stdout = "test output"
        return result

    conn.run = mock_run
    conn.close = MagicMock()

    async def mock_wait_closed():
        pass

    conn.wait_closed = mock_wait_closed
    return conn


class TestConnectionConfig:
    """Test ConnectionConfig dataclass."""

    def test_config_defaults(self):
        """Test default configuration values."""
        config = ConnectionConfig(host="test.example.com")
        assert config.host == "test.example.com"
        assert config.port == 22
        assert config.username is None
        assert config.key_file is None
        assert config.use_agent is True
        assert config.timeout == 30
        assert config.keepalive_interval == 60

    def test_config_custom_values(self):
        """Test custom configuration values."""
        config = ConnectionConfig(
            host="custom.example.com",
            port=2222,
            username="testuser",
            key_file=Path("/path/to/key"),
            use_agent=False,
        )
        assert config.host == "custom.example.com"
        assert config.port == 2222
        assert config.username == "testuser"
        assert config.key_file == Path("/path/to/key")
        assert config.use_agent is False


class TestPooledConnection:
    """Test PooledConnection dataclass."""

    def test_mark_used(self):
        """Test marking connection as used."""
        mock_conn = mock_ssh_connection()
        pooled = PooledConnection(connection=mock_conn, cluster_id=1)
        initial_time = pooled.last_used

        time.sleep(0.01)
        pooled.mark_used()

        assert pooled.in_use is True
        assert pooled.last_used > initial_time

    def test_mark_available(self):
        """Test marking connection as available."""
        mock_conn = mock_ssh_connection()
        pooled = PooledConnection(connection=mock_conn, cluster_id=1)
        pooled.mark_used()

        pooled.mark_available()

        assert pooled.in_use is False

    def test_is_stale(self):
        """Test stale connection detection."""
        mock_conn = mock_ssh_connection()
        pooled = PooledConnection(connection=mock_conn, cluster_id=1)
        pooled.created_at = time.time() - 3700  # Over 1 hour old

        assert pooled.is_stale(max_age=3600) is True
        assert pooled.is_stale(max_age=4000) is False

    def test_is_idle_too_long(self):
        """Test idle timeout detection."""
        mock_conn = mock_ssh_connection()
        pooled = PooledConnection(connection=mock_conn, cluster_id=1)
        pooled.last_used = time.time() - 350  # Idle for 350 seconds

        assert pooled.is_idle_too_long(max_idle=300) is True
        assert pooled.is_idle_too_long(max_idle=400) is False


class TestConnectionManager:
    """Test ConnectionManager class."""

    def test_init(self):
        """Test connection manager initialization."""
        manager = ConnectionManager(pool_size=5)
        assert manager.pool_size == 5
        assert manager._pools == {}
        assert manager._configs == {}
        assert manager._health_check_task is None

    @pytest.mark.asyncio
    async def test_start_stop(self, connection_manager):
        """Test starting and stopping the connection manager."""
        await connection_manager.start()
        assert connection_manager._health_check_task is not None

        await connection_manager.stop()
        assert connection_manager._health_check_task.cancelled()

    def test_register_cluster(self, connection_manager):
        """Test registering a cluster configuration."""
        connection_manager.register_cluster(
            cluster_id=1,
            host="test.example.com",
            port=2222,
            username="testuser",
            key_file=Path("/path/to/key"),
            use_agent=False,
        )

        config = connection_manager._configs[1]
        assert config.host == "test.example.com"
        assert config.port == 2222
        assert config.username == "testuser"
        assert config.key_file == Path("/path/to/key")
        assert config.use_agent is False

    @patch("src.core.connection_manager.keyring")
    def test_set_password(self, mock_keyring, connection_manager):
        """Test storing password in keyring."""
        connection_manager.set_password(1, "secret123")

        mock_keyring.set_password.assert_called_once_with(
            "crystal-tui", "cluster_1", "secret123"
        )

    @patch("src.core.connection_manager.keyring")
    def test_get_password(self, mock_keyring, connection_manager):
        """Test retrieving password from keyring."""
        mock_keyring.get_password.return_value = "secret123"

        password = connection_manager.get_password(1)

        assert password == "secret123"
        mock_keyring.get_password.assert_called_once_with("crystal-tui", "cluster_1")

    @patch("src.core.connection_manager.keyring")
    def test_delete_password(self, mock_keyring, connection_manager):
        """Test deleting password from keyring."""
        connection_manager.delete_password(1)

        mock_keyring.delete_password.assert_called_once_with("crystal-tui", "cluster_1")

    @pytest.mark.asyncio
    @patch("src.core.connection_manager.asyncssh.connect")
    async def test_connect_with_key(self, mock_connect, connection_manager):
        """Test connecting with SSH key authentication."""
        mock_conn = mock_ssh_connection()

        # Make mock_connect return a coroutine
        async def mock_connect_coro(*args, **kwargs):
            return mock_conn

        mock_connect.side_effect = mock_connect_coro
        connection_manager.register_cluster(
            1, "test.example.com", key_file=Path("/path/to/key")
        )

        conn = await connection_manager.connect(1)

        assert conn == mock_conn
        mock_connect.assert_called_once()
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["host"] == "test.example.com"
        assert call_kwargs["client_keys"] == ["/path/to/key"]

    @pytest.mark.asyncio
    @patch("src.core.connection_manager.asyncssh.connect")
    @patch("src.core.connection_manager.keyring")
    async def test_connect_with_password(
        self, mock_keyring, mock_connect, connection_manager
    ):
        """Test connecting with password authentication."""
        mock_conn = mock_ssh_connection()

        # Make mock_connect return a coroutine
        async def mock_connect_coro(*args, **kwargs):
            return mock_conn

        mock_connect.side_effect = mock_connect_coro
        mock_keyring.get_password.return_value = "secret123"
        connection_manager.register_cluster(1, "test.example.com")

        conn = await connection_manager.connect(1)

        assert conn == mock_conn
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["password"] == "secret123"

    @pytest.mark.asyncio
    async def test_connect_unregistered_cluster(self, connection_manager):
        """Test connecting to an unregistered cluster raises error."""
        with pytest.raises(ValueError, match="Cluster 99 not registered"):
            await connection_manager.connect(99)

    @pytest.mark.asyncio
    @patch("src.core.connection_manager.asyncssh.connect")
    async def test_connect_timeout(self, mock_connect, connection_manager):
        """Test connection timeout handling."""
        mock_connect.side_effect = asyncio.TimeoutError()
        connection_manager.register_cluster(1, "test.example.com")

        with pytest.raises(asyncio.TimeoutError):
            await connection_manager.connect(1)

    @pytest.mark.asyncio
    @patch("src.core.connection_manager.asyncssh.connect")
    async def test_get_connection_reuse(self, mock_connect, started_manager):
        """Test connection reuse from pool."""
        await started_manager.start()
        try:
            mock_conn = mock_ssh_connection()

            # Make mock_connect return a coroutine
            async def mock_connect_coro(*args, **kwargs):
                return mock_conn

            mock_connect.side_effect = mock_connect_coro

            started_manager.register_cluster(1, "test.example.com")

            # First connection creates new
            async with started_manager.get_connection(1) as conn1:
                assert conn1 == mock_conn

            assert mock_connect.call_count == 1

            # Second connection reuses from pool
            async with started_manager.get_connection(1) as conn2:
                assert conn2 == mock_conn

            # Should still only have one connection created
            assert mock_connect.call_count == 1
        finally:
            await started_manager.stop()

    @pytest.mark.asyncio
    @patch("src.core.connection_manager.asyncssh.connect")
    async def test_get_connection_pool_limit(self, mock_connect, started_manager):
        """Test connection pool size limit."""
        await started_manager.start()
        try:
            mock_conn = mock_ssh_connection()

            # Make mock_connect return a coroutine
            async def mock_connect_coro(*args, **kwargs):
                return mock_ssh_connection()

            mock_connect.side_effect = mock_connect_coro

            started_manager.register_cluster(1, "test.example.com")

            # Acquire all connections from pool (size=3)
            connections = []
            for _ in range(3):
                conn_ctx = started_manager.get_connection(1)
                conn = await conn_ctx.__aenter__()
                connections.append((conn_ctx, conn))

            assert mock_connect.call_count == 3
            assert len(started_manager._pools[1]) == 3

            # Release all connections
            for conn_ctx, conn in connections:
                await conn_ctx.__aexit__(None, None, None)
        finally:
            await started_manager.stop()

    @pytest.mark.asyncio
    @patch("src.core.connection_manager.asyncssh.connect")
    async def test_test_connection_success(self, mock_connect, started_manager):
        """Test successful connection test."""
        await started_manager.start()
        try:
            mock_conn = mock_ssh_connection()

            # Make mock_connect return a coroutine
            async def mock_connect_coro(*args, **kwargs):
                return mock_conn

            mock_connect.side_effect = mock_connect_coro

            started_manager.register_cluster(1, "test.example.com")

            is_working = await started_manager.test_connection(1)

            assert is_working is True
        finally:
            await started_manager.stop()

    @pytest.mark.asyncio
    @patch("src.core.connection_manager.asyncssh.connect")
    async def test_test_connection_failure(self, mock_connect, started_manager):
        """Test failed connection test."""
        await started_manager.start()
        try:
            mock_connect.side_effect = Exception("Connection failed")

            started_manager.register_cluster(1, "test.example.com")

            is_working = await started_manager.test_connection(1)

            assert is_working is False
        finally:
            await started_manager.stop()

    @pytest.mark.asyncio
    @patch("src.core.connection_manager.asyncssh.connect")
    async def test_disconnect_cluster(self, mock_connect, started_manager):
        """Test disconnecting all connections to a cluster."""
        await started_manager.start()
        try:
            mock_conn = mock_ssh_connection()

            # Make mock_connect return a coroutine
            async def mock_connect_coro(*args, **kwargs):
                return mock_conn

            mock_connect.side_effect = mock_connect_coro

            started_manager.register_cluster(1, "test.example.com")

            # Create a connection
            async with started_manager.get_connection(1):
                pass

            assert 1 in started_manager._pools
            assert len(started_manager._pools[1]) > 0

            # Disconnect
            await started_manager.disconnect(1)

            assert 1 not in started_manager._pools
            mock_conn.close.assert_called()
        finally:
            await started_manager.stop()

    @pytest.mark.asyncio
    @patch("src.core.connection_manager.asyncssh.connect")
    async def test_get_connection_metrics(self, mock_connect, started_manager):
        """Test getting connection metrics."""
        await started_manager.start()
        try:
            # Make mock_connect return a coroutine that creates new mock each time
            async def mock_connect_coro(*args, **kwargs):
                return mock_ssh_connection()

            mock_connect.side_effect = mock_connect_coro

            started_manager.register_cluster(1, "test.example.com")

            # Create connections
            async with started_manager.get_connection(1):
                async with started_manager.get_connection(1):
                    # Inside two nested contexts
                    metrics = await started_manager.get_connection_metrics(1)

                    assert metrics["total_connections"] == 2
                    assert metrics["in_use"] == 2
                    assert metrics["available"] == 0
                    assert metrics["avg_age_seconds"] >= 0
        finally:
            await started_manager.stop()

    @pytest.mark.asyncio
    async def test_health_check_removes_unhealthy(self, started_manager):
        """Test health check removes unhealthy connections."""
        await started_manager.start()
        try:
            # Create a mock that fails health checks
            mock_conn = MagicMock()

            async def mock_run_fail(*args, **kwargs):
                result = AsyncMock()
                result.exit_status = 1  # Failure
                return result

            mock_conn.run = mock_run_fail
            mock_conn.close = MagicMock()

            async def mock_wait():
                pass

            mock_conn.wait_closed = mock_wait

            pooled = PooledConnection(connection=mock_conn, cluster_id=1)
            pooled.mark_available()

            started_manager._pools[1] = [pooled]

            # Run health check
            is_healthy = await started_manager._health_check(pooled)

            assert is_healthy is False
            assert pooled.health_check_failures == 1
        finally:
            await started_manager.stop()

    @pytest.mark.asyncio
    async def test_health_check_removes_stale(self, started_manager):
        """Test health check removes stale connections."""
        await started_manager.start()
        try:
            mock_conn = mock_ssh_connection()
            pooled = PooledConnection(connection=mock_conn, cluster_id=1)
            pooled.created_at = time.time() - 4000  # Very old
            pooled.mark_available()

            started_manager._pools[1] = [pooled]

            # Manually trigger cleanup logic
            if pooled.is_stale(started_manager.MAX_CONNECTION_AGE):
                await started_manager._remove_connection(pooled)

            assert 1 not in started_manager._pools or len(started_manager._pools[1]) == 0
        finally:
            await started_manager.stop()
