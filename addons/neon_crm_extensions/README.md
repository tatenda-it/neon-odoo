# Neon CRM Extensions

Phase 1A custom Odoo module for **Neon Events Elements** — a premium event production company in Harare, Zimbabwe. Adds CRM workflow automation on top of Odoo 17 Community without modifying Odoo core.

## What this module does

Adds the following to the standard Odoo CRM:

- **8 custom fields on `crm.lead`** for branding, GDPR consent, SLA tracking, lead scoring, equipment briefs, and annual-client tracking. See [FIELDS.md](FIELDS.md).
- **1 custom field on `mail.activity`** (`x_alert_tier`) for urgency classification.
- **A combined alert ribbon** on the lead form — yellow for duplicates, red for SLA breaches, red for both.
- **Daily deduplication detection** that flags leads sharing a phone or email.
- **5 first-wave automation rules** that create Odoo activities for stuck deals, quote follow-ups, annual client check-ins, and duplicate warnings. See [SCHEDULED_ACTIONS.md](SCHEDULED_ACTIONS.md).
- **An SLA tracking hook** that automatically stamps `x_first_response_time` on the first internal-user chatter post per lead.

## What this module does NOT do (yet)

These are deferred to later phases. The hooks and infrastructure are in place — only the integrations are missing:

- **WhatsApp Business API integration** (M2 — awaiting Meta Business verification)
- **Meta Lead Ads webhook** (M2)
- **Website form ingestion** (M2)
- **AMBER daily digest email** for medium-priority alerts (M2)
- **GREEN weekly digest email** for reports (M2)
- **Monthly lost-deal report** (deferred indefinitely; low priority)
- **Weekly source performance report** (deferred indefinitely; low priority)

## Module layout

```
neon_crm_extensions/
├── __init__.py             # Module entrypoint
├── __manifest__.py         # Module metadata, dependencies, data files
├── README.md               # This file
├── FIELDS.md               # Reference for every custom field
├── SCHEDULED_ACTIONS.md    # Reference for every cron job
├── data/
│   └── cron_jobs.xml       # 6 ir.cron records (1 dedup + 5 rule runners)
├── models/
│   ├── __init__.py
│   ├── crm_lead.py         # crm.lead inheritance — fields, computes, hook, rules
│   └── mail_activity.py    # mail.activity inheritance — x_alert_tier
├── security/
│   └── ir.model.access.csv # Access rights (currently header-only)
└── views/
    └── crm_lead_views.xml  # Form + tree view inheritance
```

## Installation

This module is intended to run inside the Neon Docker stack (Odoo 17 Community + Postgres 15) defined at the repository root. To install:

1. Ensure the module folder is on Odoo's `addons_path` (already wired in `docker-compose.yml`)
2. Restart Odoo if not already running:
```bash
   docker compose up -d
```
3. Open Odoo at `http://localhost:8069` → Apps menu → Update Apps List
4. Search for `neon_crm_extensions` (remove the default Apps filter if needed)
5. Click Install

Dependencies are declared in `__manifest__.py`:
- `crm` (Odoo CRM, base)
- `sale_management` (used by Quote Sent stage logic)
- `phone_validation` (used by phone normalisation)
- `mail` (used by message_post override and activities)

## Upgrade workflow — IMPORTANT

**Never use the in-UI Upgrade button for code or view changes.** It is unreliable: it bumps the version number in `ir_module_module` but skips re-running `ALTER TABLE` migrations and view inheritance reloads, leaving the registry in an inconsistent state.

Always use the command-line forced upgrade:

```bash
docker compose stop odoo
docker compose run --rm odoo odoo -d neon_crm -u neon_crm_extensions --stop-after-init
docker compose start odoo
```

The middle command runs Odoo with `-u` (force upgrade), `--stop-after-init` (exit when done). Watch its output for `Module neon_crm_extensions loaded` and any tracebacks before bringing the regular container back up with `start`.

## Pre-flight syntax checks

Before any forced upgrade, validate Python and XML files:

```bash
docker compose exec -T odoo python3 -c "import ast; ast.parse(open('/mnt/extra-addons/neon_crm_extensions/models/crm_lead.py').read()); print('Python OK')"

docker compose exec -T odoo python3 -c "import xml.etree.ElementTree as ET; ET.parse('/mnt/extra-addons/neon_crm_extensions/views/crm_lead_views.xml'); print('XML OK')"
```

Catching syntax errors here saves a full upgrade cycle.

## Direct database queries

When Odoo's UI hides records (for permission, filter, or view reasons), query Postgres directly to see the truth:

```bash
docker compose exec -T db psql -U odoo -d neon_crm -c "SELECT id, name, x_duplicate_flag FROM crm_lead WHERE active = true;"
```

Note `db`, not `odoo` — Postgres runs in the `db` container.

## Design conventions

- **All custom field names start with `x_`** to make them easy to identify and to avoid collisions with future Odoo upstream fields.
- **All custom method names start with `_neon_`** for the same reason. The underscore also makes them private — they cannot be called via JSON-RPC.
- **Idempotent automation rules**: each rule checks for an existing activity with its `[Neon Rule N]` summary prefix before creating a new one. Daily reruns will not spam users.
- **Phone normalisation is internal-only**: stored phone values are not modified. The dedup logic normalises on read so `+263 77 210 1001` and `0772101001` resolve to the same key.

## Testing private methods via JSON-RPC

Odoo blocks remote calls to underscore-prefixed methods. For testing only, wrap a call in a temporary `ir.actions.server`:

```python
# In a server action, state=code
result = env['crm.lead']._neon_run_dedup_check()
env['ir.config_parameter'].sudo().set_param('test.result', str(result))
```

Then run the action and read the parameter back. Delete both the action and the parameter when finished.

This pattern is documented at length in the verification reports for Sections 5–7 in the project history.

## Version history

See `git log` and the milestone tracker for a full record.

| Version | Highlights |
|---|---|
| 17.0.1.0.0 | Initial release covering Sections 3–7 of the M1 Action Plan |

## Authors and ownership

- **Maintainer:** Tatenda (`@tatenda-it`)
- **Sponsor:** Neon Events Elements (Robin Goneso, MD)
- **License:** LGPL-3

## Support

For developer questions, open an issue on the GitHub repository. For end-user questions about how to use the system day-to-day, see the separate **Lisar & Munashe User Guide** (Word document, distributed outside this repository).