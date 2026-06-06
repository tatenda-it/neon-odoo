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
    "version": "17.0.1.0.0",
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
