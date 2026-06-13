# -*- coding: utf-8 -*-
"""WA-12 proof teardown — ARMED, run only on the explicit word AFTER proof #3.

Re-enumerates the live test residue AT RUN TIME (no hardcoded id list, so a
4th/Nth proof session's chain can't orphan). DRY-RUN by default (prints the
plan = the row-list gate); set TEARDOWN_APPLY=1 to delete after the human gate.

  docker compose exec -T odoo odoo shell -d neon_crm --no-http < .claude/wa12_proof_teardown.py            # DRY-RUN
  docker compose exec -T -e TEARDOWN_APPLY=1 odoo odoo shell -d neon_crm --no-http < .claude/wa12_proof_teardown.py

KEEPERS (never torn down): the WA-12 TBC placeholder VENUE (config seed
neon_finance.wa12_tbc_venue, id 4174 on prod — RULING 13-Jun: KEEP) + any
is_venue partner. The CATALOGUE stays (product.template, real prod data).

Baseline target after APPLY: quotes 0 / commercial jobs 1 / event jobs 1 /
partners 36.
"""
import os

APPLY = os.environ.get("TEARDOWN_APPLY") == "1"
P = env["res.partner"].sudo()
Q = env["neon.finance.quote"].sudo()
S = env["neon.wa.equip.session"].sudo()

# --- KEEPERS: config seeds / real records ---
keepers = set()
tbc = env.ref("neon_finance.wa12_tbc_venue", raise_if_not_found=False)
if tbc:
    keepers.add(tbc.id)

# --- RESIDUE: test-era partners (id >= the TBC seed) carrying a test signal:
# the intake source-ref, the staged [TEST-WA12] marker, or a known invented
# name (the 13-Jun reconciliation: Ellen Prestige / EC Rentals / Admire M /
# Tatenda Loyd). is_venue excluded (venues are real/config). Positive-signal
# (not a blanket id-sweep) so a real client created in the window is never hit;
# the printed plan is the gate. ---
TEST_NAMES = ["Ellen Prestige", "EC Rentals", "Admire M", "Tatenda Loyd"]
LOW_ID = min(keepers) if keepers else 0   # the TBC seed bounds the test era
residue = P.with_context(active_test=False).search([
    "&", "&",
    ("id", ">=", LOW_ID), ("id", "not in", list(keepers)),
    ("is_venue", "=", False),
    "|", "|",
    ("ref", "=", "whatsapp_quote"),
    ("ref", "=ilike", "%[TEST-WA12]%"),
    ("name", "in", TEST_NAMES),
])
# include child contacts of residue companies (e.g. Admire M under EC Rentals;
# a blank-ref contact no marker sweep would catch on its own).
children = P.with_context(active_test=False).search(
    [("parent_id", "in", residue.ids), ("id", "not in", list(keepers))])
residue = residue | children

quotes = Q.with_context(active_test=False).search(
    [("partner_id", "in", residue.ids)])
ejobs = quotes.mapped("event_job_id")
cjobs = ejobs.mapped("commercial_job_id")
# live WA-12 sessions (proof residue: q_*/qc_* steps) — deactivate, don't unlink
sessions = S.with_context(active_test=False).search([
    ("active", "=", True),
    ("step", "in", ("q_confirm", "q_reject", "q_items", "q_client",
                    "q_itemreq", "qc_pick", "qc_kind", "qc_name", "qc_dupe",
                    "qc_contact", "qc_phone", "qc_email")),
])

print("=== WA-12 PROOF TEARDOWN PLAN (%s) ===" % (
    "APPLY" if APPLY else "DRY-RUN"))
print("KEEP (config seed): %s" % [(tbc.id, tbc.name)] if tbc else "(none)")
print("residue partners (%d): %s" % (
    len(residue), [(p.id, p.name, p.ref or "") for p in residue]))
print("residue quotes (%d): %s" % (len(quotes), quotes.mapped("name")))
print("event_jobs: %s   commercial_jobs: %s" % (ejobs.ids, cjobs.ids))
print("WA-12 sessions to deactivate: %s" % sessions.mapped("phone_number"))

if not APPLY:
    print("\nDRY-RUN — review the rows above, then set TEARDOWN_APPLY=1.")
else:
    moves = env["account.move"].sudo().search(
        [("partner_id", "in", residue.ids),
         ("move_type", "in", ("out_invoice", "out_refund"))])
    moves.filtered(lambda m: m.state == "posted").button_draft()
    moves.filtered(lambda m: m.state != "draft").button_cancel()
    moves.with_context(force_delete=True).unlink()
    env["neon.finance.approval"].sudo().search(
        [("quote_id", "in", quotes.ids)]).unlink()
    env["neon.finance.invoice.schedule"].sudo().search(
        [("quote_id", "in", quotes.ids)]).unlink()
    # Meta-media / PDF residue (WA-12 teardown standard)
    env["ir.attachment"].sudo().search(
        [("res_model", "=", "neon.finance.quote"),
         ("res_id", "in", quotes.ids)]).unlink()
    env["neon.whatsapp.message"].sudo().search(
        [("message_type", "=", "document"),
         ("message_body", "in",
          ["wa12 pdf %s" % n for n in quotes.mapped("name")])]).unlink()
    quotes.unlink()
    ejobs.exists().unlink()
    cjobs.exists().unlink()
    sessions.write({"active": False})
    residue.unlink()
    env.cr.commit()
    print("\nAPPLIED + committed. Baseline now: quotes=%d / commercial jobs=%d "
          "/ event jobs=%d / partners=%d (catalogue untouched)." % (
              Q.search_count([]),
              env["commercial.job"].sudo().search_count([]),
              env["commercial.event.job"].sudo().with_context(
                  active_test=False).search_count([]),
              P.search_count([])))
