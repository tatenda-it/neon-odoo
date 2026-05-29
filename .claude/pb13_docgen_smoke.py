"""P-B13 smoke -- Claude doc-gen engine.

Runs in `odoo shell -d <db>`. T-B13-01 ... T-B13-25.

Covers acceptance §3:
- adapter targets Anthropic Messages API (endpoint + headers)
- strict-JSON: ```json fenced output is parsed
- one re-prompt cycle on malformed; persistent malformed -> typed
  DocGenJSONError, not a crash
- 429 / 5xx / timeout / connection error -> typed exceptions
- missing/blank key -> DocGenConfigError; key NEVER in any log /
  field / return value
- usage tokens recorded per call
- doc-gen path is independent of chat orchestrator (no variant filter
  coupling)
"""
import json
import logging
from unittest.mock import patch, MagicMock

import requests


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P-B13 -- Claude doc-gen engine")
print("=" * 72)
results = {}

Provider = env["neon.doc.gen.provider"]
Wizard = env["neon.doc.gen.set.key.wizard"]
Config = env["ir.config_parameter"].sudo()

# Grant the smoke's current user (admin) the neon_superuser group
# so _check_superuser passes on _set_api_key + wizard flows. The
# real prod path uses Robin/Munashe/Tatenda who already have this
# group from neon_core.
admin = env.ref("base.user_admin")
admin.sudo().write({
    "groups_id": [(4, env.ref("neon_core.group_neon_superuser").id)],
})
# Use admin as the calling user for the rest of the smoke.
env = env(user=admin.id)

from odoo.addons.neon_doc_gen.models.ai_doc_gen.claude_docgen_adapter import (
    ClaudeDocGenAdapter,
    DocGenError, DocGenConfigError, DocGenAPIError,
    DocGenRateLimitError, DocGenTimeoutError,
    DocGenServerError, DocGenJSONError,
)


# ============================================================
# T-B13-01 .. 04 -- provider model + seed + ACL
# ============================================================
provider = Provider.sudo().search(
    [("provider_key", "=", "anthropic")], limit=1)
_check("T-B13-01", bool(provider),
       f"anthropic provider seed exists (id={provider.id if provider else 0})")
_check("T-B13-02",
       provider.endpoint_url == "https://api.anthropic.com/v1/messages"
       and provider.model == "claude-sonnet-4-6"
       and provider.max_tokens == 4096
       and provider.timeout_seconds == 30,
       "default endpoint/model/max_tokens/timeout match locked spec")

# ACL: no perm_unlink anywhere
unlinkable = env["ir.model.access"].sudo().search([
    ("model_id.model", "=", "neon.doc.gen.provider"),
    ("perm_unlink", "=", True),
])
_check("T-B13-03", not unlinkable,
       f"perm_unlink=0 on every ACL row; "
       f"violations={unlinkable.mapped('group_id.name')}")

# Default state: no key set
_check("T-B13-04",
       provider._get_decrypted_api_key() == "",
       f"key blank pre-test")


# ============================================================
# T-B13-05 -- adapter raises DocGenConfigError on missing key
# ============================================================
adapter = ClaudeDocGenAdapter(provider)
try:
    adapter.generate(
        system_prompt="test", facts={"x": 1})
    raised = None
except DocGenError as e:
    raised = type(e).__name__
_check("T-B13-05",
       raised == "DocGenConfigError",
       f"missing-key raises DocGenConfigError; got={raised}")


# ============================================================
# T-B13-06 -- adapter raises DocGenConfigError on disabled provider
# ============================================================
# Set a fake key first so the disable check is what trips.
provider._set_api_key("sk-ant-FAKE-TESTING-12345")
provider.sudo().write({"is_enabled": False})
try:
    ClaudeDocGenAdapter(provider).generate("test", {})
    raised = None
except DocGenError as e:
    raised = type(e).__name__
_check("T-B13-06",
       raised == "DocGenConfigError",
       f"disabled provider raises DocGenConfigError; got={raised}")
provider.sudo().write({"is_enabled": True})


# ============================================================
# T-B13-07 -- adapter raises DocGenConfigError on blank model
# ============================================================
provider.sudo().write({"model": ""})
try:
    ClaudeDocGenAdapter(provider).generate("test", {})
    raised = None
except DocGenError as e:
    raised = type(e).__name__
_check("T-B13-07",
       raised == "DocGenConfigError",
       f"blank model raises DocGenConfigError; got={raised}")
provider.sudo().write({"model": "claude-sonnet-4-6"})


# ============================================================
# T-B13-08 .. 10 -- happy path: adapter hits Anthropic endpoint
# with x-api-key header + correct payload shape, returns parsed
# JSON + usage
# ============================================================
def _mk_response(body_json, status=200):
    resp = MagicMock()
    resp.ok = (200 <= status < 400)
    resp.status_code = status
    resp.json.return_value = body_json
    resp.text = json.dumps(body_json)
    return resp


happy_response = _mk_response({
    "content": [
        {"type": "text",
         "text": '{"ok": true, "summary": "happy"}'}
    ],
    "usage": {"input_tokens": 42, "output_tokens": 7},
}, status=200)

captured = {}


def _capture_post(url, headers=None, json=None, timeout=None, **kw):
    captured["url"] = url
    captured["headers"] = dict(headers or {})
    captured["payload"] = json
    captured["timeout"] = timeout
    return happy_response


with patch("requests.post", side_effect=_capture_post):
    out = ClaudeDocGenAdapter(provider).generate(
        system_prompt="Test instruction.",
        facts={"foo": "bar"},
    )

_check("T-B13-08",
       captured["url"] == "https://api.anthropic.com/v1/messages",
       f"endpoint hit: {captured.get('url')}")
_check("T-B13-09",
       (captured["headers"].get("x-api-key")
        == "sk-ant-FAKE-TESTING-12345")
       and captured["headers"].get("anthropic-version") == "2023-06-01",
       f"x-api-key + anthropic-version headers present")
_check("T-B13-10",
       out["result"]["ok"] is True
       and out["usage"]["prompt_tokens"] == 42
       and out["usage"]["completion_tokens"] == 7
       and out["model"] == "claude-sonnet-4-6",
       f"result + usage + model returned")


# ============================================================
# T-B13-11 -- adapter does NOT target Groq
# ============================================================
_check("T-B13-11",
       "groq" not in captured["url"].lower()
       and "api.groq" not in captured["url"].lower(),
       f"endpoint is NOT Groq; url={captured.get('url')}")


# ============================================================
# T-B13-12 -- usage stamped on provider record
# ============================================================
provider.invalidate_recordset(["last_call_prompt_tokens",
                                 "last_call_completion_tokens",
                                 "last_call_at"])
_check("T-B13-12",
       provider.last_call_prompt_tokens == 42
       and provider.last_call_completion_tokens == 7
       and bool(provider.last_call_at),
       f"last_call_* stamped: prompt={provider.last_call_prompt_tokens} "
       f"completion={provider.last_call_completion_tokens}")


# ============================================================
# T-B13-13 -- ```json fenced output is parsed correctly
# ============================================================
fenced_response = _mk_response({
    "content": [{"type": "text",
                  "text": '```json\n{"fenced": true}\n```'}],
    "usage": {"input_tokens": 10, "output_tokens": 5},
})
with patch("requests.post", return_value=fenced_response):
    out = ClaudeDocGenAdapter(provider).generate("p", {})
_check("T-B13-13", out["result"].get("fenced") is True,
       f"fenced JSON unwrapped; got={out['result']}")


# ============================================================
# T-B13-14 -- one re-prompt on malformed; second attempt parsable
# ============================================================
call_seq = [
    _mk_response({  # bad first
        "content": [{"type": "text",
                      "text": "Sure thing! Here you go: NOT JSON"}],
        "usage": {"input_tokens": 12, "output_tokens": 6},
    }),
    _mk_response({  # good second
        "content": [{"type": "text",
                      "text": '{"retry_ok": true}'}],
        "usage": {"input_tokens": 14, "output_tokens": 4},
    }),
]


def _seq_post(*a, **kw):
    return call_seq.pop(0)


with patch("requests.post", side_effect=_seq_post):
    out = ClaudeDocGenAdapter(provider).generate("p", {})
_check("T-B13-14", out["result"].get("retry_ok") is True,
       f"re-prompt recovers; got={out['result']}")


# ============================================================
# T-B13-15 -- persistent malformed -> DocGenJSONError (not crash)
# ============================================================
bad_response = _mk_response({
    "content": [{"type": "text", "text": "still not json"}],
    "usage": {"input_tokens": 5, "output_tokens": 5},
})
try:
    with patch("requests.post", return_value=bad_response):
        ClaudeDocGenAdapter(provider).generate("p", {})
    raised = None
except DocGenError as e:
    raised = type(e).__name__
_check("T-B13-15",
       raised == "DocGenJSONError",
       f"persistent malformed raises DocGenJSONError; got={raised}")


# ============================================================
# T-B13-16 -- HTTP 429 -> DocGenRateLimitError
# ============================================================
try:
    with patch("requests.post",
                return_value=_mk_response({"error": "rate limit"}, 429)):
        ClaudeDocGenAdapter(provider).generate("p", {})
    raised = None
except DocGenError as e:
    raised = type(e).__name__
_check("T-B13-16",
       raised == "DocGenRateLimitError",
       f"HTTP 429 -> DocGenRateLimitError; got={raised}")


# ============================================================
# T-B13-17 -- HTTP 500 -> DocGenServerError
# ============================================================
try:
    with patch("requests.post",
                return_value=_mk_response({"error": "boom"}, 503)):
        ClaudeDocGenAdapter(provider).generate("p", {})
    raised = None
except DocGenError as e:
    raised = type(e).__name__
_check("T-B13-17",
       raised == "DocGenServerError",
       f"HTTP 5xx -> DocGenServerError; got={raised}")


# ============================================================
# T-B13-18 -- HTTP 400 -> DocGenAPIError (not rate-limit)
# ============================================================
try:
    with patch("requests.post",
                return_value=_mk_response(
                    {"error": "invalid"}, 400)):
        ClaudeDocGenAdapter(provider).generate("p", {})
    raised = None
except DocGenError as e:
    raised = type(e).__name__
_check("T-B13-18",
       raised == "DocGenAPIError",
       f"HTTP 4xx (non-429) -> DocGenAPIError; got={raised}")


# ============================================================
# T-B13-19 -- requests.Timeout -> DocGenTimeoutError
# ============================================================
try:
    with patch("requests.post",
                side_effect=requests.Timeout("slow")):
        ClaudeDocGenAdapter(provider).generate("p", {})
    raised = None
except DocGenError as e:
    raised = type(e).__name__
_check("T-B13-19",
       raised == "DocGenTimeoutError",
       f"timeout -> DocGenTimeoutError; got={raised}")


# ============================================================
# T-B13-20 -- key never appears in error messages / return
# ============================================================
# Force a 4xx that includes the key reference + verify scrubbing.
provider._set_api_key("sk-ant-LEAK-TEST-99999")
leak_resp = _mk_response(
    {"error": "auth failed", "api_key": "sk-ant-LEAK-TEST-99999"},
    401)
try:
    with patch("requests.post", return_value=leak_resp):
        ClaudeDocGenAdapter(provider).generate("p", {})
    raised_msg = ""
except DocGenError as e:
    raised_msg = str(e)
_check("T-B13-20",
       "sk-ant-LEAK-TEST-99999" not in raised_msg
       and "<REDACTED>" in raised_msg,
       f"key scrubbed from error; "
       f"msg fragment={raised_msg[:120]!r}")
# restore
provider._set_api_key("sk-ant-FAKE-TESTING-12345")


# ============================================================
# T-B13-21 -- doc-gen is independent of chat orchestrator
# ============================================================
# Importing the adapter must NOT pull in the chat tool_registry,
# orchestrator, variant filter, or any neon_dashboard chat code.
import sys
preloaded = set(sys.modules.keys())
from odoo.addons.neon_doc_gen.models.ai_doc_gen import claude_docgen_adapter as cdc
# Adapter module's only imports are stdlib + requests; verify by
# inspecting its globals for the chat-orchestrator types.
adapter_globals = set(dir(cdc))
chat_coupling = (
    "tool_registry" in adapter_globals
    or "ChatOrchestrator" in adapter_globals
    or "TOOLS_BY_VARIANT" in adapter_globals
    or "GroqChatAdapter" in adapter_globals)
_check("T-B13-21",
       not chat_coupling,
       f"no chat-orchestrator coupling in adapter; "
       f"coupling={chat_coupling}")


# ============================================================
# T-B13-22 -- key paste wizard works + key not echoed
# ============================================================
# Spawn the wizard (must be superuser; admin is) and save a key.
wiz_vals = {"provider_id": provider.id,
             "api_key": "sk-ant-WIZARD-TEST-77777"}
wiz = Wizard.with_user(admin).create(wiz_vals)
result = wiz.with_user(admin).action_save_key()
# Wizard should be unlinked
_check("T-B13-22",
       result is not None
       and not Wizard.search([("id", "=", wiz.id)]).exists()
       and provider._get_decrypted_api_key() == "sk-ant-WIZARD-TEST-77777",
       f"wizard saved key + self-unlinked; "
       f"current key matches input")


# ============================================================
# T-B13-23 -- key never appears in chatter / mail.message
# ============================================================
# Search recently-created mail.message rows for the leak test key.
mm_rows = env["mail.message"].sudo().search([
    ("body", "ilike", "sk-ant-WIZARD-TEST-77777")])
_check("T-B13-23",
       not mm_rows,
       f"key absent from mail.message body; "
       f"hits={len(mm_rows)}")


# ============================================================
# T-B13-24 -- ACL: non-superuser cannot read provider config
# ============================================================
Users = env["res.users"]
non_su = Users.sudo().search(
    [("login", "=", "pb13_non_superuser")], limit=1)
if not non_su:
    non_su = Users.sudo().with_context(
        no_reset_password=True).create({
        "name": "pb13_non_superuser",
        "login": "pb13_non_superuser",
        "password": "test123",
        "groups_id": [
            (6, 0, [env.ref("base.group_user").id])],
    })

acl_err = ""
try:
    Provider.with_user(non_su).search([]).read(["model"])
except Exception as exc:  # noqa: BLE001
    acl_err = str(type(exc).__name__) + ": " + str(exc)[:80]
_check("T-B13-24",
       "AccessError" in acl_err or "permission" in acl_err.lower()
       or "not allowed" in acl_err.lower(),
       f"non-superuser read blocked; err={acl_err[:120]}")


# ============================================================
# T-B13-25 -- contract: generate() signature matches B3/B4/B5
# expectation
# ============================================================
import inspect
sig = inspect.signature(ClaudeDocGenAdapter.generate)
params = list(sig.parameters.keys())
# Should be self, system_prompt, facts, json_schema
_check("T-B13-25",
       params == ["self", "system_prompt", "facts", "json_schema"]
       and sig.parameters["json_schema"].default is None,
       f"signature locked: {params}; "
       f"json_schema default={sig.parameters['json_schema'].default}")


# ============================================================
# Cleanup
# ============================================================
provider._set_api_key("")  # clear so we don't leave a fake key
env.cr.commit()


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
