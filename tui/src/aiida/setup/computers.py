"""
AiiDA Computer configuration for CRYSTAL23.

This module provides functions to setup AiiDA Computers for running
CRYSTAL23 calculations on various backends:
    - localhost: Local execution with direct scheduler
    - ssh: Remote SSH execution
    - slurm: HPC clusters with SLURM scheduler
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiida.orm import Computer


def setup_localhost_computer(
    workdir: str | Path | None = None,
    label: str = "localhost",
) -> Computer:
    """
    Setup localhost Computer for local CRYSTAL23 execution.

    Args:
        workdir: Working directory for calculations. Defaults to ~/tmp_crystal/aiida/
        label: Computer label in AiiDA database.

    Returns:
        Configured and stored Computer instance.

    Example:
        >>> computer = setup_localhost_computer()
        >>> computer.label
        'localhost'
    """
    from aiida import load_profile, orm

    load_profile()

    # Check if computer already exists
    try:
        existing = orm.Computer.collection.get(label=label)
        return existing
    except Exception:
        pass

    # Default workdir
    if workdir is None:
        workdir = Path.home() / "tmp_crystal" / "aiida"
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    computer = orm.Computer(
        label=label,
        hostname="localhost",
        description="Local machine for CRYSTAL23 calculations",
        transport_type="core.local",
        scheduler_type="core.direct",
        workdir=str(workdir),
    )

    # Configure mpirun command
    computer.set_mpirun_command(["mpirun", "-np", "{tot_num_mpiprocs}"])

    computer.store()
    computer.configure()

    return computer


def setup_ssh_computer(
    hostname: str,
    username: str,
    label: str | None = None,
    workdir: str | None = None,
    scheduler: str = "slurm",
    port: int = 22,
    key_filename: str | None = None,
    look_for_keys: bool = True,
    mpirun_command: list[str] | None = None,
) -> Computer:
    """
    Setup remote SSH Computer for CRYSTAL23 execution.

    Args:
        hostname: Remote hostname or IP address.
        username: SSH username.
        label: Computer label (defaults to 'ssh_{hostname}').
        workdir: Remote working directory.
        scheduler: Scheduler type ('slurm', 'pbs', 'sge', 'direct').
        port: SSH port.
        key_filename: Path to SSH private key.
        look_for_keys: Look for SSH keys in ~/.ssh/.
        mpirun_command: MPI run command. Defaults to ['mpirun', '-np', '{tot_num_mpiprocs}'].

    Returns:
        Configured and stored Computer instance.

    Example:
        >>> computer = setup_ssh_computer(
        ...     hostname="cluster.example.com",
        ...     username="user",
        ...     scheduler="slurm",
        ... )
    """
    from aiida import load_profile, orm

    load_profile()

    if label is None:
        label = f"ssh_{hostname}"

    # Check if computer already exists
    try:
        existing = orm.Computer.collection.get(label=label)
        return existing
    except Exception:
        pass

    # Default workdir
    if workdir is None:
        workdir = f"/home/{username}/aiida_work/"

    # Map scheduler type
    scheduler_map = {
        "slurm": "core.slurm",
        "pbs": "core.pbspro",
        "sge": "core.sge",
        "direct": "core.direct",
    }
    scheduler_type = scheduler_map.get(scheduler, f"core.{scheduler}")

    computer = orm.Computer(
        label=label,
        hostname=hostname,
        description=f"Remote SSH: {username}@{hostname}",
        transport_type="core.ssh",
        scheduler_type=scheduler_type,
        workdir=workdir,
    )

    # Configure mpirun command
    if mpirun_command is None:
        mpirun_command = ["mpirun", "-np", "{tot_num_mpiprocs}"]
    computer.set_mpirun_command(mpirun_command)

    computer.store()

    # Configure SSH transport
    config = {
        "username": username,
        "port": port,
        "look_for_keys": look_for_keys,
        "allow_agent": True,
    }
    if key_filename:
        config["key_filename"] = str(Path(key_filename).expanduser())

    computer.configure(**config)

    return computer


def setup_beefcake2_computer(
    username: str = "brian",
    node: str = "pve2",
) -> Computer:
    """
    Setup beefcake2 cluster Computer.

    This is a convenience function for the beefcake2 HPC cluster.

    Args:
        username: Cluster username.
        node: Cluster node (pve1, pve2, pve3).

    Returns:
        Configured Computer instance.
    """
    # Tailscale IPs for beefcake2 nodes
    tailscale_ips = {
        "pve1": "100.127.208.104",
        "pve2": "100.91.139.90",
        "pve3": None,  # Not configured yet
    }

    hostname = tailscale_ips.get(node)
    if hostname is None:
        raise ValueError(f"Node '{node}' not configured. Available: pve1, pve2")

    return setup_ssh_computer(
        hostname=hostname,
        username=username,
        label=f"beefcake2-{node}",
        workdir=f"/home/{username}/aiida_work/",
        scheduler="slurm",
        mpirun_command=["mpirun", "-np", "{tot_num_mpiprocs}"],
    )


def list_computers() -> list[dict]:
    """
    List all configured AiiDA computers.

    Returns:
        List of computer info dictionaries.
    """
    from aiida import load_profile, orm

    load_profile()

    computers = []
    for computer in orm.Computer.collection.all():
        computers.append(
            {
                "label": computer.label,
                "hostname": computer.hostname,
                "transport_type": computer.transport_type,
                "scheduler_type": computer.scheduler_type,
                "is_configured": computer.is_configured,
            }
        )

    return computers


def test_computer(label: str) -> bool:
    """
    Test connection to a computer.

    Args:
        label: Computer label.

    Returns:
        True if connection successful.
    """
    from aiida import load_profile, orm

    load_profile()

    computer = orm.Computer.collection.get(label=label)

    try:
        with computer.get_transport() as transport:
            transport.whoami()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Setup AiiDA computers for CRYSTAL23")
    parser.add_argument(
        "--localhost",
        action="store_true",
        help="Setup localhost computer",
    )
    parser.add_argument(
        "--beefcake2",
        type=str,
        metavar="NODE",
        help="Setup beefcake2 computer (pve1, pve2)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List configured computers",
    )
    parser.add_argument(
        "--test",
        type=str,
        metavar="LABEL",
        help="Test computer connection",
    )

    args = parser.parse_args()

    if args.localhost:
        computer = setup_localhost_computer()
        print(f"Configured localhost computer: {computer.label}")
    elif args.beefcake2:
        computer = setup_beefcake2_computer(node=args.beefcake2)
        print(f"Configured beefcake2 computer: {computer.label}")
    elif args.list:
        computers = list_computers()
        for c in computers:
            status = "configured" if c["is_configured"] else "NOT configured"
            print(f"  {c['label']}: {c['hostname']} ({c['scheduler_type']}) [{status}]")
    elif args.test:
        if test_computer(args.test):
            print(f"Connection to '{args.test}' successful")
        else:
            print(f"Connection to '{args.test}' FAILED")
    else:
        parser.print_help()
