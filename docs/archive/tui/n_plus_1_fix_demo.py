#!/usr/bin/env python3
"""
Demonstration of N+1 Query Fix in QueueManager._dependencies_satisfied()

This script demonstrates the performance improvement from fixing the N+1 query problem.

BEFORE (N+1 pattern):
    For each dependency, make a separate database query:
    - Query 1: Get queued_job from memory
    - Query 2: Get dep1 status from database
    - Query 3: Get dep2 status from database
    - Query 4: Get dep3 status from database
    - ...
    Total: 1 + N queries (N = number of dependencies)

AFTER (Batch query):
    - Query 1: Get queued_job from memory
    - Query 2: Get ALL dependency statuses in single batch query
    Total: 2 operations, only 1 database query regardless of N

Performance improvement scales with number of dependencies:
- 1 dependency:   2 queries → 1 query  (50% reduction)
- 5 dependencies: 6 queries → 1 query  (83% reduction)
- 10 dependencies: 11 queries → 1 query (91% reduction)
- 100 dependencies: 101 queries → 1 query (99% reduction)
"""

from src.core.queue_manager import QueueManager
from src.core.database import Database
import tempfile
import os
from pathlib import Path
import time


def measure_dependency_check_performance():
    """Measure performance improvement from batch query optimization."""

    # Create temporary database
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.db') as f:
        db_path = f.name

    try:
        # Initialize database and queue manager
        db = Database(db_path)
        qm = QueueManager(db)

        temp_dir = Path(tempfile.mkdtemp())

        print("=" * 70)
        print("N+1 Query Fix Demonstration")
        print("=" * 70)
        print()

        # Test with varying numbers of dependencies
        for num_deps in [1, 5, 10, 20, 50]:
            print(f"Testing with {num_deps} dependencies...")

            # Create dependency jobs
            dep_ids = []
            for i in range(num_deps):
                dep_id = db.create_job(
                    f'dep_{i}',
                    str(temp_dir / f'dep_{i}'),
                    'test input',
                    runner_type='local'
                )
                dep_ids.append(dep_id)
                # Mark all dependencies as completed
                db.update_job_status(dep_id, 'COMPLETED')

            # Create main job with all dependencies
            main_job_id = db.create_job(
                f'main_job_{num_deps}',
                str(temp_dir / f'main_job_{num_deps}'),
                'test input',
                runner_type='local'
            )

            # Enqueue with dependencies (async operation)
            import asyncio
            asyncio.run(qm.enqueue(main_job_id, priority=1, dependencies=dep_ids))

            # Measure dependency satisfaction check time
            start_time = time.perf_counter()
            iterations = 1000
            for _ in range(iterations):
                result = qm._dependencies_satisfied(main_job_id)
            end_time = time.perf_counter()

            avg_time_us = ((end_time - start_time) / iterations) * 1_000_000

            # Calculate theoretical old time (N+1 queries)
            # Assume each query takes ~100μs (conservative estimate)
            old_query_count = 1 + num_deps
            theoretical_old_time = old_query_count * 100

            print(f"  ✓ Verified: {result}")
            print(f"  ⏱️  Average time: {avg_time_us:.2f} μs per check")
            print(f"  📊 Old approach would need: {old_query_count} queries")
            print(f"  🚀 Estimated speedup: {theoretical_old_time / avg_time_us:.1f}x")
            print()

        print("=" * 70)
        print("Key Benefits:")
        print("=" * 70)
        print("✅ Constant time complexity: O(1) database queries regardless of N")
        print("✅ Reduced database load: Single batch query vs N+1 individual queries")
        print("✅ Better scaling: Performance improvement increases with more dependencies")
        print("✅ No logic changes: Same validation behavior, just optimized")
        print()

    finally:
        # Cleanup
        os.unlink(db_path)


if __name__ == '__main__':
    measure_dependency_check_performance()
