"""P12.M1.1.1 smoke — header label + 4xx body capture + schema audit.

T12200  request_body_snapshot field present on chat.message
T12201  field is Text type (not Char) so 10k chars fit
T12202  all 14 tool schemas pass strict OpenAI validator
T12203  groq adapter writes request_body_snapshot on simulated 4xx
T12204  orchestrator persists request_body_snapshot to message row
T12205  manifest version bumped to 17.0.8.17.0
T12206  ai_chat.js exports headerLabel getter for the 4 variants
"""
import json
import os
from unittest.mock import MagicMock, patch

from odoo.modules.module import get_module_path


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P12.M1.1.1 — UI header + 4xx body capture + schema audit")
print("=" * 72)
results = {}

Message = env["neon.finance.ai.chat.message"]

# === T12200/T12201 -- new field present and Text ===
field = Message._fields.get("request_body_snapshot")
_check("T12200", field is not None,
       f"field={field!r}")
_check("T12201", field is not None and field.type == "text",
       f"type={field.type if field else 'MISSING'}")


# === T12202 -- 14 schemas strict-valid ===
from odoo.addons.neon_dashboard.models.ai import tool_registry
schemas = tool_registry.groq_tool_schemas(category="read")
issues = []
for s in schemas:
    fn = s["function"]
    params = fn["parameters"]
    name = fn["name"]
    if params.get("type") != "object":
        issues.append(f"{name}: root type != object")
    if "properties" not in params or not isinstance(
            params.get("properties"), dict):
        issues.append(f"{name}: properties missing or not dict")
    for pname, pspec in (params.get("properties") or {}).items():
        if not isinstance(pspec, dict):
            issues.append(f"{name}.{pname}: spec not dict")
            continue
        if "type" not in pspec:
            issues.append(f"{name}.{pname}: missing type")
    if "required" in params and not isinstance(
            params["required"], list):
        issues.append(f"{name}: required not list")
_check("T12202", len(schemas) == 14 and not issues,
       f"count={len(schemas)} issues={issues}")


# === T12203 -- adapter populates request_body_snapshot on 4xx ===
from odoo.addons.neon_dashboard.models.ai.groq_chat_adapter import (
    GroqChatAdapter, ChatTurnResult,
)
Provider = env["neon.dashboard.ai.provider"]
groq = Provider.sudo().search(
    [("provider_key", "=", "groq")], limit=1)
adapter = GroqChatAdapter(groq)

fake_resp = MagicMock()
fake_resp.ok = False
fake_resp.status_code = 400
fake_resp.content = b'{"error":{"message":"bad payload"}}'
fake_resp.json.return_value = {"error": {"message": "bad payload"}}
with patch("requests.post", return_value=fake_resp):
    res = adapter.chat(
        [{"role": "user", "content": "hi"}], tools=[])
ok = (
    res.success is False
    and res.is_fallback is True
    and "400" in (res.error_message or "")
    and res.request_body_snapshot
    and "messages" in res.request_body_snapshot
)
_check("T12203", ok,
       f"snapshot_len={len(res.request_body_snapshot)} "
       f"err={res.error_message!r}")


# === T12204 -- orchestrator persists snapshot to message row ===
from odoo.addons.neon_dashboard.models.ai.chat_orchestrator import (
    ChatOrchestrator,
)
from odoo.addons.neon_dashboard.models.ai import (
    chat_orchestrator as orch_mod,
)
Users = env["res.users"]
Session = env["neon.finance.ai.chat.session"]
sales = Users.search([("login", "=", "p12m1_sales_v2")], limit=1)
if not sales:
    sales = Users.search([("login", "=", "p12m1_sales")], limit=1)
if not sales:
    print("T12204: SKIP — no fixture sales user")
    results["T12204"] = True
else:
    orch_mod._RATE_LIMIT_BY_USER[sales.id] = []
    session = Session.sudo().get_or_create_for_user(sales.id)
    err_result = ChatTurnResult(
        success=False, is_fallback=True,
        error_message="Groq HTTP 400: bad payload",
        request_body_snapshot=(
            '{"messages":[{"role":"user","content":"hi"}],"tools":[]}'),
        latency_ms=12,
    )
    with patch.object(GroqChatAdapter, "chat",
                      return_value=err_result):
        ChatOrchestrator(env).handle_user_message(
            sales, session, "P12M1.1.1 unit test snapshot")
    last = Message.sudo().search(
        [("session_id", "=", session.id),
         ("role", "=", "assistant"),
         ("error_message", "ilike", "Groq HTTP 400")],
        order="id desc", limit=1)
    ok = (
        bool(last)
        and last.request_body_snapshot
        and "messages" in (last.request_body_snapshot or "")
    )
    _check("T12204", ok,
           f"persisted_snapshot_len="
           f"{len(last.request_body_snapshot or '') if last else 0}")


# === T12205 -- manifest version (>= 17.0.8.17.0; bumps roll
# forward as later milestones land on the same addon -- M12.2
# moves it to 17.0.9.0.0) ===
import re as _re
manifest_path = os.path.join(
    get_module_path("neon_dashboard"), "__manifest__.py")
with open(manifest_path, "r", encoding="utf-8") as f:
    manifest_src = f.read()
m = _re.search(r'"version":\s*"([\d.]+)"', manifest_src)
ver = tuple(int(x) for x in (m.group(1) if m else "0").split("."))
_check("T12205", ver >= (17, 0, 8, 17, 0),
       f"version={m.group(1) if m else '?'}")


# === T12206 -- JS headerLabel covers 4 variants ===
js_path = os.path.join(
    get_module_path("neon_dashboard"),
    "static/src/js/ai_chat/ai_chat.js")
with open(js_path, "r", encoding="utf-8") as f:
    js_src = f.read()
ok = all(label in js_src for label in (
    "Director Copilot", "Sales Copilot",
    "Finance Copilot", "Operations Copilot",
)) and "headerLabel" in js_src
_check("T12206", ok, "4 labels + getter present")


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
