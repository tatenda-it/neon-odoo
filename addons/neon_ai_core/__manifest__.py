# -*- coding: utf-8 -*-
{
    "name": "Neon AI Core",
    # B11 / PRE-WA-0 -- neutral home for the shared AI engine extracted
    # out of neon_dashboard so no consumer depends on another. Holds the
    # generic machinery: provider catalog (config + key mgmt + health),
    # Groq tool-calling chat adapter, tool-registry mechanism, the
    # two-phase write engine + chat audit models, and a role-resolver
    # seam. Concrete business tools + the dashboard insight subsystem
    # stay with their data owners (neon_dashboard).
    #
    # 17.0.1.0.0 = initial extraction. Definition-ownership shift ONLY:
    # every moved model keeps its _name (neon.finance.ai.chat.*,
    # neon.dashboard.ai.provider) so no table is renamed/copied/dropped.
    # Consumers: neon_dashboard (live Copilot), neon_channels (WA-0).
    "version": "17.0.1.0.0",
    "summary": "Shared AI engine -- provider abstraction, tool-calling "
               "chat orchestrator, two-phase write guardrail, chat "
               "audit models. Neutral core for neon_dashboard + "
               "neon_channels (WhatsApp).",
    "description": """
Neon AI Core (B11 / PRE-WA-0)
=============================

Neutral module that hoists the shared AI engine out of neon_dashboard
so multiple consumers (the live dashboard Copilot, the WhatsApp rails,
and a future in-Odoo assistant) build on it without depending on each
other.

What lives here (the generic engine):
  * neon.dashboard.ai.provider -- provider catalog: config, API-key
    management (ir.config_parameter-backed), exactly-one-default
    constraint, health-check. Generic half ONLY; the insight-
    generation entry points (cron / rpc / test-connection) are added
    back by neon_dashboard via _inherit.
  * GroqChatAdapter -- OpenAI-compatible tool-calling chat transport.
  * tool_registry -- @ai_tool decorator, dispatch, per-user group
    filter, variant-scoped advertisement, write-executor registry.
  * neon.finance.ai.chat.session / .message -- append-only chat audit.
  * neon.finance.ai.chat.write.log -- two-phase write guardrail
    (propose -> confirm -> execute) audit. APPEND-ONLY (perm_unlink=0).
  * ChatOrchestrator -- multi-turn LLM<->tool loop + confirm/cancel.

What deliberately STAYS in neon_dashboard:
  * The insight subsystem (BaseAdapter contract, GroqAdapter insights,
    RuleBasedAdapter, InsightOrchestrator, neon.dashboard.ai.insight).
  * The 14 READ + 4 WRITE business tools (they read neon_jobs /
    neon_finance / neon_training models).
  * The OWL chat panel + /neon/ai_chat controller + provider admin
    views + provider seed + insights cron.

Naming note: moved models keep their legacy _name prefixes
(neon.dashboard.* / neon.finance.*) deliberately -- a definition-
ownership shift, not a rename. Namespace cleanup to neon.ai.* is a
separately-gated, optional, cosmetic milestone (NOT this one).
    """,
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Neon/AI",
    "license": "LGPL-3",
    # mail intentionally NOT carried: none of the moved models inherit
    # mail.thread / mail.activity.mixin (session + message explicitly
    # avoid it; write.log + provider are plain models.Model). neon_core
    # supplies group_neon_superuser for the engine's ACL + role resolver.
    "depends": [
        "base",
        "neon_core",
    ],
    "data": [
        "security/ir.model.access.csv",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
