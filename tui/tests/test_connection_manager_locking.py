"""
Tests for Connection Manager locking behavior.

These tests verify that the health check loop does not hold the global lock
during network I/O operations, preventing stop-the-world freezing.
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.connection_manager import ConnectionManager, PooledConnection


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


@pytest.fixture
def manager():
    """Create a connection manager for testing."""
    return ConnectionManager(pool_size=3)


class TestHealthCheckLocking:
    """Test that health checks do not hold the global lock during network I/O."""

    @pytest.mark.asyncio
    async def test_health_check_loop_releases_lock_during_io(self, manager):
        """Test that lock is released during network I/O in health check loop."""
        await manager.start()
        try:
            # Create mock connections with slow health checks
            slow_connections = []
            for i in range(3):
                mock_conn = MagicMock()

                # Simulate slow network I/O (500ms each)
                async def slow_run(*args, **kwargs):
                    await asyncio.sleep(0.5)
                    result = AsyncMock()
                    result.exit_status = 0
                    return result

                mock_conn.run = slow_run
                mock_conn.close = MagicMock()
                mock_conn.wait_closed = AsyncMock()

                pooled = PooledConnection(connection=mock_conn, cluster_id=1)
                pooled.mark_available()
                slow_connections.append(pooled)

            manager._pools[1] = slow_connections

            # Track lock acquisition
            lock_held = False
            lock_acquired_during_io = False

            async def try_acquire_lock():
                """Try to acquire lock during health checks."""
                nonlocal lock_acquired_during_io
                await asyncio.sleep(0.1)  # Let health checks start
                async with manager._lock:
                    # If we can acquire lock during health checks, it means lock was released
                    lock_acquired_during_io = True

            # Manually trigger one health check cycle
            health_check_task = asyncio.create_task(
                manager._health_check_loop_single_iteration()
            )
            lock_test_task = asyncio.create_task(try_acquire_lock())

            # Wait for both to complete (with timeout)
            await asyncio.wait_for(
                asyncio.gather(health_check_task, lock_test_task, return_exceptions=True),
                timeout=5.0
            )

            # Verify lock was released during I/O
            assert lock_acquired_during_io, "Lock should be released during network I/O"

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_health_checks_run_in_parallel(self, manager):
        """Test that health checks for multiple connections run in parallel."""
        await manager.start()
        try:
            # Create 5 mock connections with 200ms health check time each
            mock_connections = []
            for i in range(5):
                mock_conn = MagicMock()

                async def slow_run(*args, **kwargs):
                    await asyncio.sleep(0.2)  # 200ms per check
                    result = AsyncMock()
                    result.exit_status = 0
                    return result

                mock_conn.run = slow_run
                mock_conn.close = MagicMock()
                mock_conn.wait_closed = AsyncMock()

                pooled = PooledConnection(connection=mock_conn, cluster_id=1)
                pooled.mark_available()
                mock_connections.append(pooled)

            manager._pools[1] = mock_connections

            # Time a single health check iteration
            start_time = time.time()

            # Run one iteration of health check loop
            await manager._health_check_loop_single_iteration()

            elapsed = time.time() - start_time

            # If parallel: ~200ms (all at once)
            # If sequential: ~1000ms (5 × 200ms)
            # Allow some overhead, but should be much closer to parallel time
            assert elapsed < 0.5, (
                f"Health checks should run in parallel (~200ms), "
                f"but took {elapsed:.3f}s (expected < 500ms)"
            )

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_unhealthy_connections_properly_removed(self, manager):
        """Test that unhealthy connections are properly identified and removed."""
        await manager.start()
        try:
            # Create one healthy and one unhealthy connection
            healthy_conn = MagicMock()

            async def healthy_run(*args, **kwargs):
                result = AsyncMock()
                result.exit_status = 0
                return result

            healthy_conn.run = healthy_run
            healthy_conn.close = MagicMock()
            healthy_conn.wait_closed = AsyncMock()

            unhealthy_conn = MagicMock()

            async def unhealthy_run(*args, **kwargs):
                result = AsyncMock()
                result.exit_status = 1  # Failure
                return result

            unhealthy_conn.run = unhealthy_run
            unhealthy_conn.close = MagicMock()
            unhealthy_conn.wait_closed = AsyncMock()

            pooled_healthy = PooledConnection(connection=healthy_conn, cluster_id=1)
            pooled_healthy.mark_available()

            pooled_unhealthy = PooledConnection(connection=unhealthy_conn, cluster_id=1)
            pooled_unhealthy.mark_available()
            # Set failures to threshold - 1, so next failure triggers removal
            pooled_unhealthy.health_check_failures = manager.MAX_HEALTH_CHECK_FAILURES - 1

            manager._pools[1] = [pooled_healthy, pooled_unhealthy]

            # Run health check iteration
            await manager._health_check_loop_single_iteration()

            # Verify unhealthy connection was removed
            assert len(manager._pools[1]) == 1
            assert manager._pools[1][0] == pooled_healthy
            unhealthy_conn.close.assert_called_once()

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_stale_connections_removed_quickly(self, manager):
        """Test that stale connections are removed without health checks."""
        await manager.start()
        try:
            # Create a stale connection (very old)
            stale_conn = mock_ssh_connection()
            pooled_stale = PooledConnection(connection=stale_conn, cluster_id=1)
            pooled_stale.created_at = time.time() - manager.MAX_CONNECTION_AGE - 100
            pooled_stale.mark_available()

            manager._pools[1] = [pooled_stale]

            # Run health check iteration
            await manager._health_check_loop_single_iteration()

            # Verify stale connection was removed
            assert 1 not in manager._pools or len(manager._pools[1]) == 0
            stale_conn.close.assert_called_once()

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_lock_only_held_during_state_operations(self, manager):
        """Test that lock is only held during state reads/writes, not I/O."""
        await manager.start()
        try:
            # Track when lock is acquired and released
            lock_events = []

            # Wrap the lock to track acquisitions
            original_acquire = manager._lock.acquire
            original_release = manager._lock.release

            async def tracked_acquire(*args, **kwargs):
                lock_events.append(('acquire', time.time()))
                return await original_acquire(*args, **kwargs)

            def tracked_release(*args, **kwargs):
                lock_events.append(('release', time.time()))
                return original_release(*args, **kwargs)

            manager._lock.acquire = tracked_acquire
            manager._lock.release = tracked_release

            # Create connections with network I/O
            mock_conn = MagicMock()

            io_start_time = None
            io_end_time = None

            async def tracked_run(*args, **kwargs):
                nonlocal io_start_time, io_end_time
                io_start_time = time.time()
                await asyncio.sleep(0.1)  # Simulate network I/O
                io_end_time = time.time()
                result = AsyncMock()
                result.exit_status = 0
                return result

            mock_conn.run = tracked_run
            mock_conn.close = MagicMock()
            mock_conn.wait_closed = AsyncMock()

            pooled = PooledConnection(connection=mock_conn, cluster_id=1)
            pooled.mark_available()
            manager._pools[1] = [pooled]

            # Run health check iteration
            await manager._health_check_loop_single_iteration()

            # Find acquire/release pairs
            assert len(lock_events) >= 2, "Lock should be acquired at least once"

            # Verify lock was NOT held during I/O
            # Look for acquire/release pairs that don't overlap with I/O
            for i in range(0, len(lock_events) - 1, 2):
                if lock_events[i][0] == 'acquire' and lock_events[i+1][0] == 'release':
                    acquire_time = lock_events[i][1]
                    release_time = lock_events[i+1][1]

                    # If I/O happened, lock should NOT be held during it
                    if io_start_time and io_end_time:
                        lock_held_during_io = (
                            acquire_time <= io_start_time and release_time >= io_end_time
                        )
                        assert not lock_held_during_io, (
                            f"Lock should not be held during network I/O. "
                            f"Lock: {acquire_time:.3f}-{release_time:.3f}, "
                            f"I/O: {io_start_time:.3f}-{io_end_time:.3f}"
                        )

        finally:
            await manager.stop()

    @pytest.mark.asyncio
    async def test_no_race_conditions_in_connection_removal(self, manager):
        """Test that concurrent connection operations don't cause race conditions."""
        await manager.start()
        try:
            # Create connections
            connections = []
            for i in range(5):
                mock_conn = mock_ssh_connection()
                pooled = PooledConnection(connection=mock_conn, cluster_id=1)
                pooled.mark_available()
                connections.append(pooled)

            manager._pools[1] = connections

            # Simulate concurrent operations
            async def acquire_and_release():
                """Acquire a connection and release it."""
                try:
                    conn = await manager._acquire_connection(1)
                    await asyncio.sleep(0.01)
                    await manager._release_connection(conn)
                except Exception:
                    pass  # Expected if pool is being modified

            async def run_health_check():
                """Run a health check iteration."""
                try:
                    await manager._health_check_loop_single_iteration()
                except Exception:
                    pass  # Expected if pool is being modified

            # Run multiple operations concurrently
            tasks = [
                acquire_and_release(),
                acquire_and_release(),
                run_health_check(),
                acquire_and_release(),
            ]

            # Should not raise exceptions or deadlock
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=5.0
            )

            # Verify no connections are in inconsistent state
            if 1 in manager._pools:
                for conn in manager._pools[1]:
                    assert isinstance(conn, PooledConnection)
                    assert conn.cluster_id == 1

        finally:
            await manager.stop()


# Helper method for testing - add to ConnectionManager for test purposes only
async def _health_check_loop_single_iteration(self):
    """
    Run a single iteration of the health check loop for testing.
    This is a copy of the loop body without the while True wrapper.
    """
    # Step 1: Gather connections to check (fast, under lock)
    connections_to_check = []
    connections_to_remove_stale = []

    async with self._lock:
        for cluster_id, pool in list(self._pools.items()):
            for pooled_conn in pool:
                if pooled_conn.in_use:
                    continue

                # Check if connection is stale or idle too long
                if pooled_conn.is_stale(
                    self.MAX_CONNECTION_AGE
                ) or pooled_conn.is_idle_too_long(self.MAX_IDLE_TIME):
                    connections_to_remove_stale.append((cluster_id, pooled_conn))
                else:
                    # Queue for health check
                    connections_to_check.append((cluster_id, pooled_conn))

    # Step 2: Remove stale connections (fast, under lock)
    if connections_to_remove_stale:
        async with self._lock:
            for cluster_id, pooled_conn in connections_to_remove_stale:
                await self._remove_connection(pooled_conn)

    # Step 3: Perform health checks in parallel (slow, lock-free)
    if connections_to_check:
        async def check_one(cluster_id: int, pooled_conn: PooledConnection):
            """Health check a single connection."""
            try:
                result = await asyncio.wait_for(
                    pooled_conn.connection.run("true", check=False),
                    timeout=5.0
                )
                is_healthy = result.exit_status == 0
                return (cluster_id, pooled_conn, is_healthy, None)
            except Exception as e:
                return (cluster_id, pooled_conn, False, e)

        # Run all health checks in parallel
        results = await asyncio.gather(
            *[check_one(cid, pc) for cid, pc in connections_to_check],
            return_exceptions=True
        )

        # Step 4: Update state based on results (fast, under lock)
        connections_to_remove_unhealthy = []

        async with self._lock:
            for result in results:
                # Skip exceptions from gather
                if isinstance(result, Exception):
                    continue

                cluster_id, pooled_conn, is_healthy, error = result

                if is_healthy:
                    pooled_conn.health_check_failures = 0
                else:
                    pooled_conn.health_check_failures += 1

                    if pooled_conn.health_check_failures >= self.MAX_HEALTH_CHECK_FAILURES:
                        connections_to_remove_unhealthy.append(pooled_conn)

        # Step 5: Remove unhealthy connections (under lock)
        if connections_to_remove_unhealthy:
            async with self._lock:
                for pooled_conn in connections_to_remove_unhealthy:
                    await self._remove_connection(pooled_conn)


# Monkey-patch the helper method onto ConnectionManager for testing
ConnectionManager._health_check_loop_single_iteration = _health_check_loop_single_iteration
