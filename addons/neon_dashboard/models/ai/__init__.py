# -*- coding: utf-8 -*-
"""Phase 8A.M11 -- AI Insights provider abstraction.

Plain-Python module (not an Odoo models package). Loaded by the
sibling neon_dashboard_ai_provider.py + neon_dashboard_insight.py
Models which orchestrate calls into the adapters below.

⚠️ DECISION (M11, marker inline): adapters + orchestrator are
plain Python classes, NOT AbstractModels. Per addendum §5.3:
`InsightOrchestrator(env).generate_for_dashboard(dashboard)`.
The cron + manual-refresh path instantiates the orchestrator
from a thin @api.model wrapper on neon.dashboard.ai.provider.
Keeps the adapter layer pure-Python (easy to unit-test via
mocked requests.post) without the Odoo registry overhead.

M11 ships 2 adapters: groq + rule_based. M11.1 will add
anthropic, google, ollama as siblings.
"""
from . import base_adapter
from . import groq_adapter
from . import rule_based_adapter
from . import insight_orchestrator
# P12.M1 -- AI Sales Copilot
from . import chat_session_message
from . import tool_registry
from . import tools                  # registers @ai_tool decorators
from . import groq_chat_adapter
from . import chat_orchestrator
