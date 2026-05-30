# Phase 8A — Director Dashboard
## M1-M3 Batch Prompt for Claude Code

**Context**: This is the M1-M3 batch of Phase 8A (Director Dashboard) for the Neon CRM Odoo build. We are building the dashboard framework (M1), the headline KPI strip (M2), and the Jobs block (M3). The full design is in `Phase8_Schema_Sketch.docx` and `Neon_Dashboard_Sketch_v2.pdf` — both approved by Robin Goneso (Operational Director). Build exactly to that design.

**Working directory**: `~/neon-odoo/` (existing repo with phases 1-7 already built and deployed).

**Branch**: Create new branch `phase-8a-m1-m3` from `main`.

---

## 1. What this batch delivers

A working dashboard skeleton that any user can open and see:

- The 7-tile headline KPI strip at the top (all computing live, empty states where data is missing)
- View filter chips below (`All` / `Operations` / `Sales` / `Finance`)
- The Jobs block (today + this week, with click-through to event records)
- "Edit Layout" pencil top-right (visible but not yet functional — placeholder action shows a toast saying "Coming in Phase 8B")
- "View as..." dropdown for superusers (Robin, Munashe, Tatenda) — lets them flip `dashboard_type` for the current view
- Empty-state handling for every widget (no placeholder numbers anywhere)

When Robin opens the dashboard on a fresh Odoo install with no business data, he sees: `$0` cash, `0` jobs, "No upcoming jobs" message in the Jobs block, "Set a target →" in the Forecast tile. Everything renders. Nothing fakes data.

---

## 2. Out of scope for this batch

Do **not** build in M1-M3:
- Sales block, Finance block, Alerts panel, Crew & Equipment block (M4-M7)
- Task Management widget (M8)
- AI Insights widget (M11)
- Weekly digest cron (M9)
- PDF/Excel exports (M10)
- Mobile polish (M12) — but **do** include responsive CSS foundation
- Edit Layout interactivity (Phase 8B.M5) — but **do** ship the `neon.dashboard.user.layout` model
- ZiG-USD rate cron (M6)
- All Phase 8B variants (sales / bookkeeper / lead_tech / tech)

The View filter chips render visually (per design) but only `All` does anything in M3 — clicking other chips shows a "Coming in M5/M6" toast for now. The chip framework is in place; per-chip filtering wires up alongside the relevant block.

---

## 3. Module structure

Create new module `neon_dashboard` at `~/neon-odoo/addons/neon_dashboard/`:

```
neon_dashboard/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── dashboard.py              # neon.dashboard
│   ├── dashboard_user_layout.py  # neon.dashboard.user.layout
│   └── res_users.py              # extend res.users for default dashboard_type
├── controllers/
│   ├── __init__.py
│   └── dashboard_controller.py   # /neon/dashboard endpoint, KPI computation, Jobs query
├── security/
│   ├── neon_dashboard_security.xml   # groups
│   └── ir.model.access.csv
├── data/
│   ├── default_layouts.xml       # seed default layouts for each dashboard_type
│   └── menu.xml                  # menu entry under Neon root
├── views/
│   ├── dashboard_views.xml       # client action + template
│   └── dashboard_assets.xml      # asset bundles
├── static/
│   ├── src/
│   │   ├── js/
│   │   │   ├── dashboard.js           # Main OWL component
│   │   │   ├── kpi_tile.js            # KPI tile component
│   │   │   ├── view_filter_chips.js   # Filter chip row
│   │   │   ├── view_as_dropdown.js    # Superuser dashboard_type switcher
│   │   │   ├── jobs_block.js          # Jobs block component
│   │   │   └── empty_state.js         # Reusable empty-state component
│   │   ├── xml/
│   │   │   ├── dashboard.xml
│   │   │   ├── kpi_tile.xml
│   │   │   ├── view_filter_chips.xml
│   │   │   ├── view_as_dropdown.xml
│   │   │   ├── jobs_block.xml
│   │   │   └── empty_state.xml
│   │   └── scss/
│   │       └── dashboard.scss
└── tests/
    ├── __init__.py
    ├── test_m1_models.py
    ├── test_m2_kpi.py
    └── test_m3_jobs_block.py
```

---

## 4. Manifest

`__manifest__.py`:

```python
{
    'name': 'Neon Dashboard',
    'version': '17.0.1.0.0',
    'category': 'Operations',
    'summary': 'Unified role-aware dashboard for Neon Events Elements',
    'description': """
Phase 8 of the Neon CRM Odoo build. Provides the Director Dashboard plus framework
for Sales, Bookkeeper, Lead Tech, and Tech variants (Phase 8B).
    """,
    'author': 'Tatenda Ngairongwe',
    'website': 'https://neonhiring.com',
    'license': 'OPL-1',
    'depends': [
        'base',
        'mail',
        'neon_partners',
        'neon_operations',
        'neon_finance',
        'neon_actions',
        'neon_handoff',
        'neon_quote_lifecycle',
        'neon_post_event',
    ],
    'data': [
        'security/neon_dashboard_security.xml',
        'security/ir.model.access.csv',
        'data/menu.xml',
        'data/default_layouts.xml',
        'views/dashboard_views.xml',
        'views/dashboard_assets.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'neon_dashboard/static/src/js/**/*',
            'neon_dashboard/static/src/xml/**/*',
            'neon_dashboard/static/src/scss/dashboard.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
```

---

## 5. Models (M1)

### 5.1 `neon.dashboard`

`models/dashboard.py`:

```python
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class NeonDashboard(models.Model):
    _name = 'neon.dashboard'
    _description = 'Neon Dashboard Instance'
    _rec_name = 'name'

    user_id = fields.Many2one(
        'res.users', required=True, ondelete='cascade',
        default=lambda self: self.env.user.id,
        help="Owner of this dashboard instance",
    )
    dashboard_type = fields.Selection(
        [
            ('director', 'Director'),
            ('sales', 'Sales'),
            ('bookkeeper', 'Bookkeeper'),
            ('lead_tech', 'Lead Tech'),
            ('tech', 'Tech'),
        ],
        required=True, default='director',
    )
    name = fields.Char(compute='_compute_name', store=True)
    layout_ids = fields.One2many(
        'neon.dashboard.user.layout', 'dashboard_id',
        string='Widget Layout',
    )
    last_refresh = fields.Datetime(default=fields.Datetime.now)

    _sql_constraints = [
        ('user_type_unique',
         'unique(user_id, dashboard_type)',
         'A user can only have one dashboard of each type.'),
    ]

    @api.depends('user_id', 'dashboard_type')
    def _compute_name(self):
        for rec in self:
            type_label = dict(rec._fields['dashboard_type'].selection).get(rec.dashboard_type, '')
            rec.name = f"{rec.user_id.name}'s {type_label} Dashboard" if rec.user_id else type_label

    @api.model
    def get_or_create_for_user(self, user_id=None, dashboard_type=None):
        """Lazy-create a dashboard instance for a user. Called by the controller on first load."""
        user_id = user_id or self.env.user.id
        dashboard_type = dashboard_type or self._default_dashboard_type_for_user(user_id)
        dashboard = self.search([
            ('user_id', '=', user_id),
            ('dashboard_type', '=', dashboard_type),
        ], limit=1)
        if not dashboard:
            dashboard = self.create({
                'user_id': user_id,
                'dashboard_type': dashboard_type,
            })
            dashboard._seed_default_layout()
        return dashboard

    @api.model
    def _default_dashboard_type_for_user(self, user_id):
        """Map a user to their default landing dashboard. See §6.2 of schema sketch."""
        user = self.env['res.users'].browse(user_id)
        if user.has_group('neon_dashboard.group_neon_dashboard_director'):
            return 'director'
        if user.has_group('neon_finance.group_neon_finance_bookkeeper'):
            return 'bookkeeper'
        if user.has_group('neon_operations.group_neon_ops_lead_tech'):
            return 'lead_tech'
        if user.has_group('neon_operations.group_neon_ops_tech'):
            return 'tech'
        # default fallback for sales reps
        return 'sales'

    def _seed_default_layout(self):
        """Apply the default visible widgets for this dashboard_type."""
        self.ensure_one()
        defaults = self.env.ref(
            f'neon_dashboard.default_layout_{self.dashboard_type}',
            raise_if_not_found=False,
        )
        if not defaults:
            return
        # default_layouts.xml provides a list of widget_keys and order; we materialize them
        for line in defaults.layout_lines:
            self.env['neon.dashboard.user.layout'].create({
                'dashboard_id': self.id,
                'widget_key': line.widget_key,
                'visible': line.visible,
                'order_index': line.order_index,
                'size': line.size,
            })
```

### 5.2 `neon.dashboard.user.layout`

`models/dashboard_user_layout.py`:

```python
from odoo import models, fields, api
from odoo.exceptions import ValidationError

WIDGET_KEYS = [
    # KPI tiles
    ('kpi_cash', 'KPI: Cash on Hand'),
    ('kpi_ar_overdue', 'KPI: AR Overdue'),
    ('kpi_jobs_today', 'KPI: Jobs Today'),
    ('kpi_jobs_week', 'KPI: Jobs This Week'),
    ('kpi_pipeline', 'KPI: Pipeline Value'),
    ('kpi_leads', 'KPI: New Leads'),
    ('kpi_forecast', 'KPI: Forecast vs Target'),
    # Blocks
    ('block_jobs', 'Block: Jobs'),
    ('block_sales', 'Block: Sales Pipeline'),
    ('block_finance', 'Block: Finance'),
    ('block_alerts', 'Block: Alerts'),
    ('block_crew_equipment', 'Block: Crew & Equipment'),
    ('block_tasks', 'Block: Tasks'),
    ('block_ai_insights', 'Block: AI Insights'),
]

# Widgets that cannot be hidden (Robin's decision: §4.2 of schema sketch)
MANDATORY_WIDGETS = ['kpi_cash', 'kpi_ar_overdue', 'block_alerts']


class NeonDashboardUserLayout(models.Model):
    _name = 'neon.dashboard.user.layout'
    _description = 'Per-User Dashboard Widget Layout'
    _order = 'order_index, id'

    dashboard_id = fields.Many2one(
        'neon.dashboard', required=True, ondelete='cascade',
    )
    widget_key = fields.Selection(WIDGET_KEYS, required=True)
    visible = fields.Boolean(default=True)
    order_index = fields.Integer(default=0)
    size = fields.Selection(
        [('small', 'Small'), ('medium', 'Medium'), ('large', 'Large')],
        default='medium',
    )

    _sql_constraints = [
        ('dashboard_widget_unique',
         'unique(dashboard_id, widget_key)',
         'Each widget can only appear once per dashboard.'),
    ]

    @api.constrains('widget_key', 'visible')
    def _check_mandatory_widgets(self):
        for rec in self:
            if rec.widget_key in MANDATORY_WIDGETS and not rec.visible:
                # Per schema sketch §4.2: silently ignore attempts to hide mandatory widgets
                # Log warning so admins can audit
                rec.visible = True
                self.env['ir.logging'].create({
                    'name': 'neon_dashboard',
                    'type': 'server',
                    'dbname': self.env.cr.dbname,
                    'level': 'WARNING',
                    'message': f"Attempted to hide mandatory widget {rec.widget_key} for dashboard {rec.dashboard_id.id}; ignored.",
                    'path': 'neon.dashboard.user.layout',
                    'func': '_check_mandatory_widgets',
                    'line': '0',
                })
```

### 5.3 `res.users` extension

`models/res_users.py`:

```python
from odoo import models, fields


class ResUsersDashboard(models.Model):
    _inherit = 'res.users'

    preferred_dashboard_type = fields.Selection(
        [
            ('director', 'Director'),
            ('sales', 'Sales'),
            ('bookkeeper', 'Bookkeeper'),
            ('lead_tech', 'Lead Tech'),
            ('tech', 'Tech'),
        ],
        string='Preferred Dashboard',
        help="Overrides group-derived default landing dashboard. Leave blank for auto-detect.",
    )
```

---

## 6. Security (M1)

### 6.1 `security/neon_dashboard_security.xml`

Define one group per dashboard_type. Map existing users to appropriate groups via XML data.

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="0">
        <record id="module_category_neon_dashboard" model="ir.module.category">
            <field name="name">Neon Dashboard</field>
            <field name="sequence">25</field>
        </record>

        <!-- Director — Robin, Munashe (and any superuser by extension) -->
        <record id="group_neon_dashboard_director" model="res.groups">
            <field name="name">Dashboard / Director</field>
            <field name="category_id" ref="module_category_neon_dashboard"/>
            <field name="implied_ids" eval="[(4, ref('base.group_user'))]"/>
        </record>

        <!-- Sales — Tatenda, Lisa, Evrill -->
        <record id="group_neon_dashboard_sales" model="res.groups">
            <field name="name">Dashboard / Sales</field>
            <field name="category_id" ref="module_category_neon_dashboard"/>
            <field name="implied_ids" eval="[(4, ref('base.group_user'))]"/>
        </record>

        <!-- Bookkeeper — Kudzaiishe -->
        <record id="group_neon_dashboard_bookkeeper" model="res.groups">
            <field name="name">Dashboard / Bookkeeper</field>
            <field name="category_id" ref="module_category_neon_dashboard"/>
            <field name="implied_ids" eval="[(4, ref('base.group_user'))]"/>
        </record>

        <!-- Lead Tech — Ranganai -->
        <record id="group_neon_dashboard_lead_tech" model="res.groups">
            <field name="name">Dashboard / Lead Tech</field>
            <field name="category_id" ref="module_category_neon_dashboard"/>
            <field name="implied_ids" eval="[(4, ref('base.group_user'))]"/>
        </record>

        <!-- Tech — Crew -->
        <record id="group_neon_dashboard_tech" model="res.groups">
            <field name="name">Dashboard / Tech</field>
            <field name="category_id" ref="module_category_neon_dashboard"/>
            <field name="implied_ids" eval="[(4, ref('base.group_user'))]"/>
        </record>

        <!-- Existing users into appropriate groups -->
        <record id="base.user_admin" model="res.users">
            <field name="groups_id" eval="[(4, ref('group_neon_dashboard_director'))]"/>
        </record>
        <!-- Robin -->
        <record id="neon_partners.user_robin" model="res.users">
            <field name="groups_id" eval="[(4, ref('group_neon_dashboard_director'))]"/>
        </record>
        <!-- Munashe -->
        <record id="neon_partners.user_munashe" model="res.users">
            <field name="groups_id" eval="[(4, ref('group_neon_dashboard_director'))]"/>
        </record>
        <!-- Tatenda (sales + dev superuser) -->
        <record id="neon_partners.user_tatenda" model="res.users">
            <field name="groups_id" eval="[(4, ref('group_neon_dashboard_sales')), (4, ref('group_neon_dashboard_director'))]"/>
        </record>
        <!-- Kudzaiishe -->
        <record id="neon_partners.user_kudzaiishe" model="res.users">
            <field name="groups_id" eval="[(4, ref('group_neon_dashboard_bookkeeper'))]"/>
        </record>
        <!-- Lisa -->
        <record id="neon_partners.user_lisa" model="res.users">
            <field name="groups_id" eval="[(4, ref('group_neon_dashboard_sales'))]"/>
        </record>
        <!-- Evrill -->
        <record id="neon_partners.user_evrill" model="res.users">
            <field name="groups_id" eval="[(4, ref('group_neon_dashboard_sales'))]"/>
        </record>
        <!-- Ranganai -->
        <record id="neon_partners.user_ranganai" model="res.users">
            <field name="groups_id" eval="[(4, ref('group_neon_dashboard_lead_tech'))]"/>
        </record>
    </data>
</odoo>
```

**Note**: Verify the user XML IDs against the actual `neon_partners` module. If different, adjust accordingly. If users were created by phase migration scripts and don't have stable XML IDs, fall back to a post-install hook in `__manifest__.py`.

### 6.2 `security/ir.model.access.csv`

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_neon_dashboard_director,Dashboard / Director access,model_neon_dashboard,group_neon_dashboard_director,1,1,1,1
access_neon_dashboard_sales,Dashboard / Sales access,model_neon_dashboard,group_neon_dashboard_sales,1,1,1,1
access_neon_dashboard_bookkeeper,Dashboard / Bookkeeper access,model_neon_dashboard,group_neon_dashboard_bookkeeper,1,1,1,1
access_neon_dashboard_lead_tech,Dashboard / Lead Tech access,model_neon_dashboard,group_neon_dashboard_lead_tech,1,1,1,1
access_neon_dashboard_tech,Dashboard / Tech access,model_neon_dashboard,group_neon_dashboard_tech,1,1,1,1
access_neon_dashboard_layout_director,Layout / Director access,model_neon_dashboard_user_layout,group_neon_dashboard_director,1,1,1,1
access_neon_dashboard_layout_sales,Layout / Sales access,model_neon_dashboard_user_layout,group_neon_dashboard_sales,1,1,1,1
access_neon_dashboard_layout_bookkeeper,Layout / Bookkeeper access,model_neon_dashboard_user_layout,group_neon_dashboard_bookkeeper,1,1,1,1
access_neon_dashboard_layout_lead_tech,Layout / Lead Tech access,model_neon_dashboard_user_layout,group_neon_dashboard_lead_tech,1,1,1,1
access_neon_dashboard_layout_tech,Layout / Tech access,model_neon_dashboard_user_layout,group_neon_dashboard_tech,1,1,1,1
```

### 6.3 Record rules

Add a record rule so users only see their own dashboard records:

```xml
<record id="rule_neon_dashboard_own" model="ir.rule">
    <field name="name">Users see only their own dashboards</field>
    <field name="model_id" ref="model_neon_dashboard"/>
    <field name="domain_force">[('user_id', '=', user.id)]</field>
    <field name="groups" eval="[
        (4, ref('group_neon_dashboard_director')),
        (4, ref('group_neon_dashboard_sales')),
        (4, ref('group_neon_dashboard_bookkeeper')),
        (4, ref('group_neon_dashboard_lead_tech')),
        (4, ref('group_neon_dashboard_tech')),
    ]"/>
</record>
```

Superusers (those with both director group AND `base.group_no_one` — or use the existing `neon_*.group_neon_*_superuser` pattern from prior phases) bypass this rule. Verify the existing superuser group convention from Phase 7 and reuse it.

---

## 7. Default layouts (M1)

`data/default_layouts.xml` — seed the default visible widget list for each `dashboard_type`.

Implement this as plain XML records on a small helper model `neon.dashboard.default.layout` and `.line` (or inline in the existing controller — your call, but the schema sketch §5.2 references a discrete data file).

Minimal version (each dashboard_type gets its widget set; the seed runs on module install):

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <data noupdate="1">
        <!-- Director default: all 7 KPI tiles + all 7 blocks visible -->
        <record id="default_layout_director" model="neon.dashboard.default.layout">
            <field name="dashboard_type">director</field>
            <field name="layout_lines" eval="[
                (0, 0, {'widget_key': 'kpi_cash', 'order_index': 1}),
                (0, 0, {'widget_key': 'kpi_ar_overdue', 'order_index': 2}),
                (0, 0, {'widget_key': 'kpi_jobs_today', 'order_index': 3}),
                (0, 0, {'widget_key': 'kpi_jobs_week', 'order_index': 4}),
                (0, 0, {'widget_key': 'kpi_pipeline', 'order_index': 5}),
                (0, 0, {'widget_key': 'kpi_leads', 'order_index': 6}),
                (0, 0, {'widget_key': 'kpi_forecast', 'order_index': 7}),
                (0, 0, {'widget_key': 'block_jobs', 'order_index': 10}),
                (0, 0, {'widget_key': 'block_sales', 'order_index': 11}),
                (0, 0, {'widget_key': 'block_finance', 'order_index': 12}),
                (0, 0, {'widget_key': 'block_alerts', 'order_index': 13}),
                (0, 0, {'widget_key': 'block_crew_equipment', 'order_index': 14}),
                (0, 0, {'widget_key': 'block_tasks', 'order_index': 15}),
                (0, 0, {'widget_key': 'block_ai_insights', 'order_index': 16}),
            ]"/>
        </record>

        <!-- Sales default: 4 KPI tiles, 3 blocks -->
        <record id="default_layout_sales" model="neon.dashboard.default.layout">
            <field name="dashboard_type">sales</field>
            <field name="layout_lines" eval="[
                (0, 0, {'widget_key': 'kpi_pipeline', 'order_index': 1}),
                (0, 0, {'widget_key': 'kpi_leads', 'order_index': 2}),
                (0, 0, {'widget_key': 'kpi_forecast', 'order_index': 3}),
                (0, 0, {'widget_key': 'kpi_jobs_week', 'order_index': 4}),
                (0, 0, {'widget_key': 'block_jobs', 'order_index': 10}),
                (0, 0, {'widget_key': 'block_sales', 'order_index': 11}),
                (0, 0, {'widget_key': 'block_alerts', 'order_index': 12}),
                (0, 0, {'widget_key': 'block_tasks', 'order_index': 13}),
                (0, 0, {'widget_key': 'block_ai_insights', 'order_index': 14}),
            ]"/>
        </record>

        <!-- Bookkeeper default: cash, AR, invoices to send, VAT due -->
        <record id="default_layout_bookkeeper" model="neon.dashboard.default.layout">
            <field name="dashboard_type">bookkeeper</field>
            <field name="layout_lines" eval="[
                (0, 0, {'widget_key': 'kpi_cash', 'order_index': 1}),
                (0, 0, {'widget_key': 'kpi_ar_overdue', 'order_index': 2}),
                (0, 0, {'widget_key': 'kpi_jobs_week', 'order_index': 3}),
                (0, 0, {'widget_key': 'block_jobs', 'order_index': 10}),
                (0, 0, {'widget_key': 'block_finance', 'order_index': 11}),
                (0, 0, {'widget_key': 'block_alerts', 'order_index': 12}),
                (0, 0, {'widget_key': 'block_tasks', 'order_index': 13}),
                (0, 0, {'widget_key': 'block_ai_insights', 'order_index': 14}),
            ]"/>
        </record>

        <!-- Lead Tech default -->
        <record id="default_layout_lead_tech" model="neon.dashboard.default.layout">
            <field name="dashboard_type">lead_tech</field>
            <field name="layout_lines" eval="[
                (0, 0, {'widget_key': 'kpi_jobs_week', 'order_index': 1}),
                (0, 0, {'widget_key': 'kpi_jobs_today', 'order_index': 2}),
                (0, 0, {'widget_key': 'block_jobs', 'order_index': 10}),
                (0, 0, {'widget_key': 'block_alerts', 'order_index': 11}),
                (0, 0, {'widget_key': 'block_crew_equipment', 'order_index': 12}),
                (0, 0, {'widget_key': 'block_tasks', 'order_index': 13}),
                (0, 0, {'widget_key': 'block_ai_insights', 'order_index': 14}),
            ]"/>
        </record>

        <!-- Tech default -->
        <record id="default_layout_tech" model="neon.dashboard.default.layout">
            <field name="dashboard_type">tech</field>
            <field name="layout_lines" eval="[
                (0, 0, {'widget_key': 'kpi_jobs_today', 'order_index': 1}),
                (0, 0, {'widget_key': 'block_jobs', 'order_index': 10}),
                (0, 0, {'widget_key': 'block_alerts', 'order_index': 11}),
                (0, 0, {'widget_key': 'block_tasks', 'order_index': 12}),
            ]"/>
        </record>
    </data>
</odoo>
```

(`neon.dashboard.default.layout` and `.line` are tiny helper models — define them in `models/dashboard.py` alongside the main dashboard.)

---

## 8. Controller (M1 + M2 + M3)

`controllers/dashboard_controller.py` — exposes `/neon/dashboard/data` returning a JSON payload with KPI values + Jobs block data + layout.

```python
from odoo import http, fields
from odoo.http import request
from odoo.exceptions import AccessError
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)


class NeonDashboardController(http.Controller):

    @http.route('/neon/dashboard/data', type='json', auth='user')
    def get_dashboard_data(self, dashboard_type=None):
        """
        Returns the full dashboard payload:
        - dashboard_type (resolved)
        - layout (list of visible widgets in order)
        - kpi values (all 7 tiles, with empty-state flags)
        - jobs_block data
        """
        user = request.env.user
        dashboard_type = self._resolve_dashboard_type(user, dashboard_type)

        dashboard = request.env['neon.dashboard'].get_or_create_for_user(
            user_id=user.id, dashboard_type=dashboard_type,
        )

        return {
            'dashboard_id': dashboard.id,
            'dashboard_type': dashboard_type,
            'user_name': user.name,
            'is_superuser': self._is_superuser(user),
            'layout': self._serialize_layout(dashboard),
            'kpi': self._compute_kpi(),
            'jobs_block': self._compute_jobs_block(),
            'available_types': self._available_types_for_user(user),
        }

    def _resolve_dashboard_type(self, user, requested_type):
        """If a superuser explicitly requested a type, honor it. Otherwise auto-detect."""
        if requested_type and self._is_superuser(user):
            return requested_type
        if user.preferred_dashboard_type:
            return user.preferred_dashboard_type
        return request.env['neon.dashboard']._default_dashboard_type_for_user(user.id)

    def _is_superuser(self, user):
        """Robin, Munashe, Tatenda — has director group OR follow Phase 7 superuser convention."""
        return user.has_group('neon_dashboard.group_neon_dashboard_director')

    def _available_types_for_user(self, user):
        """For the View as... dropdown. Superusers see all types; others see only their own."""
        if self._is_superuser(user):
            return [
                {'value': 'director', 'label': 'Director'},
                {'value': 'sales', 'label': 'Sales'},
                {'value': 'bookkeeper', 'label': 'Bookkeeper'},
                {'value': 'lead_tech', 'label': 'Lead Tech'},
                {'value': 'tech', 'label': 'Tech'},
            ]
        return []

    def _serialize_layout(self, dashboard):
        return [{
            'widget_key': l.widget_key,
            'visible': l.visible,
            'order_index': l.order_index,
            'size': l.size,
        } for l in dashboard.layout_ids.sorted('order_index')]

    # ---------- KPI computation (M2) ----------
    def _compute_kpi(self):
        """All 7 KPI tile values + empty-state flags. Each method returns dict with:
           value, value_display, trend_pct, trend_dir, empty, empty_message, deeplink_action.
        """
        return {
            'kpi_cash': self._kpi_cash_on_hand(),
            'kpi_ar_overdue': self._kpi_ar_overdue(),
            'kpi_jobs_today': self._kpi_jobs_today(),
            'kpi_jobs_week': self._kpi_jobs_week(),
            'kpi_pipeline': self._kpi_pipeline(),
            'kpi_leads': self._kpi_new_leads(),
            'kpi_forecast': self._kpi_forecast(),
        }

    def _kpi_cash_on_hand(self):
        # ZiG-USD rate is M6; for M1-M3 use USD only and flag the gap in empty state.
        Account = request.env['neon.bank.account']
        usd_accounts = Account.search([('currency_id.name', '=', 'USD')])
        if not usd_accounts:
            return self._empty_kpi('No bank accounts configured yet')
        total = sum(a.current_balance for a in usd_accounts)
        return {
            'value': total,
            'value_display': self._format_money(total, 'USD'),
            'currency': 'USD',
            'trend_pct': None,  # MoM computed in M2 v2; left null for first batch
            'trend_dir': 'flat',
            'empty': False,
            'deeplink_action': 'neon_finance.action_neon_bank_account',
        }

    def _kpi_ar_overdue(self):
        today = fields.Date.today()
        Invoice = request.env['neon.invoice']
        overdue = Invoice.search([
            ('state', '=', 'posted'),
            ('payment_state', 'in', ['not_paid', 'partial']),
            ('date_due', '<', today),
        ])
        if not overdue:
            return self._empty_kpi('No overdue invoices', value_display='$0')
        total = sum(i.amount_residual for i in overdue)
        return {
            'value': total,
            'value_display': self._format_money(total, 'USD'),
            'count': len(overdue),
            'subtitle': f"{len(overdue)} invoice{'s' if len(overdue) != 1 else ''}",
            'trend_pct': None,
            'trend_dir': 'flat',
            'empty': False,
            'deeplink_action': 'neon_finance.action_neon_invoice_overdue',
        }

    def _kpi_jobs_today(self):
        today = fields.Date.today()
        Event = request.env['neon.event']
        jobs = Event.search([
            ('event_date', '=', today),
            ('state', 'not in', ['cancelled', 'draft']),
        ])
        if not jobs:
            return self._empty_kpi('No jobs scheduled today', value_display='0')
        # Subtitle: count of "prep" vs "active"
        prep = jobs.filtered(lambda j: j.state == 'prep')
        active = jobs.filtered(lambda j: j.state in ('confirmed', 'active'))
        return {
            'value': len(jobs),
            'value_display': str(len(jobs)),
            'subtitle': f"{len(prep)} prep / {len(active)} confirmed",
            'empty': False,
            'deeplink_action': 'neon_operations.action_neon_event_today',
        }

    def _kpi_jobs_week(self):
        today = fields.Date.today()
        end = today + timedelta(days=7)
        Event = request.env['neon.event']
        jobs = Event.search([
            ('event_date', '>=', today),
            ('event_date', '<=', end),
            ('state', '!=', 'cancelled'),
        ])
        if not jobs:
            return self._empty_kpi('No jobs in next 7 days', value_display='0')
        return {
            'value': len(jobs),
            'value_display': str(len(jobs)),
            'subtitle': f"Next 7 days",
            'empty': False,
            'deeplink_action': 'neon_operations.action_neon_event_week',
        }

    def _kpi_pipeline(self):
        Quote = request.env['neon.quote']
        active = Quote.search([
            ('stage_id.name', 'in', ['Qualified', 'Proposal Sent', 'Negotiation']),
        ])
        if not active:
            return self._empty_kpi('No active deals', value_display='$0')
        total = sum(q.amount_total for q in active)
        return {
            'value': total,
            'value_display': self._format_money(total, 'USD'),
            'count': len(active),
            'subtitle': f"{len(active)} active deal{'s' if len(active) != 1 else ''}",
            'empty': False,
            'deeplink_action': 'neon_quote_lifecycle.action_neon_quote_active',
        }

    def _kpi_new_leads(self):
        yesterday = fields.Datetime.now() - timedelta(days=1)
        Lead = request.env['neon.lead']
        leads = Lead.search([('create_date', '>=', yesterday)])
        if not leads:
            return self._empty_kpi('No new leads', value_display='0')
        return {
            'value': len(leads),
            'value_display': str(len(leads)),
            'subtitle': 'Since yesterday',
            'empty': False,
            'deeplink_action': 'neon_partners.action_neon_lead',
        }

    def _kpi_forecast(self):
        # No neon.dashboard.target model yet (M5). Return CTA empty state.
        return {
            'value': None,
            'value_display': 'Set a target →',
            'subtitle': 'Forecast vs Target not configured',
            'empty': True,
            'empty_message': 'Set a target →',
            'deeplink_action': None,  # M5 will wire to target settings page
            'cta_label': 'Configure target',
        }

    def _empty_kpi(self, message, value_display='$0'):
        return {
            'value': 0,
            'value_display': value_display,
            'subtitle': message,
            'empty': True,
            'empty_message': message,
            'trend_pct': None,
            'trend_dir': 'flat',
        }

    def _format_money(self, amount, currency='USD'):
        prefix = '$' if currency == 'USD' else 'ZiG '
        if abs(amount) >= 1000:
            return f"{prefix}{amount/1000:.1f}k"
        return f"{prefix}{amount:,.0f}"

    # ---------- Jobs block (M3) ----------
    def _compute_jobs_block(self):
        today = fields.Date.today()
        end = today + timedelta(days=7)
        Event = request.env['neon.event']
        jobs = Event.search([
            ('event_date', '>=', today),
            ('event_date', '<=', end),
            ('state', '!=', 'cancelled'),
        ], order='event_date asc, amount_total desc', limit=10)

        if not jobs:
            return {
                'empty': True,
                'empty_message': 'No upcoming jobs',
                'empty_cta_label': 'Create your first event →',
                'empty_cta_action': 'neon_operations.action_neon_event_new',
                'rows': [],
            }

        rows = []
        for j in jobs:
            days_out = (j.event_date - today).days
            crew_total = j.crew_required_count or 0
            crew_assigned = j.crew_assigned_count or 0
            crew_gap = crew_total - crew_assigned if crew_total > crew_assigned else 0
            rows.append({
                'id': j.id,
                'client_name': j.partner_id.name or '',
                'event_name': j.name or '',
                'event_date': j.event_date.strftime('%a') if days_out > 0 else 'Today',
                'days_label': f"{days_out} day{'s' if days_out != 1 else ''}" if days_out > 0 else '0 days',
                'state': j.state,
                'state_label': self._state_label(j.state),
                'state_color': self._state_color(j.state),
                'crew_assigned': crew_assigned,
                'crew_required': crew_total,
                'crew_gap': crew_gap,
                'venue': j.venue_id.name if j.venue_id else (j.venue_text or ''),
                'value_display': self._format_money(j.amount_total, 'USD'),
                'deeplink_action': 'neon_operations.action_neon_event',
                'deeplink_id': j.id,
            })

        return {
            'empty': False,
            'rows': rows,
        }

    def _state_label(self, state):
        # Map P2 event states to dashboard badge labels (per mockup v2)
        return {
            'prep': 'PREP',
            'confirmed': 'READY',
            'active': 'ACTIVE',
            'in_progress': 'ACTIVE',
            'draft': 'PENDING',
            'done': 'DONE',
        }.get(state, state.upper())

    def _state_color(self, state):
        return {
            'prep': 'amber',       # F5A623
            'confirmed': 'blue',   # 3A7BD5
            'active': 'green',     # 3FBF7F
            'in_progress': 'green',
            'draft': 'grey',       # A0A0B0
            'done': 'grey',
        }.get(state, 'grey')
```

**Important**: Check the actual field names in `neon.event` (Phase 2). Likely candidates that may need renaming if Claude Code finds different actual names: `crew_required_count`, `crew_assigned_count`, `venue_id`, `venue_text`, `amount_total`. Read the Phase 2 model file first and adjust the JSON keys to match.

Similarly for `neon.invoice`, `neon.bank.account`, `neon.quote`, `neon.lead` — verify field names in the actual modules and adjust.

---

## 9. View + assets (M1)

### 9.1 `views/dashboard_views.xml`

Client action that mounts the OWL dashboard:

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="action_neon_dashboard" model="ir.actions.client">
        <field name="name">Dashboard</field>
        <field name="tag">neon_dashboard</field>
    </record>

    <menuitem
        id="menu_neon_dashboard_root"
        name="Dashboard"
        parent="neon_partners.menu_neon_root"
        action="action_neon_dashboard"
        sequence="1"/>
</odoo>
```

(Adjust the parent menu reference based on existing Neon menu structure.)

### 9.2 OWL components

`static/src/js/dashboard.js`:

```javascript
/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { KpiTile } from "./kpi_tile";
import { ViewFilterChips } from "./view_filter_chips";
import { ViewAsDropdown } from "./view_as_dropdown";
import { JobsBlock } from "./jobs_block";
import { EmptyState } from "./empty_state";

export class NeonDashboard extends Component {
    static template = "neon_dashboard.Dashboard";
    static components = { KpiTile, ViewFilterChips, ViewAsDropdown, JobsBlock, EmptyState };

    setup() {
        this.rpc = useService("rpc");
        this.actionService = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            data: null,
            activeFilter: 'all',  // all / operations / sales / finance
        });

        onWillStart(async () => {
            await this.loadData();
        });
    }

    async loadData(dashboard_type = null) {
        this.state.loading = true;
        try {
            this.state.data = await this.rpc('/neon/dashboard/data', {
                dashboard_type: dashboard_type,
            });
        } catch (err) {
            this.notification.add('Failed to load dashboard', { type: 'danger' });
        } finally {
            this.state.loading = false;
        }
    }

    onViewAsChange(newType) {
        this.loadData(newType);
    }

    onFilterChange(filter) {
        if (filter !== 'all') {
            this.notification.add(`'${filter}' filter coming in Phase 8A M5/M6`, { type: 'info' });
            return;
        }
        this.state.activeFilter = filter;
    }

    onEditLayoutClick() {
        this.notification.add('Edit Layout coming in Phase 8B M5', { type: 'info' });
    }

    onKpiClick(widget_key, action) {
        if (!action) return;
        this.actionService.doAction(action);
    }

    onJobClick(eventId) {
        this.actionService.doAction({
            type: 'ir.actions.act_window',
            res_model: 'neon.event',
            res_id: eventId,
            views: [[false, 'form']],
        });
    }

    isWidgetVisible(widget_key) {
        if (!this.state.data) return false;
        const layout = this.state.data.layout.find(l => l.widget_key === widget_key);
        return layout ? layout.visible : false;
    }
}

registry.category("actions").add("neon_dashboard", NeonDashboard);
```

`static/src/xml/dashboard.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">
    <t t-name="neon_dashboard.Dashboard">
        <div class="neon-dashboard">
            <div t-if="state.loading" class="neon-dashboard__loading">
                <span>Loading dashboard…</span>
            </div>

            <div t-else="" class="neon-dashboard__inner">
                <!-- Header row -->
                <header class="neon-dashboard__header">
                    <div class="neon-dashboard__brand">
                        <h1>Neon CRM — <t t-esc="dashboardTypeLabel"/> Dashboard</h1>
                        <p class="subtitle">Operations · Sales · Finance · Alerts</p>
                    </div>
                    <div class="neon-dashboard__header-right">
                        <span class="user-line"><t t-esc="state.data.user_name"/> · <t t-esc="userRoleLabel"/></span>
                        <ViewAsDropdown
                            t-if="state.data.is_superuser"
                            currentType="state.data.dashboard_type"
                            options="state.data.available_types"
                            onChange.bind="onViewAsChange"/>
                        <button class="neon-edit-layout-btn" t-on-click="onEditLayoutClick">
                            ✎ EDIT LAYOUT
                        </button>
                    </div>
                </header>

                <!-- KPI strip (7 tiles, always visible if in layout) -->
                <section class="neon-dashboard__kpi-strip">
                    <KpiTile t-if="isWidgetVisible('kpi_cash')" widget_key="'kpi_cash'" data="state.data.kpi.kpi_cash" label="'Cash on Hand'" big="true" onClick.bind="onKpiClick"/>
                    <KpiTile t-if="isWidgetVisible('kpi_ar_overdue')" widget_key="'kpi_ar_overdue'" data="state.data.kpi.kpi_ar_overdue" label="'AR Overdue'" onClick.bind="onKpiClick"/>
                    <KpiTile t-if="isWidgetVisible('kpi_jobs_today')" widget_key="'kpi_jobs_today'" data="state.data.kpi.kpi_jobs_today" label="'Jobs Today'" onClick.bind="onKpiClick"/>
                    <KpiTile t-if="isWidgetVisible('kpi_jobs_week')" widget_key="'kpi_jobs_week'" data="state.data.kpi.kpi_jobs_week" label="'Jobs This Week'" onClick.bind="onKpiClick"/>
                    <KpiTile t-if="isWidgetVisible('kpi_pipeline')" widget_key="'kpi_pipeline'" data="state.data.kpi.kpi_pipeline" label="'Pipeline Value'" onClick.bind="onKpiClick"/>
                    <KpiTile t-if="isWidgetVisible('kpi_leads')" widget_key="'kpi_leads'" data="state.data.kpi.kpi_leads" label="'New Leads'" onClick.bind="onKpiClick"/>
                    <KpiTile t-if="isWidgetVisible('kpi_forecast')" widget_key="'kpi_forecast'" data="state.data.kpi.kpi_forecast" label="'Forecast vs Target'" onClick.bind="onKpiClick"/>
                </section>

                <!-- View filter chips -->
                <ViewFilterChips activeFilter="state.activeFilter" onChange.bind="onFilterChange"/>

                <!-- Jobs block (M3 — the only block in this batch) -->
                <section class="neon-dashboard__row-a">
                    <JobsBlock
                        t-if="isWidgetVisible('block_jobs')"
                        data="state.data.jobs_block"
                        onJobClick.bind="onJobClick"/>
                    <!-- Sales block placeholder (M5) -->
                    <div t-if="isWidgetVisible('block_sales')" class="neon-block neon-block--placeholder">
                        <h3>Sales Pipeline</h3>
                        <p class="muted">Coming in M5</p>
                    </div>
                </section>

                <!-- More blocks placeholders -->
                <section class="neon-dashboard__row-b">
                    <div t-if="isWidgetVisible('block_finance')" class="neon-block neon-block--placeholder">
                        <h3>Finance — AR &amp; Cash Detail</h3>
                        <p class="muted">Coming in M6</p>
                    </div>
                    <div t-if="isWidgetVisible('block_alerts')" class="neon-block neon-block--placeholder">
                        <h3>Alerts</h3>
                        <p class="muted">Coming in M7</p>
                    </div>
                    <div t-if="isWidgetVisible('block_crew_equipment')" class="neon-block neon-block--placeholder">
                        <h3>Crew &amp; Equipment</h3>
                        <p class="muted">Coming in M4</p>
                    </div>
                </section>
            </div>
        </div>
    </t>
</templates>
```

(Also create the smaller per-component `.js` and `.xml` files for `kpi_tile`, `view_filter_chips`, `view_as_dropdown`, `jobs_block`, `empty_state` — each follows the same OWL pattern. Match the visual design of `Neon_Dashboard_Sketch_v2.pdf` exactly.)

### 9.3 SCSS

`static/src/scss/dashboard.scss` — match the mockup palette:

```scss
$neon-purple: #5B2A8A;
$neon-purple-light: #9F7BD3;
$neon-purple-pale: #F0E7FA;
$neon-accent-green: #3FBF7F;
$neon-accent-amber: #F5A623;
$neon-accent-red: #E94F4F;
$neon-accent-blue: #3A7BD5;
$neon-text: #2D2D3F;
$neon-muted: #6B6B7E;
$neon-line: #E5E5EE;
$neon-bg: #FAFAFC;

.neon-dashboard {
    padding: 16px;
    background: $neon-bg;
    min-height: 100vh;

    &__inner { max-width: 1400px; margin: 0 auto; }

    &__header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        border-bottom: 1px solid $neon-purple-light;
        padding-bottom: 8px;
        margin-bottom: 12px;
        h1 { color: $neon-purple; font-size: 1.6em; margin: 0; font-weight: 700; }
        .subtitle { color: $neon-muted; font-size: 0.85em; margin: 2px 0 0; }
    }

    &__header-right {
        text-align: right;
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 4px;
    }

    .user-line { font-size: 0.85em; color: $neon-text; }
    .neon-edit-layout-btn {
        background: none; border: none; color: $neon-purple; font-weight: 700;
        font-size: 0.8em; cursor: pointer; padding: 2px 6px;
        &:hover { background: $neon-purple-pale; border-radius: 4px; }
    }

    &__kpi-strip {
        display: grid;
        grid-template-columns: repeat(7, 1fr);
        gap: 8px;
        margin-bottom: 12px;
    }

    /* KPI tile, blocks, etc — follow mockup v2 exactly */
    /* ... full styles to match Neon_Dashboard_Sketch_v2.pdf ... */

    /* Mobile auto-stack */
    @media (max-width: 768px) {
        &__kpi-strip { grid-template-columns: repeat(2, 1fr); }
        &__row-a, &__row-b { grid-template-columns: 1fr; }
        .neon-edit-layout-btn { display: none; }
    }
}
```

Implement the full styles to match the mockup. Use CSS Grid for the row layouts. Mobile breakpoint at 768px stacks everything to single column. Tablet breakpoint at 1024px collapses KPI strip to 2 rows of 3-4 tiles.

---

## 10. Tests

All three test files must pass before this batch is signed off.

### 10.1 `tests/test_m1_models.py`

```python
from odoo.tests.common import TransactionCase

class TestNeonDashboardModels(TransactionCase):

    def setUp(self):
        super().setUp()
        self.user = self.env.ref('base.user_admin')

    def test_create_dashboard_lazy(self):
        """get_or_create returns existing or creates new"""
        Dashboard = self.env['neon.dashboard']
        d1 = Dashboard.get_or_create_for_user(self.user.id, 'director')
        self.assertTrue(d1.id)
        d2 = Dashboard.get_or_create_for_user(self.user.id, 'director')
        self.assertEqual(d1.id, d2.id, "Should return existing, not create new")

    def test_seed_default_layout(self):
        """Director dashboard seeds with all expected widgets"""
        Dashboard = self.env['neon.dashboard']
        d = Dashboard.get_or_create_for_user(self.user.id, 'director')
        widget_keys = set(d.layout_ids.mapped('widget_key'))
        # Director should have all 7 KPI tiles + all 7 blocks
        expected = {'kpi_cash', 'kpi_ar_overdue', 'kpi_jobs_today', 'kpi_jobs_week',
                    'kpi_pipeline', 'kpi_leads', 'kpi_forecast',
                    'block_jobs', 'block_sales', 'block_finance', 'block_alerts',
                    'block_crew_equipment', 'block_tasks', 'block_ai_insights'}
        self.assertEqual(widget_keys, expected)

    def test_mandatory_widget_cannot_be_hidden(self):
        """Per schema sketch §4.2 — visible=False on mandatory widget is silently ignored"""
        Dashboard = self.env['neon.dashboard']
        d = Dashboard.get_or_create_for_user(self.user.id, 'director')
        cash_widget = d.layout_ids.filtered(lambda l: l.widget_key == 'kpi_cash')
        cash_widget.visible = False
        cash_widget.invalidate_cache()
        self.assertTrue(cash_widget.visible, "kpi_cash must remain visible")

    def test_unique_user_dashboard_type(self):
        """Cannot create two director dashboards for the same user"""
        from psycopg2 import IntegrityError
        Dashboard = self.env['neon.dashboard']
        Dashboard.create({'user_id': self.user.id, 'dashboard_type': 'director'})
        with self.assertRaises(IntegrityError):
            Dashboard.create({'user_id': self.user.id, 'dashboard_type': 'director'})
            self.env.cr.flush()

    def test_default_dashboard_type_for_user(self):
        """Admin (director group) gets director; verify routing for other users"""
        Dashboard = self.env['neon.dashboard']
        # Admin has director group implicitly via XML data
        self.assertEqual(
            Dashboard._default_dashboard_type_for_user(self.user.id),
            'director',
        )
```

### 10.2 `tests/test_m2_kpi.py`

```python
from odoo.tests.common import HttpCase
from odoo.tests import tagged

@tagged('-at_install', 'post_install')
class TestKpiTiles(HttpCase):

    def test_kpi_empty_states(self):
        """Fresh install with no business data should return empty states cleanly"""
        self.authenticate('admin', 'admin')
        result = self.url_open(
            '/web/dataset/call_kw/neon_dashboard.controller/get_dashboard_data',
            data='{"params": {}}',
            headers={'Content-Type': 'application/json'},
        ).json()
        # Actually call via JSON-RPC endpoint — use self.opener / make_jsonrpc
        # ... shape: data['result']['kpi'] has all 7 tiles
        # ... each tile has 'empty': True if no underlying data
        # ... assert no exceptions, all tiles return shape

    def test_kpi_forecast_returns_cta(self):
        """Forecast tile returns 'Set a target' CTA when no neon.dashboard.target exists"""
        # Test the JSON shape from controller
        pass  # Implement
```

(Claude Code: complete the HttpCase tests with proper JSON-RPC invocation matching the Odoo 17 pattern. The structure shown is the expected shape; fill in details.)

### 10.3 `tests/test_m3_jobs_block.py`

```python
from odoo.tests.common import TransactionCase
from datetime import date, timedelta

class TestJobsBlock(TransactionCase):

    def test_jobs_block_empty_state(self):
        """With no events, returns empty=True and a CTA"""
        from neon_dashboard.controllers.dashboard_controller import NeonDashboardController
        # Use http test client or mock request — verify the empty shape
        pass

    def test_jobs_block_orders_by_date(self):
        """Multiple events show in event_date asc, value desc"""
        Event = self.env['neon.event']
        partner = self.env['res.partner'].create({'name': 'Test Client'})
        today = date.today()
        e1 = Event.create({
            'name': 'Event A',
            'partner_id': partner.id,
            'event_date': today,
            'state': 'confirmed',
            'amount_total': 5000,
        })
        e2 = Event.create({
            'name': 'Event B',
            'partner_id': partner.id,
            'event_date': today + timedelta(days=2),
            'state': 'confirmed',
            'amount_total': 10000,
        })
        # Call controller method directly; verify e1 comes before e2 (date asc)
        # Verify status badges map correctly (READY for confirmed, etc.)
        pass
```

(Claude Code: complete these tests properly. The expected shape and ordering are what we test for; fill in the actual invocations.)

---

## 11. Acceptance criteria

This batch is **done** when all of the following pass on the local dev environment:

1. ✅ Module installs without error: `python odoo-bin -i neon_dashboard -d neon_dev --stop-after-init`
2. ✅ All 3 test files pass: `python odoo-bin --test-enable -i neon_dashboard -d neon_test --stop-after-init`
3. ✅ Logged in as `admin`, navigate to Dashboard menu → see the framework with KPI strip + view filter chips + Edit Layout button + Jobs block placeholder area
4. ✅ All 7 KPI tiles render, each showing either a real value (if data exists) or empty state (if not)
5. ✅ Forecast tile shows "Set a target →" CTA
6. ✅ Jobs block shows "No upcoming jobs. Create your first event →" with link
7. ✅ Logged in as Robin (director) — same dashboard
8. ✅ Logged in as Robin, click "View as..." dropdown → 5 options visible → select "Sales" → dashboard reloads with Sales-default layout (fewer KPI tiles, different blocks visible)
9. ✅ Logged in as Lisa (sales rep, non-superuser) — lands on Sales dashboard, NO "View as..." dropdown visible
10. ✅ Click any of the KPI tiles with deeplink_action → opens correct list/form view
11. ✅ Click a Jobs row (when data exists) → opens event form
12. ✅ Click "Operations" / "Sales" / "Finance" filter chips → toast notification: "Coming in Phase 8A M5/M6"
13. ✅ Click "Edit Layout" → toast: "Edit Layout coming in Phase 8B M5"
14. ✅ Mobile viewport (≤ 768px) — KPI strip stacks to 2 columns, blocks stack to 1 column, Edit Layout button hidden
15. ✅ No JS console errors. No Python tracebacks in the log on dashboard load.

---

## 12. Hetzner deploy (after acceptance)

Once acceptance criteria pass locally, push to `phase-8a-m1-m3` branch and deploy to staging:

```bash
git checkout -b phase-8a-m1-m3
git add addons/neon_dashboard
git commit -m "Phase 8A M1-M3: dashboard framework + KPI strip + Jobs block"
git push origin phase-8a-m1-m3

# On Hetzner staging server:
cd /opt/neon-odoo
git fetch origin
git checkout phase-8a-m1-m3
sudo systemctl restart odoo
# Upgrade module via UI or:
sudo -u odoo /opt/odoo/odoo-bin -d neon_staging -u neon_dashboard --stop-after-init
```

Then smoke-test on staging with all 5 user accounts before merging to main.

---

## 13. Notes for Claude Code

- **Field name verification**: Several models from Phase 2-7 have fields I'm guessing at (e.g., `neon.event.crew_required_count`, `neon.event.venue_id`). Read the actual model files first and adjust the JSON keys / controller queries to match. If a guessed field doesn't exist, propose the closest equivalent and mention it in the commit message.
- **Existing patterns**: Reuse OWL component patterns, asset bundle conventions, and SCSS conventions from prior phases. Don't invent new patterns.
- **Superuser group**: Phase 7 may have defined a `group_neon_superuser` or similar. If it exists, use it for the `_is_superuser` check instead of just `group_neon_dashboard_director`.
- **User XML IDs**: The `security/neon_dashboard_security.xml` references user XML IDs like `neon_partners.user_robin`. If these don't exist, look up the actual IDs created in phase migrations. If users were created without stable IDs, replace the XML assignments with a post-install Python hook that resolves users by email and adds them to groups.
- **`mail` dependency**: Required for `ir.logging` and standard Odoo activity stream. Already in the depends list.
- **Browser support**: Chrome/Edge/Safari latest. Don't add IE polyfills.
- **Commit style**: One commit per milestone (M1, M2, M3) with descriptive messages.

---

## 14. Reference files in this conversation

- `Neon_Dashboard_Sketch_v2.pdf` — the approved visual design (build to this exactly)
- `Phase8_Schema_Sketch.docx` — the full schema doc this batch implements §3.1–§3.2 + §4.1 + §4.3 of
- `Robin_Dashboard_Questionnaire_Completed.docx` — the user research that shaped all design decisions

---

## End of M1-M3 prompt
