{
    'name': 'Neon Channels',
    # 17.0.1.2.0 = WhatsApp (Meta Cloud API) + Twilio transport + bot.user.
    # 17.0.1.3.0 = B11/WA-0 rails: WhatsApp Copilot (resolution + scope
    # intersection reusing neon_ai_core), single-call agent (Gemini
    # default), two-phase guardrail via cta_url confirm-in-Odoo, no money
    # tools, X-Hub-Signature-256 verification, verify-token-from-config,
    # Twilio identity converged on neon.bot.user (authorised_numbers
    # deprecated, data retained). DEPENDS on neon_ai_core now.
    # 17.0.1.4.0 = B11/WA-1: stateful WhatsApp Copilot (conversation
    # memory, last 10 msgs / 30 min per sender, current inbound excluded)
    # + single-source phone normalization (phone_utils.to_e164) applied at
    # the handle_inbound boundary -> canonical E.164 stored; resolve() +
    # history match + lead-intake all canonical, raw `from` kept for the
    # outbound SEND. Method-only (no schema/data). Interactive renderer
    # (buttons/list/cards) remains DEFERRED.
    'version': '17.0.1.4.0',
    'summary': 'WhatsApp + Twilio integration + WA-0 role-aware WhatsApp '
               'Copilot rails (on neon_ai_core)',
    'author': 'Tatenda Ngairongwe',
    'website': 'https://neonhiring.com',
    'category': 'CRM',
    # neon_ai_core: shared AI engine (tool registry, chat adapters incl.
    # Gemini, two-phase write guardrail, role resolver). It brings
    # neon_core (tier groups) transitively. No neon_jobs dep -- the
    # business tools register into the shared registry globally; the
    # confirm act_window is gated by neon_core tier groups only.
    'depends': ['base', 'crm', 'mail', 'utm', 'neon_ai_core'],
    'data': [
        'security/ir.model.access.csv',
        # WA-0 data: provider row + WA provider selection. Load before
        # views (the confirm act_window references neon_core groups via
        # the neon_ai_core->neon_core dependency).
        'data/gemini_provider_seed.xml',
        'data/wa_config_params.xml',
        'views/whatsapp_config_views.xml',
        'views/twilio_config_views.xml',
        'views/bot_user_views.xml',
        'views/login_template.xml',
        # WA-0 confirm-in-Odoo deep-link target (form + act_window).
        'views/whatsapp_writelog_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
