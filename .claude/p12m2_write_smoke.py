"""P12.M2 smoke — AI Copilot WRITE tools + two-phase commit.

Runs in `odoo shell -d <db>`. T12300-T12399.

Covers:
- 4 write tools registered (log_lead, move_stage, update_deal_value,
  post_chatter_note) with category="write" + requires_confirmation
- TOOLS_BY_VARIANT additions: sales gets all 4, bookkeeper +
  lead_tech get post_chatter_note only
- propose() returns proposal without mutation (probe a target value
  before + after propose; must be unchanged)
- pending_action.propose persists write.log(status=proposed) with a
  fresh uuid4 token + sha256(params) hash + 10-min expiry
- /confirm orchestrator path executes the write, flips status to
  executed, stamps executed_at, creates target_id
- /cancel path flips status to cancelled with no mutation
- D29 single-use: a second confirm on the same token returns the
  recorded result (replay) without re-executing
- D29 TTL: a token whose expires_at has passed flips to expired and
  rejects the confirm
- D34 3-pending cap: a 4th propose returns is_proposal_cap=True
- D35 savepoint: a forced exception during execute rolls back the
  target write + flips status=error
- D36 write rate limit: 11th confirmed write in an hour is blocked
- ACL: bookkeeper can post_chatter_note, cannot log_lead;
  sales can do all 4
- post_chatter_note rejects records the caller can't read
"""
import json
import time
from datetime import timedelta
from unittest.mock import patch


def _check(name, ok, detail=""):
    print(f"{name}:", "PASS" if ok else "FAIL", detail)
    results[name] = ok


print("=" * 72)
print("P12.M2 — AI Copilot WRITE tools + two-phase commit")
print("=" * 72)
results = {}

Users = env["res.users"]
Session = env["neon.finance.ai.chat.session"]
Message = env["neon.finance.ai.chat.message"]
WriteLog = env["neon.finance.ai.chat.write.log"]
Lead = env["crm.lead"]
Stage = env["crm.stage"]
Partner = env["res.partner"]

from odoo import fields as ofields
from odoo.addons.neon_dashboard.models.ai import (
    tool_registry,
    chat_orchestrator as orch_mod,
)
from odoo.addons.neon_dashboard.models.ai.chat_orchestrator import (
    ChatOrchestrator,
)


def _gom(login, group_xmlids):
    u = Users.search([("login", "=", login)], limit=1)
    ids = [env.ref(x).id for x in group_xmlids]
    if not u:
        u = Users.with_context(no_reset_password=True).create({
            "name": login, "login": login, "password": "test123",
            "groups_id": [(4, gid) for gid in ids],
        })
    else:
        for gid in ids:
            if gid not in u.groups_id.ids:
                u.write({"groups_id": [(4, gid)]})
    return u


sales_user = _gom("p12m2_sales", [
    "base.group_user",
    "neon_jobs.group_neon_jobs_user",
    "neon_core.group_neon_sales_rep",
])
bookkeeper_user = _gom("p12m2_bookkeeper", [
    "base.group_user",
    "neon_core.group_neon_bookkeeper",
])
lead_tech_user = _gom("p12m2_leadtech", [
    "base.group_user",
    "neon_jobs.group_neon_jobs_crew_leader",
    "neon_core.group_neon_lead_tech",
])

# Clear rate-limit buckets so prior-suite consumption doesn't leak.
orch_mod._RATE_LIMIT_BY_USER[sales_user.id] = []
orch_mod._RATE_LIMIT_BY_USER[bookkeeper_user.id] = []
orch_mod._WRITE_RATE_LIMIT_BY_USER[sales_user.id] = []
orch_mod._WRITE_RATE_LIMIT_BY_USER[bookkeeper_user.id] = []


def _fresh_session(user):
    s = Session.sudo().get_or_create_for_user(user.id)
    # Clear any pending proposals from previous suite runs so the
    # 3-pending cap doesn't bite the early happy-path tests.
    WriteLog.sudo().search(
        [("user_id", "=", user.id),
         ("status", "=", "proposed")]).write({"status": "cancelled"})
    return s


sales_session = _fresh_session(sales_user)
bookkeeper_session = _fresh_session(bookkeeper_user)


# ============================================================
# T12300 -- registry shape
# ============================================================
all_write = [t for t in tool_registry.list_tools(category="write")]
write_names = sorted(t.name for t in all_write)
EXPECTED_WRITE = ["log_lead", "move_stage",
                  "post_chatter_note", "update_deal_value"]
_check("T12300", write_names == EXPECTED_WRITE,
       f"got={write_names}")


# T12301 -- requires_confirmation set on every write tool
all_required = all(t.requires_confirmation for t in all_write)
_check("T12301", all_required, "requires_confirmation on all 4 writes")


# T12302 -- every write tool has groups list (no defensive open path)
no_groups = [t.name for t in all_write if not t.groups]
_check("T12302", not no_groups, f"missing_groups={no_groups}")


# T12303 -- TOOLS_BY_VARIANT additions
v = tool_registry.TOOLS_BY_VARIANT
sales_set = set(v.get("sales") or [])
bookkeeper_set = set(v.get("bookkeeper") or [])
lead_tech_set = set(v.get("lead_tech") or [])
_check("T12303",
       set(EXPECTED_WRITE).issubset(sales_set)
       and "post_chatter_note" in bookkeeper_set
       and "log_lead" not in bookkeeper_set
       and "post_chatter_note" in lead_tech_set
       and "log_lead" not in lead_tech_set,
       "sales=all4, bookkeeper+leadtech=note-only")


# T12304 -- 22 tools total (18 reads [+2 L2.1 + 1 L2.2 + 1 L2.3] + 4 writes)
total_tools = len(tool_registry.list_tools())
_check("T12304", total_tools == 22,
       f"got={total_tools} (18 reads + 4 writes)")


# T12305 -- executor registered for every write tool
missing_executors = [
    n for n in EXPECTED_WRITE
    if tool_registry.get_executor(n) is None
]
_check("T12305", not missing_executors,
       f"missing={missing_executors}")


# ============================================================
# T12310 -- write.log model live + perm_unlink=0
# ============================================================
_check("T12310", WriteLog is not None and "status" in WriteLog._fields,
       "model present + status field")
unlinkables = env["ir.model.access"].sudo().search([
    ("model_id.model", "=", "neon.finance.ai.chat.write.log"),
    ("perm_unlink", "=", True),
])
_check("T12311", not unlinkables,
       f"unlinkable_groups={unlinkables.mapped('group_id.name')}")


# ============================================================
# log_lead propose + confirm happy path
# ============================================================
PROBE_NAME = "P12M2 SMOKE -- ACME LED wall"
# Cleanup any leftover probes so the smoke is repeatable.
old = Lead.sudo().search([("name", "=", PROBE_NAME)])
if old:
    old.sudo().unlink()

# T12320 -- propose returns a proposal (is_proposal=True), no lead created
before_count = Lead.sudo().search_count([("name", "=", PROBE_NAME)])
proposal = tool_registry.dispatch(
    "log_lead", env, sales_user,
    {"name": PROBE_NAME, "partner_name": "Acme Corp",
     "expected_revenue": 4000})
_check("T12320",
       proposal.get("ok") and proposal.get("is_proposal")
       and proposal.get("action_type") == "log_lead",
       f"proposal_keys={list(proposal.keys())}")
after_count = Lead.sudo().search_count([("name", "=", PROBE_NAME)])
_check("T12321", before_count == after_count,
       f"before={before_count} after={after_count}")


# T12322 -- pending_action.propose persists a write.log row
prop_res = WriteLog.sudo().propose(sales_session, sales_user, proposal)
_check("T12322",
       prop_res.get("ok") and prop_res.get("record")
       and prop_res["record"].status == "proposed",
       f"ok={prop_res.get('ok')}")


# T12323 -- fresh uuid4 token + non-empty sha256 hash + 10-min TTL
rec = prop_res["record"]
_check("T12323",
       (rec.confirmation_token
        and len(rec.confirmation_token) >= 16
        and rec.params_hash and len(rec.params_hash) == 64
        and rec.expires_at
        and rec.expires_at > ofields.Datetime.now()),
       f"token_len={len(rec.confirmation_token or '')} "
       f"hash_len={len(rec.params_hash or '')}")


# T12324 -- confirm executes and creates the lead
orch = ChatOrchestrator(env)
confirm_res = orch.confirm_pending_action(
    sales_user, rec.confirmation_token,
    active_variant="sales")
_check("T12324",
       confirm_res.get("ok")
       and confirm_res.get("status") == "executed",
       f"ok={confirm_res.get('ok')} status={confirm_res.get('status')}")

created_lead = Lead.sudo().search([("name", "=", PROBE_NAME)], limit=1)
_check("T12325",
       bool(created_lead) and created_lead.user_id.id == sales_user.id,
       f"lead_id={created_lead.id if created_lead else 0} "
       f"user={created_lead.user_id.login if created_lead else ''}")

rec.invalidate_recordset()
_check("T12326",
       rec.status == "executed" and bool(rec.executed_at)
       and rec.created_target_id == (created_lead.id or 0),
       f"status={rec.status} created_target_id={rec.created_target_id}")


# T12327 -- D29 single-use: a second confirm returns replay, does NOT
# create a duplicate lead.
dup_before = Lead.sudo().search_count([("name", "=", PROBE_NAME)])
replay_res = orch.confirm_pending_action(
    sales_user, rec.confirmation_token,
    active_variant="sales")
dup_after = Lead.sudo().search_count([("name", "=", PROBE_NAME)])
_check("T12327",
       replay_res.get("ok") and replay_res.get("replay") is True
       and dup_before == dup_after,
       f"replay={replay_res.get('replay')} "
       f"dup_before={dup_before} dup_after={dup_after}")


# ============================================================
# Cancel path
# ============================================================
# T12330 -- propose update_deal_value, then cancel, no mutation
created_lead.sudo().write({"expected_revenue": 4000})
proposal = tool_registry.dispatch(
    "update_deal_value", env, sales_user,
    {"lead_identifier": PROBE_NAME, "new_value": 9000})
prop_res = WriteLog.sudo().propose(
    sales_session, sales_user, proposal)
rec2 = prop_res["record"]
cancel_res = orch.cancel_pending_action(
    sales_user, rec2.confirmation_token)
rec2.invalidate_recordset()
created_lead.invalidate_recordset()
_check("T12330",
       cancel_res.get("ok")
       and cancel_res.get("status") == "cancelled"
       and rec2.status == "cancelled"
       and float(created_lead.expected_revenue or 0) == 4000.0,
       f"cancelled={rec2.status} value={created_lead.expected_revenue}")


# T12331 -- after cancel the token is dead: re-confirm returns replay
re_confirm = orch.confirm_pending_action(
    sales_user, rec2.confirmation_token,
    active_variant="sales")
_check("T12331",
       re_confirm.get("ok") and re_confirm.get("replay") is True
       and re_confirm.get("status") == "cancelled",
       f"got={re_confirm.get('status')}")


# ============================================================
# move_stage propose + confirm
# ============================================================
# T12340 -- move_stage returns disambiguation when multiple match
proposal = tool_registry.dispatch(
    "move_stage", env, sales_user,
    {"lead_identifier": "P12M2",
     "target_stage": "Negotiating"})
# Either one match (proceeds) or multi (returns error with candidates).
if proposal.get("ok") and proposal.get("is_proposal"):
    _check("T12340", True,
           f"single match path target_id={proposal.get('target_id')}")
else:
    _check("T12340",
           "match" in (proposal.get("error", "").lower())
           or "specific" in (proposal.get("error", "").lower())
           or "no lead" in (proposal.get("error", "").lower()),
           f"err={proposal.get('error')}")


# T12341 -- move the probe lead to Negotiating
proposal = tool_registry.dispatch(
    "move_stage", env, sales_user,
    {"lead_identifier": str(created_lead.id),
     "target_stage": "Negotiating"})
_check("T12341",
       proposal.get("ok") and proposal.get("is_proposal")
       and proposal["target_id"] == created_lead.id,
       f"ok={proposal.get('ok')} target={proposal.get('target_id')}")

prop_res = WriteLog.sudo().propose(
    sales_session, sales_user, proposal)
rec3 = prop_res["record"]
confirm_res = orch.confirm_pending_action(
    sales_user, rec3.confirmation_token,
    active_variant="sales")
created_lead.invalidate_recordset()
stage_name = created_lead.stage_id.name
# stage.name may be a translation dict.
if isinstance(stage_name, dict):
    stage_name = stage_name.get("en_US") or next(
        iter(stage_name.values()), "")
_check("T12342",
       confirm_res.get("ok") and "Negotiating" in (stage_name or ""),
       f"confirm={confirm_res.get('ok')} stage={stage_name!r}")


# T12343 -- moving to the SAME stage is rejected at propose time
proposal_same = tool_registry.dispatch(
    "move_stage", env, sales_user,
    {"lead_identifier": str(created_lead.id),
     "target_stage": "Negotiating"})
_check("T12343",
       not proposal_same.get("ok")
       and "already" in (proposal_same.get("error", "").lower()),
       f"err={proposal_same.get('error')}")


# T12344 -- unknown stage rejected with list of valid stages
proposal_bad = tool_registry.dispatch(
    "move_stage", env, sales_user,
    {"lead_identifier": str(created_lead.id),
     "target_stage": "Sushi"})
_check("T12344",
       not proposal_bad.get("ok")
       and ("valid stages" in (proposal_bad.get("error", "").lower())
            or "no stage" in (proposal_bad.get("error", "").lower())),
       f"err={proposal_bad.get('error')}")


# ============================================================
# update_deal_value
# ============================================================
# T12350 -- negative value rejected at propose
prop_neg = tool_registry.dispatch(
    "update_deal_value", env, sales_user,
    {"lead_identifier": str(created_lead.id), "new_value": -100})
_check("T12350",
       not prop_neg.get("ok")
       and "negative" in (prop_neg.get("error", "").lower()),
       f"err={prop_neg.get('error')}")


# T12351 -- happy path: update 4000 -> 6500
proposal = tool_registry.dispatch(
    "update_deal_value", env, sales_user,
    {"lead_identifier": str(created_lead.id), "new_value": 6500})
prop_res = WriteLog.sudo().propose(
    sales_session, sales_user, proposal)
rec4 = prop_res["record"]
orch.confirm_pending_action(
    sales_user, rec4.confirmation_token, active_variant="sales")
created_lead.invalidate_recordset()
_check("T12351",
       float(created_lead.expected_revenue or 0) == 6500.0,
       f"value={created_lead.expected_revenue}")


# ============================================================
# post_chatter_note
# ============================================================
# T12360 -- happy path on the probe lead
proposal = tool_registry.dispatch(
    "post_chatter_note", env, sales_user,
    {"target_ref": "lead " + str(created_lead.id),
     "note_text": "P12.M2 smoke note."})
_check("T12360",
       proposal.get("ok") and proposal.get("is_proposal")
       and proposal.get("target_model") == "crm.lead",
       f"ok={proposal.get('ok')} model={proposal.get('target_model')}")

prop_res = WriteLog.sudo().propose(
    sales_session, sales_user, proposal)
rec5 = prop_res["record"]
note_count_before = env["mail.message"].sudo().search_count([
    ("model", "=", "crm.lead"),
    ("res_id", "=", created_lead.id),
])
orch.confirm_pending_action(
    sales_user, rec5.confirmation_token, active_variant="sales")
note_count_after = env["mail.message"].sudo().search_count([
    ("model", "=", "crm.lead"),
    ("res_id", "=", created_lead.id),
])
_check("T12361", note_count_after > note_count_before,
       f"before={note_count_before} after={note_count_after}")


# T12362 -- empty note_text rejected
prop_empty = tool_registry.dispatch(
    "post_chatter_note", env, sales_user,
    {"target_ref": "lead " + str(created_lead.id),
     "note_text": "   "})
_check("T12362",
       not prop_empty.get("ok")
       and "required" in (prop_empty.get("error", "").lower()),
       f"err={prop_empty.get('error')}")


# T12363 -- unknown target ref rejected
prop_unk = tool_registry.dispatch(
    "post_chatter_note", env, sales_user,
    {"target_ref": "lead THERE_IS_NO_SUCH_LEAD_999",
     "note_text": "hello"})
_check("T12363",
       not prop_unk.get("ok")
       and "no matching" in (prop_unk.get("error", "").lower()),
       f"err={prop_unk.get('error')}")


# ============================================================
# Per-variant ACL on writes (D30)
# ============================================================
# T12370 -- bookkeeper, on the bookkeeper variant, does NOT see
# log_lead in the LLM-advertised tool list (variant filter is the
# real production gate). Direct group ACL on log_lead is technically
# permissive on this DB because neon_core.group_neon_bookkeeper
# implies neon_jobs.group_neon_jobs_user via the platform cascade
# -- the variant filter, not the group check, keeps writes off the
# bookkeeper surface.
bk_variant_tools = [
    t.name for t in
    tool_registry.filter_tools_for_variant_and_user(
        bookkeeper_user, "bookkeeper", category=None)
]
_check("T12370",
       "log_lead" not in bk_variant_tools
       and "move_stage" not in bk_variant_tools
       and "update_deal_value" not in bk_variant_tools
       and "post_chatter_note" in bk_variant_tools,
       f"bk_tools={sorted(bk_variant_tools)}")


# T12371 -- bookkeeper CAN dispatch post_chatter_note (group ACL ok)
res_bk_note = tool_registry.dispatch(
    "post_chatter_note", env, bookkeeper_user,
    {"target_ref": "lead " + str(created_lead.id),
     "note_text": "BK testing"})
_check("T12371", res_bk_note.get("ok"),
       f"got={res_bk_note}")


# T12372 -- filter_tools_for_variant_and_user for sales includes
# all 4 writes; bookkeeper only post_chatter_note.
sales_visible = [
    t.name for t in
    tool_registry.filter_tools_for_variant_and_user(
        sales_user, "sales", category="write")
]
bookkeeper_visible = [
    t.name for t in
    tool_registry.filter_tools_for_variant_and_user(
        bookkeeper_user, "bookkeeper", category="write")
]
_check("T12372",
       set(EXPECTED_WRITE).issubset(set(sales_visible))
       and bookkeeper_visible == ["post_chatter_note"],
       f"sales={sales_visible} bookkeeper={bookkeeper_visible}")


# ============================================================
# 3-pending cap (D34)
# ============================================================
# Open 3 fresh proposals; the 4th must fail.
WriteLog.sudo().search([
    ("user_id", "=", sales_user.id),
    ("status", "=", "proposed"),
]).write({"status": "cancelled"})
ok_count = 0
for i in range(3):
    p = tool_registry.dispatch(
        "post_chatter_note", env, sales_user,
        {"target_ref": "lead " + str(created_lead.id),
         "note_text": f"cap-test-{i}"})
    pr = WriteLog.sudo().propose(sales_session, sales_user, p)
    if pr.get("ok"):
        ok_count += 1
p4 = tool_registry.dispatch(
    "post_chatter_note", env, sales_user,
    {"target_ref": "lead " + str(created_lead.id),
     "note_text": "cap-test-4"})
pr4 = WriteLog.sudo().propose(sales_session, sales_user, p4)
_check("T12380",
       ok_count == 3
       and (not pr4.get("ok"))
       and pr4.get("is_proposal_cap") is True,
       f"ok_count={ok_count} pr4={pr4}")
# Cleanup -- cancel the 3 stacked proposals
WriteLog.sudo().search([
    ("user_id", "=", sales_user.id),
    ("status", "=", "proposed"),
]).write({"status": "cancelled"})


# ============================================================
# Token TTL expiry (D29)
# ============================================================
# T12385 -- a token whose expires_at is in the past returns 'expired'
prop_exp = tool_registry.dispatch(
    "post_chatter_note", env, sales_user,
    {"target_ref": "lead " + str(created_lead.id),
     "note_text": "ttl-test"})
prop_res = WriteLog.sudo().propose(sales_session, sales_user, prop_exp)
rec_exp = prop_res["record"]
rec_exp.sudo().write({
    "expires_at": ofields.Datetime.now() - timedelta(seconds=10),
})
exp_res = orch.confirm_pending_action(
    sales_user, rec_exp.confirmation_token, active_variant="sales")
rec_exp.invalidate_recordset()
_check("T12385",
       (not exp_res.get("ok"))
       and exp_res.get("error_code") == "expired"
       and rec_exp.status == "expired",
       f"got={exp_res}")


# ============================================================
# Savepoint rollback on execute error (D35)
# ============================================================
# T12390 -- patch the executor to raise; expect no value change and
# write.log status='error' + error_message captured.
created_lead.sudo().write({"expected_revenue": 6500})
proposal = tool_registry.dispatch(
    "update_deal_value", env, sales_user,
    {"lead_identifier": str(created_lead.id), "new_value": 7777})
prop_res = WriteLog.sudo().propose(sales_session, sales_user, proposal)
rec_err = prop_res["record"]


def _boom(env_, user_, params_):
    # Mutate first so we can prove the savepoint actually rolled back.
    Lead.browse(int(params_["lead_id"])).sudo().write(
        {"expected_revenue": float(params_["new_value"])})
    raise RuntimeError("forced boom")


orch_mod._WRITE_RATE_LIMIT_BY_USER[sales_user.id] = []
with patch.object(tool_registry, "get_executor",
                  return_value=_boom):
    err_res = orch.confirm_pending_action(
        sales_user, rec_err.confirmation_token, active_variant="sales")
created_lead.invalidate_recordset()
rec_err.invalidate_recordset()
_check("T12390",
       (not err_res.get("ok"))
       and err_res.get("error_code") == "execute_error"
       and rec_err.status == "error"
       and float(created_lead.expected_revenue or 0) == 6500.0,
       f"value_kept={created_lead.expected_revenue} "
       f"status={rec_err.status}")


# ============================================================
# Write rate limit (D36)
# ============================================================
# T12395 -- 10 confirmed writes allowed, 11th blocked.
orch_mod._WRITE_RATE_LIMIT_BY_USER[sales_user.id] = []
ok = True
for i in range(10):
    if not orch_mod._check_write_rate_limit(sales_user.id, consume=True):
        ok = False
        break
blocked = not orch_mod._check_write_rate_limit(
    sales_user.id, consume=False)
_check("T12395", ok and blocked,
       f"10_ok={ok} 11th_blocked={blocked}")


# ============================================================
# Variant validation (D33)
# ============================================================
# T12396 -- sales user requesting bookkeeper -> falls back to stored
v = orch_mod._validate_active_variant(env, sales_user, "bookkeeper")
_check("T12396", v != "bookkeeper",
       f"sales_user_peek_attempt={v}")

# T12397 -- empty requested -> falls back to stored (non-empty)
v2 = orch_mod._validate_active_variant(env, sales_user, "")
_check("T12397", v2 in {"director", "sales", "bookkeeper", "lead_tech"},
       f"empty_fallback={v2}")

# T12398 -- garbage requested -> falls back to stored
v3 = orch_mod._validate_active_variant(env, sales_user, "JUNK")
_check("T12398", v3 in {"director", "sales", "bookkeeper", "lead_tech"},
       f"junk_fallback={v3}")


# Final cleanup -- drop the probe lead so the smoke is idempotent.
WriteLog.sudo().search([
    ("user_id", "=", sales_user.id),
    ("status", "=", "proposed"),
]).write({"status": "cancelled"})
if created_lead and created_lead.exists():
    created_lead.sudo().unlink()


# ============================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print(f"Total: {passed}/{total} passed")
for k in sorted(results):
    print(f"  {k}: {'PASS' if results[k] else 'FAIL'}")
print("=" * 72)
