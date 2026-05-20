# -*- coding: utf-8 -*-
{
    'name': 'Neon Training',
    'version': '17.0.7.0.0',
    'summary': 'Phase 7a — workforce training, certification, and '
               'skill tracking for Neon Events Elements crew + '
               'employees. M1: certification category + type '
               'reference models with append-only audit discipline.',
    'description': """
Neon Training
=============
Phase 7a (this milestone, P7a.M1): the foundation reference layer
for the training system.

* neon.training.certification.category — top-level taxonomy
  (Equipment, Role Tier, Safety, Soft Skill). Drives default
  policies (skill-level mode, expiry, external-trainer
  requirement) inherited by all child types.

* neon.training.certification.type — individual certifications
  (e.g. "MA3 Console", "First Aid", "Class 4 Driver Licence").
  Cross-references neon.equipment.category / product.template
  for equipment-bound certifications. Sign-off authority +
  regulatory metadata captured per type.

Audit discipline: every Phase 7a model carries perm_unlink=0
for ALL groups (admin included). Corrections via deactivation
+ new record with later effective scope, never via delete.

Subsequent milestones (M2-M12) layer on certification grants,
training events, expiry tracking, dashboards, and event_job
crew-gating. M1 ships reference data + admin surfaces only;
no operational integration.
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
        # seed data: categories MUST load before types so the
        # category_id ref="..." lookups resolve.
        'data/neon_training_data.xml',
        # views.
        'views/neon_training_certification_category_views.xml',
        'views/neon_training_certification_type_views.xml',
        # menus last so action ref()s resolve.
        'views/neon_training_menu.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
}
