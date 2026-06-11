# -*- coding: utf-8 -*-
{
    "name": "Neon Programme Status",
    # B11 -- Programme Status board served as a real Odoo page.
    # First version of a deliberately tiny, single-purpose module:
    # one HTTP controller (the /neon/status page + a server-side
    # /neon/status/data refresh endpoint), one AbstractModel read
    # collector, one self-contained QWeb template. Read-only.
    #
    # Lives in its OWN module (NOT neon_dashboard) so the large
    # dashboard module does not have to take a new neon_channels
    # dependency just to read bot.user / whatsapp.message counts.
    # (Gate-1 decision 1, B11.)
    # 17.0.1.0.1 = planning-constant refresh after WA-1 shipped: WA-1
    # 60->100 (interactive renderer DONE), AI track 70->73, overall
    # 84->85; renderer moves Decided->Done. Constants/template only.
    # 17.0.1.0.2 = WA-2 shipped: WA-2 card 0->100/live, AI track 73->76,
    # overall 85->86; WA-2 moves Decided->Done. Constants/template only.
    # 17.0.1.0.3 = WA-3 shipped: WA-3 card 0->100/live, AI track 76->79,
    # overall 86->87; WA-3 moves Decided->Done. Constants/template only.
    # 17.0.1.0.4 = WA-4 shipped: WA-4 card 0->100/live, AI track 79->82,
    # overall 87->88; WA-4 moves Decided->Done; WA-5 promoted reserved->
    # "Client lane" lead roadmap item. Constants/template only.
    # 17.0.1.0.5 = WA-5 progress (NOT done): WA-5 card -> "In verification"
    # / 90% (built + deployed neon_channels 17.0.1.12.0; final live
    # assign-persistence + decline re-test pending). New 'verifying' card
    # state (label + CSS). WA-5 removed from "Decided · not yet built"
    # (it's built) but deliberately kept OUT of "Done & verified".
    # Overall (88) + AI-track (82) figures UNCHANGED -- WA-5 not credited
    # as complete yet. Constants/template only.
    # 17.0.1.0.6 = WA-5 -> DONE & VERIFIED (card live/100%, into "Done &
    # verified" with the ~hourly flood root-cause fix); WA-6 NEW card
    # "Crew + OD equipment face" -> in verification / 85% (deployed
    # neon_crew_comms 17.0.1.2.0 + neon_channels 17.0.1.17.0, 11 wa6_
    # intents, wa6_od_login set; pending real-phone proof + Meta
    # template). Added the equipment end-to-end prod proof to "Done &
    # verified". AI-track 82->86, overall 88->89 (milestone-count; WA-6
    # NOT over-claimed). Live box now reports neon_jobs + neon_crew_comms
    # (read live from prod). Constants + live-collector list only.
    # 17.0.1.0.7 = WA-5 card 100% -> 95% (still LIVE / Done & verified):
    # surfaces the two outstanding phone round-trip sub-checks (Munashe
    # 3-button render + cold-template render) numerically, not just in the
    # card body. WA-5 stays a DONE milestone -> AI-track (86) + overall
    # (89) rollups UNCHANGED by milestone count. Single constant.
    # 17.0.1.0.8 = WA-6 DONE (proof passed end-to-end on real phones): WA-6
    # card -> live/100%; AI Equipment Module 86->90 + overall 89->90
    # (milestone count: WA-6 done + P5.M11 quantity engine + WA-6.1 Face-3
    # dispatch all live). Added P5.M11 + WA-6 to "Done & verified"; AI track
    # text reflects B11 WhatsApp complete for the built scope. Constants.
    # 17.0.1.0.9 = WA-6.2 note: WA-6 card text gains the OD WhatsApp-
    # initiated finalize entry (text "finalize" → list from-scratch
    # planning/prep jobs → pick → existing 3-button choice). Text-only;
    # scores unchanged (WA-6.2 is part of the equipment face: 100/90/90).
    # 17.0.1.0.10 = WA-7 DONE (crew selection, real-phone proof passed):
    # new WA-7 card live/100%; AI-track "live" text now claims the full
    # phone-native ops cycle (crew select -> finalize -> checkout -> checkin)
    # end-to-end; fixed the stale "WA-0-WA-4" overall + B11 intro paragraphs
    # to WA-0 through WA-7. Text-only; scores unchanged (WA-7 within the
    # already-counted WhatsApp arm).
    # 17.0.1.0.11 = WA-8 DONE (sales availability Face 1, real-phone proof +
    # WA-8.1 re-proof passed): new WA-8 card live/100% ("Sales availability
    # (Face 1)"); promoted Face 1 from the AI-track "remaining/deferred" list
    # to live; intros + overall framing WA-0-WA-7 -> WA-0-WA-8; dropped the
    # stale "Sales Face 1 deferred" tail from the WA-6 card. Text/constants
    # only; scores UNCHANGED (90/90/90 -- one read-only face within the
    # already-90% AI module, within rounding, same call as WA-6.2/WA-7).
    # 17.0.1.0.12 = WA-9 client contact-matching card -> "In verification"
    # (live, neon_channels 17.0.1.19.0; Proof A passed, cross-session fold
    # proof pending a handset). Honest house rule: live but NOT done while a
    # proof is outstanding. Text/constants only; scores unchanged.
    # 17.0.1.0.13 = WA-5 card 95 -> 100 (DONE): the cold-template
    # handoff->assign loop is proven on real flows (Munashe assigned twice
    # after a ~48h window gap); buttons/rendering confirmed. The two in-window
    # link-reply buttons stay optional (read-only). Text/constants only;
    # scores unchanged (WA-5 was already milestone-counted).
    "version": "17.0.1.0.13",
    "summary": "Authenticated Programme Status board at /neon/status "
               "with a server-side, read-only live-from-prod refresh.",
    "description": """
Neon Programme Status (B11)
===========================

Serves the hand-rendered "Neon Events -- Programme Status" board as a
real, authenticated Odoo page at ``/neon/status`` so the team opens it
via a stable link and the "Refresh live status" button pulls real prod
values.

Design (Gate-1, B11)
--------------------

* ``GET  /neon/status``       -- the page (``auth='user'``, internal
  users only; portal/public excluded).
* ``POST /neon/status/data``  -- the refresh endpoint (``type='json'``,
  ``auth='user'``). Reads four datasets server-side with ``.sudo()``
  and returns AGGREGATES ONLY (counts / versions / id:status) -- never
  the sensitive ``neon.bot.user`` or ``neon.finance.ai.chat.write.log``
  rows themselves.

Why a server-side endpoint instead of raw ``/web/dataset/call_kw``
(the original spec mechanism): two of the four read targets are not
readable by a non-admin --- ``neon.bot.user`` is ``base.group_system``
only and ``neon.finance.ai.chat.write.log`` is ``group_neon_superuser``
only (an append-only financial audit model). Loosening those ACLs to
make ``call_kw`` work would breach the audit-trail discipline, so the
refresh goes through a ``.sudo()`` collector that exposes only the
aggregate numbers. This is the only way "refresh works for a logged-in
non-admin user" can be true.

The page is read-only: no model on this module owns a table, there are
no writes anywhere in the request path, and the whole surface is behind
Odoo login.

Audience is a one-line gate-constant
(``neon_status.controllers.main.STATUS_BOARD_GROUPS``). It ships empty
== all internal users (Gate-1 decision 2); set it to a tuple of group
xmlids to tighten to leadership later.
    """,
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Neon/Reporting",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        # res.groups xmlids for the (currently empty) audience gate +
        # tier reference parity.
        "neon_core",
        # neon.finance.ai.chat.write.log lives here (moved into the
        # shared AI engine at B11/PRE-WA-0).
        "neon_ai_core",
        # neon.bot.user + neon.whatsapp.message.
        "neon_channels",
    ],
    "data": [
        "views/neon_status_templates.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
