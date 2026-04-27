# Custom Fields Reference

This file documents every custom field added by `neon_crm_extensions`. All field names are prefixed `x_` to make them easy to identify and to avoid collisions with future Odoo upstream fields.

## Fields on `crm.lead`

### x_brand
- **Type:** Selection (`neonhiring`, `neonevents`)
- **Tracked:** Yes
- **Set by:** Salesperson manually, during the Qualifying stage
- **Read by:** All users; visible on form and list views
- **Purpose:** Identifies which Neon brand owns the opportunity. `neonhiring` is equipment hire only; `neonevents` is full event production.

### x_consent_given
- **Type:** Boolean
- **Tracked:** Yes
- **Default:** `False`
- **Set by:** Salesperson manually, when GDPR consent is obtained
- **Read by:** Anyone preparing marketing communication; future M2 marketing module
- **Purpose:** Records explicit consent from the contact for marketing communications. Required before adding the contact to any newsletter or campaign list.

### x_equipment_required
- **Type:** Text (multi-line)
- **Set by:** Salesperson manually, on the Event Brief notebook tab
- **Read by:** Production team during event prep
- **Purpose:** Free-text capture of equipment the client is asking about. Phase 1 forward hook for Phase 3's structured equipment allocation module.

### x_annual_event_month
- **Type:** Selection (months `01`–`12`)
- **Set by:** Salesperson, after first confirmed annual booking
- **Read by:** Rule 8 (Annual Client re-engagement) for messaging context
- **Purpose:** For contacts tagged `Annual Client`, records the month their event typically falls in. Lets Rule 8's check-in messaging be more specific ("your November awards dinner is coming up").

### x_first_response_time
- **Type:** Datetime
- **Readonly:** Yes
- **Copy:** False (does not duplicate when the lead is duplicated)
- **Set by:** The `message_post()` override on `crm.lead` — automatically stamped on the first internal-user chatter message with content
- **Read by:** The `_compute_sla_breached` method
- **Purpose:** SLA tracking. Captures when Neon first responded to a new lead. The compute method `x_sla_breached` then checks whether this is more than 2 hours after `create_date`.

### x_sla_breached
- **Type:** Boolean (computed, stored)
- **Computed by:** `_compute_sla_breached`
- **Depends on:** `create_date`, `x_first_response_time`
- **Purpose:** True when first response took more than 2 hours after the lead was created. Drives the red `SLA Breached` ribbon and feeds into the unified alert label/colour.

> **Note:** The 2-hour threshold does not account for business hours yet. A lead created at 6 PM Friday with a response Monday 9 AM will be flagged as breached. This is acceptable for M1 — see the User Guide for context.

### x_lead_score
- **Type:** Integer (computed, stored — values 1–5)
- **Computed by:** `_compute_lead_score`
- **Depends on:** `expected_revenue`, `probability`
- **Purpose:** A 1–5 score auto-calculated from `expected_revenue × probability ÷ 100` — the *probable* revenue. Higher = more valuable lead. Currently shown as a plain integer next to the priority stars on the form, and as a sortable column in the list view.

| Probable revenue (USD) | Score |
|---|---|
| ≥ 10,000 | 5 |
| ≥ 5,000  | 4 |
| ≥ 2,000  | 3 |
| ≥ 500    | 2 |
| < 500    | 1 |

> **Tuning note:** The thresholds are reasonable starting values. Once Neon has 6+ months of real lead data, revisit them in `_compute_lead_score`.

### x_duplicate_flag
- **Type:** Boolean
- **Default:** `False`
- **Copy:** False
- **Set by:** `_neon_run_dedup_check` — daily scheduled action
- **Read by:** Rule 9 (duplicate warning), the unified alert ribbon
- **Purpose:** True when the dedup scan finds another active lead sharing this lead's phone or email. Both leads in a matching pair get flagged. The flag clears automatically when the matching lead is archived or deleted.

### x_alert_label
- **Type:** Char (computed, stored)
- **Computed by:** `_compute_alert`
- **Depends on:** `x_sla_breached`, `x_duplicate_flag`
- **Purpose:** Display text for the unified alert ribbon. One of: `"SLA + DUPLICATE"`, `"SLA Breached"`, `"Possible Duplicate"`, or empty.

### x_alert_color
- **Type:** Selection (`none`, `warning`, `danger`)
- **Computed by:** `_compute_alert`
- **Depends on:** `x_sla_breached`, `x_duplicate_flag`
- **Default:** `none`
- **Purpose:** Background colour class for the unified alert ribbon. SLA-related alerts use `danger` (red); duplicate-only uses `warning` (yellow).

> **Why two fields drive the ribbon:** Odoo's `web_ribbon` widget reads `title` and `bg_color` as static XML attributes. Three conditional ribbons in the form view (one per alert state) is simpler than fighting the framework with custom JavaScript.

## Fields on `mail.activity`

### x_alert_tier
- **Type:** Selection (`red`, `amber`, `green`)
- **Default:** `red`
- **Set by:** `_neon_create_activity` (called by Section 6 rules)
- **Purpose:** Urgency classification for Neon-generated activities. `red` activities surface in the bell icon and "My Activities" immediately. `amber` and `green` will roll up into M2's daily and weekly digest emails respectively (delivery deferred to M2; field is queryable from M1).

## Field placement in the form view

| Field | Form location |
|---|---|
| `x_brand` | Right-hand group, after Tags |
| `x_annual_event_month` | Right-hand group, after Brand |
| `x_consent_given` | After `email_from` in the contact group |
| `x_lead_score` | Inline next to priority stars on the Expected Closing row |
| `x_first_response_time` | Top of the Internal Notes notebook tab (readonly) |
| `x_equipment_required` | New "Event Brief" notebook tab (full width) |
| `x_sla_breached` / `x_duplicate_flag` | Hidden fields driving the unified ribbon (top-right) |

The list view shows `x_brand` and `x_lead_score` as columns after the Salesperson column, both with `optional="show"` so users can hide them if needed.