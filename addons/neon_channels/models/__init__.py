from . import whatsapp_config
from . import whatsapp_message
from . import twilio_config
from . import bot_user
from . import res_partner
# WA-5 -- client intake lane (session state + the lane/handoff/assignment
# loop on neon.whatsapp.message). Loaded AFTER whatsapp_message so the
# _inherit resolves.
from . import wa_client_session
from . import wa_client_lane
