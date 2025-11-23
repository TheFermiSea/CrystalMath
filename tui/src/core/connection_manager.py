"""
Connection Manager for SSH connections with pooling, authentication, and health monitoring.

Provides a robust connection management system with:
- Connection pooling for reusable SSH connections
- Multiple authentication methods (key-based, password, agent)
- Automatic connection health checks and recycling
- Secure credential storage using keyring
- Thread-safe connection sharing
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple
from contextlib import asynccontextmanager

import asyncssh
import keyring

logger = logging.getLogger(__name__)


@dataclass
class ConnectionConfig:
    """Configuration for an SSH connection."""

    host: str
    port: int = 22
    username: Optional[str] = None
    key_file: Optional[Path] = None
    use_agent: bool = True
    timeout: int = 30
    keepalive_interval: int = 60
    known_hosts_file: Optional[Path] = None
    strict_host_key_checking: bool = True


@dataclass
class PooledConnection:
    """Wrapper for a pooled SSH connection with metadata."""

    connection: asyncssh.SSHClientConnection
    cluster_id: int
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    in_use: bool = False
    health_check_failures: int = 0

    def mark_used(self) -> None:
        """Mark connection as used, updating timestamp."""
        self.last_used = time.time()
        self.in_use = True

    def mark_available(self) -> None:
        """Mark connection as available for reuse."""
        self.in_use = False

    def is_stale(self, max_age: float) -> bool:
        """Check if connection is too old to be reused."""
        age = time.time() - self.created_at
        return age > max_age

    def is_idle_too_long(self, max_idle: float) -> bool:
        """Check if connection has been idle too long."""
        idle_time = time.time() - self.last_used
        return idle_time > max_idle


class ConnectionManager:
    """Manages a pool of SSH connections with authentication and health monitoring."""

    KEYRING_SERVICE = "crystal-tui"
    MAX_POOL_SIZE = 5
    MAX_CONNECTION_AGE = 3600  # 1 hour
    MAX_IDLE_TIME = 300  # 5 minutes
    MAX_HEALTH_CHECK_FAILURES = 3

    def __init__(self, pool_size: int = MAX_POOL_SIZE):
        """
        Initialize the connection manager.

        Args:
            pool_size: Maximum number of connections per cluster
        """
        self.pool_size = pool_size
        self._pools: Dict[int, List[PooledConnection]] = {}
        self._configs: Dict[int, ConnectionConfig] = {}
        self._lock = asyncio.Lock()
        self._health_check_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the connection manager and background tasks."""
        logger.info("Starting connection manager")
        self._health_check_task = asyncio.create_task(self._health_check_loop())

    async def stop(self) -> None:
        """Stop the connection manager and close all connections."""
        logger.info("Stopping connection manager")

        # Cancel health check task
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        # Close all connections
        async with self._lock:
            for cluster_id in list(self._pools.keys()):
                await self._close_cluster_pool(cluster_id)

    def register_cluster(
        self,
        cluster_id: int,
        host: str,
        port: int = 22,
        username: Optional[str] = None,
        key_file: Optional[Path] = None,
        use_agent: bool = True,
        known_hosts_file: Optional[Path] = None,
        strict_host_key_checking: bool = True,
    ) -> None:
        """
        Register a cluster configuration.

        Args:
            cluster_id: Unique identifier for the cluster
            host: SSH hostname or IP address
            port: SSH port (default: 22)
            username: SSH username (optional, uses current user if not set)
            key_file: Path to SSH private key file (optional)
            use_agent: Whether to use SSH agent for authentication
            known_hosts_file: Path to SSH known_hosts file for host key verification.
                If None, uses ~/.ssh/known_hosts by default.
                Set to empty Path() to disable host key checking (NOT RECOMMENDED).
            strict_host_key_checking: Whether to strictly verify host keys and fail on
                unknown hosts (default: True). When False, unknown hosts are logged but
                connection proceeds (NOT RECOMMENDED for production).

        Note:
            Host key verification is ENABLED by default for security. To verify host keys:
            1. Ensure the remote host's public key is in ~/.ssh/known_hosts
            2. You can manually add it by running: ssh-keyscan -H <host> >> ~/.ssh/known_hosts
            3. Or connect once manually and confirm the host key to add it automatically
        """
        config = ConnectionConfig(
            host=host,
            port=port,
            username=username,
            key_file=key_file,
            use_agent=use_agent,
            known_hosts_file=known_hosts_file,
            strict_host_key_checking=strict_host_key_checking,
        )
        self._configs[cluster_id] = config
        logger.info(f"Registered cluster {cluster_id}: {host}:{port}")

    def set_password(self, cluster_id: int, password: str) -> None:
        """
        Store password for a cluster in system keyring.

        Args:
            cluster_id: Cluster identifier
            password: SSH password to store securely
        """
        key = f"cluster_{cluster_id}"
        keyring.set_password(self.KEYRING_SERVICE, key, password)
        logger.info(f"Stored password for cluster {cluster_id}")

    def get_password(self, cluster_id: int) -> Optional[str]:
        """
        Retrieve password for a cluster from system keyring.

        Args:
            cluster_id: Cluster identifier

        Returns:
            Password if stored, None otherwise
        """
        key = f"cluster_{cluster_id}"
        return keyring.get_password(self.KEYRING_SERVICE, key)

    def delete_password(self, cluster_id: int) -> None:
        """
        Delete password for a cluster from system keyring.

        Args:
            cluster_id: Cluster identifier
        """
        key = f"cluster_{cluster_id}"
        try:
            keyring.delete_password(self.KEYRING_SERVICE, key)
            logger.info(f"Deleted password for cluster {cluster_id}")
        except keyring.errors.PasswordDeleteError:
            logger.warning(f"No password stored for cluster {cluster_id}")

    async def connect(self, cluster_id: int) -> asyncssh.SSHClientConnection:
        """
        Create a new SSH connection to a cluster with host key verification.

        Establishes SSH connection with strict host key verification enabled by default.
        Host keys are verified against ~/.ssh/known_hosts (or custom known_hosts file).

        Args:
            cluster_id: Cluster identifier

        Returns:
            Established SSH connection

        Raises:
            ValueError: If cluster is not registered
            asyncssh.HostKeyNotVerifiable: If host key cannot be verified and strict
                checking is enabled. This indicates the host is unknown or has a changed
                key (potential MITM attack). To fix:
                1. Verify the host is correct
                2. Add the host key: ssh-keyscan -H <host> >> ~/.ssh/known_hosts
                3. Or connect manually and confirm the key
            asyncssh.Error: If connection fails for other reasons
            asyncio.TimeoutError: If connection times out
        """
        config = self._configs.get(cluster_id)
        if not config:
            raise ValueError(f"Cluster {cluster_id} not registered")

        logger.info(f"Creating new connection to cluster {cluster_id}")

        # Determine known_hosts file path
        known_hosts = self._get_known_hosts_file(config)
        logger.debug(
            f"Using known_hosts file: {known_hosts} (strict checking: "
            f"{config.strict_host_key_checking})"
        )

        # Build connection options with host key verification
        connect_kwargs = {
            "host": config.host,
            "port": config.port,
            "username": config.username,
            "known_hosts": known_hosts,
            "keepalive_interval": config.keepalive_interval,
        }

        # Configure host key verification behavior
        if not config.strict_host_key_checking:
            connect_kwargs["known_hosts"] = ()  # Accept unknown hosts with warning

        # Add authentication options
        if config.key_file:
            connect_kwargs["client_keys"] = [str(config.key_file)]

        password = self.get_password(cluster_id)
        if password:
            connect_kwargs["password"] = password

        # Create connection with timeout
        try:
            connection = await asyncio.wait_for(
                asyncssh.connect(**connect_kwargs), timeout=config.timeout
            )
            logger.info(
                f"Successfully connected to cluster {cluster_id} "
                f"(host key verified: {config.strict_host_key_checking})"
            )
            return connection
        except asyncio.TimeoutError:
            logger.error(f"Connection timeout for cluster {cluster_id}")
            raise
        except asyncssh.HostKeyNotVerifiable as e:
            error_msg = (
                f"Host key verification failed for cluster {cluster_id} ({config.host}). "
                f"The host is either unknown or has a changed key (potential MITM attack). "
                f"To add the host key, run: ssh-keyscan -H {config.host} >> ~/.ssh/known_hosts"
            )
            logger.error(error_msg)
            raise asyncssh.HostKeyNotVerifiable(error_msg) from e
        except asyncssh.Error as e:
            logger.error(f"Connection failed for cluster {cluster_id}: {e}")
            raise

    @staticmethod
    def _get_known_hosts_file(config: ConnectionConfig) -> Union[str, Tuple[()], None]:
        """
        Determine the known_hosts file path to use for host key verification.

        Args:
            config: Connection configuration

        Returns:
            Path to known_hosts file as string, or None to use asyncssh defaults,
            or empty tuple () to disable host key verification.

        Precedence:
            1. Custom known_hosts_file from config (if set to Path)
            2. Empty Path() to disable checking
            3. Default ~/.ssh/known_hosts
        """
        # If custom known_hosts file explicitly set
        if config.known_hosts_file is not None:
            # Empty Path() means disable host key checking
            if config.known_hosts_file.parts == ():
                return ()
            # Otherwise use the specified path
            return str(config.known_hosts_file.expanduser().resolve())

        # Use default SSH known_hosts location
        default_known_hosts = Path.home() / ".ssh" / "known_hosts"
        return str(default_known_hosts) if default_known_hosts.exists() else None

    async def disconnect(self, cluster_id: int) -> None:
        """
        Close all connections to a cluster.

        Args:
            cluster_id: Cluster identifier
        """
        async with self._lock:
            await self._close_cluster_pool(cluster_id)

    @asynccontextmanager
    async def get_connection(self, cluster_id: int):
        """
        Get a connection from the pool (context manager).

        Usage:
            async with manager.get_connection(cluster_id) as conn:
                result = await conn.run("ls")

        Args:
            cluster_id: Cluster identifier

        Yields:
            SSH connection from the pool
        """
        pooled_conn = await self._acquire_connection(cluster_id)
        try:
            yield pooled_conn.connection
        finally:
            await self._release_connection(pooled_conn)

    async def test_connection(self, cluster_id: int) -> bool:
        """
        Test if connection to a cluster is working.

        Args:
            cluster_id: Cluster identifier

        Returns:
            True if connection successful, False otherwise
        """
        try:
            async with self.get_connection(cluster_id) as conn:
                result = await conn.run("echo test", check=True)
                return result.exit_status == 0
        except Exception as e:
            logger.error(f"Connection test failed for cluster {cluster_id}: {e}")
            return False

    async def get_connection_metrics(self, cluster_id: int) -> Dict[str, any]:
        """
        Get metrics for connections to a cluster.

        Args:
            cluster_id: Cluster identifier

        Returns:
            Dictionary with connection metrics
        """
        async with self._lock:
            pool = self._pools.get(cluster_id, set())
            total = len(pool)
            in_use = sum(1 for pc in pool if pc.in_use)
            avg_age = (
                sum(time.time() - pc.created_at for pc in pool) / total if total > 0 else 0
            )
            avg_idle = (
                sum(time.time() - pc.last_used for pc in pool if not pc.in_use)
                / max(1, total - in_use)
                if total > in_use
                else 0
            )

            return {
                "total_connections": total,
                "in_use": in_use,
                "available": total - in_use,
                "avg_age_seconds": avg_age,
                "avg_idle_seconds": avg_idle,
            }

    # Private methods

    async def _acquire_connection(self, cluster_id: int) -> PooledConnection:
        """Acquire a connection from the pool, creating one if needed."""
        async with self._lock:
            # Initialize pool if needed
            if cluster_id not in self._pools:
                self._pools[cluster_id] = []

            pool = self._pools[cluster_id]

            # Try to find an available connection
            for pooled_conn in pool:
                if not pooled_conn.in_use and not pooled_conn.is_stale(self.MAX_CONNECTION_AGE):
                    # Health check before reuse
                    if await self._health_check(pooled_conn):
                        pooled_conn.mark_used()
                        logger.debug(f"Reusing connection from pool for cluster {cluster_id}")
                        return pooled_conn
                    else:
                        # Remove unhealthy connection
                        await self._remove_connection(pooled_conn)

            # Create new connection if pool not full
            if len(pool) < self.pool_size:
                connection = await self.connect(cluster_id)
                pooled_conn = PooledConnection(connection=connection, cluster_id=cluster_id)
                pooled_conn.mark_used()
                pool.append(pooled_conn)
                logger.debug(f"Created new pooled connection for cluster {cluster_id}")
                return pooled_conn

            # Wait for a connection to become available
            logger.warning(
                f"Pool full for cluster {cluster_id}, waiting for available connection"
            )

        # Wait and retry (outside lock to allow releases)
        await asyncio.sleep(0.5)
        return await self._acquire_connection(cluster_id)

    async def _release_connection(self, pooled_conn: PooledConnection) -> None:
        """Release a connection back to the pool."""
        async with self._lock:
            pooled_conn.mark_available()
            logger.debug(f"Released connection for cluster {pooled_conn.cluster_id}")

    async def _health_check(self, pooled_conn: PooledConnection) -> bool:
        """
        Check if a connection is healthy.

        Args:
            pooled_conn: Connection to check

        Returns:
            True if healthy, False otherwise
        """
        try:
            result = await asyncio.wait_for(
                pooled_conn.connection.run("true", check=False), timeout=5.0
            )
            is_healthy = result.exit_status == 0

            if is_healthy:
                pooled_conn.health_check_failures = 0
            else:
                pooled_conn.health_check_failures += 1

            return is_healthy
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            pooled_conn.health_check_failures += 1
            return False

    async def _health_check_loop(self) -> None:
        """
        Background task to periodically check connection health.

        Uses lock-free parallel health checks to avoid stop-the-world freezing.
        Lock is held only for microseconds during state reads/writes, not during
        network I/O operations.
        """
        logger.info("Health check loop started", extra={
            "component": "connection_manager",
            "interval_seconds": 60
        })

        loop_iteration = 0

        while True:
            loop_iteration += 1
            start_time = time.time()

            try:
                await asyncio.sleep(60)  # Check every minute

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
                                logger.info(
                                    f"Removing stale/idle connection for cluster {cluster_id}"
                                )
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
                    healthy_count = 0
                    unhealthy_count = 0

                    async with self._lock:
                        for result in results:
                            # Skip exceptions from gather
                            if isinstance(result, Exception):
                                logger.error(f"Health check raised exception: {result}")
                                unhealthy_count += 1
                                continue

                            cluster_id, pooled_conn, is_healthy, error = result

                            if is_healthy:
                                pooled_conn.health_check_failures = 0
                                healthy_count += 1
                            else:
                                pooled_conn.health_check_failures += 1
                                unhealthy_count += 1
                                if error:
                                    logger.warning(f"Health check failed for cluster {cluster_id}: {error}")

                                if pooled_conn.health_check_failures >= self.MAX_HEALTH_CHECK_FAILURES:
                                    logger.warning(
                                        f"Removing unhealthy connection for cluster {cluster_id} "
                                        f"after {pooled_conn.health_check_failures} failures"
                                    )
                                    connections_to_remove_unhealthy.append(pooled_conn)

                    # Step 5: Remove unhealthy connections (under lock)
                    if connections_to_remove_unhealthy:
                        async with self._lock:
                            for pooled_conn in connections_to_remove_unhealthy:
                                await self._remove_connection(pooled_conn)

                    # Log iteration completion
                    elapsed = time.time() - start_time
                    logger.debug("Health check iteration completed", extra={
                        "iteration": loop_iteration,
                        "elapsed_seconds": round(elapsed, 3),
                        "connections_checked": len(connections_to_check),
                        "stale_removed": len(connections_to_remove_stale),
                        "healthy": healthy_count,
                        "unhealthy": unhealthy_count,
                        "unhealthy_removed": len(connections_to_remove_unhealthy)
                    })
                else:
                    # No connections to check
                    elapsed = time.time() - start_time
                    logger.debug("Health check iteration completed", extra={
                        "iteration": loop_iteration,
                        "elapsed_seconds": round(elapsed, 3),
                        "connections_checked": 0,
                        "stale_removed": len(connections_to_remove_stale)
                    })

            except asyncio.CancelledError:
                logger.info("Health check loop stopped")
                break
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error("Health check loop error", extra={
                    "iteration": loop_iteration,
                    "elapsed_seconds": round(elapsed, 3),
                    "error": str(e)
                }, exc_info=True)

    async def _remove_connection(self, pooled_conn: PooledConnection) -> None:
        """Remove and close a connection from the pool."""
        pool = self._pools.get(pooled_conn.cluster_id)
        if pool:
            try:
                pool.remove(pooled_conn)
            except ValueError:
                # Connection already removed
                pass

        try:
            pooled_conn.connection.close()
            await pooled_conn.connection.wait_closed()
        except Exception as e:
            logger.error(f"Error closing connection: {e}")

    async def _close_cluster_pool(self, cluster_id: int) -> None:
        """Close all connections for a cluster."""
        pool = self._pools.get(cluster_id)
        if not pool:
            return

        logger.info(f"Closing all connections for cluster {cluster_id}")
        for pooled_conn in list(pool):
            await self._remove_connection(pooled_conn)

        del self._pools[cluster_id]
