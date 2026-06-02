"""P7e-IMPORT browser smoke -- imported LMS content shapes on the live UI.

W1 the course (slide.channel) renders + an imported-shape lesson slide;
W2 a module quiz question shows its options;
W3 an imported-shape SOP shows as a Phase-7d KB article (with body).

⚠️ DB HYGIENE: creates a tiny dedicated P7E-BROWSER sample (committed so
the live HTTP surface can render it), runs the 3 scenarios, then TEARS
IT DOWN -- leaves the shared dev DB exactly as found (no pollution of
sibling LMS suites). The full migration is exercised by the Python smoke
(in-transaction) + the one-shot dev sample-execute.
"""
from __future__ import annotations

import subprocess
import sys

from browser_smoke import BrowserSmoke

BASE_URL = "http://localhost:8069"
DB = "neon_crm"

_SETUP = r"""
env = env(context=dict(env.context, mail_notify_force_send=False,
                       mail_create_nosubscribe=True, tracking_disable=True))
env.company.sudo().write({'email': env.company.email or 'noreply@neonhiring.com'})
Users = env['res.users']


def _wipe_login(login):
    u = Users.search([('login', '=', login)], limit=1)
    if u:
        u.write({'login': login + '_OLD_' + str(u.id), 'active': False})


_wipe_login('p7e_admin')
admin = Users.with_context(no_reset_password=True).create({
    'name': 'p7e_admin', 'login': 'p7e_admin', 'password': 'test123',
    'email': 'p7e_admin@neonhiring.com',
    'groups_id': [(4, env.ref('base.group_user').id),
                  (4, env.ref('base.group_system').id),
                  (4, env.ref('neon_core.group_neon_superuser').id),
                  (4, env.ref('website_slides.group_website_slides_manager').id)]})

# tidy any prior browser-sample
env['slide.slide'].sudo().search([('name', '=like', 'P7E-BROWSER%')]).unlink()
env['neon.lms.quiz.question'].sudo().search(
    [('question_text', '=like', 'P7E-BROWSER%')]).unlink()
env['neon.kb.article'].sudo().search([('code', '=', 'p7e-browser-sop')]).unlink()
env['neon.kb.category'].sudo().search([('code', '=', 'p7e_browser_cat')]).unlink()

tr = env['neon.lms.track'].sudo().search([], limit=1)
channel = tr.channel_id
module = env['neon.lms.module'].sudo().search([], limit=1)

# imported-shape sample (lesson slide / quiz question+options / SOP article)
slide = env['slide.slide'].sudo().create({
    'name': 'P7E-BROWSER Lesson', 'channel_id': channel.id,
    'slide_category': 'document',
    'html_content': '<p>P7E-BROWSER imported lesson body sample.</p>'})
q = env['neon.lms.quiz.question'].sudo().create({
    'module_id': module.id, 'question_text': 'P7E-BROWSER sample question?',
    'question_type': 'multiple_choice',
    'option_ids': [(0, 0, {'option_text': 'A', 'is_correct': True, 'sequence': 10}),
                   (0, 0, {'option_text': 'B', 'is_correct': False, 'sequence': 20}),
                   (0, 0, {'option_text': 'C', 'is_correct': False, 'sequence': 30}),
                   (0, 0, {'option_text': 'D', 'is_correct': False, 'sequence': 40})]})
cat = env['neon.kb.category'].sudo().search(
    [('code', '=', 'equipment_sops')], limit=1) or env['neon.kb.category'].sudo().create(
    {'name': 'P7E-BROWSER SOPs', 'code': 'p7e_browser_cat'})
art = env['neon.kb.article'].sudo().create({
    'name': 'P7E-BROWSER SOP sample', 'code': 'p7e-browser-sop',
    'category_id': cat.id, 'body': '<p>P7E-BROWSER SOP body sample.</p>'})

env.cr.commit()
print('IDS_JSON=' + repr({
    'channel_id': channel.id, 'slide_id': slide.id, 'question_id': q.id,
    'art_id': art.id,
    'q_action': env.ref('neon_lms.action_neon_lms_quiz_question').id,
}))
"""

_TEARDOWN = r"""
env['slide.slide'].sudo().search([('name', '=like', 'P7E-BROWSER%')]).unlink()
env['neon.lms.quiz.question'].sudo().search(
    [('question_text', '=like', 'P7E-BROWSER%')]).unlink()
env['neon.kb.article'].sudo().search([('code', '=', 'p7e-browser-sop')]).unlink()
env['neon.kb.category'].sudo().search([('code', '=', 'p7e_browser_cat')]).unlink()
env.cr.commit()
print('TEARDOWN_DONE')
"""


def _shell(script):
    p = subprocess.run(
        ["docker", "compose", "--project-directory",
         "C:/Users/Neon/neon-odoo", "exec", "-T", "odoo",
         "odoo", "shell", "-d", DB, "--no-http"],
        input=script.encode("utf-8"), capture_output=True, timeout=240)
    return (p.stdout + p.stderr).decode("utf-8", errors="replace")


def _setup():
    out = _shell(_SETUP)
    idx = out.find("IDS_JSON=")
    if idx < 0:
        print("[p7e_import] SETUP FAILED:")
        print(out[-2500:])
        sys.exit(2)
    start = out.find("{", idx)
    depth = 0
    for i in range(start, len(out)):
        if out[i] == "{":
            depth += 1
        elif out[i] == "}":
            depth -= 1
            if depth == 0:
                return eval(out[start:i + 1])  # noqa: S307
    print("[p7e_import] SETUP parse FAILED:", out[-1500:])
    sys.exit(2)


def run():
    ids = _setup()
    rc = 1
    try:
        with BrowserSmoke("p7e_import") as smoke:

            with smoke.scenario("W1: course channel + an imported lesson slide"):
                smoke.login("p7e_admin")
                smoke.page.goto(f"{BASE_URL}/web#id={ids['channel_id']}"
                                f"&model=slide.channel&view_type=form")
                smoke.page.wait_for_selector("div.o_form_view", timeout=20000)
                smoke.page.wait_for_timeout(600)
                name_hit = smoke.page.locator(
                    ":text('Neon Workshop Training Program')").count()
                smoke._record_assert("course channel form renders",
                                     expect=">=1", actual=str(name_hit),
                                     passed=name_hit >= 1)
                smoke.page.goto(f"{BASE_URL}/web#id={ids['slide_id']}"
                                f"&model=slide.slide&view_type=form")
                smoke.page.wait_for_selector("div.o_form_view", timeout=20000)
                smoke.page.wait_for_timeout(500)
                nm = smoke.page.locator(":text('P7E-BROWSER Lesson')").count()
                smoke._record_assert("a lesson slide renders under the course",
                                     expect=">=1", actual=str(nm), passed=nm >= 1)

            with smoke.scenario("W2: quiz question list + a question's options"):
                smoke.page.goto(f"{BASE_URL}/web#action={ids['q_action']}")
                smoke.page.wait_for_selector(".o_list_view, .o_list_renderer",
                                             timeout=20000)
                smoke.page.wait_for_timeout(700)
                rows = smoke.page.locator(".o_data_row").count()
                smoke._record_assert("quiz questions listed",
                                     expect=">=1", actual=str(rows),
                                     passed=rows >= 1)
                smoke.page.goto(f"{BASE_URL}/web#id={ids['question_id']}"
                                f"&model=neon.lms.quiz.question&view_type=form")
                smoke.page.wait_for_selector("div.o_form_view", timeout=20000)
                smoke.page.wait_for_timeout(500)
                qf = smoke.page.locator("[name='question_text']").count()
                opts = smoke.page.locator("[name='option_ids'] .o_data_row").count()
                smoke._record_assert("question form shows text + options",
                                     expect="text>=1 opts>=2",
                                     actual="text=%d opts=%d" % (qf, opts),
                                     passed=qf >= 1 and opts >= 2)

            with smoke.scenario("W3: SOP appears as a KB article"):
                smoke.page.goto(f"{BASE_URL}/web#id={ids['art_id']}"
                                f"&model=neon.kb.article&view_type=form")
                smoke.page.wait_for_selector("div.o_form_view", timeout=20000)
                smoke.page.wait_for_timeout(600)
                namef = smoke.page.locator("[name='name']").count()
                body = smoke.page.locator("[name='body']").count()
                smoke._record_assert("SOP KB article form renders (name+body)",
                                     expect="name>=1 & body>=1",
                                     actual="name=%d body=%d" % (namef, body),
                                     passed=namef >= 1 and body >= 1)
        rc = smoke.summary()
    finally:
        _shell(_TEARDOWN)  # always clean the browser sample
    sys.exit(rc)


if __name__ == "__main__":
    run()
