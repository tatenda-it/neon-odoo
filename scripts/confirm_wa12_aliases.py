# -*- coding: utf-8 -*-
"""Apply Robin's 6 rulings to the seeded alias rows (2026-06-13).

CONFIRM the 9 confident PROPOSED rows; RE-TARGET + CONFIRM the slang Robin
settled (cans/pars/parcans->term 'led can'; smoke->VERTICAL SMOKE MACHINES;
wedge->POWERWORKS MONITOR; blinder/blinders->term 'molefay'); LEAVE OPEN the
shortlist-only rows (totem(s)->trussing category hint; pa/sound system->term
'pa system' but shortlist; monitor->shortlist).

Touches ONLY the 21 rows by phrase; idempotent; prints before/after. Gated.

  docker compose exec -T odoo odoo shell -d neon_crm --no-http < scripts/confirm_wa12_aliases.py            # DRY-RUN
  docker compose exec -T -e WA12_ALIAS_CONFIRM_APPLY=1 odoo odoo shell -d neon_crm --no-http < scripts/confirm_wa12_aliases.py
"""
import os

APPLY = os.environ.get("WA12_ALIAS_CONFIRM_APPLY") == "1"

Alias = env["neon.equipment.alias"].sudo()
Cat = env["neon.equipment.category"].sudo()
PT = env["product.template"].sudo()
log = []


def out(m):
    log.append(m)


def prod_id(*needles):
    dom = [("active", "=", True), ("name", "not ilike", "[TEST"),
           ("name", "not ilike", "REMOTES"), ("name", "not ilike", "PACKAGE"),
           ("name", "not ilike", "WEDDING")]
    for n in needles:
        dom.append(("name", "ilike", n))
    p = PT.search(dom, order="name", limit=1)
    return (p.id, p.name) if p else (False, None)


def cat_id(code):
    c = Cat.search([("code", "=", code)], limit=1)
    return (c.id, c.code) if c else (False, None)


# (phrase, action). action ∈ {('confirm',), ('retarget_product', *needles),
#  ('retarget_term', term), ('retarget_cat', code), ('open_term', term),
#  ('open_cat', code), ('open',)}. confirm = state->confirmed, keep target.
PW_MONITOR = ("powerworks", "monitor")  # excludes 'INEAR' via order? no -> needle
PLAN = [
    # 9 confident -> CONFIRM (keep seeded target)
    ("screen", ("confirm",)), ("led screen", ("confirm",)),
    ("video wall", ("confirm",)), ("stage", ("confirm",)),
    ("staging", ("confirm",)), ("truss", ("confirm",)),
    ("trussing", ("confirm",)), ("fogger", ("confirm",)),
    ("fog machine", ("confirm",)),
    # re-target + confirm per Robin
    ("cans", ("retarget_term", "led can")),
    ("pars", ("retarget_term", "led can")),
    ("parcans", ("retarget_term", "led can")),
    ("smoke", ("retarget_product", "vertical smoke machine")),
    ("wedge", ("retarget_product_exact", "POWERWORKS MONITOR")),
    ("blinder", ("retarget_term", "molefay")),
    ("blinders", ("retarget_term", "molefay")),
    # leave OPEN (shortlist-only) -- but normalise their target to Robin's hint
    ("totem", ("open_cat", "trussing")),
    ("totems", ("open_cat", "trussing")),
    ("pa", ("open_term", "pa system")),
    ("sound system", ("open_term", "pa system")),
    ("monitor", ("open",)),  # keep as-is, OPEN, funnel shortlists the 4
]


def clear_targets(vals):
    vals["product_template_id"] = False
    vals["category_id"] = False
    vals["term"] = False


changes = []
for phrase, action in PLAN:
    row = Alias.search([("phrase", "=", phrase)], limit=1)
    if not row:
        out("!! MISSING ROW: %s" % phrase)
        continue
    before = "%s/%s/%s [%s]" % (
        row.product_template_id.name or "-", row.category_id.code or "-",
        row.term or "-", row.state)
    vals = {}
    act = action[0]
    if act == "confirm":
        vals = {"state": "confirmed"}
    elif act == "retarget_term":
        clear_targets(vals)
        vals.update({"term": action[1], "state": "confirmed"})
    elif act == "retarget_product":
        pid, pname = prod_id(action[1])
        if not pid:
            out("!! %s: product %r not found -> leaving OPEN" % (phrase, action[1]))
            vals = {"state": "open"}
        else:
            clear_targets(vals)
            vals.update({"product_template_id": pid, "state": "confirmed"})
    elif act == "retarget_product_exact":
        p = PT.search([("name", "=", action[1])], limit=1)
        if not p:
            out("!! %s: exact product %r not found -> OPEN" % (phrase, action[1]))
            vals = {"state": "open"}
        else:
            clear_targets(vals)
            vals.update({"product_template_id": p.id, "state": "confirmed"})
    elif act == "open_cat":
        cid, code = cat_id(action[1])
        clear_targets(vals)
        vals.update({"category_id": cid, "state": "open"})
    elif act == "open_term":
        clear_targets(vals)
        vals.update({"term": action[1], "state": "open"})
    elif act == "open":
        vals = {"state": "open"}

    # Compute the EFFECTIVE post-write state for an honest before/after, whether
    # or not we APPLY. `clear_targets` writes explicit False keys, so a key
    # PRESENT in vals is authoritative; a key ABSENT means "unchanged from row".
    def eff(key, current):
        return vals[key] if key in vals else current
    e_pid = eff("product_template_id", row.product_template_id.id)
    e_cid = eff("category_id", row.category_id.id)
    e_term = eff("term", row.term)
    e_state = eff("state", row.state)
    after = "%s/%s/%s [%s]" % (
        (PT.browse(e_pid).name if e_pid else "-"),
        (Cat.browse(e_cid).code if e_cid else "-"),
        (e_term or "-"), e_state)
    # invariant guard: exactly one target on a CONFIRMED row.
    ntargets = bool(e_pid) + bool(e_cid) + bool(e_term)
    if e_state == "confirmed" and ntargets != 1:
        out("!! CONSTRAINT RISK %s: %d targets on a confirmed row -> %s"
            % (phrase, ntargets, after))
    if APPLY:
        row.write(vals)
    changes.append("  %-13s %s  ->  %s" % (phrase, before, after))

out("=== ALIAS CONFIRM (%s) — Robin's 6 rulings ===" % (
    "APPLY" if APPLY else "DRY-RUN"))
for c in changes:
    out(c)
confirmed = Alias.search_count([("state", "=", "confirmed")])
openc = Alias.search_count([("state", "=", "open")])
prop = Alias.search_count([("state", "=", "proposed")])
out("\nstates now: confirmed=%d open=%d proposed=%d (proposed should be 0)"
    % (confirmed, openc, prop))
if APPLY:
    env.cr.commit()
    out("APPLIED + committed.")
else:
    out("DRY-RUN only — set WA12_ALIAS_CONFIRM_APPLY=1 to write.")
print("\n".join(log))
