#!/usr/bin/env python3
"""Offline docs checker.

Modes:
  --stale-only : fail only on references to the archived pre-redesign paths
                 `.planning/` or `REFACTOR/` (must use archive/...). BLOCKING in CI.
  (default)    : also report broken relative markdown links (report-only in CI).

Skips fenced code blocks, inline code, and network/anchor/mailto links so the
output is deterministic and false-positive-free.
"""
from __future__ import annotations
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOTS = ["docs", "README.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md"]
SKIP_DIRS = {"archive", ".git", ".venv", "node_modules", "site-packages", "target"}
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
STALE = re.compile(r"(^|[^a-zA-Z0-9_/])(\.planning|REFACTOR)/")
STALE_ONLY = "--stale-only" in sys.argv[1:]

def md_files():
    for r in ROOTS:
        p = ROOT / r
        if p.is_file() and p.suffix == ".md":
            yield p
        elif p.is_dir():
            for f in p.rglob("*.md"):
                if not any(part in SKIP_DIRS for part in f.relative_to(ROOT).parts):
                    yield f

def strip_code(text: str) -> list[str]:
    """Return lines with fenced code blocks blanked and inline-code spans removed."""
    out, in_fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else re.sub(r"`[^`]*`", "", line))
    return out

stale_hits, broken = [], []
for f in md_files():
    raw = f.read_text(encoding="utf-8", errors="replace")
    for i, line in enumerate(strip_code(raw), 1):
        if STALE.search(line):
            stale_hits.append(f"{f.relative_to(ROOT)}:{i}: {line.strip()[:100]}")
        if STALE_ONLY:
            continue
        for m in LINK.finditer(line):
            tgt = m.group(1).strip()
            if tgt.startswith(("http://", "https://", "mailto:", "#", "<")):
                continue
            path_part = tgt.split("#", 1)[0].split("?", 1)[0].strip()
            if not path_part:
                continue
            if not (f.parent / path_part).resolve().exists():
                broken.append(f"{f.relative_to(ROOT)}:{i}: broken link -> {tgt}")

ok = True
if stale_hits:
    ok = False
    print("FAIL: stale archived-path references (use archive/planning or archive/REFACTOR):")
    for h in stale_hits: print("  " + h)
if broken:
    print(f"\nREPORT: {len(broken)} broken relative markdown link(s) (pre-existing debt; not blocking):")
    for b in broken: print("  " + b)
if ok and not broken:
    print("doc-link check: OK")
elif ok:
    print(f"\ndoc-link check: no stale paths (the {len(broken)} broken links above are report-only).")
sys.exit(0 if ok else 1)
