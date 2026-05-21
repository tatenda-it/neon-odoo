# -*- coding: utf-8 -*-
{
    'name': 'Neon Training',
    'version': '17.0.7.11.0',
    'summary': 'Phase 7a -- workforce training, certification, and '
               'skill tracking. M1: category + type reference. '
               'M2: per-person cert records with state machine. '
               'M3: per-category level UX + complete soft-skill '
               'seeding. M4: expiry cron + lifecycle compute + '
               'mail.template stubs. M5: notification dispatch '
               'cron + final template copy + TODO activities. '
               'M6: cross-competency model. M7: sign-off authority '
               'workflow. M8: event_job crew gate inference engine '
               '(inferred requirements + per-crew gate_status + '
               'event-level roll-up). M9: gating tier 1 -- '
               'informational toast + assignment_gate_log on crew '
               'assignment with missing qualifications. M10: '
               'gating tier 2 -- warn + override-reason wizard at '
               'quote acceptance. M11: gating tier 3 -- BLOCK + '
               'override-reason wizard at event_job in_progress '
               'transition; 24h freshness window suppresses '
               'wizard re-fire on recent override.',
    'description': """
Neon Training
=============
Phase 7a, the training and certification module.

M1 (17.0.7.0.0): foundation reference layer.

* neon.training.certification.category -- top-level taxonomy
  (Equipment, Role Tier, Safety, Soft Skill). Drives default
  policies (skill-level mode, expiry, external-trainer
  requirement) inherited by all child types.

* neon.training.certification.type -- individual certifications
  (e.g. "MA3 Console", "First Aid", "Class 4 Driver Licence").
  Cross-references neon.equipment.category / product.template
  for equipment-bound certifications. Sign-off authority +
  regulatory metadata captured per type.

M2 (17.0.7.1.0): per-person certification records.

* neon.training.certification -- the per-person record. State
  machine: draft -> pending_verification -> active -> expired /
  suspended. Self-upload with admin verify (B3=C). Many2many
  ir.attachment for certificate PDFs / photos. ir.rule scopes
  training_user to own records only (H2=A). res.users gains a
  Training tab with One2many to the user's certifications + two
  computed counts (active, expiring-soon).

Audit discipline (H3=A): perm_unlink=0 for ALL groups (admin
included) on every model. Corrections via state transitions
(suspend / re-cert with a new record) -- never via delete.

M3 (17.0.7.2.0): per-category level UX + seed completion.

* neon_dynamic_selection JS widget narrows the level dropdown on
  the certification form to only the values valid for the
  selected type's effective_skill_level_mode (binary /
  tiered_3 / custom). Backed by a computed available_levels Char
  on the record.

* Soft-skill seed completion per Robin's 10-category framing:
  Leadership, Client-Facing Comfort, Photography / Videography,
  Cash Handling / Financial Responsibility.

* Ranganai-knowledge seed polish: MA2 Console, Truss Climbing
  -- Prolyte, Class 2 / 3 / 5 Driver Licences, PSV Endorsement.

M4 (17.0.7.3.0): expiry tracking + daily cron + lifecycle states.

* Daily ir.cron walks active certs whose date_expires has passed
  into the 'expired' terminal state. Suspended records skipped
  (admin override trumps time); never-expires certs (validity
  _months=0) skipped.

* Three non-stored computed fields: days_to_expiry,
  is_expiring_soon, expiry_urgency. M5 dispatch logic reads
  expiry_urgency to pick the matching mail.template.

* Three mail.template stubs (90 / 30 / 7 day reminder copy).
  M4 ships record definitions only; M5 wires the dispatch cron.

* DP3 strict: state='expired' is set by cron only. Manual write
  raises UserError pointing users to action_suspend. M2's
  action_mark_expired removed accordingly; _action_force_expire
  added as protected superuser-only helper for the cron itself.

* action_reactivate now blocks transition when date_expires <=
  today -- forces a new cert record with a fresh date_obtained
  rather than reactivating an aged-out record.

M5 (17.0.7.4.0): notification dispatch.

* Daily ir.cron _cron_dispatch_renewal_notifications reads
  expiry_urgency on active certs and fires the matching
  mail.template (90 / 30 / 7 day reminder) plus a mail.activity
  TODO on the cert holder. Channels: email + TODO. WhatsApp
  deferred to M5.1 / Phase 9.

* last_notification_sent_urgency field tracks the most-urgent
  tier already notified. Cron skips records whose urgency
  matches the recorded tier, so each cert lifecycle dispatches
  exactly 3 notifications (warn_90 then warn_30 then warn_7).

* Reset triggers: state change out of 'active', date_obtained
  edit, or type_id swap all clear the tracking field so the
  next cron pass re-evaluates.

* CC routing by sign_off_authority via group membership lookup
  (DP1=c): lead_tech to neon_jobs.group_neon_jobs_crew_leader,
  od_md to neon_finance.group_neon_finance_approver,
  external_trainer + self_with_peer add no CC.

* TODO discard on renewal (DP2): when a new active cert lands
  for an existing (user, type) pair, the create() override
  marks any open TODOs on prior records done via
  action_feedback (preserves chatter audit).

M6 (17.0.7.5.0): cross-competency model.

* neon.training.cross_competency captures real-world capability
  demonstrated on an event_job without requiring a formal cert
  (Robin's A4 'data analytics' angle).

* Sync TODO surface on commercial.event.job state transition
  to 'completed' (NOT 'closed' -- the operational moment vs
  the admin reconciliation moment; schema sketch section 4.3
  text inaccuracy logged as polish).

* Cross-cutting touch on commercial.event.job is surgical per
  the CLAUDE.md amendment from M4: 0 new fields, 2 new methods
  (write override + _create_cross_competency_todo helper), 0
  new buttons, 0 view modifications.

* Constraints: unique (user, type, event); demonstrated_at not
  in future; observer authority (signoff or admin); event date
  range (-7d / +90d window).

* Append-only audit (H3=A): perm_unlink=0 on every group.

M7 (17.0.7.6.0): sign-off authority workflow.

* _SIGN_OFF_AUTHORITY_GROUP module-level constant maps
  sign_off_authority enum to the Odoo group xmlid that holds
  the verification authority. Single source of truth consumed
  by M5's _resolve_cc_partners (refactored) + M7's new
  _resolve_verify_authority_partners + future M8 routing.

* Authority-routed verification TODOs: when a cert transitions
  to pending_verification, _create_verification_todo fires a
  mail.activity on the first user in the resolved authority
  group (DP1=a). Empty authority group falls back to admin
  with a chatter note for production deploy-gap detection
  (DP4).

* action_verify hardened with an authority gate: verifier
  must hold the authority group OR be admin/SUPERUSER. Admin
  bypass preserves emergency edits when the proper authority
  is unavailable.

* source_cross_competency_id field links a promoted cert back
  to its originating observation. Consistency constraint
  enforces user_id + type_id alignment with the source.

* action_promote_to_cert on cross_competency creates a draft
  cert from a flagged observation. Field-lock constraint on
  the observation side prevents source-of-truth drift after
  promotion.

* 4 M2 smoke verifier swaps (u_signoff -> u_admin) per
  CLAUDE.md 'M_N owns the fix' discipline.

M8 (17.0.7.7.0): event_job crew gate inference engine.

* commercial.job.crew inherit -- five computed (non-stored)
  fields: required_certification_type_ids, gate_status,
  gate_missing_certification_ids, gate_softening_cross
  _competency_ids, gate_softening_used. Six methods:
  _compute_required_certifications, _infer_role_tier
  _certifications, _infer_equipment_certifications,
  _compute_gate_status, _compute_gate_missing_certification
  _ids, _compute_gate_softening_cross_competency_ids.

* G1=B: requirements are INFERRED from crew.role +
  event_job equipment context, not declared. Role-tier
  inference via _ROLE_TIER_TO_CERT_XMLID dict. Equipment
  inference via job.event_job_ids.equipment_line_ids.product
  _template_id -> cert_type.equipment_model_id reverse
  lookup (sudo()).

* Gate status precedence: pending (no user) -> qualified
  (no requirements or all held) -> needs_cross_competency
  (gap fully softened by cc observations) -> unqualified
  (gap with no softener).

* commercial.event.job rollup: training_gate_status field +
  _compute (worst-status-wins) + _action_check_training_gate
  helper (returns structured dict for M9-M11 entry points).
  Tier semantics: info always ok; warn ok only when fully
  qualified; block ok unless unqualified (softened crew pass
  block per M6 + M11 design).

* res.users reverse o2m cross_competency_ids retroactively
  closes the M6 enumeration gap (gate-1 logged Phase 11
  polish item for the CLAUDE.md amendment).

* DATA LAYER ONLY. No state writes from M8. M9-M11 read the
  computed fields + call _action_check_training_gate to
  enact the three-tier layered gating.

M9 (17.0.7.8.0): gating tier 1 -- assignment-moment info toast.

* neon.training.assignment_gate_log model (NEW; schema sketch
  section 2.5 deferred from M1, M9 owns creation). 13 fields:
  event_job_id, crew_id, user_id, gate_tier, severity (computed
  from gate_tier), gate_status_at_fire, missing_certification
  _type_ids, softening_cross_competency_ids, override_reason,
  overridden_by_id, overridden_at, fired_at, triggered_by_id.
  H3=A perm_unlink=0 on every group; model unlink() raises
  UserError as belt-and-braces against sudo() bypass.

* commercial.job.crew create + write hooks (DP6 -- both
  lifecycle paths fire the gate, not just write). When
  user_id transitions to a truthy new value and the M8
  gate_status is in (unqualified, needs_cross_competency),
  one log per (crew, event_job) pair is created (DP7) for
  every event_job under the parent commercial.job in a
  non-terminal state. Terminal states (completed, closed,
  cancelled, released) are skipped -- late re-assignment on
  a closed event is an admin reconciliation, not an active
  gate decision.

* bus.bus._sendone toast on the triggering user's
  partner_id (DP1=a). Single-crew toast carries inline
  softener detail when there are <=2 softeners (DP4),
  summary phrasing otherwise. Multi-crew batch fires ONE
  summary toast (DP3); individual gate_log records still
  created per crew. Idempotent: a save that doesn't change
  user_id never re-fires the toast (DP5).

* commercial.event.job assignment_gate_log_ids o2m
  surfaces the gate-log notebook tab on the form. Tab is
  read-only (audit only); no edit buttons exposed.

* Tier 1 (M9 info) NEVER populates override_reason /
  overridden_by_id. Those fields stay nullable for tier-1
  records; M10 / M11 populate on their tiers.

Subsequent milestones (M10-M12) layer on tier 2 warn at
quote_accept (with Approver override) and tier 3 block at
event_start (with override; cross-competency softeners
downgrade to warn). M12 adds the training compliance
dashboard.
""",
    'author': 'Neon Events Elements Pvt Ltd',
    'website': 'https://neonhiring.com',
    'category': 'Neon/Training',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        # neon_jobs provides neon.equipment.category + the
        # product.template workshop extension that certification
        # types Many2one into for equipment-bound certs.
        'neon_jobs',
        # neon_crm_extensions is not consumed by M1 surfaces but
        # M2+ will hook into res.partner / employee linkage for
        # certification grants; declared now to avoid manifest
        # churn on the next install.
        'neon_crm_extensions',
        # P7a.M10 -- neon_finance dependency for the
        # neon.finance.quote inherit (action_accept hook).
        # No circular dep risk: neon_finance does not depend on
        # neon_training. Verified at install time during M10
        # gate-1 discovery.
        'neon_finance',
    ],
    'data': [
        # security loads first so groups exist before the CSV
        # references them.
        'security/neon_training_groups.xml',
        'security/ir.model.access.csv',
        # P7a.M2 -- ir.rule on the certification model. Loads
        # AFTER the CSV so the model row exists in the registry
        # before domain_force compiles. noupdate=1 in the XML so
        # admin tweaks to a rule survive future upgrades.
        'security/neon_training_certification_rules.xml',
        # P7a.M6 -- ir.rule on the cross-competency model.
        'security/neon_training_cross_competency_rules.xml',
        # P7a.M9 -- ir.rule on the assignment_gate_log model.
        # Loads after the CSV via the same ordering convention.
        'security/neon_training_assignment_gate_log_rules.xml',
        # seed data: categories MUST load before types so the
        # category_id ref="..." lookups resolve.
        'data/neon_training_data.xml',
        # P7a.M4 -- daily expiry cron + reminder mail templates.
        # Load after the seed XML so model_id refs in the cron
        # record + templates resolve cleanly. noupdate=1 preserves
        # admin tweaks (cron active flag, template copy) on -u.
        'data/neon_training_cron.xml',
        'data/neon_training_mail_templates.xml',
        # views.
        'views/neon_training_certification_category_views.xml',
        'views/neon_training_certification_type_views.xml',
        # P7a.M2 -- certification record views + res.users tab.
        'views/neon_training_certification_views.xml',
        'views/res_users_views.xml',
        # P7a.M6 -- cross-competency views (load before menu so
        # the action ref resolves).
        'views/neon_training_cross_competency_views.xml',
        # P7a.M9 -- assignment_gate_log views + action. Load
        # before menu so the menuitem action ref resolves.
        'views/neon_training_assignment_gate_log_views.xml',
        # P7a.M8 -- crew + event_job view inherits for training
        # gate display. Load before menu (no action refs to
        # resolve, but keeps grouping clean). After cross
        # _competency_views so any cross-file xpath ordering is
        # deterministic.
        'views/commercial_job_crew_views.xml',
        'views/commercial_event_job_views.xml',
        # P7a.M10 -- quote-accept override wizard view (transient
        # model; opened by the M10 hook on action_accept). No
        # menu entry -- wizard is only ever reached via the
        # ir.actions.act_window return from neon.finance.quote.
        'views/neon_training_quote_gate_override_wizard_views.xml',
        # P7a.M11 -- event-start (tier 3) BLOCK wizard view.
        'views/neon_training_event_start_gate_override_wizard_views.xml',
        # P7a.M12 -- find-qualified-user wizard view + server
        # action (loaded BEFORE menu so the menuitem ref resolves).
        'views/neon_training_find_qualified_user_wizard_views.xml',
        # P7a.M12 -- training compliance dashboard form + server
        # action (loaded BEFORE menu).
        'views/neon_training_dashboard_views.xml',
        # menus last so action ref()s resolve. M2 added the
        # Configuration submenu; M6 adds Cross-Competencies at
        # sequence=20 between Certifications and Configuration.
        'views/neon_training_menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            # P7a.M3 -- neon_dynamic_selection widget (mirror of
            # account.dynamic_selection kept local to avoid a
            # semantic dep on the account module).
            'neon_training/static/src/js/neon_dynamic_selection.js',
        ],
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
