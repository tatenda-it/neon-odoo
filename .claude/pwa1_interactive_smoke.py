# -*- coding: utf-8 -*-
"""B11 / WA-1 interactive renderer smoke. Run via:
    docker compose exec -T odoo odoo shell -d <DB> --no-http < pwa1_interactive_smoke.py

Integration tests THROUGH handle_inbound (the lesson from WA-0): for each
slice we send -> simulate the button/list reply webhook -> assert routing.
Meta sends + the provider chat are mocked; ROLLS BACK at the end.

Covers: Slice 1 (Confirm/Cancel buttons -> write.log execute/cancel +
the <=3 stage picker), Slice 2 (pick-one list from a list-producing
tool -> selection feeds the id back), Slice 3 (capability menu -> route),
the tap-back negatives (unknown / tampered / expired -> safe fallback),
the mandatory text fallback on a Meta send error, and the money
guardrail (no interactive path surfaces/queues a money tool, for any
variant incl. director).
"""
import json
import traceback
from contextlib import ExitStack
from unittest.mock import patch

from odoo import fields

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append((name, ok))
    line = ("PASS" if ok else "FAIL") + " " + name
    if detail and not ok:
        line += " :: " + str(detail)
    print(line)


# Capture buffers + send-success switches (toggled to force fallback).
_sent = []
_seen = []  # message arrays passed to the (stubbed) provider
SEND_OK = {"buttons": True, "list": True}
STUB = {"resp": None}

try:
    from odoo.addons.neon_channels.models import wa_payload
    from odoo.addons.neon_channels.models.wa_copilot import (
        WhatsAppCopilotService, _WA_SAFE_WRITES,
    )
    from odoo.addons.neon_ai_core.models.ai import tool_registry
    from odoo.addons.neon_ai_core.models.ai.groq_chat_adapter import (
        ChatTurnResult,
    )

    env = env(context=dict(env.context, tracking_disable=True,
                           mail_create_nosubscribe=True,
                           mail_notify_force_send=False))
    WM = env["neon.whatsapp.message"].sudo()
    WMcls = type(WM)
    secret = env["ir.config_parameter"].sudo().get_param(
        "database.secret") or ""

    def dec(pid):
        return wa_payload.decode(secret, pid)

    def user_in_group(xmlid):
        g = env.ref(xmlid, raise_if_not_found=False)
        if not g:
            return env["res.users"]
        return env["res.users"].sudo().search(
            [("groups_id", "in", g.id), ("share", "=", False),
             ("active", "=", True)], limit=1)

    sales = user_in_group("neon_core.group_neon_sales_rep")
    director = user_in_group("neon_core.group_neon_superuser")
    check("fixtures: a sales-rep + a superuser user exist",
          bool(sales) and bool(director))

    SALES_PHONE = "+263990771001"
    SALES_FROM = "263990771001"
    DIR_PHONE = "+263990771002"
    bu_sales = env["neon.bot.user"].sudo().create({
        "name": "WA1 sales", "phone_number": SALES_PHONE,
        "user_id": sales.id})
    bu_dir = env["neon.bot.user"].sudo().create({
        "name": "WA1 dir", "phone_number": DIR_PHONE,
        "user_id": director.id})

    # ---- stubs ------------------------------------------------------
    def s_buttons(self, to, body, buttons):
        _sent.append(("buttons", {"to": to, "body": body,
                                  "buttons": buttons}))
        return SEND_OK["buttons"]

    def s_list(self, to, body, button_text, sections):
        _sent.append(("list", {"to": to, "body": body,
                               "button_text": button_text,
                               "sections": sections}))
        return SEND_OK["list"]

    def s_cta(self, to, body, disp, url):
        _sent.append(("cta", {"to": to, "body": body, "url": url}))
        return True

    def s_msg(self, to, body):
        _sent.append(("text", {"to": to, "body": body}))
        return True

    def _stub_provider_chat(self, messages, schemas):
        _seen.append(json.dumps(messages, default=str))
        return (STUB["resp"], "google")

    def text_msg(body, frm=SALES_FROM):
        return {"id": "wamid.T", "from": frm, "type": "text",
                "text": {"body": body}}

    def tap_msg(rid, title, frm=SALES_FROM, kind="button"):
        key = "button_reply" if kind == "button" else "list_reply"
        return {"id": "wamid.TAP", "from": frm, "type": "interactive",
                "interactive": {"type": kind,
                                key: {"id": rid, "title": title}}}

    def last(kind):
        for k, payload in reversed(_sent):
            if k == kind:
                return payload
        return None

    stack = ExitStack()
    stack.enter_context(patch.object(WMcls, "send_buttons", s_buttons))
    stack.enter_context(patch.object(WMcls, "send_list", s_list))
    stack.enter_context(patch.object(WMcls, "send_cta_url", s_cta))
    stack.enter_context(patch.object(WMcls, "send_message", s_msg))
    stack.enter_context(patch.object(
        WhatsAppCopilotService, "_provider_chat", _stub_provider_chat))

    with stack:
        # =============================================================
        # SLICE 1a -- proposal -> Confirm/Cancel buttons -> CONFIRM exec
        # =============================================================
        _sent.clear()
        STUB["resp"] = ChatTurnResult(
            success=True, assistant_message="",
            tool_calls=[{"tool_call_id": "c1", "tool_name": "log_lead",
                         "params": {"name": "WA1 SMOKE LEAD"}}])
        WM.handle_inbound(text_msg("log a lead WA1 SMOKE LEAD"), {})
        b = last("buttons")
        ok_btns = (b and len(b["buttons"]) == 2)
        cfm = dec(b["buttons"][0]["id"]) if ok_btns else None
        cxl = dec(b["buttons"][1]["id"]) if ok_btns else None
        check("S1a: proposal renders 2 reply buttons",
              ok_btns, b)
        check("S1a: button ids = confirm/cancel of the SAME token",
              cfm and cxl and cfm[0] == "confirm" and cxl[0] == "cancel"
              and cfm[1] == cxl[1], "%s / %s" % (cfm, cxl))
        token = cfm[1][0] if cfm else None
        # tap Confirm
        _sent.clear()
        n_before = env["crm.lead"].sudo().search_count(
            [("name", "=", "WA1 SMOKE LEAD")])
        WM.handle_inbound(tap_msg(b["buttons"][0]["id"], "Confirm"), {})
        wl = env["neon.finance.ai.chat.write.log"].sudo().search(
            [("confirmation_token", "=", token)], limit=1)
        n_after = env["crm.lead"].sudo().search_count(
            [("name", "=", "WA1 SMOKE LEAD")])
        check("S1a: Confirm tap EXECUTES the write.log token",
              wl and wl.status == "executed",
              "status=%s" % (wl.status if wl else None))
        check("S1a: Confirm tap created the lead (write happened)",
              n_after == n_before + 1, "%s->%s" % (n_before, n_after))
        check("S1a: user gets a Done reply (text, no crash)",
              last("text") and "done" in last("text")["body"].lower())

        # =============================================================
        # SLICE 1b -- CANCEL tap voids the proposal (no write)
        # =============================================================
        _sent.clear()
        STUB["resp"] = ChatTurnResult(
            success=True, assistant_message="",
            tool_calls=[{"tool_call_id": "c2", "tool_name": "log_lead",
                         "params": {"name": "WA1 CANCEL LEAD"}}])
        WM.handle_inbound(text_msg("log lead WA1 CANCEL LEAD"), {})
        b = last("buttons")
        tok2 = dec(b["buttons"][0]["id"])[1][0]
        _sent.clear()
        WM.handle_inbound(tap_msg(b["buttons"][1]["id"], "Cancel"), {})
        wl2 = env["neon.finance.ai.chat.write.log"].sudo().search(
            [("confirmation_token", "=", tok2)], limit=1)
        check("S1b: Cancel tap -> status cancelled, NO lead created",
              wl2 and wl2.status == "cancelled"
              and env["crm.lead"].sudo().search_count(
                  [("name", "=", "WA1 CANCEL LEAD")]) == 0,
              "status=%s" % (wl2.status if wl2 else None))

        # =============================================================
        # SLICE 1c -- <=3 stage picker (move_stage missing target stage)
        # =============================================================
        Stage = env["crm.stage"].sudo()
        low = Stage.search([], order="sequence, id", limit=1)
        fwd = Stage.search([("sequence", ">", low.sequence)])
        if len(fwd) < 2:  # guarantee >=2 forward stages exist
            for i in range(2):
                Stage.create({"name": "WA1 STG %d" % i,
                              "sequence": low.sequence + 1 + i})
        lead_stage = env["crm.lead"].sudo().create({
            "name": "WA1 STAGE LEAD", "type": "opportunity",
            "user_id": sales.id, "stage_id": low.id})
        _sent.clear()
        STUB["resp"] = ChatTurnResult(
            success=True, assistant_message="",
            tool_calls=[{"tool_call_id": "c3", "tool_name": "move_stage",
                         "params": {"lead_identifier": str(lead_stage.id),
                                    "target_stage": ""}}])
        WM.handle_inbound(text_msg("move WA1 STAGE LEAD forward"), {})
        b = last("buttons")
        stage_ids = [dec(x["id"]) for x in b["buttons"]] if b else []
        check("S1c: missing-stage move_stage -> stage picker (<=3 buttons)",
              b and 2 <= len(b["buttons"]) <= 3
              and all(d and d[0] == "stage"
                      and d[1][0] == str(lead_stage.id) for d in stage_ids),
              stage_ids)
        # tap a stage -> a fresh Confirm/Cancel proposal (gate not bypassed)
        _sent.clear()
        WM.handle_inbound(tap_msg(b["buttons"][0]["id"], "Stage"), {})
        b2 = last("buttons")
        d_cfm = dec(b2["buttons"][0]["id"]) if b2 else None
        check("S1c: stage tap PROPOSES (Confirm/Cancel) -- tap != bypass",
              b2 and len(b2["buttons"]) == 2 and d_cfm
              and d_cfm[0] == "confirm")

        # =============================================================
        # SLICE 2 -- pick-one list from a list-producing tool
        # =============================================================
        mid = Stage.search([], order="sequence, id")[
            1 if len(Stage.search([])) > 1 else 0]
        pipe_leads = []
        for i in range(3):
            pipe_leads.append(env["crm.lead"].sudo().create({
                "name": "WA1 PIPE %d" % i, "type": "opportunity",
                "user_id": sales.id, "stage_id": mid.id,
                "probability": 50.0, "expected_revenue": 1000 + i}))
        _sent.clear()
        STUB["resp"] = ChatTurnResult(
            success=True, assistant_message="",
            tool_calls=[{"tool_call_id": "c4",
                         "tool_name": "get_my_pipeline", "params": {}}])
        WM.handle_inbound(text_msg("show my pipeline"), {})
        lst = last("list")
        rows = (lst["sections"][0]["rows"]
                if lst and lst["sections"] else [])
        decoded_rows = [dec(r["id"]) for r in rows]
        pipe_ids = {str(l.id) for l in pipe_leads}
        check("S2: list-producing tool (>=2 rows) renders a LIST",
              lst and len(rows) >= 2)
        check("S2: list rows are pick_lead:<lead_id> (nested shape flattened)",
              decoded_rows
              and all(d and d[0] == "pick_lead" for d in decoded_rows)
              and pipe_ids.issubset({d[1][0] for d in decoded_rows}),
              decoded_rows)
        # tap a row -> selection feeds the chosen id back into a turn
        _seen.clear()
        _sent.clear()
        STUB["resp"] = ChatTurnResult(
            success=True, assistant_message="Here are the details.",
            tool_calls=[])
        chosen = decoded_rows[0][1][0]
        WM.handle_inbound(
            tap_msg(rows[0]["id"], "WA1 PIPE", kind="list"), {})
        steered = _seen[-1] if _seen else ""
        check("S2: list selection feeds the chosen lead id into the turn",
              ("Let's work with lead" in steered) and (chosen in steered),
              steered[-160:])
        check("S2: selection turn replies (no name-typing needed)",
              last("text") and "details" in last("text")["body"].lower())

        # =============================================================
        # SLICE 3 -- capability menu -> route a tapped capability
        # =============================================================
        _sent.clear()
        WM.handle_inbound(text_msg("menu"), {})
        menu = last("list") or last("buttons")
        if last("list"):
            menu_ids = [dec(r["id"])
                        for r in menu["sections"][0]["rows"]]
        else:
            menu_ids = [dec(x["id"]) for x in menu["buttons"]]
        allowed = {t.name for t in WhatsAppCopilotService(env).whatsapp_tools(
            sales, "sales")}
        check("S3: 'menu' renders a capability picker",
              bool(menu) and bool(menu_ids))
        # WA-12.6: a quote-capable lens (sales) now LEADS with a "Quote a
        # client" row (wa12_start, not a menu:<tool> id). Every OTHER row is
        # still a scoped menu:<key>.
        check("S3: menu rows are menu:<scoped-key> (or the Quote-a-client lead)",
              all(d and ((d[0] == "menu" and d[1][0] in allowed)
                         or d[0] == "wa12_start")
                  for d in menu_ids), menu_ids)
        check("S3: sales menu LEADS with the 'Quote a client' (wa12_start) row",
              bool(menu_ids) and menu_ids[0] and menu_ids[0][0] == "wa12_start",
              menu_ids[0] if menu_ids else None)
        # tap a read capability -> routed through run_turn (canned phrase)
        menu_read = next((d for d in menu_ids
                          if d[1][0] == "get_my_pipeline"), None)
        if menu_read:
            _seen.clear()
            _sent.clear()
            STUB["resp"] = ChatTurnResult(
                success=True, assistant_message="On it.", tool_calls=[])
            mid_id = wa_payload.encode(secret, "menu", "get_my_pipeline")
            WM.handle_inbound(tap_msg(mid_id, "My pipeline"), {})
            check("S3: menu tap routes to the capability (canned phrase ran)",
                  _seen and "pipeline" in _seen[-1].lower())

        # =============================================================
        # NEGATIVES -- unknown / tampered / expired -> safe fallback
        # =============================================================
        _sent.clear()
        WM.handle_inbound(tap_msg("totally-unsigned-garbage", "x"), {})
        check("NEG: unknown payload id -> safe text fallback (no crash)",
              last("text") and "couldn't read" in last("text")["body"].lower())

        good_id = wa_payload.encode(secret, "confirm", "deadbeef" * 4)
        tampered = good_id[:-1] + ("0" if good_id[-1] != "0" else "1")
        _sent.clear()
        WM.handle_inbound(tap_msg(tampered, "x"), {})
        check("NEG: tampered signature -> safe fallback, never routed",
              last("text") and "couldn't read" in last("text")["body"].lower()
              and dec(tampered) is None)

        # expired write.log token
        _sent.clear()
        STUB["resp"] = ChatTurnResult(
            success=True, assistant_message="",
            tool_calls=[{"tool_call_id": "c5", "tool_name": "log_lead",
                         "params": {"name": "WA1 EXPIRED LEAD"}}])
        WM.handle_inbound(text_msg("log lead WA1 EXPIRED LEAD"), {})
        b = last("buttons")
        exp_tok = dec(b["buttons"][0]["id"])[1][0]
        env["neon.finance.ai.chat.write.log"].sudo().search(
            [("confirmation_token", "=", exp_tok)], limit=1).write(
            {"expires_at": fields.Datetime.subtract(
                fields.Datetime.now(), minutes=1)})
        _sent.clear()
        WM.handle_inbound(tap_msg(b["buttons"][0]["id"], "Confirm"), {})
        wl_exp = env["neon.finance.ai.chat.write.log"].sudo().search(
            [("confirmation_token", "=", exp_tok)], limit=1)
        check("NEG: expired token tap -> 'expired' msg + status expired, "
              "no write",
              last("text") and "expired" in last("text")["body"].lower()
              and wl_exp.status == "expired"
              and env["crm.lead"].sudo().search_count(
                  [("name", "=", "WA1 EXPIRED LEAD")]) == 0)

        # =============================================================
        # TEXT FALLBACK -- Meta rejects the buttons send -> still a reply
        # =============================================================
        SEND_OK["buttons"] = False
        _sent.clear()
        STUB["resp"] = ChatTurnResult(
            success=True, assistant_message="",
            tool_calls=[{"tool_call_id": "c6", "tool_name": "log_lead",
                         "params": {"name": "WA1 FALLBACK LEAD"}}])
        WM.handle_inbound(text_msg("log lead WA1 FALLBACK LEAD"), {})
        check("FALLBACK: buttons send rejected -> cta_url text fallback fires",
              last("cta") is not None,
              "sent=%s" % [k for k, _ in _sent])
        check("FALLBACK: a reply was still delivered (never silent)",
              len([1 for k, _ in _sent if k in ("cta", "text")]) >= 1)
        SEND_OK["buttons"] = True

        # =============================================================
        # MONEY GUARDRAIL -- no interactive path reaches a money tool
        # =============================================================
        svc = WhatsAppCopilotService(env)
        env_sales = env(user=sales.id)
        money_res = svc._propose_and_confirm(
            sales, env_sales, "update_deal_value",
            {"lead_identifier": "1", "value": 999})
        check("MONEY: _propose_and_confirm rejects a non-WA-safe money tool",
              "isn't available" in (money_res.get("text") or "").lower()
              and money_res.get("interactive") is None)

        dir_menu = svc.build_menu_result(bu_dir)
        if dir_menu.get("interactive"):
            inter = dir_menu["interactive"]
            d_rows = (inter.get("buttons")
                      or inter["sections"][0]["rows"])
            d_keys = [dec(x["id"])[1][0] for x in d_rows if dec(x["id"])]
        else:
            d_keys = []
        writes_in_menu = [k for k in d_keys
                          if (tool_registry.get_tool(k)
                              and tool_registry.get_tool(k).category
                              == "write")]
        check("MONEY: director menu exposes NO money tool",
              "update_deal_value" not in d_keys, d_keys)
        check("MONEY: every write in the director menu is a WA-safe write",
              all(k in _WA_SAFE_WRITES for k in writes_in_menu),
              writes_in_menu)
        # even a validly-signed menu id for a money tool is scope-rejected
        forged = wa_payload.encode(secret, "menu", "update_deal_value")
        forged_res = svc.handle_tap(bu_dir, forged, "x")
        check("MONEY: signed menu id for a money tool -> scope-rejected",
              "isn't available" in (forged_res.get("text") or "").lower()
              and forged_res.get("interactive") is None)

        # =============================================================
        # REGRESSION BAR -- Copilot engine unchanged
        # =============================================================
        nr = len(tool_registry.list_tools(category="read"))
        nw = len(tool_registry.list_tools(category="write"))
        check("REG: 18 tools (14 read + 4 write) unchanged", nr == 14
              and nw == 4, "read=%d write=%d" % (nr, nw))
        dft = env["neon.dashboard.ai.provider"].sudo().search(
            [("is_default", "=", True)], limit=1)
        check("REG: Groq still the Copilot default", dft
              and dft.provider_key == "groq")
        check("REG: update_deal_value absent from WhatsApp tools (director)",
              "update_deal_value" not in {
                  t.name for t in svc.whatsapp_tools(director, "director")})

except Exception:  # noqa: BLE001
    traceback.print_exc()
    results.append(("smoke crashed", False))
finally:
    try:
        env.cr.rollback()
    except Exception:  # noqa: BLE001
        pass

passed = sum(1 for _, ok in results if ok)
print("\nTotal: %d/%d passed" % (passed, len(results)))