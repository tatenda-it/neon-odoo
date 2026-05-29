# -*- coding: utf-8 -*-
"""Phase 12.1 — AI Sales Copilot HTTP endpoints.

Two JSON endpoints used by the OWL chat panel:
- POST /neon/ai_chat/send  — send a user message + receive
  assistant response with tool cards.
- POST /neon/ai_chat/history — load existing conversation rows
  for the panel on mount.

⚠️ DECISION (M12.1, marker inline): use type='json' (Odoo's
JSON-RPC controller decorator) rather than type='http'+csrf=True.
JSON-RPC handles CSRF + JSON marshalling + permission checks more
cleanly than rolling our own. Matches the @http.route pattern
used elsewhere in Odoo internals.
"""
import json
import logging

from odoo import http
from odoo.http import request

from ..models.ai.chat_orchestrator import ChatOrchestrator


_logger = logging.getLogger(__name__)


# P12.M1.1 (D22) -- widened the chat ACL: Bookkeeper + Lead Tech
# tiers now see the panel alongside Sales + MD/OD. Crew tier stays
# excluded (no dashboard variant for them).
_CHAT_GROUPS = (
    "neon_jobs.group_neon_jobs_user",
    "neon_jobs.group_neon_jobs_manager",
    "neon_jobs.group_neon_jobs_crew_leader",
    "neon_core.group_neon_bookkeeper",
)


def _user_has_chat_access():
    user = request.env.user
    return any(user.has_group(g) for g in _CHAT_GROUPS)


class NeonAiChatController(http.Controller):

    @http.route(
        "/neon/ai_chat/send", type="json", auth="user", methods=["POST"],
    )
    def send(self, message=None, active_variant=None, **kw):
        if not _user_has_chat_access():
            return {"ok": False, "error": "access_denied"}
        text = (message or "").strip()
        if not text:
            return {"ok": False, "error": "empty_message"}
        user = request.env.user
        Session = request.env["neon.finance.ai.chat.session"].sudo()
        session = Session.get_or_create_for_user(user.id)
        orch = ChatOrchestrator(request.env)
        return orch.handle_user_message(
            user, session, text, active_variant=active_variant)

    @http.route(
        "/neon/ai_chat/history", type="json", auth="user",
        methods=["POST"],
    )
    def history(self, limit=50, **kw):
        if not _user_has_chat_access():
            return {"ok": False, "error": "access_denied"}
        user = request.env.user
        Session = request.env["neon.finance.ai.chat.session"].sudo()
        session = Session.get_or_create_for_user(user.id)
        Message = request.env["neon.finance.ai.chat.message"].sudo()
        rows = Message.search(
            [("session_id", "=", session.id)],
            order="created_at desc, id desc",
            limit=int(limit or 50),
        ).sorted("created_at")
        out = []
        for m in rows:
            entry = {
                "id": m.id,
                "role": m.role,
                "content": m.content or "",
                "created_at": (m.created_at.isoformat()
                                if m.created_at else ""),
                "is_fallback": bool(m.is_fallback),
            }
            if m.role == "tool" and m.content:
                try:
                    entry["tool_result"] = json.loads(m.content)
                    entry["tool_name"] = m.tool_name or ""
                except json.JSONDecodeError:
                    pass
            out.append(entry)
        return {
            "ok": True,
            "session_id": session.id,
            "messages": out,
        }

    @http.route(
        "/neon/ai_chat/toggle", type="json", auth="user",
        methods=["POST"],
    )
    def toggle(self, expanded=None, **kw):
        """Persist the user's chat-panel-expanded preference."""
        if not _user_has_chat_access():
            return {"ok": False, "error": "access_denied"}
        request.env.user.sudo().write(
            {"chat_panel_expanded": bool(expanded)})
        return {"ok": True,
                "chat_panel_expanded": bool(expanded)}

    # ==============================================================
    # P12.M2 -- two-phase write endpoints (D28).
    # ==============================================================
    @http.route(
        "/neon/ai_chat/confirm", type="json", auth="user",
        methods=["POST"],
    )
    def confirm(self, confirmation_token=None,
                active_variant=None, **kw):
        """Phase 2 -- execute the proposed write. Returns a result
        card payload (or an error card) the OWL component renders
        in place of the original confirmation card."""
        if not _user_has_chat_access():
            return {"ok": False, "error_code": "access_denied",
                    "error": "access_denied"}
        if not confirmation_token:
            return {"ok": False, "error_code": "missing_token",
                    "error": "confirmation_token is required."}
        user = request.env.user
        orch = ChatOrchestrator(request.env)
        return orch.confirm_pending_action(
            user, confirmation_token,
            active_variant=active_variant)

    @http.route(
        "/neon/ai_chat/cancel", type="json", auth="user",
        methods=["POST"],
    )
    def cancel(self, confirmation_token=None, **kw):
        """Phase 2 cancel path -- void the token, no execution."""
        if not _user_has_chat_access():
            return {"ok": False, "error_code": "access_denied",
                    "error": "access_denied"}
        if not confirmation_token:
            return {"ok": False, "error_code": "missing_token",
                    "error": "confirmation_token is required."}
        user = request.env.user
        orch = ChatOrchestrator(request.env)
        return orch.cancel_pending_action(user, confirmation_token)
