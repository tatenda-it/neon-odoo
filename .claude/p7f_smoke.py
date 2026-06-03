# -*- coding: utf-8 -*-
"""P7f smoke — certificate numbering + PDF render + verification.

Run in an odoo shell:  odoo shell -d neon_crm --no-http < p7f_smoke.py

Scope (P7f does NOT rebuild issuance — that is M8): the create() override
that assigns NEON-<TOKEN>-<YEAR>-<SEQ> numbers (LMS sub + capstone types
only) + a verification_token (every cert); the Design-A QWeb/wkhtmltopdf
report (one track lit for a sub-cert, all 7 for the capstone); revoke
(active=False, append-only — never deleted); and the internal
verification lookup wizard (resolve by number or token; valid / revoked /
expired / not_found).

Numbering runs inside create(), which every issuance path calls, so
creating a cert of the capstone type (code 'neon_technical') exercises
the exact numbering path the M8 chain uses — hence T-P7F-02 proves the
capstone gets a NEON-TC number, not just the sub-certs (watch-item).

All creates roll back at the end (certs are perm_unlink=0 / append-only;
res_users is never unlinked). Only ir.sequence counters advance — gaps
are accepted (numbers stay unique; contiguity does not matter).
"""
import re

from odoo import fields
from odoo.exceptions import AccessError

env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))

results = {}


def _check(name, ok, detail=""):
    results[name] = bool(ok)
    if not ok:
        print("  %s: FAIL %s" % (name, detail))


Cert = env["neon.training.certification"].sudo()
CT = env["neon.training.certification.type"].sudo()
Users = env["res.users"].sudo()
Report = env["ir.actions.report"].sudo()
IMA = env["ir.model.access"].sudo()
Wiz = env["neon.training.cert.verify.wizard"].sudo()
year = fields.Date.today().year

# expected token per LMS cert-type code (mirror of NEON_CERT_META)
TOKENS = {
    "neon_foundations_safety": "FND", "neon_audio": "AUD",
    "neon_lighting": "LIG", "neon_video_led": "VID",
    "neon_workflow_ops": "WFL", "neon_rigging": "RIG",
    "neon_client_ready": "SOF", "neon_technical": "TC",
}
CAP_CODE = "neon_technical"


def _type(code):
    return CT.search([("code", "=", code)], limit=1)


# throwaway learner (get-or-create; rolled back at end either way)
learner = Users.search([("login", "=", "p7f_learner")], limit=1)
if not learner:
    learner = Users.with_context(no_reset_password=True).create({
        "name": "P7F Learner", "login": "p7f_learner",
        "email": "p7f_learner@neonhiring.com",
        "groups_id": [(6, 0, [env.ref("base.group_user").id])]})


def _cert(code, state="draft"):
    # default draft: numbering is assigned in create() regardless of
    # state, and draft avoids the one-active-per-(user,type) constraint
    # so the numbering/render checks can mint many same-type certs for
    # one learner. The verification checks pass explicit active/expired
    # states (each a distinct type, so no duplicate-active collision).
    return Cert.create({
        "user_id": learner.id, "type_id": _type(code).id,
        "date_obtained": fields.Date.today(), "state": state})


# =====================================================================
# 1-8  NUMBERING (scheme + per-token mapping + capstone watch-item)
# =====================================================================
sub = _cert("neon_audio")
_check("T-P7F-01", (sub.certificate_number or "").startswith("NEON-AUD-"),
       "sub audio number=%r" % sub.certificate_number)

cap = _cert(CAP_CODE)
_check("T-P7F-02", (cap.certificate_number or "").startswith("NEON-TC-"),
       "CAPSTONE number=%r (watch-item: must be NEON-TC)"
       % cap.certificate_number)

_check("T-P7F-03", str(year) in (cap.certificate_number or ""),
       "issue year %s in number %r" % (year, cap.certificate_number))

_check("T-P7F-04",
       bool(re.match(r"^NEON-AUD-%d-\d{4}$" % year,
                     sub.certificate_number or "")),
       "scheme NEON-AUD-YYYY-#### : %r" % sub.certificate_number)

# every LMS sub-track + capstone token maps correctly
token_ok = True
token_detail = []
for code, tok in TOKENS.items():
    c = _cert(code)
    pref = "NEON-%s-" % tok
    if not (c.certificate_number or "").startswith(pref):
        token_ok = False
        token_detail.append("%s->%r(want %s)" % (code, c.certificate_number,
                                                  pref))
_check("T-P7F-05", token_ok, "; ".join(token_detail))

a1 = _cert("neon_audio")
a2 = _cert("neon_audio")
seq1 = int(a1.certificate_number.rsplit("-", 1)[1])
seq2 = int(a2.certificate_number.rsplit("-", 1)[1])
_check("T-P7F-06", seq2 == seq1 + 1,
       "sequential AUD %d -> %d" % (seq1, seq2))

_check("T-P7F-07", TOKENS[CAP_CODE] == "TC" and not any(
    t == "TC" for k, t in TOKENS.items() if k != CAP_CODE),
    "capstone token TC distinct from sub tokens")

# non-LMS operational type -> NO number, but still a token
op = _cert("first_aid")
_check("T-P7F-08",
       not op.certificate_number
       and Cert._next_cert_number(_type("first_aid").id) is False,
       "non-LMS first_aid number=%r (expect empty)"
       % op.certificate_number)

# =====================================================================
# 9-11  VERIFICATION TOKEN + uniqueness constraints
# =====================================================================
_check("T-P7F-09",
       bool(re.match(r"^[0-9a-f]{32}$", cap.verification_token or "")),
       "capstone token=%r" % cap.verification_token)

_check("T-P7F-10", op.verification_token
       and op.verification_token != cap.verification_token,
       "non-LMS cert still gets a (unique) token")

cons = dict(Cert._sql_constraints and
            [(c[0], c[1]) for c in Cert._sql_constraints])
_check("T-P7F-11",
       "certificate_number_unique" in cons
       and "verification_token_unique" in cons,
       "unique constraints declared: %s" % list(cons))

# =====================================================================
# 12-20  RENDER VALS + PDF (Design A: tracks, signatory, seal, logo)
# =====================================================================
cv = cap._get_certificate_render_vals()
sv = sub._get_certificate_render_vals()

_check("T-P7F-12", sum(1 for t in cv["tracks"] if t["on"]) == 7,
       "capstone lights all 7 tracks (%d)"
       % sum(1 for t in cv["tracks"] if t["on"]))

on_sub = [t["label"] for t in sv["tracks"] if t["on"]]
_check("T-P7F-13", on_sub == ["Audio"],
       "sub-cert lights exactly its own track: %r" % on_sub)

_check("T-P7F-14", cv["signatory"] == "Robin Goneso"
       and cv["signatory_role"] == "Operations Director",
       "signatory=%r role=%r" % (cv["signatory"], cv["signatory_role"]))

_check("T-P7F-15", cv["seal"] == "NEON CERTIFIED"
       and sv["seal"] == "AUDIO TRACK",
       "seal cap=%r sub=%r" % (cv["seal"], sv["seal"]))

_check("T-P7F-16", cv["number"] == cap.certificate_number and cv["issued"],
       "render number=%r issued=%r" % (cv["number"], cv["issued"]))

_check("T-P7F-17", (cv["logo"] or "").startswith("data:image/png;base64,"),
       "logo data-uri present (len=%d)" % len(cv["logo"] or ""))

_check("T-P7F-18", "Technical Certification" in cv["title_html"],
       "capstone title=%r" % cv["title_html"])
_check("T-P7F-19", "Audio" in sv["title_html"]
       and "Track 2 of 7" in sv["eyebrow"],
       "sub title=%r eyebrow=%r" % (sv["title_html"], sv["eyebrow"]))

pdf_c, ext_c = Report._render_qweb_pdf(
    "neon_training.report_certificate_document", cap.ids)
pdf_s, _e = Report._render_qweb_pdf(
    "neon_training.report_certificate_document", sub.ids)
_check("T-P7F-20", pdf_c[:4] == b"%PDF" and len(pdf_c) > 5000
       and ext_c == "pdf",
       "capstone PDF %r len=%d" % (pdf_c[:4], len(pdf_c)))
_check("T-P7F-21", pdf_s[:4] == b"%PDF" and len(pdf_s) > 5000,
       "sub PDF %r len=%d" % (pdf_s[:4], len(pdf_s)))

# =====================================================================
# 22-25  REVOKE (active=False, append-only, chatter, ACL)
# =====================================================================
rev = _cert("neon_lighting")
rev.with_context(revoke_reason="smoke test").action_revoke()
_check("T-P7F-22", rev.active is False,
       "revoke -> active=%r (archived, not deleted)" % rev.active)

# still resolvable with active_test=False (record preserved)
still = Cert.with_context(active_test=False).search(
    [("id", "=", rev.id)])
_check("T-P7F-23", bool(still) and any(
    "REVOK" in (m.body or "").upper() for m in rev.message_ids),
    "record preserved + REVOKED chatter posted")

# append-only ACL: no group may unlink
unlink_perms = IMA.search(
    [("model_id.model", "=", "neon.training.certification")]
).mapped("perm_unlink")
_check("T-P7F-24", len(unlink_perms) > 0 and not any(unlink_perms),
       "perm_unlink=0 on every ACL row: %r" % unlink_perms)

# non-verifier / non-admin cannot revoke
plain = Users.search([("login", "=", "p7f_plain")], limit=1)
if not plain:
    plain = Users.with_context(no_reset_password=True).create({
        "name": "P7F Plain", "login": "p7f_plain",
        "email": "p7f_plain@neonhiring.com",
        "groups_id": [(6, 0, [env.ref("base.group_user").id])]})
denied = False
try:
    cap.with_user(plain).action_revoke()
except AccessError:
    denied = True
_check("T-P7F-25", denied,
       "plain user revoke -> AccessError (got denied=%s)" % denied)

# =====================================================================
# 26-30  VERIFICATION LOOKUP WIZARD
# =====================================================================
w = Wiz.create({})

c_active = _cert("neon_video_led", state="active")
cert_r, st = w._lookup(c_active.certificate_number)
_check("T-P7F-26", cert_r == c_active and st == "valid",
       "lookup by number -> %s (%s)" % (st, cert_r.id))

cert_r2, st2 = w._lookup(c_active.verification_token)
_check("T-P7F-27", cert_r2 == c_active and st2 == "valid",
       "lookup by token -> %s" % st2)

_, st3 = w._lookup("NEON-XXX-9999-9999-not-real")
_check("T-P7F-28", st3 == "not_found",
       "bogus query -> %s (expect not_found)" % st3)

c_rev = _cert("neon_rigging", state="active")
c_rev.with_context(revoke_reason="x").action_revoke()
cert_r4, st4 = w._lookup(c_rev.certificate_number)
_check("T-P7F-29", cert_r4 == c_rev and st4 == "revoked",
       "revoked cert lookup -> %s (resolves, not not_found)" % st4)

c_exp = _cert("neon_workflow_ops", state="expired")
_, st5 = w._lookup(c_exp.certificate_number)
_check("T-P7F-30", st5 == "expired",
       "expired-state cert lookup -> %s" % st5)

# idempotency: a write never renumbers (numbering is create-only)
n_before = c_active.certificate_number
c_active.write({"state": "active"})
_check("T-P7F-31", c_active.certificate_number == n_before,
       "write does not renumber (%r == %r)"
       % (c_active.certificate_number, n_before))

# =====================================================================
# 32-33  WIZARD ACL (signoff/admin can use it; plain user cannot) —
# the wizard is a TransientModel; with NO ACL rows even the intended
# signoff/admin users hit AccessError on open. with_user (not sudo)
# exercises the real grant, mirroring the signoff+admin-gated menu.
# =====================================================================
sign_u = Users.search([("login", "=", "p7f_signoff")], limit=1)
if not sign_u:
    sign_u = Users.with_context(no_reset_password=True).create({
        "name": "P7F Signoff", "login": "p7f_signoff",
        "email": "p7f_signoff@neonhiring.com",
        "groups_id": [(6, 0, [
            env.ref("base.group_user").id,
            env.ref("neon_training.group_neon_training_signoff").id])]})
acl_ok = False
try:
    wsign = Wiz.with_user(sign_u).create({})
    wsign.with_user(sign_u)._lookup("BOGUS")
    acl_ok = True
except AccessError:
    acl_ok = False
_check("T-P7F-32", acl_ok,
       "signoff user can create+lookup the verify wizard")

plain_denied = False
try:
    Wiz.with_user(plain).create({})
except AccessError:
    plain_denied = True
_check("T-P7F-33", plain_denied,
       "plain user denied the verify wizard (matches hidden menu)")

# =====================================================================
print()
print("=" * 72)
total = len(results)
passed = sum(1 for v in results.values() if v)
print("Total: {}/{} passed".format(passed, total))
for k in sorted(results):
    if not results[k]:
        print("  {}: FAIL".format(k))

env.cr.rollback()
