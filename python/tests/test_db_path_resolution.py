"""Tests for find_database_path() resolution parity with Rust (crystalmath-pha).

Mirrors the order in src/bridge.rs::find_database_path so the Python CLI/server
open the same .crystal_tui.db as the Rust TUI. Tests are hermetic: they chdir to
a tmp dir (no Cargo.toml ancestors) and control CRYSTAL_TUI_DB explicitly, so they
never reach the real home/platform-data-dir branches.
"""

from __future__ import annotations

from crystalmath.backends import find_database_path


def test_env_var_existing_file_wins(tmp_path, monkeypatch):
    db = tmp_path / "explicit.db"
    db.write_text("")
    monkeypatch.setenv("CRYSTAL_TUI_DB", str(db))
    assert find_database_path() == str(db)


def test_env_var_nonexistent_but_creatable(tmp_path, monkeypatch):
    db = tmp_path / "sub" / "new.db"  # parent absent but creatable
    monkeypatch.setenv("CRYSTAL_TUI_DB", str(db))
    assert find_database_path() == str(db)
    assert db.parent.exists()


def test_cwd_crystal_tui_db(tmp_path, monkeypatch):
    monkeypatch.delenv("CRYSTAL_TUI_DB", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".crystal_tui.db").write_text("")
    assert find_database_path() == str(tmp_path / ".crystal_tui.db")


def test_cwd_tui_subdir(tmp_path, monkeypatch):
    monkeypatch.delenv("CRYSTAL_TUI_DB", raising=False)
    monkeypatch.chdir(tmp_path)
    tui = tmp_path / "tui"
    tui.mkdir()
    (tui / ".crystal_tui.db").write_text("")
    assert find_database_path() == str(tui / ".crystal_tui.db")


def test_env_var_beats_cwd(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit.db"
    explicit.write_text("")
    monkeypatch.setenv("CRYSTAL_TUI_DB", str(explicit))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".crystal_tui.db").write_text("")
    assert find_database_path() == str(explicit)
