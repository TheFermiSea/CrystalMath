"""AI Service for LLM-powered assistance in CrystalMath.

Provides job error analysis, parameter suggestions, and general DFT chat.
"""

from __future__ import annotations

import os
from typing import Any

from anthropic import Anthropic

# System prompt for CRYSTAL23/DFT expertise
SYSTEM_PROMPT = """\
You are an expert assistant for CRYSTAL23 density functional theory (DFT) calculations.
You help users:
- Diagnose and fix failed calculations
- Optimize input parameters for convergence
- Understand error messages and output files
- Suggest appropriate basis sets and computational settings

When analyzing errors, be specific about:
1. The likely cause of the failure
2. Concrete steps to fix it
3. Any input file changes needed (show exact syntax)

Keep responses concise and actionable. Use technical language appropriate for computational chemists.
"""


class AIService:
    """Service for AI-powered job analysis and chat.

    Uses the Anthropic Claude API for intelligent assistance with
    CRYSTAL23 DFT calculations.

    Attributes:
        client: Anthropic API client instance.
        model: Model identifier to use for completions.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        """Initialize AIService.

        Args:
            api_key: Anthropic API key. If None, uses ANTHROPIC_API_KEY env var.
            model: Model identifier. Defaults to claude-sonnet-4-20250514.
        """
        self.client = Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.model = model

    def diagnose_job(
        self,
        job_pk: int,
        error_output: str,
        input_file: str | None = None,
        additional_context: dict[str, Any] | None = None,
    ) -> str:
        """Analyze a failed job and suggest fixes.

        Args:
            job_pk: Primary key of the failed job.
            error_output: Error message or output from the failed calculation.
            input_file: Optional input file contents for context.
            additional_context: Optional dict with extra job metadata.

        Returns:
            AI-generated diagnosis and suggested fixes.
        """
        # Build context message
        context_parts = [
            f"Job PK: {job_pk}",
            f"Error Output:\n```\n{error_output}\n```",
        ]

        if input_file:
            context_parts.append(f"Input File:\n```\n{input_file}\n```")

        if additional_context:
            context_parts.append(f"Additional Context: {additional_context}")

        user_message = (
            "Please analyze this failed CRYSTAL23 calculation and provide:\n"
            "1. Likely cause of failure\n"
            "2. Suggested fixes\n"
            "3. Any input file modifications needed\n\n" + "\n\n".join(context_parts)
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        # Extract text from response
        return response.content[0].text

    def chat(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> str:
        """General chat with DFT context.

        Args:
            message: User's message/question.
            context: Optional dict with current job/calculation context.
            conversation_history: Optional list of previous messages for multi-turn.

        Returns:
            AI-generated response.
        """
        # Build messages list
        messages: list[dict[str, str]] = []

        # Add conversation history if provided
        if conversation_history:
            messages.extend(conversation_history)

        # Build user message with context
        if context:
            user_content = f"Current context: {context}\n\nUser question: {message}"
        else:
            user_content = message

        messages.append({"role": "user", "content": user_content})

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=messages,
        )

        return response.content[0].text

    def suggest_parameters(
        self,
        calculation_type: str,
        system_description: str,
    ) -> str:
        """Suggest input parameters for a calculation type.

        Args:
            calculation_type: Type of calculation (e.g., 'geometry optimization', 'band structure').
            system_description: Description of the system being studied.

        Returns:
            AI-generated parameter suggestions.
        """
        user_message = (
            f"I'm setting up a {calculation_type} calculation in CRYSTAL23 for:\n"
            f"{system_description}\n\n"
            "Please suggest appropriate:\n"
            "1. SCF convergence settings (TOLDEE, LEVSHIFT, etc.)\n"
            "2. K-point sampling (SHRINK)\n"
            "3. Any calculation-specific keywords\n"
            "4. Potential convergence issues to watch for"
        )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )

        return response.content[0].text
