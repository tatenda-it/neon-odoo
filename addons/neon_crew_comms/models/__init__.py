# -*- coding: utf-8 -*-
from . import commercial_job_crew
from . import commercial_job
from . import whatsapp_message
from . import neon_readiness_digest
# WA-6 -- crew + OD equipment face. Imported AFTER whatsapp_message so the
# single handle_inbound override (in whatsapp_message) and the WA-6 method
# bank coexist on neon.whatsapp.message.
from . import wa_equip_session
from . import whatsapp_message_wa6
from . import commercial_event_job_wa6
# WA-7 -- crew selection (mapped OD/superuser). Method bank on
# neon.whatsapp.message; intercept hook wired in whatsapp_message.
from . import whatsapp_message_wa7
# WA-8 -- Face 1 availability check (read-only). Method bank on
# neon.whatsapp.message; intercept hook wired in whatsapp_message BETWEEN
# the WA-7 and WA-6 intercepts.
from . import whatsapp_message_wa8
# WA-10 -- post-event feedback loop. Method bank on neon.whatsapp.message;
# intercept hook wired in whatsapp_message AFTER WA-8, before WA-6. Extends
# the P3.M7 commercial.event.feedback model (neon_jobs) with staff voices.
from . import whatsapp_message_wa10
# WA-12 -- quote-by-WhatsApp (first money-adjacent face). Extends
# neon.whatsapp.message; intercept hook wired in whatsapp_message AFTER WA-10,
# before WA-6. Provisioning + lifecycle live in neon_finance; this is the
# parse / entitlement / FSM / approval-dispatch / Price: orchestration.
from . import whatsapp_message_wa12
# WA-13 -- quote/invoice retrieval + invoice-from-quote. Extends
# neon.whatsapp.message; intercept hook wired in whatsapp_message AFTER WA-12,
# before WA-6. A WhatsApp face on the EXISTING P6.M7 invoice machinery (no new
# finance engine); reuses the WA-12 rails.
from . import whatsapp_message_wa13
# Resolver v2 -- team-slang alias store (matcher normalise step).
from . import neon_equipment_alias
# QUOTE-UX-1 -- routing unification: _inherit neon.finance.quote to fire the
# WhatsApp approval ping from the SHARED action_submit_for_approval, so both
# the Odoo form button and the WA submit ping the approver exactly once. The
# ping itself lives on neon.whatsapp.message (whatsapp_message_wa12, above).
from . import neon_finance_quote_wa
