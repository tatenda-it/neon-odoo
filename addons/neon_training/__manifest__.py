# -*- coding: utf-8 -*-
{
    'name': 'Neon Training',
    'version': '17.0.7.1.0',
    'summary': 'Phase 7a -- workforce training, certification, and '
               'skill tracking for Neon Events Elements crew + '
               'employees. M1: category + type reference models. '
               'M2: per-person certification records with state '
               'machine, attachments, and admin verification.',
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

Subsequent milestones (M3-M12) layer on configurable skill
levels, expiry cron + reminders, cross-competency, sign-off
authority routing, and event_job assignment gating.
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
    'installable': True,
    'auto_install': False,
    'application': False,
}
