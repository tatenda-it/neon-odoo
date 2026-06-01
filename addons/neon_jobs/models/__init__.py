# -*- coding: utf-8 -*-
# Action Centre abstract mixin must load before the source models
# that inherit it (commercial.job, commercial.event.job). The other
# Action Centre models (tag, trigger_config, item, history) carry
# no inheritance edges into the Phase 2/3 source models, so they
# can stay grouped at the bottom for readability.
from . import action_centre_mixin
from . import venue_room
from . import res_partner
from . import commercial_job_master
from . import commercial_job
from . import commercial_job_gate
from . import commercial_job_crew
from . import commercial_event_job
from . import commercial_checklist_template
from . import commercial_event_job_checklist
from . import commercial_scope_change
from . import commercial_event_feedback
from . import commercial_job_dashboard
from . import crm_stage
from . import crm_lead
from . import sale_order
from . import action_centre_item_tag
from . import action_centre_trigger_config
from . import action_centre_item
from . import action_centre_item_history
# P5.M1 — Workshop equipment register foundation
from . import neon_equipment_category
from . import product_template_extension
from . import neon_equipment_unit
# P5.M4 — Equipment reservation (time-window holds on units)
from . import neon_equipment_reservation
# P5.M5 — Equipment lines + movement audit log
from . import commercial_event_job_equipment_line
from . import neon_equipment_movement
# P5.M8 — Weekly stock take + per-unit attestation
from . import neon_equipment_stock_take
from . import neon_equipment_stock_take_line
# P5.M9 — Repair + incident workflows
from . import neon_equipment_repair_order
from . import neon_equipment_incident
# P5.M10 — Workshop Dashboard (virtual model + OWL client action)
from . import neon_equipment_dashboard
# P-B2 — Conflict Detection Engine (header + line + engine service)
from . import neon_equipment_conflict
# P-B3 — AI Deployment Plan (model + helpers; B13 adapter wired
# via neon_doc_gen depends).
from . import deployment_plan_call_time_config
from . import deployment_plan_renderer
from . import deployment_plan_fact_gatherer
from . import deployment_plan_validator
from . import deployment_plan_generator
from . import neon_deployment_plan
# P-B4 — Sub-hire drafting + PO draft (reuses B3's fact-gather;
# lazy-imports B13's adapter for the draft generation).
from . import subhire_request_renderer
from . import subhire_request_fact_gatherer
from . import subhire_request_validator
from . import subhire_request_generator
from . import subhire_po_draft_builder
from . import neon_subhire_request
from . import neon_subhire_request_line
# P-B5 — Post-event reconciliation (reuses B3's fact-gather; reads
# B3 plan + B4 sub-hire; lazy-imports B13 adapter; READ-ONLY on
# finance models via sudo()).
from . import event_reconciliation_renderer
from . import event_reconciliation_fact_gatherer
from . import event_reconciliation_validator
from . import event_reconciliation_generator
from . import neon_event_reconciliation
