# -*- coding: utf-8 -*-
"""Phase 8A.M11 -- BaseAdapter contract + dataclass shapes.

Every concrete adapter (Groq, RuleBased, M11.1's Anthropic /
Google / Ollama) implements `generate_insights(context)` and
`health_check()`. The orchestrator routes calls + handles
fallback.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class InsightItem:
    """One row in the AI Insights widget.

    priority:    1 = highest. Used for sort + visual emphasis.
    title:       one-line headline (max ~80 chars).
    detail:      2-3 sentence explanation (max ~300 chars).
    source_ref:  {model: <odoo model name>, res_id: <int>} for
                 click-through, or None for general advisory
                 with no specific source record.
    """
    priority: int
    title: str
    detail: str
    source_ref: Optional[dict] = None

    def to_dict(self):
        return {
            "priority": int(self.priority),
            "title": str(self.title or ""),
            "detail": str(self.detail or ""),
            "source_ref": self.source_ref,
        }


@dataclass
class AdapterResult:
    """Wraps an adapter call result. The orchestrator inspects
    `success` to decide whether to fall back."""
    success: bool
    insights: List[InsightItem] = field(default_factory=list)
    raw_response: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    error_message: Optional[str] = None

    def insights_as_dicts(self):
        return [i.to_dict() for i in self.insights]


class BaseAdapter(ABC):
    """Contract every AI provider adapter must implement.

    Adapters MUST NOT raise exceptions out of generate_insights or
    health_check -- they catch all and surface via the
    AdapterResult / boolean shape. The orchestrator relies on
    this contract to keep the cron + dashboard load path
    crash-free.

    The ``provider`` argument is the neon.dashboard.ai.provider
    record. For the rule-based adapter (no config row), pass
    None and have the adapter not touch ``self.provider``.
    """

    def __init__(self, provider_record):
        self.provider = provider_record

    @abstractmethod
    def generate_insights(self, dashboard_context: dict) -> AdapterResult:
        """Generate 3-5 InsightItems from the dashboard context
        dict. Return AdapterResult with success=False + error_message
        on any failure; never re-raise."""

    @abstractmethod
    def health_check(self) -> bool:
        """Quick reachability + auth probe. Return True if the
        provider is usable; False otherwise. Must not re-raise."""
