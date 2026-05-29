# -*- coding: utf-8 -*-
{
    "name": "Neon Doc-Gen Engine",
    # P-B13 -- shared Claude-API doc-gen adapter for B3 (deployment
    # plans), B4 (sub-hire drafts), B5 (reconciliation). Lives in a
    # standalone module so non-neon_dashboard callers (neon_jobs,
    # neon_finance) can import the adapter without pulling the whole
    # dashboard stack as a dependency.
    "version": "17.0.1.0.0",
    "summary": "Claude API doc-generation engine -- shared adapter "
               "for B3/B4/B5 high-value document generation.",
    "description": """
Neon Doc-Gen Engine (P-B13)
===========================

Provides a single ClaudeDocGenAdapter callable by any module that
needs structured-JSON output from the Anthropic Messages API.

Separation of concerns (per gate-1 D1):
  - Groq adapter (neon_dashboard.models.ai.groq_adapter +
    groq_chat_adapter): high-frequency insights + chat. Rate-limited
    daily. Tuned for tool calls.
  - Claude doc-gen adapter (HERE): low-frequency, high-value
    structured document generation. No tool-calling. Strict JSON
    out. Per-call usage recorded on the provider record.

⚠️ DECISION (B13, D1): standalone module. Phase 8A encryption
pattern is COPIED inline (the helper lives only in neon_dashboard
which we deliberately do not depend on -- B3 lives in neon_jobs +
neon_finance which would create a circular pull through
neon_dashboard).

⚠️ DECISION (B13, D2): direct requests.post to
https://api.anthropic.com/v1/messages -- no SDK dependency, matches
the GroqAdapter precedent (thin deps, mock-friendly).
    """,
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Neon/AI",
    "license": "LGPL-3",
    "depends": [
        "base",
        # neon_core supplies group_neon_superuser (the only group
        # allowed to read/write provider config + the api key).
        "neon_core",
    ],
    "data": [
        # Security first so the ACL exists before the seed loads.
        "security/ir.model.access.csv",
        # Provider seed -- one Anthropic row, noupdate=1.
        "data/neon_doc_gen_provider_seed.xml",
        # Wizard view (paste-the-key dialog) loads before the
        # provider form view that references its action.
        "wizards/neon_doc_gen_set_key_wizard_views.xml",
        # Provider form + tree.
        "views/neon_doc_gen_provider_views.xml",
        "views/neon_doc_gen_menu.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
