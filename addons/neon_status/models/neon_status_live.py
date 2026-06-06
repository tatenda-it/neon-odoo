# -*- coding: utf-8 -*-
"""B11 -- live-from-prod read collector for the Programme Status board.

A single AbstractModel (no table, no ACL row needed) whose ``collect()``
performs the four read-only lookups the board's "Refresh live status"
box shows. Every read is ``.sudo()`` and only AGGREGATES leave this
method --- counts, module version strings, and ``id:status`` pairs.
The sensitive rows themselves (``neon.bot.user`` phone mappings, the
``neon.finance.ai.chat.write.log`` audit bodies) never cross the
boundary.

⚠️ DECISION (B11, Gate-1, forced by ACL reality): the original spec had
the browser refresh via raw ``/web/dataset/call_kw``. Two of the four
models are unreadable by a non-admin --- ``neon.bot.user`` is
``base.group_system`` only and ``neon.finance.ai.chat.write.log`` is
``group_neon_superuser`` only (append-only financial audit model). So a
logged-in non-admin would hit ``AccessError`` on half the reads.
Loosening those ACLs would breach the audit-trail discipline, so the
refresh goes through this ``.sudo()`` collector instead. Read-only,
aggregates only.
"""
from odoo import api, fields, models

# The three modules whose installed versions the board reports. Kept as
# a module-level constant so it reads as one obvious list. (B11.)
_REPORTED_MODULES = ("neon_ai_core", "neon_channels", "neon_dashboard")


class NeonStatusLive(models.AbstractModel):
    _name = "neon.status.live"
    _description = "Programme Status -- live-from-prod read collector"

    @api.model
    def collect(self):
        """Return the live aggregates for the status board.

        Shape (all values are plain JSON types so the dict round-trips
        unchanged through both the QWeb render and the JSON endpoint)::

            {
              "module_versions": [{"name", "version", "state"}, ...],
              "bot_users":       {"active": int, "total": int},
              "whatsapp":        {"canonical": int, "total": int},
              "write_log":       [{"id": int, "status": str}, ...],
              "generated_at":         "<utc iso8601>",
              "generated_at_display": "<user-tz human string>",
            }
        """
        # 1. Installed module versions ---------------------------------
        imm = self.env["ir.module.module"].sudo()
        rows = imm.search_read(
            [("name", "in", list(_REPORTED_MODULES))],
            ["name", "installed_version", "latest_version", "state"],
        )
        by_name = {r["name"]: r for r in rows}
        module_versions = []
        for name in _REPORTED_MODULES:
            r = by_name.get(name)
            # installed_version is the display field; fall back to the
            # stored latest_version, then to an em-dash for "absent".
            version = "—"
            state = "not installed"
            if r:
                version = r.get("installed_version") or r.get(
                    "latest_version") or "—"
                state = r.get("state") or state
            module_versions.append(
                {"name": name, "version": version, "state": state})

        # 2. Bot users (mapped WhatsApp team members) ------------------
        bot = self.env["neon.bot.user"].sudo()
        bot_total = bot.search_count([])
        bot_active = bot.search_count([("active", "=", True)])

        # 3. WhatsApp messages -- total + canonical (E.164) ------------
        # "canonical" == phone_number stored in E.164 (leading '+'),
        # which the WA-1 boundary normalization writes. No dedicated
        # field, so the '+%' prefix is the canonical marker.
        wa = self.env["neon.whatsapp.message"].sudo()
        wa_total = wa.search_count([])
        wa_canonical = wa.search_count([("phone_number", "=like", "+%")])

        # 4. AI Copilot write-audit log -- id:status list --------------
        wl = self.env["neon.finance.ai.chat.write.log"].sudo()
        log_rows = wl.search_read([], ["id", "status"], order="id asc")
        write_log = [
            {"id": r["id"], "status": r.get("status") or "unknown"}
            for r in log_rows
        ]

        # Timestamp -- UTC iso for the machine, user-tz string for the
        # human-facing "last read" label.
        now = fields.Datetime.now()
        local = fields.Datetime.context_timestamp(self, now)
        return {
            "module_versions": module_versions,
            "bot_users": {"active": bot_active, "total": bot_total},
            "whatsapp": {"canonical": wa_canonical, "total": wa_total},
            "write_log": write_log,
            "generated_at": now.isoformat(),
            "generated_at_display": local.strftime("%d %b %Y, %H:%M %Z")
            or local.strftime("%d %b %Y, %H:%M"),
        }
