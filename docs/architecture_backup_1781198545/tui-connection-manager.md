# Connection Manager

The Connection Manager provides a robust SSH connection management system for the CRYSTAL TUI. It handles connection pooling, authentication, health monitoring, and automatic recovery.

## Features

### Connection Pooling
- **Reusable Connections**: Maintains a pool of SSH connections per cluster
- **Configurable Size**: Default 5 connections per cluster (configurable)
- **Automatic Recycling**: Connections are recycled after timeout or health check failure
- **Thread-Safe**: Safe to use from multiple async tasks

### Authentication Methods
- **SSH Key-Based**: Private key file authentication (recommended)
- **Password**: Secure password storage using system keyring
- **SSH Agent**: Support for SSH agent forwarding
- **SSH Config**: Honors `~/.ssh/config` settings

### Health Monitoring
- **Automatic Health Checks**: Periodic connection validation
- **Keepalive**: Configurable keepalive intervals (default: 60s)
- **Stale Connection Detection**: Removes connections older than 1 hour
- **Idle Timeout**: Closes connections idle for more than 5 minutes
- **Retry Logic**: Automatic reconnection on failure

### Security
- **Secure Credential Storage**: Uses system keyring (Keychain on macOS)
- **No Plain Text Passwords**: Never stores passwords in plain text
- **Connection Metrics**: Track connection usage and health

## Basic Usage

### Initialization

```python
from src.core.connection_manager import ConnectionManager

# Create manager with custom pool size
manager = ConnectionManager(pool_size=5)

# Start background tasks
await manager.start()

# Always stop when done
await manager.stop()
```

### Register a Cluster

```python
from pathlib import Path

# Register with SSH key authentication (recommended)
manager.register_cluster(
    cluster_id=1,
    host="cluster.example.com",
    port=22,
    username="user",
    key_file=Path("~/.ssh/id_rsa").expanduser(),
    use_agent=True
)

# Register with password authentication
manager.register_cluster(
    cluster_id=2,
    host="other-cluster.example.com",
    username="user"
)
manager.set_password(2, "secure_password")
```

### Using Connections

```python
# Context manager (recommended - automatic release)
async with manager.get_connection(cluster_id=1) as conn:
    result = await conn.run("ls -la")
    print(result.stdout)

# Multiple commands on same connection
async with manager.get_connection(cluster_id=1) as conn:
    result1 = await conn.run("cd /tmp")
    result2 = await conn.run("pwd")
    result3 = await conn.run("ls")
```

### Connection Testing

```python
# Test if connection works
is_working = await manager.test_connection(cluster_id=1)
if is_working:
    print("Connection successful")
else:
    print("Connection failed")
```

### Connection Metrics

```python
# Get connection statistics
metrics = await manager.get_connection_metrics(cluster_id=1)
print(f"Total connections: {metrics['total_connections']}")
print(f"In use: {metrics['in_use']}")
print(f"Available: {metrics['available']}")
print(f"Average age: {metrics['avg_age_seconds']:.1f}s")
```

## Advanced Usage

### Custom Connection Configuration

```python
from src.core.connection_manager import ConnectionConfig

config = ConnectionConfig(
    host="cluster.example.com",
    port=2222,
    username="admin",
    key_file=Path("/secure/keys/cluster_key"),
    use_agent=False,
    timeout=60,  # Connection timeout in seconds
    keepalive_interval=30  # Keepalive every 30 seconds
)
```

### Password Management

```python
# Store password securely
manager.set_password(cluster_id=1, password="secret123")

# Retrieve password (rarely needed - manager handles this)
password = manager.get_password(cluster_id=1)

# Delete password
manager.delete_password(cluster_id=1)
```

### Manual Connection Management

```python
# Create connection manually
connection = await manager.connect(cluster_id=1)

# Use connection
result = await connection.run("hostname")

# Remember to close when done
connection.close()
await connection.wait_closed()
```

### Disconnect All Connections

```python
# Close all connections to a cluster
await manager.disconnect(cluster_id=1)
```

## Connection Lifecycle

### Connection States

1. **Created**: New connection established
2. **In Use**: Connection acquired from pool
3. **Available**: Connection released back to pool
4. **Stale**: Connection exceeds max age (1 hour)
5. **Unhealthy**: Connection fails health checks
6. **Closed**: Connection removed from pool

### Automatic Cleanup

The manager automatically cleans up connections:
- **Age**: Connections older than 1 hour are closed
- **Idle**: Connections idle for 5+ minutes are closed
- **Health**: Connections failing 3+ health checks are closed

### Health Checks

Background health checks run every 60 seconds:
- Runs `true` command on idle connections
- Tracks failure count per connection
- Removes connections after 3 consecutive failures
- Resets failure count on successful check

## Error Handling

### Connection Failures

```python
import asyncssh

try:
    async with manager.get_connection(cluster_id=1) as conn:
        result = await conn.run("command")
except asyncssh.Error as e:
    print(f"SSH error: {e}")
except asyncio.TimeoutError:
    print("Connection timeout")
except ValueError as e:
    print(f"Configuration error: {e}")
```

### Retry Logic

The manager automatically retries on transient failures:
- Waits 0.5s when pool is full
- Creates new connection if unhealthy connection removed
- Attempts reconnection on health check failure

## Performance Considerations

### Pool Sizing

Choose pool size based on:
- **Concurrent Tasks**: Number of simultaneous operations
- **Connection Cost**: Overhead of creating connections
- **Resource Limits**: Server's max concurrent SSH sessions

```python
# Low concurrency (1-3 tasks)
manager = ConnectionManager(pool_size=2)

# Medium concurrency (4-10 tasks)
manager = ConnectionManager(pool_size=5)

# High concurrency (10+ tasks)
manager = ConnectionManager(pool_size=10)
```

### Connection Reuse

Connections are reused when:
- Not currently in use
- Less than 1 hour old
- Pass health check

This avoids connection overhead for sequential operations.

### Resource Cleanup

Always use context managers or properly close connections:

```python
# ✅ GOOD: Context manager auto-releases
async with manager.get_connection(cluster_id=1) as conn:
    result = await conn.run("command")

# ❌ BAD: Manual management error-prone
conn = await manager.connect(cluster_id=1)
result = await conn.run("command")
# Forgot to release/close!
```

## Security Best Practices

### SSH Key Authentication

**Recommended** - More secure than passwords:

```python
manager.register_cluster(
    cluster_id=1,
    host="cluster.example.com",
    key_file=Path("~/.ssh/id_rsa").expanduser()
)
```

### Password Storage

Passwords are stored in system keyring:
- **macOS**: Keychain
- **Linux**: Secret Service (gnome-keyring, KWallet)
- **Windows**: Windows Credential Locker

Never store passwords in code or config files.

### SSH Config

The manager honors `~/.ssh/config`:

```
# ~/.ssh/config
Host cluster
    HostName cluster.example.com
    User myuser
    Port 2222
    IdentityFile ~/.ssh/cluster_key
```

```python
# Uses settings from ~/.ssh/config
manager.register_cluster(cluster_id=1, host="cluster")
```

### Known Hosts

**Production**: Enable known_hosts checking:

```python
# In connection_manager.py, change:
"known_hosts": None  # Testing only

# To:
"known_hosts": str(Path("~/.ssh/known_hosts").expanduser())
```

## Troubleshooting

### Connection Timeout

```python
# Increase timeout for slow networks
config = ConnectionConfig(
    host="cluster.example.com",
    timeout=120  # 2 minutes
)
```

### Too Many Connections

```
Error: Resource temporarily unavailable
```

**Solution**: Reduce pool size or check server limits:

```bash
# On server, check max sessions
grep MaxSessions /etc/ssh/sshd_config
```

### Health Check Failures

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

Check logs for:
- Network issues
- Server unreachable
- Authentication failures

### Keyring Access Errors

**macOS**: Grant terminal access to Keychain in System Preferences

**Linux**: Install keyring backend:
```bash
pip install secretstorage  # For Secret Service
# or
pip install keyrings.alt  # Fallback backend
```

## API Reference

### ConnectionManager

#### Methods

- `__init__(pool_size: int = 5)`: Initialize manager
- `async start()`: Start background tasks
- `async stop()`: Stop and cleanup
- `register_cluster(...)`: Register cluster configuration
- `set_password(cluster_id, password)`: Store password
- `get_password(cluster_id) -> str | None`: Retrieve password
- `delete_password(cluster_id)`: Delete password
- `async connect(cluster_id) -> SSHClientConnection`: Create connection
- `async disconnect(cluster_id)`: Close all connections
- `get_connection(cluster_id)`: Get connection (context manager)
- `async test_connection(cluster_id) -> bool`: Test connection
- `async get_connection_metrics(cluster_id) -> dict`: Get metrics

### ConnectionConfig

Configuration dataclass for SSH connections.

**Fields**:
- `host: str` - SSH hostname or IP
- `port: int = 22` - SSH port
- `username: str | None` - SSH username
- `key_file: Path | None` - Private key file path
- `use_agent: bool = True` - Use SSH agent
- `timeout: int = 30` - Connection timeout (seconds)
- `keepalive_interval: int = 60` - Keepalive interval (seconds)

### PooledConnection

Internal dataclass representing a pooled connection.

**Fields**:
- `connection: SSHClientConnection` - The SSH connection
- `cluster_id: int` - Cluster identifier
- `created_at: float` - Creation timestamp
- `last_used: float` - Last use timestamp
- `in_use: bool` - Whether currently in use
- `health_check_failures: int` - Consecutive failure count

## Examples

### Complete Example

```python
import asyncio
from pathlib import Path
from src.core.connection_manager import ConnectionManager

async def main():
    # Create and start manager
    manager = ConnectionManager(pool_size=5)
    await manager.start()

    try:
        # Register cluster
        manager.register_cluster(
            cluster_id=1,
            host="cluster.example.com",
            username="user",
            key_file=Path("~/.ssh/id_rsa").expanduser()
        )

        # Test connection
        if await manager.test_connection(1):
            print("✅ Connection successful")
        else:
            print("❌ Connection failed")
            return

        # Run commands
        async with manager.get_connection(1) as conn:
            # Get hostname
            result = await conn.run("hostname")
            print(f"Hostname: {result.stdout.strip()}")

            # List directory
            result = await conn.run("ls -la /tmp")
            print(f"Files:\n{result.stdout}")

        # Check metrics
        metrics = await manager.get_connection_metrics(1)
        print(f"Pool stats: {metrics}")

    finally:
        # Always cleanup
        await manager.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

### Multiple Clusters

```python
async def multi_cluster():
    manager = ConnectionManager()
    await manager.start()

    try:
        # Register multiple clusters
        for i, host in enumerate(["cluster1.com", "cluster2.com"], 1):
            manager.register_cluster(
                cluster_id=i,
                host=host,
                key_file=Path(f"~/.ssh/cluster{i}_key").expanduser()
            )

        # Run commands on all clusters concurrently
        async def run_on_cluster(cluster_id):
            async with manager.get_connection(cluster_id) as conn:
                result = await conn.run("uname -a")
                return cluster_id, result.stdout.strip()

        results = await asyncio.gather(
            run_on_cluster(1),
            run_on_cluster(2)
        )

        for cluster_id, output in results:
            print(f"Cluster {cluster_id}: {output}")

    finally:
        await manager.stop()
```

## Integration with TUI

The Connection Manager integrates with the TUI remote runner:

```python
from src.runners.remote import RemoteRunner
from src.core.connection_manager import ConnectionManager

# In your TUI app
async def on_mount(self):
    # Create shared connection manager
    self.conn_manager = ConnectionManager(pool_size=5)
    await self.conn_manager.start()

    # Register configured clusters
    for cluster in self.db.get_clusters():
        self.conn_manager.register_cluster(
            cluster_id=cluster.id,
            host=cluster.host,
            port=cluster.port,
            username=cluster.username,
            key_file=Path(cluster.key_file) if cluster.key_file else None
        )

    # Create runner with shared manager
    self.remote_runner = RemoteRunner(self.conn_manager)

async def on_unmount(self):
    # Cleanup
    await self.conn_manager.stop()
```

## See Also

- [Database Documentation](DATABASE.md)
- [Remote Runner Documentation](REMOTE_RUNNER.md)
- [asyncssh Documentation](https://asyncssh.readthedocs.io/)
