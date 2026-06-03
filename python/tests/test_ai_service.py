"""Tests for AIService construction (crystalmath-6pb).

AI features rely on the optional ``crystalmath[llm]`` extra (the Anthropic SDK),
so the whole module is skipped when it is not installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("anthropic", reason="crystalmath[llm] extra not installed")


def test_aiservice_requires_api_key(monkeypatch):
    """Constructing AIService without any key fails fast with a clear error."""
    from crystalmath.ai.service import AIService

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        AIService()


def test_aiservice_accepts_explicit_key(monkeypatch):
    """An explicit key is accepted even when the env var is unset."""
    from crystalmath.ai.service import AIService

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    service = AIService(api_key="sk-ant-test-fake")
    assert service.model


def test_aiservice_uses_env_key(monkeypatch):
    """The ANTHROPIC_API_KEY environment variable satisfies the key requirement."""
    from crystalmath.ai.service import AIService

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-fake")
    service = AIService()
    assert service.model
