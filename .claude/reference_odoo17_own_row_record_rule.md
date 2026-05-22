# Odoo 17 "own row" record rule pattern

Established across Phase 7b + Phase 7e. Documents the canonical shape for restricting a user-tier group to records they own, plus the four (now six) instances in the codebase.

## The pattern

```xml
<record id="rule_X_owner_own" model="ir.rule">
    <field name="name">{Tier} sees own {model} records</field>
    <field name="model_id" ref="model_X"/>
    <field name="groups" eval="[(4, ref('<group_xmlid>'))]"/>
    <field name="domain_force">[('<owner_field>', '=', user.<id_or_partner>)]</field>
    <field name="perm_read" eval="True"/>
    <field name="perm_write" eval="False"/>
    <field name="perm_create" eval="False"/>
    <field name="perm_unlink" eval="False"/>
</record>
```

Pair with an `ir.model.access.csv` row granting `perm_read=1` to the same group. The CSV row gives the user access to the model; the rule narrows them to their own rows.

## The "owner" field shape

Three shapes appear:

| Shape | Domain | When |
|---|---|---|
| Direct `user_id` | `[('user_id', '=', user.id)]` | Model has a direct M2O to res.users |
| Direct `partner_id` | `[('partner_id', '=', user.partner_id.id)]` | Model has M2O to res.partner (stdlib pattern) |
| Nested via parent | `[('parent_id.user_id', '=', user.id)]` | Model is a child whose parent carries the owner field |

Nested chains can go any depth Odoo's ORM supports (e.g., `enrollment_id.partner_id`). Performance is fine in practice — Odoo evaluates the rule via JOIN.

## Instances in the codebase (as of Phase 7e M7)

| Phase / Milestone | Model | Group | Domain |
|---|---|---|---|
| 7b M1 | `neon.onboarding.candidate` | `neon_jobs.group_neon_jobs_crew` | `[('user_id', '=', user.id)]` |
| 7b M1 | `neon.onboarding.audit.log` | `neon_jobs.group_neon_jobs_crew` | `[('candidate_id.user_id', '=', user.id)]` |
| 7b M8 | `neon.onboarding.candidate` | `base.group_portal` | `[('user_id', '=', user.id)]` |
| 7b M8 | `neon.onboarding.audit.log` | `base.group_portal` | `[('candidate_id.user_id', '=', user.id)]` |
| 7e M5 | `neon.lms.scenario.completion` | `neon_jobs.group_neon_jobs_crew` | `[('learner_id', '=', user.id)]` |
| 7e M7 | `slide.channel.partner` | `neon_jobs.group_neon_jobs_crew` | `[('partner_id', '=', user.partner_id.id)]` |
| 7e M7 | `neon.lms.track.completion` | `neon_jobs.group_neon_jobs_crew` | `[('enrollment_id.partner_id', '=', user.partner_id.id)]` |
| 7e M7 | `neon.lms.module.completion` | `neon_jobs.group_neon_jobs_crew` | `[('enrollment_id.partner_id', '=', user.partner_id.id)]` |

## Pairing with the access CSV

The rule narrows, the CSV grants. Both required for the tier to see anything. Example from `neon_lms/security/ir.model.access.csv`:

```csv
access_lms_track_completion_crew,LMS Track Completion - Crew (own via rule),model_neon_lms_track_completion,neon_jobs.group_neon_jobs_crew,1,0,0,0
```

CSV: read=1, write/create/unlink=0. Rule: domain narrows the read. Crew never writes their own completion record — M8 workflow writes via sudo.

## When to write to the model from the user's session

If a tier needs to update their own row (e.g., portal user updating their profile), bump `perm_write=True` in the rule AND set `perm_write=1` in the CSV. The write is then scoped to rows the user owns.

For Phase 7e: learners NEVER write to track / module / scenario completion directly. M8 workflow sudo-writes on their behalf based on quiz submissions + scenario signoffs. So the rule stays write=False.

## Why partner_id for stdlib slide.channel.partner

Stdlib Odoo models use `partner_id` (M2O to res.partner) instead of `user_id` (M2O to res.users) because partners can be customers (non-users). For Neon, every learner is also an internal or portal user, so `user.partner_id.id` resolves cleanly.

When inheriting an Odoo stdlib model, follow its convention: `partner_id` if the stdlib model uses it.

## Anti-pattern: rule alone without CSV

Just adding a rule without a CSV row means the tier has zero base access. The rule narrows what's accessible, but if nothing is accessible (no CSV row), the rule is moot. The tier sees nothing.

## Anti-pattern: CSV alone without rule

The CSV row grants read on the whole model. Without the rule, the tier sees everyone's rows. For "own row" semantics, you need both.
