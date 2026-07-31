"""Shared LLM plumbing: an Instructor-wrapped client and token accounting."""
from __future__ import annotations

from dataclasses import dataclass, field

import instructor
from openai import OpenAI

from app.config import get_settings


def raw_client() -> OpenAI:
    settings = get_settings()
    if not settings.llm_configured:
        raise RuntimeError("OPENAI_API_KEY is not set — copy .env.example to .env.")
    return OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)


def instructor_client() -> instructor.Instructor:
    """Structured output that survives whichever model the proxy routes to.

    MD_JSON asks for a ```json block and extracts the JSON from it. Gemini wraps
    its output in fences and Qwen returns it bare; MD_JSON handles both, while
    plain JSON mode chokes on the fences.
    """
    return instructor.from_openai(raw_client(), mode=instructor.Mode.MD_JSON)


@dataclass
class TokenUsage:
    """Accumulates cost across the several LLM round-trips one report takes."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    models: list[str] = field(default_factory=list)

    def add(self, completion) -> None:
        self.llm_calls += 1
        model = getattr(completion, "model", None)
        if model and model not in self.models:
            self.models.append(model)
        usage = getattr(completion, "usage", None)
        if usage:
            self.prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
            self.completion_tokens += getattr(usage, "completion_tokens", 0) or 0
            self.total_tokens += getattr(usage, "total_tokens", 0) or 0

    def merge(self, other: "TokenUsage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        self.llm_calls += other.llm_calls
        for m in other.models:
            if m not in self.models:
                self.models.append(m)

    def as_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "llm_calls": self.llm_calls,
            "models": self.models,
        }
