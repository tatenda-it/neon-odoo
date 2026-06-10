# -*- coding: utf-8 -*-
"""B11 / WA-8 (+WA-8.1) Face 1 availability check smoke. Run via:
    docker exec -i neon-odoo-app odoo shell -d <DB> --no-http \
        < pwa8_availability_smoke.py

REAL path -- an entitled mapped user texts "free on <date>? <items>" ->
handle_inbound -> _wa8_maybe_intercept -> a traffic-light availability PER
ITEM for the time-window. PURE READ (WA-8 creates no reservation/line/unit;
the FIXTURE seeds the holds). Text-only. Rolls back.

Deterministic against the real catalogue: fixture products carry UNIQUE
pure-alpha tokens (wazqty/wazser/wazxfr/wazbnd/wazdst/wazcfd/wazsmk) used
verbatim in the item text, so the WA-6 matcher resolves to OUR products.

PARSE   tight command; mid-sentence / no-date / no-matched-item NOT grabbed
ENTITLE OD/superuser + sales tier + crew-leader + any mapped fallback; unmapped no
TZ      Harare-local window -> UTC (midnight-local = 22:00 UTC prev day; 2-6pm
        = 12:00-16:00 UTC); explicit reservation midnight boundary (no off-by-2h)
TIERS   (WA-8.1) spare -> green; exact capacity (free == needed) -> yellow tight/
        no-spare; short -> red ("only N in inventory" vs "N committed" + clash)
SERIAL  same-day non-overlap shares (green); same-day overlap eats the spare
XFER    a transferred unit drops from availability
EDIT    items sticky; bare new DATE re-checks; bare new TIME re-uses last date
LOCK    today/past refused; the day before allowed
CONFID  (WA-8.1) a confident multi-word match answers directly; a low-confidence
        fuzzy hit (product is a different KIND of thing) -> suggestion, never a
        silent answer; "yes" promotes + checks the suggested product
"""
import traceback
from contextlib import ExitStack
from datetime import datetime, time as dtime, timedelta
from unittest.mock import patch

import pytz

from odoo import fields

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
    from odoo.addons.neon_jobs.models.neon_equipment_conflict import (
        ConflictEngine,
    )

    env = env(context=dict(env.context, tracking_disable=True,
                           mail_create_nosubscribe=True, mail_create_nolog=True,
                           mail_notify_force_send=False))
    WM = env["neon.whatsapp.message"].sudo()
    WMcls = type(WM)
    EJ = env["commercial.event.job"].sudo()
    CJ = env["commercial.job"].sudo()
    Line = env["commercial.event.job.equipment.line"].sudo()
    Prod = env["product.template"].sudo()
    Unit = env["neon.equipment.unit"].sudo()
    Res = env["neon.equipment.reservation"].sudo()
    Sess = env["neon.wa.equip.session"].sudo()

    HARARE = pytz.timezone("Africa/Harare")
    now = fields.Datetime.now()
    today_l = pytz.utc.localize(now).astimezone(HARARE).date()
    check_d = today_l + timedelta(days=60)
    far_d = today_l + timedelta(days=90)
    past_d = today_l - timedelta(days=1)
    tomorrow_d = today_l + timedelta(days=1)

    def cmd_date(d):
        return d.strftime("%d %b %Y")   # explicit year -> no year-roll

    def utc_str(d, h, m=0):
        return "%s %02d:%02d:00" % (d.isoformat(), h, m)

    g_user = env.ref("base.group_user")
    g_su = env.ref("neon_core.group_neon_superuser")
    g_jobs_user = env.ref("neon_jobs.group_neon_jobs_user")
    g_crew_leader = env.ref("neon_jobs.group_neon_jobs_crew_leader")
    cat_truss = env.ref("neon_jobs.equipment_category_trussing")
    sample = CJ.search([], limit=1, order="id desc")
    venue_id = sample.venue_id.id if sample and sample.venue_id else False
    currency_id = (sample.currency_id.id if sample and sample.currency_id
                   else env.ref("base.USD").id)
    check("fixtures: groups + cat + venue/currency present",
          bool(g_user and g_su and g_jobs_user and cat_truss and venue_id
               and currency_id), (venue_id, currency_id))

    def mk_user(login, groups):
        return env["res.users"].sudo().create({
            "name": login, "login": login,
            "email": "".join(login.split()).lower() + "@test.neon",
            "groups_id": [(6, 0, [g.id for g in groups])]})

    def mk_bot(u, phone):
        env["neon.bot.user"].sudo().create({
            "name": u.login, "phone_number": phone, "user_id": u.id})

    sales = mk_user("wa8_sales", [g_user, g_jobs_user])
    SALES_PHONE, SALES_FROM = "+263881007001", "263881007001"
    mk_bot(sales, SALES_PHONE)
    su = mk_user("wa8_su", [g_user, g_su])
    SU_PHONE, SU_FROM = "+263881007002", "263881007002"
    mk_bot(su, SU_PHONE)
    env["ir.config_parameter"].sudo().set_param(
        "neon_channels.wa6_od_login", su.login)
    lead = mk_user("wa8_lead", [g_user, g_crew_leader])
    plain = mk_user("wa8_plain", [g_user])
    PLAIN_PHONE, PLAIN_FROM = "+263881007003", "263881007003"
    mk_bot(plain, PLAIN_PHONE)
    UNMAPPED_FROM = "263881007999"

    def warm(phone):
        env["neon.whatsapp.message"].sudo().create({
            "name": "warm-" + phone, "direction": "inbound",
            "phone_number": phone, "message_type": "text",
            "message_body": "warm", "state": "received"})
    for ph in (SALES_PHONE, SU_PHONE, PLAIN_PHONE):
        warm(ph)

    test_partner = env["res.partner"].sudo().create(
        {"name": "WA8 Test Client", "is_company": True})
    parent = CJ.create({"name": "WA8 Parent", "partner_id": test_partner.id,
                        "venue_id": venue_id, "currency_id": currency_id,
                        "state": "active", "event_date": check_d.isoformat()})
    gala = EJ.create({"commercial_job_id": parent.id, "name": "WA8 GALA",
                      "state": "planning", "event_date": check_d.isoformat()})
    gala.invalidate_recordset()

    # --- products (UNIQUE pure-alpha tokens; name == token unless a
    #     multi-word confidence case) ---
    def mk_qty(token, qoh, name=None, cat=None):
        return Prod.create({
            "name": name or token.upper(), "workshop_name": token,
            "is_workshop_item": True, "tracking_mode": "quantity",
            "quantity_on_hand": qoh,
            "equipment_category_id": cat.id if cat else False})

    def mk_serial(token, n, n_transferred=0):
        p = Prod.create({"name": token.upper(), "workshop_name": token,
                         "is_workshop_item": True, "tracking_mode": "serial"})
        units = Unit.create([{
            "product_template_id": p.id, "serial_number": "%s-%d" % (token, i),
            "condition_status": "good"} for i in range(n)])
        for u in units[:n_transferred]:
            u.sudo().write({"state": "transferred"})
        return p, units

    p_qty = mk_qty("wazqty", 10)
    p_ser, ser_units = mk_serial("wazser", 4)
    p_xfr, _xu = mk_serial("wazxfr", 3, n_transferred=1)     # supply 2
    p_bnd = mk_qty("wazbnd", 5)
    p_dst, _du = mk_serial("wazdst", 2)                       # 2, no holds
    # WA-8.1 confidence: a confident multi-word match (head noun 'truss' is in
    # the query) vs a low-confidence fuzzy hit (head noun 'remotes' is NOT).
    p_cfd = mk_qty("wazcfd", 5, name="WAZCFD Black Truss", cat=cat_truss)
    p_smk = mk_qty("wazsmk", 3, name="WAZSMK Machine Remotes")

    def mk_qty_hold(product, qty, frm, to):
        L = Line.create({"event_job_id": gala.id,
                         "product_template_id": product.id,
                         "quantity_planned": qty})
        L.reservation_ids.sudo().write({"reserve_from": frm, "reserve_to": to})
        return L

    Lq = mk_qty_hold(p_qty, 7, utc_str(check_d, 6), utc_str(check_d, 14))
    mk_qty_hold(p_bnd, 5, utc_str(check_d - timedelta(days=1), 22, 30),
                utc_str(check_d - timedelta(days=1), 23, 30))
    Res.create({"event_job_id": gala.id, "unit_id": ser_units[0].id,
                "reserve_from": utc_str(check_d, 6),
                "reserve_to": utc_str(check_d, 10), "state": "soft_hold"})

    check("FIX: supplies wazqty=10 ser=4 xfr=2(1 transferred) bnd=5 dst=2 "
          "cfd=5 smk=3",
          [ConflictEngine(env)._available_for_product(p.id)
           for p in (p_qty, p_ser, p_xfr, p_bnd, p_dst, p_cfd, p_smk)]
          == [10, 4, 2, 5, 2, 5, 3])
    check("FIX: qty COUNT hold = 7 over the daytime window",
          sum(Lq.reservation_ids.mapped("quantity")) == 7)

    # ================= PARSE =================
    check("PARSE: tight command; mid-sentence / no-command NOT a command",
          WM._wa8_is_command("free on 14 aug? truss x4")
          and WM._wa8_is_command("availability")
          and WM._wa8_is_command("available on the 14th")
          and not WM._wa8_is_command("are you free on friday for a call")
          and not WM._wa8_is_command("i'm free on monday")
          and not WM._wa8_is_command(""))
    check("PARSE: strip command leaves date + items",
          WM._wa8_strip_command("free on 14 aug? truss x4")
          == "14 aug? truss x4"
          and WM._wa8_strip_command("availability of truss") == "of truss")

    # ================= CONFIDENCE helper (WA-8.1 unit) =================
    check("CONFIDENCE: head-noun in query -> confident; extra head noun "
          "(remotes) -> not; dimension mismatch tolerated",
          WM._wa8_is_confident("wazcfd black truss", p_cfd)
          and not WM._wa8_is_confident("wazsmk machine", p_smk)
          and WM._wa8_head_noun("WAZSMK Machine Remotes") == "remotes"
          and WM._wa8_head_noun("17 AMP 6 WAY DISTRO") == "distro"
          and WM._wa8_head_noun("2.5M BLACK TRUSS") == "truss",
          [WM._wa8_is_confident("wazcfd black truss", p_cfd),
           WM._wa8_is_confident("wazsmk machine", p_smk),
           WM._wa8_head_noun("17 AMP 6 WAY DISTRO")])

    # ================= ENTITLEMENT =================
    check("ENTITLE: sales/OD/crew-leader/plain-mapped pass; empty fails",
          WM._wa8_can_check(sales) and WM._wa8_can_check(su)
          and WM._wa8_can_check(lead) and WM._wa8_can_check(plain)
          and not WM._wa8_can_check(env["res.users"].sudo().browse()))

    # ================= TZ =================
    w1 = WM._wa8_parse_window(cmd_date(check_d), now, HARARE)
    exp1 = HARARE.localize(datetime.combine(check_d, dtime(0, 0, 0))) \
        .astimezone(pytz.utc).replace(tzinfo=None)
    check("TZ: full-day local-midnight -> 22:00 UTC prev day (no off-by-2h)",
          w1.get("ok") and not w1["had_time"]
          and w1["w_from"] == exp1 and w1["w_from"].hour == 22, w1.get("w_from"))
    w2 = WM._wa8_parse_window(cmd_date(check_d) + " 2-6pm", now, HARARE)
    exp2 = HARARE.localize(datetime.combine(check_d, dtime(14, 0))) \
        .astimezone(pytz.utc).replace(tzinfo=None)
    check("TZ: '2-6pm' Harare -> 12:00-16:00 UTC; label shown",
          w2.get("ok") and w2["had_time"] and w2["w_from"] == exp2
          and w2["w_from"].hour == 12 and "14:00" in w2["time_label"]
          and "18:00" in w2["time_label"], w2.get("w_from"))
    w3 = WM._wa8_parse_window(cmd_date(check_d) + " 9-5", now, HARARE)
    check("TZ: ambiguous '9-5' -> conservative full day", w3.get("ok")
          and not w3["had_time"])

    # ================= mocks + spies =================
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

    def _d(s):
        return "".join(c for c in str(s or "") if c.isdigit())

    def last(kind="text", to=SALES_PHONE):
        for e in reversed(_sent):
            if isinstance(e, tuple) and e[0] == kind \
                    and (to is None or _d(e[1]) == _d(to)):
                return e
        return None

    def sess_for(phone):
        return Sess.search([("phone_number", "=", phone),
                            ("active", "=", True)], limit=1)

    def clear(phone):
        Sess.search([("phone_number", "=", phone)]).write({"active": False})

    def ask(body, frm=SALES_FROM):
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg(body, frm), {})
        return last("text", "".join(c for c in frm if c.isdigit()))

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

        D = cmd_date(check_d)

        # ---- TIERS: yellow exact, red short(dates), red inventory, green spare
        clear(SALES_PHONE)
        r = ask("free on %s? wazqty x3" % D)         # avail 3 == req 3
        s = sess_for(SALES_PHONE)
        check("T1 EXACT yellow: x3 vs avail 3 -> tight/no-spare (names WA8 "
              "GALA); av_check session; Copilot 0",
              r and "🟡" in r[2] and "tight" in r[2] and "WA8 GALA" in r[2]
              and s and s.step == "av_check" and counters["run_turn"] == 0,
              r[2] if r else None)

        # WA-8.1 headline (the distro 2-of-2 finding): exact, NO commitments
        clear(SALES_PHONE)
        r = ask("free on %s? wazdst x2" % D)          # 2 owned, 0 held
        check("T-DISTRO yellow: 2 owned / 2 needed, nothing booked -> tight, "
              "no spare (NOT green, no 'committed')",
              r and "🟡" in r[2] and "no spare" in r[2]
              and "committed" not in r[2] and "🟢" not in r[2],
              r[2] if r else None)

        r = ask("free on %s? wazqty x7" % D)          # avail 3 < 7, supply 10
        check("T2 red dates: x7 -> short, 'committed on these dates' (3 of 7) "
              "+ names WA8 GALA",
              r and "🔴" in r[2] and "committed on these dates" in r[2]
              and "3 of 7" in r[2] and "WA8 GALA" in r[2], r[2] if r else None)

        r = ask("free on %s? wazqty x12" % D)         # supply 10 < 12
        check("T3 red inventory: x12 -> 'only 10 in inventory' (NOT a clash)",
              r and "🔴" in r[2] and "only 10 in inventory" in r[2]
              and "committed" not in r[2], r[2] if r else None)

        clear(SALES_PHONE)
        r = ask("free on %s? wazqty x8" % cmd_date(far_d))   # avail 10 > 8
        check("T4 green spare: x8 on a clash-free date -> free (10 available)",
              r and "🟢" in r[2] and "10 available" in r[2], r[2] if r else None)

        # ---- SERIAL same-day overlap vs non-overlap ----
        clear(SALES_PHONE)
        r = ask("free on %s? wazser x4" % D)          # full day, hold 1, avail 3
        check("T5 red SERIAL full-day: x4 vs 3 free -> short, 3 of 4 + WA8 GALA",
              r and "🔴" in r[2] and "3 of 4" in r[2]
              and "committed on these dates" in r[2], r[2] if r else None)

        clear(SALES_PHONE)
        r = ask("free on %s 2-6pm? wazser x3" % D)    # clear of 6-10am, avail 4
        check("T6 green same-day NON-overlap: 2-6pm clear of the 6-10am hold "
              "-> spare (4 available); label 14:00",
              r and "🟢" in r[2] and "4 available" in r[2]
              and "14:00" in r[2], r[2] if r else None)

        clear(SALES_PHONE)
        r = ask("free on %s 8-11am? wazser x3" % D)   # hits 6-10am, avail 3
        check("T7 yellow same-day OVERLAP: 8-11am eats the spare -> x3 vs 3 "
              "-> tight, no spare",
              r and "🟡" in r[2] and "no spare" in r[2], r[2] if r else None)

        # ---- TRANSFER + TZ boundary ----
        clear(SALES_PHONE)
        r = ask("free on %s? wazxfr x3" % D)          # supply 2 < 3
        check("T8 red TRANSFER: 1 of 3 transferred -> 'only 2 in inventory'",
              r and "🔴" in r[2] and "only 2 in inventory" in r[2],
              r[2] if r else None)

        clear(SALES_PHONE)
        r = ask("free on %s? wazbnd x5" % D)          # 00:30-01:30 Harare hold
        check("T-TZ-BOUNDARY red: a 00:30-01:30 Harare hold IS caught by the "
              "full-day window (no off-by-2h) -> 0 of 5 / committed",
              r and "🔴" in r[2] and "committed on these dates" in r[2]
              and "0 of 5" in r[2], r[2] if r else None)

        # ---- EDIT LOOP: sticky items, new date / new time ----
        clear(SALES_PHONE)
        ask("free on %s? wazqty x3" % D)
        s0 = sess_for(SALES_PHONE)
        items0 = (s0._get_buffer() or {}).get("items") or []
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg(cmd_date(far_d), SALES_FROM), {})   # new DATE
        r = last("text", SALES_PHONE)
        s1 = sess_for(SALES_PHONE)
        items1 = (s1._get_buffer() or {}).get("items") or []
        check("T9 EDIT new-DATE: bare future date re-checks the SAME items "
              "(green on the clear date); av_check; items unchanged; Copilot 0",
              r and "🟢" in r[2] and cmd_date(far_d) in r[2]
              and s1 and s1.step == "av_check"
              and [it["product_id"] for it in items1]
              == [it["product_id"] for it in items0]
              and counters["run_turn"] == 0, r[2] if r else None)

        _sent.clear(); _reset()
        WM.handle_inbound(text_msg("8-11am", SALES_FROM), {})          # new TIME
        r = last("text", SALES_PHONE)
        s2 = sess_for(SALES_PHONE)
        items2 = (s2._get_buffer() or {}).get("items") or []
        check("T10 EDIT new-TIME: a bare time re-uses the last date + SAME "
              "items (label 08:00-11:00); av_check; Copilot 0",
              r and "08:00" in r[2] and "11:00" in r[2]
              and s2 and s2.step == "av_check"
              and [it["product_id"] for it in items2]
              == [it["product_id"] for it in items0]
              and counters["run_turn"] == 0, r[2] if r else None)

        # ---- DAY-BEFORE LOCK ----
        clear(SALES_PHONE)
        r = ask("free on %s? wazqty x3" % cmd_date(past_d))
        check("T11 LOCK: a past date is refused; NO session opened",
              r and "🔒" in r[2] and not sess_for(SALES_PHONE),
              r[2] if r else None)

        clear(SALES_PHONE)
        r = ask("free on %s? wazqty x3" % cmd_date(tomorrow_d))
        ok_tom = bool(r and "🔒" not in r[2] and sess_for(SALES_PHONE))
        _sent.clear()
        WM.handle_inbound(text_msg(cmd_date(today_l), SALES_FROM), {})
        r2 = last("text", SALES_PHONE)
        check("T11b LOCK boundary: tomorrow ALLOWED; a re-check for TODAY "
              "refused", ok_tom and r2 and "🔒" in r2[2],
              (ok_tom, r2[2] if r2 else None))

        # ---- UNKNOWN alongside a matched item ----
        clear(SALES_PHONE)
        r = ask("free on %s? wazqty x2, fizzbuzznope x1" % D)
        check("T12 UNKNOWN: unmatched -> 'not found'; matched item answered",
              r and "not found" in r[2] and "fizzbuzznope" in r[2]
              and ("🟢" in r[2] or "🟡" in r[2] or "🔴" in r[2]),
              r[2] if r else None)

        # ---- NOT GRABBED ----
        clear(SALES_PHONE)
        n1 = WM._wa8_maybe_intercept(
            text_msg("are you free on friday for a call", SALES_FROM))
        n2 = WM._wa8_maybe_intercept(
            text_msg("available for lunch?", SALES_FROM))
        n3 = WM._wa8_maybe_intercept(
            text_msg("free on %s? widgetnope gizmonope" % D, SALES_FROM))
        n4 = WM._wa8_maybe_intercept(
            text_msg("free on %s? wazqty x3" % D, UNMAPPED_FROM))
        check("T13-16 NOT GRABBED: mid-sentence / no-date / no-matched-item / "
              "unmapped -> intercept None",
              n1 is None and n2 is None and n3 is None and n4 is None,
              (n1, n2, n3, n4))
        clear(SALES_PHONE)
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg("hello what's the plan", SALES_FROM), {})
        check("T17 regression: an ordinary message -> Copilot ran (no grab)",
              counters["run_turn"] >= 1 and not sess_for(SALES_PHONE),
              dict(counters))

        # ---- mapped FALLBACK entitlement ----
        clear(PLAIN_PHONE)
        g = WM._wa8_maybe_intercept(
            text_msg("free on %s? wazqty x3" % D, PLAIN_FROM))
        check("T18 FALLBACK: a plain mapped user IS grabbed; av_check session",
              g is True and sess_for(PLAIN_PHONE), g)

        # ---- fresh command in-session = new check ----
        clear(SALES_PHONE)
        ask("free on %s? wazqty x3" % D)
        _sent.clear(); _reset()
        WM.handle_inbound(
            text_msg("free on %s? wazser x3" % D, SALES_FROM), {})
        sf = sess_for(SALES_PHONE)
        items_f = (sf._get_buffer() or {}).get("items") or []
        check("T19 fresh command in-session -> NEW check (items -> wazser); "
              "av_check; Copilot 0",
              sf and sf.step == "av_check"
              and any(it.get("product_id") == p_ser.id for it in items_f)
              and not any(it.get("product_id") == p_qty.id for it in items_f)
              and counters["run_turn"] == 0,
              [it.get("product_id") for it in items_f])

        # ---- PURE READ ----
        res_before = Res.search_count([("event_job_id", "=", gala.id)])
        ask("free on %s? wazqty x3" % D)
        ask("free on %s? wazser x3" % D)
        check("T20 PURE READ: repeated checks create ZERO new reservations",
              Res.search_count([("event_job_id", "=", gala.id)]) == res_before,
              res_before)

        # ================= WA-8.1 CONFIDENCE (real path) =================
        # T-CONF-1: a confident multi-word match answers DIRECTLY (the
        # "2.5 black truss" must-pass analog: head noun 'truss' is in query).
        clear(SALES_PHONE)
        r = ask("free on %s? wazcfd black truss x1" % D)
        check("T-CONF-1 confident: 'wazcfd black truss' (head noun in query) "
              "-> answered directly (green), NOT a suggestion",
              r and "🟢" in r[2] and "WAZCFD Black Truss" in r[2]
              and "🔎" not in r[2], r[2] if r else None)

        # T-CONF-2: a low-confidence fuzzy hit (the "smoke machine" ->
        # "...REMOTES" finding) -> SUGGESTION, never a silent answer.
        clear(SALES_PHONE)
        r = ask("free on %s? wazsmk machine x2" % D)
        sc = sess_for(SALES_PHONE)
        pend = (sc._get_buffer() or {}).get("pending") or []
        check("T-CONF-2 suggestion: 'wazsmk machine' -> suggestion naming "
              "WAZSMK Machine Remotes + 'yes', NOT a silent green/yellow/red; "
              "pending stored",
              r and "🔎" in r[2] and "WAZSMK Machine Remotes" in r[2]
              and "yes" in r[2].lower()
              and "🟢" not in r[2] and "🟡" not in r[2] and "🔴" not in r[2]
              and len(pend) == 1, (r[2] if r else None, len(pend)))

        # T-CONF-3: "yes" promotes + checks the suggested product.
        _sent.clear(); _reset()
        WM.handle_inbound(text_msg("yes", SALES_FROM), {})
        r = last("text", SALES_PHONE)
        sy = sess_for(SALES_PHONE)
        buf_y = sy._get_buffer() if sy else {}
        check("T-CONF-3 'yes': promotes + checks WAZSMK Machine Remotes (green, "
              "3 available); pending cleared; item now sticky; Copilot 0",
              r and "🟢" in r[2] and "WAZSMK Machine Remotes" in r[2]
              and not (buf_y.get("pending") or [])
              and any(it.get("product_id") == p_smk.id
                      for it in (buf_y.get("items") or []))
              and counters["run_turn"] == 0,
              (r[2] if r else None, buf_y.get("pending")))

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
