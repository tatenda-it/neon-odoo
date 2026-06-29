# -*- coding: utf-8 -*-
{
    "name": "Neon Core",
    "version": "17.0.1.0.1",
    "summary": "Neon RBAC meta-groups + ACL hygiene. Defines "
               "5 tier meta-groups (superuser / bookkeeper / "
               "sales_rep / lead_tech / crew) that cascade "
               "implied_ids across every Neon + relevant "
               "stdlib group. Resolves the base.user_admin != "
               "Robin gap and the universal-developer-mode "
               "leak from base.group_user.implied_ids.",
    "description": """
Neon Core
=========

The convergence point for Neon RBAC. Establishes 5 tier meta
groups whose implied_ids cascade the right Odoo + Neon groups
per tier. Resolves two structural drifts surfaced during the
Phase 7a deploy + pre-deploy Chrome sessions:

1. base.user_admin xmlid resolves to a system superuser on
   prod (not Robin), so every module's _post_init_hook that
   grants admin tier to base.user_admin silently misses
   Robin + Munashe.
2. base.group_user accumulated 4 implied_ids (group_no_one,
   group_multi_currency, product.group_product_pricelist,
   mail.group_mail_template_editor) via manual UI config
   during Phase 1-2 setup, granting developer mode + template
   editing + pricing visibility to every internal user.

Solution:
* Five meta-groups in data/neon_core_groups.xml whose
  implied_ids list the right stdlib + Neon groups per tier.
* _post_init_hook assigns known canonical users to their
  meta-group by login lookup (not base.user_admin xmlid).
* migrations/17.0.1.0.0/post-migrate.py strips the four
  unwanted implications from base.group_user so future user
  creation defaults clean.

Forward-compatible: future Neon modules adding new tier-
specific groups append themselves to the relevant meta
group's implied_ids via their own post_init_hook + ORM (4,
id) write (per reference_odoo17_implied_ids_orm_vs_sql.md).

Tier mapping:

* group_neon_superuser    (Robin, Munashe, Tatenda)
  Full Neon access + developer mode + everything stdlib

* group_neon_bookkeeper   (Kudzaiishe via admin@)
  Finance + Sales read-all + Training user, NO dev mode

* group_neon_sales_rep    (Lisa, Evrill)
  CRM + own quotes + Training user, NO finance / NO dev

* group_neon_lead_tech    (permanent role; currently VACANT)
  Crew leader + Training signoff, NO finance / NO CRM

* group_neon_crew         (9 paused users + future hires)
  Internal user + jobs crew + Training user only

Phase 11 amendment candidates #6 + #7 from Chrome sessions
now structurally addressed.
""",
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Neon/Core",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        # Stdlib modules whose groups we cascade.
        "sale_management",
        "account",
        "crm",
        "product",
        # Neon modules whose groups we cascade. neon_workshop
        # does not exist in this repo; Workshop functionality
        # lives inside neon_jobs.
        "neon_jobs",
        "neon_finance",
        "neon_training",
        "neon_crm_extensions",
    ],
    "data": [
        # Category first so groups can reference it.
        "data/neon_core_category.xml",
        # Then the 5 meta-groups.
        "data/neon_core_groups.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "post_init_hook": "_post_init_hook",
}
