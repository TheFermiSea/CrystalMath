"""Security tests for SQLiteJobStore SQL-identifier validation (crystalmath-1tg).

Column/field identifiers cannot be parameterized in SQL, so they are interpolated
directly into the statement. These tests assert that every interpolation site
validates the identifier against a strict allowlist, rejecting injection attempts.
"""

from __future__ import annotations

import pytest

from crystalmath.integrations.jobflow_store import SQLiteJobStore, _validate_column


class TestColumnValidation:
    def test_validate_column_accepts_identifiers(self):
        assert _validate_column("uuid", context="x") == "uuid"
        assert _validate_column("state", context="x") == "state"
        assert _validate_column("_private", context="x") == "_private"

    def test_validate_column_rejects_injection(self):
        for bad in [
            "uuid; DROP TABLE jobflow_jobs",
            "1 OR 1=1",
            "name)--",
            "a b",
            "",
            None,
            123,
        ]:
            with pytest.raises(ValueError):
                _validate_column(bad, context="distinct field")


class TestDistinctSqlInjection:
    def _store(self, tmp_path) -> SQLiteJobStore:
        store = SQLiteJobStore(db_path=tmp_path / "jobs.db")
        store.connect()
        return store

    def test_distinct_rejects_malicious_field(self, tmp_path):
        store = self._store(tmp_path)
        try:
            with pytest.raises(ValueError, match="Invalid column name"):
                store.distinct("uuid; DROP TABLE jobflow_jobs")
        finally:
            store.close()

    def test_distinct_rejects_malicious_criteria_key(self, tmp_path):
        store = self._store(tmp_path)
        try:
            with pytest.raises(ValueError, match="Invalid column name"):
                store.distinct("uuid", criteria={"1=1); DROP TABLE x;--": "y"})
        finally:
            store.close()

    def test_distinct_valid_field_returns_values(self, tmp_path):
        store = self._store(tmp_path)
        try:
            store.update(
                [
                    {"uuid": "a", "name": "shared"},
                    {"uuid": "b", "name": "shared"},
                    {"uuid": "c", "name": "unique"},
                ]
            )
            assert set(store.distinct("name")) == {"shared", "unique"}
        finally:
            store.close()

    def test_query_rejects_malicious_sort_key(self, tmp_path):
        store = self._store(tmp_path)
        try:
            with pytest.raises(ValueError, match="Invalid column name"):
                list(store.query(sort={"name; DROP TABLE x": 1}))
        finally:
            store.close()
