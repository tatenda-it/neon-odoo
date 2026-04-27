# Scheduled Actions Reference

This file documents every `ir.cron` record defined by `neon_crm_extensions`. All scheduled actions are defined in `data/cron_jobs.xml` with `noupdate="1"` so user customisations to schedule survive module upgrades.

## Where to manage these in the UI

Settings → Technical → Scheduled Actions → search for "Neon"

From there you can:
- Pause a job (toggle `active`)
- Change the schedule (`interval_number` + `interval_type`)
- Run manually for testing (the "Execute Manually" button)
- View next scheduled run (`nextcall`)

## Quick reference

| Cron name | Schedule | Calls | Tier |
|---|---|---|---|
| Neon: Daily lead deduplication check | Daily | `_neon_run_dedup_check` | infrastructure |
| Neon Rule 3: Quote follow-up Day 3 | Every 12 hours | `_neon_rule3_quote_followup_d3` | red |
| Neon Rule 4: Quote follow-up Day 7 escalation | Daily | `_neon_rule4_quote_followup_d7` | red |
| Neon Rule 5: Stuck deal alert | Daily | `_neon_rule5_stuck_deal` | red |
| Neon Rule 8: Annual client re-engagement | Weekly | `_neon_rule8_annual_client` | red |
| Neon Rule 9: Duplicate lead warning | Daily | `_neon_rule9_duplicate_warning` | red |

## Cron details

### Neon: Daily lead deduplication check

**Schedule:** Once per day
**Method called:** `crm.lead._neon_run_dedup_check()`
**XML id:** `ir_cron_neon_dedup_check`

**What it does:**
1. Fetches all active opportunities that have at least a phone or email
2. Builds two lookup maps: normalised phone → lead IDs, lowercased email → lead IDs
3. Any phone or email value mapping to 2+ lead IDs marks all those leads as duplicates
4. Sets `x_duplicate_flag = True` on all flagged leads
5. Clears `x_duplicate_flag` on any previously-flagged lead whose match has gone away (archived or deleted)

**Phone normalisation:** strips spaces, dashes, parentheses; drops a leading `0` or `+263` country code. So `+263 77 210 1001`, `(077) 210-1001`, and `0772101001` all resolve to the same key.

**Idempotent:** safe to run as many times as you like. Only writes flag changes when state actually changes.

**Drives:** Rule 9 (duplicate warning), the yellow ribbon on the lead form.

### Neon Rule 3: Quote follow-up Day 3

**Schedule:** Every 12 hours
**Method called:** `crm.lead._neon_rule3_quote_followup_d3()`
**XML id:** `ir_cron_neon_rule3_quote_d3`

**What it does:** Finds leads at the `Quote Sent` stage with no chatter activity for 3+ days, and creates a `mail.activity` for the assigned salesperson asking them to chase the client.

**Activity created:**
- Summary: `[Neon Rule 3] Chase quote — Day 3`
- Assigned to: lead's `user_id`, falls back to Munashe (MD) then Administrator
- Deadline: tomorrow
- Tier: red
- Note: prompt to send a friendly chase message

**Idempotency:** if the lead already has an open activity with `[Neon Rule 3]` in the summary, no new activity is created.

**Why every 12 hours:** quote follow-up is time-sensitive. A 12-hour cycle catches breaches twice a day so the salesperson is reminded the same business day where possible.

### Neon Rule 4: Quote follow-up Day 7 escalation

**Schedule:** Daily
**Method called:** `crm.lead._neon_rule4_quote_followup_d7()`
**XML id:** `ir_cron_neon_rule4_quote_d7`

**What it does:** Finds leads at `Quote Sent` with no chatter for 7+ days, and creates a `mail.activity` escalating to Munashe (MD), not the original salesperson.

**Activity created:**
- Summary: `[Neon Rule 4] Quote ESCALATION — Day 7`
- Assigned to: Munashe (always — this is the escalation tier), falls back to Administrator
- Deadline: tomorrow
- Tier: red
- Note: prompt indicating the Day 3 reminder fired but was not actioned

### Neon Rule 5: Stuck deal alert

**Schedule:** Daily
**Method called:** `crm.lead._neon_rule5_stuck_deal()`
**XML id:** `ir_cron_neon_rule5_stuck_deal`

**What it does:** Finds active opportunities in any non-`Confirmed` stage (with `probability > 0`) that have had no chatter for 7+ days, and creates a stuck-deal review activity for Munashe.

**Why exclude `probability = 0`:** lost deals (manually marked) shouldn't generate alerts.

**Activity created:**
- Summary: `[Neon Rule 5] Stuck deal — review`
- Assigned to: Munashe (MD)
- Deadline: 2 days from now
- Tier: red

### Neon Rule 8: Annual client re-engagement

**Schedule:** Weekly
**Method called:** `crm.lead._neon_rule8_annual_client()`
**XML id:** `ir_cron_neon_rule8_annual_client`

**What it does:** Finds leads tagged `Annual Client` with no activity for 270+ days (~9 months), and creates a personal-outreach reminder.

**Why weekly:** annual client data changes slowly. Daily would generate the same alerts repeatedly with little value.

**Activity created:**
- Summary: `[Neon Rule 8] Annual client check-in`
- Assigned to: lead's `user_id`, falls back to Munashe then Administrator
- Deadline: 3 days from now
- Tier: red
- Note: explicitly asks for a personal WhatsApp or call (not a mass email)

**Tag dependency:** if the `Annual Client` tag does not exist, the rule logs a warning and skips. To stop using this rule entirely, simply ensure no leads are tagged `Annual Client` (the cron will run but find nothing).

### Neon Rule 9: Duplicate lead warning

**Schedule:** Daily
**Method called:** `crm.lead._neon_rule9_duplicate_warning()`
**XML id:** `ir_cron_neon_rule9_duplicate_warning`

**What it does:** Reads `x_duplicate_flag` (set by the dedup check above) and creates a review activity for each flagged lead.

**Activity created:**
- Summary: `[Neon Rule 9] Possible duplicate — review`
- Assigned to: lead's `user_id`, falls back to Munashe then Administrator
- Deadline: tomorrow
- Tier: red
- Note: instructs the user to open both records and decide whether to merge or dismiss

**Order matters:** the dedup check (which sets the flag) and Rule 9 (which reads the flag) both run daily. As long as they're scheduled in either order they'll catch up within 24 hours.

## Tier classification

All five Section 6 rules currently produce `red`-tier activities. The tier field exists on `mail.activity` for future M2 work which will introduce:

- **AMBER (daily digest email):** medium-priority alerts batched into one daily email
- **GREEN (weekly digest email):** low-priority reports batched weekly

To filter activities by tier:

```python
env['mail.activity'].search([('x_alert_tier', '=', 'red')])
```

## Adding a new rule

The pattern, in `models/crm_lead.py`:

```python
@api.model
def _neon_ruleX_short_name(self):
    """One-line description of when this fires."""
    leads = self.search([
        # domain expressing the trigger condition
    ])
    prefix = "[Neon Rule X]"
    created = 0
    for lead in leads:
        if self._neon_has_open_activity(lead, prefix):
            continue  # idempotency guard
        self._neon_create_activity(
            lead=lead,
            summary=f"{prefix} <short user-facing summary>",
            note="<p>Action prompt for the user.</p>",
            user_id=lead.user_id.id or self._neon_md_user_id(),
            deadline_days=1,
        )
        created += 1
    import logging
    logging.getLogger(__name__).info(
        "[Neon Rule X] scanned %d, %d activities created",
        len(leads), created,
    )
    return leads
```

And in `data/cron_jobs.xml`:

```xml
<record id="ir_cron_neon_ruleX_short_name" model="ir.cron">
    <field name="name">Neon Rule X: Short description</field>
    <field name="model_id" ref="crm.model_crm_lead"/>
    <field name="state">code</field>
    <field name="code">model._neon_ruleX_short_name()</field>
    <field name="interval_number">1</field>
    <field name="interval_type">days</field>
    <field name="numbercall">-1</field>
    <field name="active" eval="True"/>
</record>
```

## Troubleshooting

**A rule isn't firing in production:** check Settings → Technical → Scheduled Actions → confirm `Active` is True and `Next Execution Date` is in the future (not stuck in the past, which means manual intervention).

**A rule is firing but no activity appears:** check the Odoo log for `[Neon Rule N]` log lines — each rule prints what it scanned and what it created. If `created = 0` despite matching records, the idempotency guard is hitting (an activity already exists with that prefix).

**An activity won't go away:** activities don't auto-delete when their underlying condition clears. Users mark activities done via the UI (which logs to chatter). To programmatically clean them up:

```python
env['mail.activity'].search([
    ('res_model', '=', 'crm.lead'),
    ('res_id', '=', LEAD_ID),
    ('summary', '=like', '[Neon Rule N]%'),
]).unlink()
```