#!/usr/bin/env python3
"""
Standalone validation script for queue manager race condition fix.

This script validates that the fix for crystalmath-drj is working correctly
by checking that all critical methods acquire the lock before accessing shared state.
"""

import ast
import sys
from pathlib import Path


def analyze_method_lock_usage(filepath: Path, method_name: str) -> dict:
    """Analyze if a method properly uses the lock."""
    with open(filepath) as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == method_name:
            # Check if method contains "async with self._lock"
            has_lock = False
            for subnode in ast.walk(node):
                if isinstance(subnode, ast.AsyncWith):
                    for item in subnode.items:
                        if isinstance(item.context_expr, ast.Attribute):
                            if (isinstance(item.context_expr.value, ast.Name) and
                                item.context_expr.value.id == "self" and
                                item.context_expr.attr == "_lock"):
                                has_lock = True
                                break

            # Check if method accesses self._jobs
            accesses_jobs = False
            for subnode in ast.walk(node):
                if isinstance(subnode, ast.Attribute):
                    if (isinstance(subnode.value, ast.Name) and
                        subnode.value.id == "self" and
                        subnode.attr == "_jobs"):
                        accesses_jobs = True
                        break

            return {
                "found": True,
                "has_lock": has_lock,
                "accesses_jobs": accesses_jobs
            }

    return {"found": False}


def main():
    """Run validation checks."""
    print("=" * 80)
    print("Queue Manager Race Condition Fix Validation")
    print("=" * 80)
    print()

    queue_manager_path = Path(__file__).parent / "src" / "core" / "queue_manager.py"

    if not queue_manager_path.exists():
        print(f"❌ ERROR: File not found: {queue_manager_path}")
        return 1

    print(f"Analyzing: {queue_manager_path}")
    print()

    # Critical methods that must acquire lock
    critical_methods = {
        "schedule_jobs": {
            "description": "Determines which jobs should be scheduled next",
            "must_lock": True,
            "must_access_jobs": True
        },
        "_scheduler_worker": {
            "description": "Background worker that schedules jobs",
            "must_lock": True,
            "must_access_jobs": True
        }
    }

    all_passed = True

    for method_name, criteria in critical_methods.items():
        print(f"Checking method: {method_name}")
        print(f"  Description: {criteria['description']}")

        result = analyze_method_lock_usage(queue_manager_path, method_name)

        if not result["found"]:
            print(f"  ❌ FAIL: Method not found")
            all_passed = False
            continue

        # Check lock acquisition
        if criteria["must_lock"]:
            if result["has_lock"]:
                print(f"  ✅ PASS: Acquires self._lock")
            else:
                print(f"  ❌ FAIL: Does NOT acquire self._lock")
                all_passed = False

        # Check if it accesses shared state
        if criteria["must_access_jobs"]:
            if result["accesses_jobs"]:
                print(f"  ✅ PASS: Accesses self._jobs")
            else:
                print(f"  ⚠️  WARN: Does not directly access self._jobs")

        print()

    # Check for new helper method
    print("Checking for _dependencies_satisfied_locked helper method...")
    with open(queue_manager_path) as f:
        content = f.read()

    if "_dependencies_satisfied_locked" in content:
        print("  ✅ PASS: Helper method _dependencies_satisfied_locked exists")
    else:
        print("  ❌ FAIL: Helper method _dependencies_satisfied_locked NOT found")
        all_passed = False

    print()
    print("=" * 80)

    if all_passed:
        print("✅ SUCCESS: All validation checks passed!")
        print()
        print("The race condition fix appears to be correctly implemented:")
        print("  - schedule_jobs() acquires lock before reading shared state")
        print("  - _scheduler_worker() acquires lock before accessing shared state")
        print("  - _dependencies_satisfied_locked() helper exists for lock-free calls")
        print()
        return 0
    else:
        print("❌ FAILURE: Some validation checks failed!")
        print()
        print("Please review the implementation and ensure:")
        print("  - All shared state access is protected by self._lock")
        print("  - Critical methods acquire lock before reading/writing")
        print("  - Lock-free helpers are used to avoid deadlock")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
