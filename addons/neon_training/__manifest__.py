# -*- coding: utf-8 -*-
{
    'name': 'Neon Training',
    'version': '17.0.7.4.0',
    'summary': 'Phase 7a -- workforce training, certification, and '
               'skill tracking. M1: category + type reference. '
               'M2: per-person cert records with state machine. '
               'M3: per-category level UX + complete soft-skill '
               'seeding. M4: expiry cron + lifecycle compute + '
               'mail.template stubs. M5: notification dispatch '
               'cron + final template copy + TODO activities.',
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

Subsequent milestones (M6-M12) layer on cross-competency,
sign-off authority routing, and event_job assignment gating.
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
        # menus last so action ref()s resolve. Menu file rewritten
        # in M2: Certifications added at top; Categories + Types
        # reparented under a new Configuration submenu.
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
