"""AI/LLM integration module for CrystalMath.

This module provides AI-powered features like job error diagnosis
and interactive chat assistance. All LLM dependencies are optional
and the module gracefully degrades when they are not installed.

Install with: pip install crystalmath[llm]
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .service import AIService as AIServiceType

try:
    from .service import AIService

    AI_AVAILABLE = True
except ImportError:
    AIService = None  # type: ignore[assignment, misc]
    AI_AVAILABLE = False


def get_ai_service(api_key: str | None = None) -> AIServiceType:
    """Get an AIService instance.

    Args:
        api_key: Anthropic API key. If None, uses ANTHROPIC_API_KEY env var.

    Returns:
        AIService instance.

    Raises:
        RuntimeError: If LLM dependencies are not installed.
    """
    if not AI_AVAILABLE or AIService is None:
        msg = "AI features require the 'llm' extra. Install with: pip install crystalmath[llm]"
        raise RuntimeError(msg)
    return AIService(api_key=api_key)


__all__ = ["AIService", "AI_AVAILABLE", "get_ai_service"]
