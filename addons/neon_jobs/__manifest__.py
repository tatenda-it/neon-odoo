# -*- coding: utf-8 -*-
{
    "name": "Neon Jobs",
    # 17.0.4.1.0 = P9.M9.1 Venue Maps Step 1 (base_geolocalize + embedded
    # map on event-job form). Minor bump = new layer per CLAUDE.md.
    # (Prompt said "17.0.2.x"; actual live version was 17.0.4.0.15.)
    # 17.0.4.2.0 = P9.M9.1.1 Leaflet drop-pin (first vendored library).
    # 17.0.4.3.0 = P9.M9.2 NeonVenueMapView refactor (render logic
    # lifted out of NeonVenueMap form widget so neon_dashboard can
    # mount the same view inside a Dialog).
    # 17.0.4.4.0 = P9.M9.3 Venues · Map multi-pin client action
    # (NeonVenueMultiPinMap; forked from M9.1.1 per D6, Leaflet
    # bootstrap duplicated by ~30 LOC; consolidation deferred).
    # 17.0.4.5.0 = P-B1 Data-model completion (Conflict-Engine
    # foundation). commercial.event.job gets 4 venue-side
    # load-in/out Datetime fields + a stored compute
    # (occupation_start / occupation_end) widened per D2 to
    # include dispatch_datetime + return_eta_datetime. Equipment
    # gets condition_status + last_checked_at on the unit
    # (write-on-attest hook), parent_id + low_stock_threshold on
    # the category. B2's overlap engine reads occupation_start/end
    # and category.low_stock_threshold as its inputs.
    # 17.0.5.0.0 = P-B2 Conflict Detection Engine. NEW central
    # pivot models neon.equipment.conflict (header) +
    # neon.equipment.conflict.line (detail) + the rules-based
    # engine that flags products whose aggregated demand across
    # overlapping events exceeds the available pool. Per
    # CLAUDE.md, a new central pivot model triggers a MAJOR bump.
    # Reuses the existing 'equipment_conflict' AC trigger; adds a
    # new 'load_window_missing' nudge trigger; adds a daily 06:00
    # backstop cron.
    # 17.0.6.0.0 = P-B3 AI Deployment Plan Generation. NEW
    # central pivot model neon.deployment.plan + the fact-gather /
    # Claude-via-B13 / strict-validator orchestrator. Major bump
    # per CLAUDE.md (new pivot model). Adds neon_doc_gen as a
    # depends. PDF render deferred (D10 trim); on-screen HTML
    # render only this milestone.
    # 17.0.6.1.0 = P-B14 Equipment Inventory CSV loader. Standalone
    # script (scripts/load_inventory.py) + @api.model wrapper on
    # neon.equipment.unit. asset_tag-only idempotency key
    # (gate-1 D3 confirmed). Patch bump -- no schema change, no
    # new pivot model; pure additive feature.
    # 17.0.7.0.0 = P-B4 Sub-hire request drafting + PO draft. NEW
    # models neon.subhire.request + neon.subhire.request.line.
    # Reuses B3's DeploymentPlanFactGatherer (no conflict
    # recomputation). Adds 'purchase' as a hard depends so
    # purchase.order is available -- prod will auto-install
    # purchase on next -u. Minor bump (new layer on top of B3 +
    # B13; not a new central pivot model in the B2/B3 sense).
    # 17.0.8.0.0 = P-B5 Post-event reconciliation. NEW model
    # neon.event.reconciliation. Reuses B3's fact-gatherer +
    # snapshots the active B3 plan + B4 sub-hire requests +
    # equipment condition deltas + planned-vs-actual cost
    # variance (READ-ONLY on finance models via sudo()). Lazy-
    # imports the B13 adapter (cycle pattern). NO writes to any
    # financial model; condition_status never auto-flipped. Minor
    # bump (new backward-view layer on top of B3/B4).
    # 17.0.8.1.0 = P-B14c quantity_on_hand field + B2 availability
    # branch (D1 follow-up). Adds Integer quantity_on_hand to
    # product.template (one number per product, semantically
    # meaningful only for tracking_mode in ('quantity','batch'));
    # B2._available_for_product() now branches on tracking_mode --
    # serial path UNCHANGED, quantity/batch reads
    # product.quantity_on_hand. Standalone back-fill script
    # scripts/backfill_quantity_on_hand.py parses 'legacy_qty=N'
    # from unit notes (idempotent; force=False default prevents
    # clobbering manual edits). Patch bump -- additive field +
    # availability branch; no new pivot model.
    # 17.0.8.2.0 = P-B14d Workshop dashboard adds an "In Maintenance"
    # tile counting neon.equipment.unit where state='maintenance'.
    # Distinct from the existing "Repair Orders" tile (which counts
    # neon.equipment.repair.order workflow records). Inventory-
    # snapshot row, attention urgency, click-through to a unit list
    # filtered to state='maintenance'. Patch bump -- additive
    # tile/compute/action; no model changes, no schema risk.
    # 17.0.8.2.1 = Transfer-accept window bugfix. _accept_atomic
    # defaulted both reserve_from AND reserve_to to fields.Datetime.now()
    # when the destination event_job had no event_date/schedule -> two
    # equal (second-truncated) timestamps -> CHECK (reserve_from <
    # reserve_to) violation -> whole accept rolled back. Now anchors
    # reserve_from=now() and reserve_to=rf+1h when the window is empty.
    # Surfaced by the 2026-06-09 equipment-flow prod proof. Method-only,
    # no schema change. Regression test: p5m6 T333. [tag:odoo-datetime-
    # now-equal-strict-check]
    # 17.0.8.3.0 = P5.M11 quantity-aware reservation engine. The
    # reserve->allocate->checkout->checkin path (M4-M7) now honours
    # quantity_on_hand for tracking_mode='quantity'/'batch' (unit-less
    # COUNT reservations) instead of only counting unit rows; serial
    # per-unit binding is UNCHANGED. New: reservation.quantity + product/
    # category computed-stored (unit_id.* else line product); movement
    # unit_id optional + movement.quantity + product_template_id;
    # line.action_allocate (unified) + _available_qty_for_window; quantity
    # checkout/check-in (damaged count -> stock_adjust + qoh decrement,
    # actor-audited). Migration 17.0.8.3.0 recomputes product_template_id,
    # collapses the pre-M11 N-soft_hold quantity pattern to one COUNT row,
    # cancels true orphans (idempotent; dry-run reportable).
    "version": "17.0.8.3.0",
    "summary": "Phase 2 — Commercial Job Record + Calendar / Capacity",
    "description": """
Neon Events Elements — Phase 2 — P2.M1 Schema

The Commercial Job is the central operational record connecting CRM, Finance,
Calendar, Operations, Workshop, and Training. This module defines the schema:

* commercial_job_master — Optional parent for multi-event corporate contracts
  (e.g. C Suite, Kuyana, Boxing, Lusitania).
* commercial_job — The central record. Two-state lifecycle (pending → active),
  three parallel status tracks (commercial / finance / operational).
* commercial_job_crew — Crew assignment with confirm/decline workflow.
* venue.room — Room granularity within venues for calendar conflict detection.

Extensions:
* res.partner — is_venue flag and room_ids.
* crm.lead — commercial_job_ids reverse pointer.
* sale.order — commercial_job_ids reverse pointer.

Status: P2.M1 (schema + base form views). State machines, CRM linkage,
capacity gate, calendar UI, and capacity warnings come in P2.M2-M9.
    """,
    "author": "Neon Events Elements Pvt Ltd",
    "website": "https://neonhiring.com",
    "category": "Operations",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
        "sale",
        "crm",
        "contacts",
        "account",
        "product",
        # P9.M9.1 -- partner_latitude/partner_longitude + geo_localize()
        # for venue mapping. Registers the geo fields the event-job map
        # widget reads via the venue_id related chain.
        "base_geolocalize",
        # P-B4 -- needed for purchase.order + purchase.order.line.
        # `-u neon_jobs` will auto-install `purchase` on prod
        # (standard Odoo Community, well-tested). Gate-1 D9
        # consciously accepts this. See SubhirePoDraftBuilder for
        # the integration shape.
        "purchase",
    ],
    # P-B3 NOTE: neon_doc_gen is NOT a hard depends here because
    # neon_core -> neon_jobs (group cascade) + neon_doc_gen ->
    # neon_core would create a cycle. The adapter is imported
    # LAZILY inside DeploymentPlanGenerator._call_claude with an
    # ImportError -> UserError surface so the user sees a clear
    # "install neon_doc_gen" message rather than a load failure.
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "data/ir_sequence_data.xml",
        "data/res_partner_data.xml",
        "data/crm_stage_data.xml",
        "data/ir_cron_data.xml",
        "data/action_centre_cron_data.xml",
        # cross_module_menu_security patches menus from EXTERNAL
        # modules (sale, crm, account, base, utm, spreadsheet_dashboard)
        # which have already loaded — those records exist in the DB by
        # the time we get here, so the patch updates groups_id cleanly
        # on both -i and -u.
        "data/cross_module_menu_security.xml",
        "data/checklist_templates_data.xml",
        "data/action_centre_sequence_data.xml",
        "data/action_centre_trigger_config_data.xml",
        "data/neon_equipment_category_data.xml",
        "views/venue_room_views.xml",
        "views/res_partner_views.xml",
        "views/commercial_job_views.xml",
        "views/commercial_job_for_crew_views.xml",
        "views/commercial_event_job_views.xml",
        "views/commercial_checklist_template_views.xml",
        "views/commercial_event_job_checklist_views.xml",
        "views/commercial_scope_change_views.xml",
        "views/commercial_job_master_views.xml",
        "views/commercial_job_crew_views.xml",
        "views/commercial_job_calendar_view.xml",
        "views/commercial_job_loss_wizard_views.xml",
        "views/commercial_job_gate_override_wizard_views.xml",
        "views/commercial_job_soft_hold_extend_wizard_views.xml",
        "views/commercial_job_crew_decline_wizard_views.xml",
        "views/commercial_event_job_readiness_override_wizard_views.xml",
        "views/commercial_event_job_gear_reconciled_override_wizard_views.xml",
        "views/commercial_event_job_finance_handoff_override_wizard_views.xml",
        "views/commercial_event_feedback_views.xml",
        "views/commercial_event_job_closeout_queue_views.xml",
        "views/commercial_job_dashboard_views.xml",
        "views/action_centre_trigger_config_views.xml",
        "views/action_centre_item_history_views.xml",
        "views/action_centre_item_views.xml",
        "views/action_centre_item_cancel_wizard_views.xml",
        "views/neon_equipment_unit_views.xml",
        "views/neon_equipment_category_views.xml",
        "views/product_template_extension_views.xml",
        "views/neon_equipment_recommission_wizard_views.xml",
        "views/neon_equipment_reservation_views.xml",
        "views/commercial_event_job_equipment_line_views.xml",
        "views/neon_equipment_movement_views.xml",
        "views/neon_equipment_allocate_wizard_views.xml",
        "views/neon_equipment_transfer_wizard_views.xml",
        "views/neon_equipment_checkin_wizard_views.xml",
        "views/neon_equipment_stock_take_views.xml",
        "views/neon_equipment_stock_take_wizard_views.xml",
        "views/neon_equipment_repair_order_views.xml",
        "views/neon_equipment_incident_views.xml",
        "views/crm_lead_views.xml",
        "views/sale_order_views.xml",
        # menu.xml defines our own menus (with required `name` field).
        # operations_submenu_security.xml patches groups_id on those
        # same menus, so it MUST load AFTER menu.xml — otherwise the
        # patch records create rows with NULL name and Odoo aborts the
        # install transaction. This bit P2.M9 Hetzner deploy because
        # local dev DB always had neon_jobs installed (so -u worked) —
        # the -i codepath was unexercised until production.
        "views/menu.xml",
        "data/operations_submenu_security.xml",
        # P5.M10 — Workshop Dashboard. Loads after menu.xml so the
        # menuitem can resolve menu_workshop_root as its parent.
        "views/neon_equipment_dashboard_views.xml",
        # P-B2 — Conflict Detection Engine views + menu. Loads after
        # the dashboard so menu_workshop_overview resolves.
        "views/neon_equipment_conflict_views.xml",
        "data/ir_cron_conflict_backstop.xml",
        # P-B3 -- Deployment Plan model + views + Lisa-tunable
        # call-time policy config. Loads after the dashboard so
        # the Operations submenu parent resolves.
        "data/neon_deployment_plan_config_seed.xml",
        "views/neon_deployment_plan_call_time_config_views.xml",
        "views/neon_deployment_plan_views.xml",
        # P-B4 -- Sub-hire request model + views + menu. Loads
        # after the Operations submenu (parent) is registered.
        "views/neon_subhire_request_views.xml",
        # P-B5 -- Post-event reconciliation model + views + menu.
        # Loads after the B3/B4 views so any future cross-refs
        # resolve.
        "views/neon_event_reconciliation_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            # P5.M10 — Workshop Dashboard OWL client action.
            "neon_jobs/static/src/js/workshop_dashboard/workshop_dashboard.js",
            "neon_jobs/static/src/js/workshop_dashboard/workshop_dashboard.xml",
            "neon_jobs/static/src/js/workshop_dashboard/workshop_dashboard.scss",
            # P9.M9.1 -- venue map embed widget (view_widget on the
            # event-job form's Venue page).
            # P9.M9.2 -- venue_map_view.js carries the presentational
            # OWL component reused by both the form widget and the
            # dashboard dialog; loaded first so venue_map.js can
            # import it.
            "neon_jobs/static/src/js/venue_map/venue_map_view.js",
            "neon_jobs/static/src/js/venue_map/venue_map.js",
            "neon_jobs/static/src/js/venue_map/venue_map.xml",
            "neon_jobs/static/src/js/venue_map/venue_map.scss",
            # P9.M9.1.1 -- vendored Leaflet (first static/lib/ precedent).
            # leaflet.js MUST load before venue_pin_picker.js (which
            # uses the global L); css order is cosmetic.
            "neon_jobs/static/lib/leaflet/leaflet.css",
            "neon_jobs/static/lib/leaflet/leaflet.js",
            # P9.M9.1.1 -- interactive drop-pin widget (venue form).
            "neon_jobs/static/src/js/venue_pin/venue_pin.js",
            "neon_jobs/static/src/js/venue_pin/venue_pin.xml",
            "neon_jobs/static/src/js/venue_pin/venue_pin.scss",
            # P9.M9.3 -- Venues · Map multi-pin client action. Loads
            # AFTER venue_pin.js so the global L.Icon.Default.imagePath
            # set there is in effect by the time we mount; the multi-
            # map widget also sets it defensively in _initMap.
            "neon_jobs/static/src/js/venue_multi_map/venue_multi_map.js",
            "neon_jobs/static/src/js/venue_multi_map/venue_multi_map.xml",
            "neon_jobs/static/src/js/venue_multi_map/venue_multi_map.scss",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
    "post_init_hook": "_post_init_hook",
}
