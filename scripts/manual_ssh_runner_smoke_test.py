#!/usr/bin/env python3
"""Manual, real-hardware smoke test for SSHRunner.

NOT part of the automated test suite (python/tests/test_ssh_runner.py covers
that with mocks) — this makes a real SSH connection and runs a real CRYSTAL23
calculation. Requires:
  - Passwordless SSH to the target host already working
  - A real, working CRYSTAL23 install on the target (built via
    install-crystal23-optimized.sh; see docs/architecture and the
    ultrafastlab-1 USER_GUIDE.md this was developed alongside)

Usage:
    uv run python scripts/manual_ssh_runner_smoke_test.py [--ntasks N] [--host HOST]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path

from crystalmath._vendor.core.codes import DFTCode
from crystalmath._vendor.core.connection_manager import ConnectionManager
from crystalmath._vendor.runners.base import JobStatus, RunnerConfig
from crystalmath._vendor.runners.ssh_runner import SSHJobConfig, SSHRunner

# The official CRYSTAL Tutorial Project's MgO bulk STO-3G example (verified
# working against the real ultrafastlab-1 build during development of this
# script — see docs/architecture/ for provenance).
MGO_D12 = """MgO bulk
CRYSTAL
0 0 0
225
4.21
2
12 0. 0. 0.
8 0.5 0.5 0.5
END
12 3
1 0 3 2. 0.
1 1 3 8. 0.
1 1 3 2. 0.
8 2
1 0 3 2. 0.
1 1 3 6. 0.
99 0
END
SHRINK
8 8
END
"""


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="ultrafastlab-1.tail0bd2a2.ts.net")
    parser.add_argument("--user", default="jens")
    parser.add_argument("--ntasks", type=int, default=8, help="MPI ranks (0 = serial)")
    parser.add_argument("--remote-scratch", default="/tmp/crystalmath_ssh_runner_smoke_test")
    args = parser.parse_args()

    manager = ConnectionManager()
    await manager.start()
    manager.register_cluster(
        cluster_id=1,
        host=args.host,
        port=22,
        username=args.user,
        key_file=Path.home() / ".ssh" / "id_ed25519",
    )

    runner = SSHRunner(
        connection_manager=manager,
        cluster_id=1,
        dft_code=DFTCode.CRYSTAL,
        remote_scratch_base=args.remote_scratch,
        config=RunnerConfig(dft_code=DFTCode.CRYSTAL),
    )

    with tempfile.TemporaryDirectory() as tmp:
        work_dir = Path(tmp)
        input_file = work_dir / "mgo.d12"
        input_file.write_text(MGO_D12)

        job_config = SSHJobConfig(
            ntasks=args.ntasks,
            threads=1,
            environment_setup="source /opt/CRYSTAL23/setup-crystal23.sh",
        )

        print(f"=> Submitting to {args.user}@{args.host} (ntasks={args.ntasks})...")
        handle = await runner.submit_job(
            job_id=1, input_file=input_file, work_dir=work_dir, config=job_config
        )
        print(f"=> Job handle: {handle}")

        status = await runner.wait_for_completion(handle, poll_interval=1.0, timeout=120.0)
        print(f"=> Final status: {status}")

        results_dir = work_dir / "results"
        await runner.retrieve_results(handle, results_dir, cleanup=False)

        out_files = list(results_dir.glob("*.out"))
        if not out_files:
            print("!! No output file retrieved", file=sys.stderr)
            return 1

        out_text = out_files[0].read_text()
        print(f"=> Retrieved {out_files[0].name} ({len(out_text)} bytes)")

        energy_lines = [line for line in out_text.splitlines() if "TOTAL ENERGY(" in line]
        termination = "EEEEEEEEEE TERMINATION" in out_text

        print(f"=> Energy line: {energy_lines[-1] if energy_lines else '(none found)'}")
        print(f"=> Clean termination: {termination}")

        await manager.stop()

        success = status == JobStatus.COMPLETED and termination and bool(energy_lines)
        print(f"\n{'PASS' if success else 'FAIL'}: real end-to-end SSHRunner calculation")
        return 0 if success else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
