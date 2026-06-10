# -*- coding: utf-8 -*-
"""B11 / WA-9 CRM contact-matching for the client lane smoke. Run via:
    docker exec -i neon-odoo-app odoo shell -d <DB> --no-http \
        < pwa9_crm_matching_smoke.py

REAL path -- an UNMAPPED client texts the lane (handle_inbound -> client
lane); WA-9 links the new crm.lead to an existing res.partner by exact
phone_sanitized, dedupes across sessions (fold open / new-opp after closed),
and NEVER auto-creates a res.partner. Plus the GATED dry-run backfill.
Rolls back.

T1   known number -> lead.partner_id = the matched partner; NO partner created
T2   unknown number -> partner_id empty; res.partner count UNCHANGED
T3   cross-session repeat while OPEN -> folds into the open lead, no duplicate
T4   repeat after CLOSED (lost) -> NEW opportunity, partner from the old lead
T5   shared number (2 partners) -> most-recent match
T6   backfill dry-run -> correct rows, writes NOTHING, no partner created
T7   backfill apply -> partner_id set only where matched; idempotent re-run
TR   _wa9 helpers are pure-read (create no partner/lead)
TL   a MAPPED staff number does NOT enter the lane (Copilot), no WA-9 lead
"""
import traceback
from contextlib import ExitStack
from unittest.mock import patch

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append((name, ok))
    print(("PASS" if ok else "FAIL") + " " + name
          + (("" if ok else " :: " + str(detail))))


_sent = []
counters = {"run_turn": 0, "variant_for": 0}


def _reset():
    for k in counters:
        counters[k] = 0


try:
    from odoo.addons.neon_channels.models.wa_copilot import (
        WhatsAppCopilotService,
    )
    from odoo.addons.neon_ai_core.models.ai import tool_registry  # noqa: F401
    from odoo.addons.neon_ai_core.models.ai.groq_chat_adapter import (
        ChatTurnResult,
    )

    env = env(context=dict(env.context, tracking_disable=True,
                           mail_create_nosubscribe=True, mail_create_nolog=True,
                           mail_notify_force_send=False))
    WM = env["neon.whatsapp.message"].sudo()
    WMcls = type(WM)
    Lead = env["crm.lead"].sudo()
    Partner = env["res.partner"].sudo()
    Sess = env["neon.wa.client.session"].sudo()
    g_user = env.ref("base.group_user")

    def n_partners():
        return Partner.with_context(active_test=False).search_count([])

    def mk_partner(name, phone=None):
        vals = {"name": name}
        if phone:
            vals["phone"] = phone
        return Partner.create(vals)

    def leads_for(phone):
        return Lead.with_context(active_test=False).search(
            [("phone", "=", phone)], order="id")

    def reset_session(phone_e164):
        s = Sess.search([("phone_number", "=", phone_e164)])
        if s:
            s.write({"step": "greeted", "lead_id": False, "last_notify": False})

    # ---- stubs (no network; capture sends) ----
    def s_msg(self, to, body):
        _sent.append(("text", to, body)); return True

    def s_buttons(self, to, body, buttons):
        _sent.append(("buttons", to, body, buttons)); return True

    def s_list(self, to, body, bt, sections):
        _sent.append(("list", to, body, sections)); return True

    def s_iot(self, to, interactive, body):
        _sent.append(("iot", to, interactive, body)); return "interactive"

    def s_tmpl(self, to, name, language="en", body_params=None,
               quick_reply_payloads=None, url_button_param=None,
               recipient_partner=None, audit_body=None):
        return {"ok": True, "reason": "sent"}

    def stub_chat(self, messages, schemas):
        return (ChatTurnResult(success=True, assistant_message="ok",
                               tool_calls=[]), "google")

    o_rt = WhatsAppCopilotService.run_turn
    o_vf = WhatsAppCopilotService.variant_for

    def sp_rt(*a, **k):
        counters["run_turn"] += 1; return o_rt(*a, **k)

    def sp_vf(*a, **k):
        counters["variant_for"] += 1; return o_vf(*a, **k)

    def text_msg(b, frm):
        return {"id": "wamid.X", "from": frm, "type": "text",
                "text": {"body": b}}

    ENQ = "Hi, what's the pricing for a corporate dinner?"  # 'pricing' handoff

    def enquire(frm):
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg(ENQ, frm), {})

    with ExitStack() as st:
        st.enter_context(patch.object(WMcls, "send_message", s_msg))
        st.enter_context(patch.object(WMcls, "send_buttons", s_buttons))
        st.enter_context(patch.object(WMcls, "send_list", s_list))
        st.enter_context(patch.object(
            WMcls, "send_interactive_or_text", s_iot))
        st.enter_context(patch.object(WMcls, "send_template", s_tmpl))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "_provider_chat", stub_chat))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "run_turn", sp_rt))
        st.enter_context(patch.object(
            WhatsAppCopilotService, "variant_for", sp_vf))

        # ---- helper units (pure read) ----
        KNOWN = "+263772000001"
        p1 = mk_partner("WA9 Known Client Ltd", KNOWN)
        before = n_partners()
        m = WM._wa9_match_partner(KNOWN)
        miss = WM._wa9_match_partner("+263772000998")
        check("TR: _wa9_match_partner known->partner, unknown->empty, "
              "pure-read (no partner created)",
              m.id == p1.id and not miss and n_partners() == before,
              (m.id, bool(miss)))

        # ---- T1: known number links the partner ----
        enquire("263772000001")
        L1 = leads_for(KNOWN)
        check("T1 KNOWN: client lead linked to the matched partner; exactly "
              "one lead; Copilot 0",
              len(L1) == 1 and L1.partner_id.id == p1.id
              and counters["run_turn"] == 0,
              (len(L1), L1.partner_id.id if L1 else None))

        # ---- T2: unknown number -> empty partner_id, NO partner created ----
        UNK = "+263772000999"
        pcount = n_partners()
        enquire("263772000999")
        Lu = leads_for(UNK)
        check("T2 UNKNOWN: lead created, partner_id EMPTY, res.partner count "
              "UNCHANGED (no auto-create)",
              len(Lu) == 1 and not Lu.partner_id and n_partners() == pcount,
              (len(Lu), Lu.partner_id.id if Lu and Lu.partner_id else None,
               n_partners() - pcount))

        # ---- T3: cross-session repeat while OPEN -> fold (no duplicate) ----
        FOLD = "+263772000010"
        enquire("263772000010")
        Lf = leads_for(FOLD)
        chatter_before = len(Lf.message_ids) if Lf else 0
        reset_session(FOLD)                      # simulate >24h fresh session
        enquire("263772000010")
        Lf2 = leads_for(FOLD)
        chatter_after = len(Lf2.message_ids) if len(Lf2) == 1 else -1
        check("T3 FOLD: repeat-while-open folds into the SAME lead (no "
              "duplicate); follow-up appended to its chatter",
              len(Lf2) == 1 and Lf2.id == Lf.id
              and chatter_after > chatter_before,
              (len(Lf2), chatter_before, chatter_after))

        # ---- T4: repeat after CLOSED (lost) -> NEW opp, partner from old ----
        CLOSED = "+263772000020"
        p4 = mk_partner("WA9 Returning Co")      # NO phone -> direct match miss
        enquire("263772000020")
        Lc = leads_for(CLOSED)
        Lc.write({"partner_id": p4.id})
        Lc.write({"active": False})              # lost/archived == closed
        reset_session(CLOSED)
        pcount4 = n_partners()
        enquire("263772000020")
        Lc_all = leads_for(CLOSED)               # active + archived
        new_opp = Lc_all.filtered(lambda l: l.active and l.id != Lc.id)
        check("T4 CLOSED->NEW-OPP: a NEW active lead under the SAME contact "
              "(partner from the closed lead's fallback); no partner created",
              len(new_opp) == 1 and new_opp.partner_id.id == p4.id
              and n_partners() == pcount4,
              (Lc_all.ids, new_opp.partner_id.id if new_opp else None))

        # ---- T5: shared number -> most-recent partner ----
        SHARED = "+263772000030"
        mk_partner("WA9 Shared A", SHARED)
        p5b = mk_partner("WA9 Shared B", SHARED)  # created later -> most recent
        enquire("263772000030")
        Ls = leads_for(SHARED)
        check("T5 SHARED-NUMBER: most-recent partner matched",
              len(Ls) == 1 and Ls.partner_id.id == p5b.id,
              Ls.partner_id.id if Ls else None)

        # ---- T6 / T7: backfill dry-run + apply ----
        OK_PH, NO_PH = "+263772000040", "+263772000041"
        pk = mk_partner("WA9 Backfill Match", OK_PH)
        wtag = env.ref("neon_channels.crm_tag_whatsapp",
                       raise_if_not_found=False)
        o1 = Lead.create({"type": "lead", "name": "orphan match",
                          "phone": OK_PH, "user_id": False,
                          "tag_ids": [(4, wtag.id)] if wtag else False})
        o2 = Lead.create({"type": "lead", "name": "orphan nomatch",
                          "phone": NO_PH, "user_id": False,
                          "tag_ids": [(4, wtag.id)] if wtag else False})
        pcount6 = n_partners()
        rows = WM._wa9_backfill_orphans([o1.id, o2.id], dry_run=True)
        by_id = {r["lead_id"]: r for r in rows}
        check("T6 BACKFILL dry-run: o1 would_set the match, o2 no-match; "
              "writes NOTHING (partner_id still empty); no partner created",
              by_id[o1.id]["would_set_partner_id"] == pk.id
              and by_id[o2.id]["would_set_partner_id"] is None
              and not by_id[o1.id]["applied"]
              and not o1.partner_id and not o2.partner_id
              and n_partners() == pcount6,
              rows)
        rows2 = WM._wa9_backfill_orphans([o1.id, o2.id], dry_run=False)
        o1.invalidate_recordset(); o2.invalidate_recordset()
        check("T7 BACKFILL apply: o1.partner_id set to the match, o2 stays "
              "empty; no partner created",
              o1.partner_id.id == pk.id and not o2.partner_id
              and n_partners() == pcount6,
              (o1.partner_id.id, bool(o2.partner_id)))
        rows3 = WM._wa9_backfill_orphans([o1.id, o2.id], dry_run=False)
        o1.invalidate_recordset()
        check("T7b BACKFILL idempotent: re-apply is a no-op (already linked, "
              "not re-written)",
              o1.partner_id.id == pk.id
              and not [r for r in rows3 if r["applied"]],
              [r["applied"] for r in rows3])

        # ---- TL: a MAPPED staff number bypasses the lane (Copilot) ----
        STAFF = "+263772000050"
        su = env["res.users"].sudo().create({
            "name": "wa9_staff", "login": "wa9_staff",
            "email": "wa9staff@test.neon", "groups_id": [(6, 0, [g_user.id])]})
        env["neon.bot.user"].sudo().create(
            {"name": su.login, "phone_number": STAFF, "user_id": su.id})
        env["neon.whatsapp.message"].sudo().create({
            "name": "warm-staff", "direction": "inbound",
            "phone_number": STAFF, "message_type": "text",
            "message_body": "warm", "state": "received"})
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg(ENQ, "263772000050"), {})
        check("TL LANE-ONLY: a mapped staff number goes to the Copilot, NOT "
              "the client lane -> no WA-9 client lead created",
              counters["run_turn"] >= 1 and not leads_for(STAFF),
              (dict(counters), leads_for(STAFF).ids))

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
