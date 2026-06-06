# -*- coding: utf-8 -*-
"""B11 Programme Status board smoke. Run via:
    docker compose exec -T odoo odoo shell -d <DB> --no-http < pb11_status_smoke.py

Asserts the read collector (neon.status.live.collect) returns the right
shape and aggregates ONLY, that it works under a NON-ADMIN env via its
internal .sudo() (the headline guarantee -- "refresh works for a
logged-in non-admin user"), that the two restricted models are indeed
unreadable by that same non-admin directly (proving the sudo path is
necessary, not gratuitous), and that the audience gate predicate admits
internal users and rejects portal/public. ROLLS BACK at the end.
"""
import traceback

from odoo.exceptions import AccessError

results = []


def check(name, cond, detail=""):
    ok = bool(cond)
    results.append((name, ok))
    line = ("PASS" if ok else "FAIL") + " " + name
    if detail and not ok:
        line += " :: " + str(detail)
    print(line)


_ALLOWED_STATUS = {"proposed", "confirmed", "executed", "cancelled",
                   "error", "expired", "unknown"}

try:
    # -- module + model present --------------------------------------
    mod = env["ir.module.module"].sudo().search(
        [("name", "=", "neon_status")], limit=1)
    check("neon_status installed", mod and mod.state == "installed",
          "state=%s" % (mod.state if mod else None))
    Live = env["neon.status.live"]
    # NB: bool() of an AbstractModel singleton is False (empty recordset);
    # presence is the registered _name.
    check("neon.status.live model present",
          Live._name == "neon.status.live")

    # -- collect() shape ---------------------------------------------
    data = Live.collect()
    for key in ("module_versions", "bot_users", "whatsapp", "write_log",
                "generated_at", "generated_at_display"):
        check("collect() has key '%s'" % key, key in data)

    # -- module versions: the 3 reported modules, in order, installed -
    from odoo.addons.neon_status.models.neon_status_live import (
        _REPORTED_MODULES)
    mv = data["module_versions"]
    check("module_versions: 3 rows in reported order",
          [m["name"] for m in mv] == list(_REPORTED_MODULES),
          [m["name"] for m in mv])
    check("module_versions: every version is a non-empty string",
          all(isinstance(m["version"], str) and m["version"] not in ("", "—")
              for m in mv),
          [(m["name"], m["version"]) for m in mv])
    check("module_versions: all 3 report state 'installed'",
          all(m["state"] == "installed" for m in mv),
          [(m["name"], m["state"]) for m in mv])

    # -- bot_users + whatsapp: int aggregates, canonical <= total ----
    bu = data["bot_users"]
    check("bot_users: active/total ints, 0 <= active <= total",
          isinstance(bu["active"], int) and isinstance(bu["total"], int)
          and 0 <= bu["active"] <= bu["total"], bu)
    wa = data["whatsapp"]
    check("whatsapp: canonical/total ints, 0 <= canonical <= total",
          isinstance(wa["canonical"], int) and isinstance(wa["total"], int)
          and 0 <= wa["canonical"] <= wa["total"], wa)

    # canonical counts ONLY '+'-prefixed (E.164). Create one of each and
    # assert the delta: canonical +1, total +2.
    WM = env["neon.whatsapp.message"].sudo()
    base = Live.collect()["whatsapp"]
    WM.create({"name": "B11-CANON", "direction": "inbound",
               "phone_number": "+263990001111", "message_type": "text"})
    WM.create({"name": "B11-RAW", "direction": "inbound",
               "phone_number": "263990002222", "message_type": "text"})
    after = Live.collect()["whatsapp"]
    check("whatsapp canonical = '+'-prefixed only (delta +1 of +2 added)",
          after["total"] - base["total"] == 2
          and after["canonical"] - base["canonical"] == 1,
          "base=%s after=%s" % (base, after))

    # -- write_log: list of {id:int, status:str}, ascending by id ----
    wl = data["write_log"]
    ids = [w["id"] for w in wl]
    check("write_log: list of {id,status}, valid statuses",
          isinstance(wl, list)
          and all(isinstance(w["id"], int)
                  and w["status"] in _ALLOWED_STATUS for w in wl),
          wl[:5])
    check("write_log: ordered ascending by id",
          ids == sorted(ids), ids[:10])

    # -- timestamps non-empty ----------------------------------------
    check("generated_at + display are non-empty strings",
          isinstance(data["generated_at"], str) and data["generated_at"]
          and isinstance(data["generated_at_display"], str)
          and data["generated_at_display"])

    # =================================================================
    # HEADLINE: collect() works for a NON-ADMIN, and that same non-admin
    # CANNOT read the restricted models directly (so the sudo path is
    # required, not gratuitous).
    # =================================================================
    def user_in_group(xmlid):
        g = env.ref(xmlid, raise_if_not_found=False)
        if not g:
            return env["res.users"]
        return env["res.users"].sudo().search(
            [("groups_id", "in", g.id), ("share", "=", False),
             ("active", "=", True)], limit=1)

    sales = user_in_group("neon_core.group_neon_sales_rep")
    check("a non-admin sales-rep fixture exists", bool(sales),
          "no sales-rep user on DB")
    if sales:
        check("non-admin is NOT base.group_system",
              not sales.has_group("base.group_system"))
        # collect() under the non-admin must succeed + match admin counts
        nd = Live.with_user(sales).collect()
        check("collect() succeeds under NON-ADMIN env",
              isinstance(nd, dict) and "bot_users" in nd)
        admin_counts = Live.collect()
        check("non-admin collect() == admin collect() (sudo parity)",
              nd["bot_users"] == admin_counts["bot_users"]
              and nd["whatsapp"] == admin_counts["whatsapp"]
              and len(nd["write_log"]) == len(admin_counts["write_log"])
              and [m["name"] for m in nd["module_versions"]]
              == [m["name"] for m in admin_counts["module_versions"]],
              "nd=%s admin=%s" % (nd["bot_users"], admin_counts["bot_users"]))

        # The BINDING constraint: neon.bot.user is base.group_system only,
        # so a non-admin is blocked reading it directly. This alone makes
        # the sudo collector necessary (the call_kw refresh in the spec
        # would AccessError here for every non-admin, incl. the broadest
        # audience member).
        try:
            env["neon.bot.user"].with_user(sales).search_count([])
            direct_bot = True
        except AccessError:
            direct_bot = False
        check("non-admin CANNOT read neon.bot.user directly (binding ACL)",
              not direct_bot)
        # whatsapp.message IS readable by base.group_user...
        try:
            env["neon.whatsapp.message"].with_user(sales).search_count([])
            wa_read = True
        except AccessError:
            wa_read = False
        check("non-admin CAN read whatsapp.message (base.group_user)",
              wa_read)
        # ...and write.log is readable by the Copilot tiers BY DESIGN:
        # neon_dashboard grants jobs_user/manager/bookkeeper/crew_leader
        # read so the Copilot panel can show its own audit. The board's
        # sudo read of id:status is therefore no wider than the existing
        # Copilot read path. (This CORRECTS the Gate-1 'write.log is
        # superuser-only' note, which only inspected neon_ai_core's CSV;
        # the design decision still holds on the strength of bot.user.)
        try:
            env["neon.finance.ai.chat.write.log"].with_user(
                sales).search_count([])
            wl_read = True
        except AccessError:
            wl_read = False
        check("write.log readable by a Copilot-tier non-admin (by design)",
              wl_read)

    # =================================================================
    # Audience gate predicate (shipped default == all internal users).
    # =================================================================
    from odoo.addons.neon_status.controllers.main import (
        user_may_view, STATUS_BOARD_GROUPS)
    check("shipped audience gate == all internal users (empty groups)",
          STATUS_BOARD_GROUPS == ())
    check("gate admits an internal user (env.user)",
          user_may_view(env.user) is True)
    if sales:
        check("gate admits a non-admin internal user",
              user_may_view(sales) is True)
    public = env.ref("base.public_user", raise_if_not_found=False)
    if public:
        check("gate REJECTS a share/public user",
              user_may_view(public) is False)
    else:
        check("base.public_user present to test the negative", False)

    # -- read-only guarantee: collect() created nothing --------------
    # (the two WM rows above were our explicit fixtures; collect itself
    # must not write -- assert it returns plain data and the model owns
    # no table.)
    check("neon.status.live is an AbstractModel (no table)",
          Live._abstract is True)

except Exception:  # noqa: BLE001
    traceback.print_exc()
    results.append(("smoke crashed", False))
finally:
    env.cr.rollback()

passed = sum(1 for _, ok in results if ok)
print("\nTotal: %d/%d passed" % (passed, len(results)))