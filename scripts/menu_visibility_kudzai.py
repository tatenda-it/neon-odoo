# -*- coding: utf-8 -*-
"""MENU-VISIBILITY (Kudzai only) -- one-shot, idempotent, reversible.

USABILITY declutter of Kudzai's launcher ONLY (login admin@neonhiring.co.zw).
NOT a security change; NOT a module. A menu-visibility module that re-gates
menus cannot hide a menu from ONE user without affecting every user in the
menu's group(s) -- menu visibility is the UNION of a user's groups. The only
per-user mechanism is adjusting Kudzai's OWN group membership, which is what
this does.

Run:  docker compose exec -T odoo odoo shell -d <db> --no-http < scripts/menu_visibility_kudzai.py

APPLIES (resolved by xml-id, never numeric):
  + neon_hr.group_neon_hr_admin            -> her HR-Admin half (full HR access).
  - website_slides.group_website_slides_officer  } hides the "eLearning" app from
  - website_slides.group_website_slides_manager  } her launcher (the only HIDE item
                                                   cleanly hideable per-user; these
                                                   grant no finance/HR/operational
                                                   ACL she needs).

REVERSE (to undo): swap the (4,..)/(3,..) commands --
  k.write({"groups_id": [(3, hr_admin.id), (4, ws_off.id), (4, ws_mgr.id)]})

⚠️ NOT DONE here (cannot be hidden per-user without breaking others / her ACL --
   flagged for Robin, see the gate report):
  - CRM, Sales: she sees them only via neon_jobs.group_neon_jobs_user, whose
    removal would strip her commercial.job READ (no other group of hers grants
    it) -- an access break, not a declutter.
  - Website, Neon Training, External Training: gated to base.group_user / empty
    (everyone); hiding them requires re-gating for ALL users (team-session round).

Idempotent: only writes the deltas that are still needed; safe to re-run.
⚠️ Modifies a LIVE non-test user row -> on prod this is a hard gate (separate GO).
"""
LOGIN = "admin@neonhiring.co.zw"  # Kudzai (Bookkeeper / HR-Admin)

U = env["res.users"].sudo()
k = U.search([("login", "=", LOGIN)], limit=1)
if not k:
    print("MENU-VIS: user %s not found -- aborting (no-op)." % LOGIN)
else:
    hr_admin = env.ref("neon_hr.group_neon_hr_admin")
    ws_off = env.ref("website_slides.group_website_slides_officer")
    ws_mgr = env.ref("website_slides.group_website_slides_manager")
    ops = []
    if hr_admin not in k.groups_id:
        ops.append((4, hr_admin.id))
    if ws_off in k.groups_id:
        ops.append((3, ws_off.id))
    if ws_mgr in k.groups_id:
        ops.append((3, ws_mgr.id))
    if ops:
        k.write({"groups_id": ops})
        env.cr.commit()
        print("MENU-VIS: applied %d delta(s) to %s." % (len(ops), LOGIN))
    else:
        print("MENU-VIS: already in target state for %s (no-op)." % LOGIN)
    # verification
    M = env["ir.ui.menu"]
    tops = sorted(x.name for x in M.with_user(k).search([("parent_id", "=", False)]))
    print("MENU-VIS: Kudzai now sees %d top-level apps; eLearning present=%s, "
          "Quotes present=%s, HR-admin=%s" % (
              len(tops), "eLearning" in tops, "Quotes" in tops,
              hr_admin in k.groups_id))
