# -*- coding: utf-8 -*-
"""P7g smoke -- LMS course-page branding (data + logic).

Run in an odoo shell:  odoo shell -d neon_crm --no-http < p7g_smoke.py

Covers the branding helpers (track cards + hero stats, reusing the
existing neon.lms.track model), the one-shot branding-config method
(neon_branded + members-publish + Robin responsible + cover cleared +
lessons published + orphan 'MNN content' cleanup), the 17->7 track
grouping, and that module/section titles are real (not 'M0X content').
The rendered page is covered by p7g_browser_smoke.py.

Mutations run in-transaction and roll back at the end.
"""
import re

from odoo import fields

env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))

results = {}


def _check(name, ok, detail=""):
    results[name] = bool(ok)
    if not ok:
        print("  %s: FAIL %s" % (name, detail))


Ch = env["slide.channel"].sudo()
Sl = env["slide.slide"].sudo()
Users = env["res.users"].sudo()
ch = Ch.search([("neon_track_ids", "!=", False)], limit=1)
_check("T-P7G-00", bool(ch), "Neon channel (with tracks) exists")

# =====================================================================
# 1-6  track cards (helper reuses neon.lms.track -- no parallel map)
# =====================================================================
cards = ch._neon_track_cards()
_check("T-P7G-01", len(cards) == 7, "7 track cards, got %d" % len(cards))

by_name = {c["name"]: c for c in cards}
found = next((c for c in cards if c["is_gate"]), None)
_check("T-P7G-02", found and found["module_count"] == 2,
       "Foundations gate card has 2 modules: %s" % (found and found["module_count"]))
_check("T-P7G-03", sum(1 for c in cards if c["is_gate"]) == 1,
       "exactly 1 gate (Foundations) card")
_check("T-P7G-04", sum(c["module_count"] for c in cards) == 17,
       "card module counts sum to 17: %d" % sum(c["module_count"] for c in cards))
_check("T-P7G-05",
       all(re.match(r"^#[0-9a-fA-F]{6}$", c["color"]) for c in cards),
       "every card has a hex accent colour")
_check("T-P7G-06", all(c["cert_label"] for c in cards),
       "every card names the sub-cert it earns")

# =====================================================================
# 7-10  hero stats strip
# =====================================================================
stats = ch._neon_branding_stats()
_check("T-P7G-07", stats["tracks"] == 7, "stats tracks=%s" % stats["tracks"])
_check("T-P7G-08", stats["modules"] == 17, "stats modules=%s" % stats["modules"])
_check("T-P7G-09", stats["certs"] == 8,
       "stats certs=8 (7 sub + capstone): %s" % stats["certs"])
_check("T-P7G-10",
       stats["lessons"] == Sl.search_count([
           ("channel_id", "=", ch.id), ("is_category", "=", False),
           ("sequence", ">=", 1000)]),
       "stats lessons matches content-slide count: %s" % stats["lessons"])

# =====================================================================
# 11-17  branding-config method (reset -> apply -> assert; in-tx)
# =====================================================================
robin = Users.search([("login", "=", "robin@neonhiring.co.zw")], limit=1)
_check("T-P7G-11", bool(robin), "robin@neonhiring.co.zw user resolves")

# reset to a pre-branding state + seed an orphan + an unpublished lesson
ch.write({"neon_branded": False, "visibility": "public", "is_published": False})
orphan = Sl.create({
    "name": "M09 content", "channel_id": ch.id, "slide_category": "article",
    "sequence": 0, "is_category": False, "is_published": False})
lesson = Sl.create({
    "name": "L9.9 -- P7g test lesson", "channel_id": ch.id,
    "slide_category": "article", "sequence": 1599, "is_category": False,
    "is_published": False})

ch._neon_apply_branding_config()

_check("T-P7G-12", ch.neon_branded is True, "neon_branded set")
_check("T-P7G-13", ch.visibility == "members",
       "visibility=members (enrolled-only, NOT public): %s" % ch.visibility)
_check("T-P7G-14", ch.is_published is True, "channel published")
_check("T-P7G-15", ch.user_id.login == "robin@neonhiring.co.zw",
       "Responsible=Robin (not OdooBot): %s" % ch.user_id.login)
_check("T-P7G-16", lesson.is_published is True, "real lesson published")
_check("T-P7G-17", not orphan.exists(), "orphan 'M09 content' deleted")
_check("T-P7G-18", not ch.image_1920, "stock cover image cleared")

# idempotent: a second apply is a no-op (no error, state stable)
ch._neon_apply_branding_config()
_check("T-P7G-19", ch.neon_branded and ch.visibility == "members",
       "config idempotent on re-apply")

# =====================================================================
# 20-23  titles real + 17->7 grouping (mapping confirmed at Gate 1)
# =====================================================================
secs = Sl.search([("channel_id", "=", ch.id), ("is_category", "=", True)])
_check("T-P7G-20",
       secs and not any(re.match(r"^M\d{2} content$", s.name or "") for s in secs),
       "section titles are real, none are 'M0X content'")

fnd = ch.neon_track_ids.filtered(lambda t: t.code == "TRK_FOUND_SAFETY")
fnd_mods = set(fnd.module_ids.mapped("code"))
_check("T-P7G-21", {"M01", "M08"} <= fnd_mods,
       "Foundations gate = M01 + M08 (power=safety): %s" % fnd_mods)

lig = ch.neon_track_ids.filtered(lambda t: t.code == "TRK_LIGHTING")
aud = ch.neon_track_ids.filtered(lambda t: t.code == "TRK_AUDIO")
vid = ch.neon_track_ids.filtered(lambda t: t.code == "TRK_VIDEO_LED")
_check("T-P7G-22",
       "M14" in lig.module_ids.mapped("code")
       and "M15" in aud.module_ids.mapped("code")
       and "M16" in vid.module_ids.mapped("code"),
       "console modules mapped: M14->Lighting, M15->Audio, M16->Video")

rig = ch.neon_track_ids.filtered(lambda t: t.code == "TRK_RIGGING")
_check("T-P7G-23", rig.module_count == 1 and not rig.is_foundation_gate,
       "Rigging = single module, not a gate")

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
