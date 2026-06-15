# -*- coding: utf-8 -*-
"""
CREW LOAD — crew technicians (gated one-shot, run at the human gate by Tatenda).

Creates, per tech:
  * a res.users (internal) + the neon_jobs crew group (group_neon_jobs_crew,
    resolved by XML id — NEVER the numeric res.groups id, per install-order rule)
  * one neon.bot.user (phone_number + user_id -> the new user) for WhatsApp
  * a random temp password written to a LOCAL 0600 file — NEVER printed to stdout
    and NEVER placed in chat. Tatenda distributes via WhatsApp, then shreds it.

Scope (EXACTLY as specced): res.users + crew group + bot.user. Idempotent
(get-or-create by login / by phone; existing users are NOT password-reset).

NOT in this op (flagged, awaiting a separate decision):
  * Employment classification. The category lives on hr.employee.neon_category_id
    (neon_hr extends hr.employee) — NOT on res.users / neon.bot.user. Tagging
    "Employed Technician" (4) vs "Freelance Technician" (5) therefore needs an
    hr.employee per tech and engages neon_hr's doc-compliance / assignment-gate
    machinery. Held for the A/B decision before any hr.employee is created here.
  * Lovejoy — separate repair-tech lane.
  * Ranganai (res.users uid 13, bot.user id 7) — already the lead; untouched.

Run (two-step, gated):
  # 1) DRY-RUN (default) — prints the full plan + collision re-check, NO writes,
  #    NO passwords generated:
  docker compose exec -T odoo odoo shell -d neon_crm --no-http < scripts/load_crew_techs.py
  # 2) APPLY (after the human gate on the printed plan) — use `exec` (running
  #    container) so the password file persists for retrieval:
  docker compose exec -T -e CREW_LOAD_APPLY=1 odoo odoo shell -d neon_crm --no-http < scripts/load_crew_techs.py
  # 3) Retrieve the credentials on the HOST terminal (never chat), distribute via
  #    WhatsApp, then shred:
  docker compose exec odoo cat /tmp/crew_temp_passwords.txt
  docker compose exec odoo shred -u /tmp/crew_temp_passwords.txt   # or rm

If the password file is lost before retrieval, the users still exist — recover by
resetting each password in Settings -> Users (no data loss, just a reset).
"""
import os
import secrets

APPLY = os.environ.get("CREW_LOAD_APPLY") == "1"
PW_FILE = os.environ.get("CREW_PW_FILE", "/tmp/crew_temp_passwords.txt")
DOMAIN = "neonhiring.co.zw"

# (display name, login handle, +263 phone, employment) — employment is recorded
# here only for the SEPARATE hr.employee classification step; this op does NOT
# apply it. Phones assistant-verified collision-free (no bot.user, no partner).
# 10 techs (Tadiwa added 2026-06-15, Robin confirmed freelance + active now).
CREW = [
    ("Arnold M", "arnold.m", "+263786280490", "permanent"),
    ("John",     "john",     "+263783433852", "freelance"),
    ("Bothwell", "bothwell", "+263776519710", "freelance"),
    ("Kelvin",   "kelvin",   "+263786956047", "freelance"),
    ("Stanley",  "stanley",  "+263781369828", "permanent"),
    ("Kudzai M", "kudzai.m", "+263733946158", "freelance"),   # NOT admin@ (bookkeeper)
    ("Trymore",  "trymore",  "+263773141666", "permanent"),
    ("Oswell",   "oswell",   "+263775617220", "freelance"),
    ("Adam M",   "adam",     "+263782232883", "permanent"),
    ("Tadiwa M", "tadiwa",   "+263782203304", "freelance"),   # starts next month, active now
]

# Unambiguous alphabet (no O/0/I/l/1) for WhatsApp-typeable temp passwords.
_PW_ALPHA = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


def _gen_pw(n=10):
    while True:
        pw = "".join(secrets.choice(_PW_ALPHA) for _ in range(n))
        if any(c.isdigit() for c in pw) and any(c.isalpha() for c in pw):
            return pw


Users = env["res.users"].sudo()
Bot = env["neon.bot.user"].sudo()
crew_group = env.ref("neon_jobs.group_neon_jobs_crew")   # res.groups (XML id)
base_user = env.ref("base.group_user")

print("=" * 70)
print("CREW LOAD — %d technicians  (APPLY=%s)" % (len(CREW), APPLY))
print("crew group: %s  (res.groups id %d — confirm == 49)"
      % (crew_group.name, crew_group.id))
print("=" * 70)

# ---- plan + collision re-check (always, no writes) ----
collisions = []
plan = []
for name, handle, phone, emp in CREW:
    login = "%s@%s" % (handle, DOMAIN)
    u = Users.with_context(active_test=False).search([("login", "=", login)], limit=1)
    b = Bot.with_context(active_test=False).search([("phone_number", "=", phone)], limit=1)
    if u:
        collisions.append("login %s already exists (uid %d)" % (login, u.id))
    if b:
        collisions.append("phone %s already mapped (bot.user %d -> uid %s)"
                          % (phone, b.id, b.user_id.id))
    plan.append((name, login, phone, emp, bool(u), bool(b)))

print("%-10s %-26s %-15s %-10s %-8s %-8s"
      % ("NAME", "LOGIN", "PHONE", "EMP*", "USER?", "BOT?"))
for name, login, phone, emp, hu, hb in plan:
    print("%-10s %-26s %-15s %-10s %-8s %-8s"
          % (name, login, phone, emp, "EXISTS" if hu else "new",
             "EXISTS" if hb else "new"))
print("-" * 70)
print("* EMP column is for the SEPARATE hr.employee classification (NOT applied "
      "here).")
if collisions:
    print("\n⚠️  COLLISIONS (idempotent skip on APPLY, but verify these are "
          "intended):")
    for c in collisions:
        print("   - %s" % c)

if not APPLY:
    print("\nDRY-RUN — no writes, no passwords generated. Re-run with "
          "CREW_LOAD_APPLY=1 to apply.")
else:
    creds = []
    n_users = n_bots = 0
    for name, handle, phone, emp in CREW:
        login = "%s@%s" % (handle, DOMAIN)
        u = Users.with_context(active_test=False).search(
            [("login", "=", login)], limit=1)
        if not u:
            pw = _gen_pw()
            u = Users.with_context(no_reset_password=True).create({
                "name": name, "login": login, "email": login, "password": pw,
                "groups_id": [(4, base_user.id), (4, crew_group.id)],
            })
            creds.append((login, name, pw))
            n_users += 1
        else:
            # idempotent: ensure crew group on a pre-existing user; never reset pw
            u.write({"groups_id": [(4, crew_group.id)]})
        b = Bot.with_context(active_test=False).search(
            [("phone_number", "=", phone)], limit=1)
        if not b:
            Bot.create({"name": name, "phone_number": phone, "user_id": u.id})
            n_bots += 1

    if creds:
        with open(PW_FILE, "w") as fh:
            fh.write("# Neon crew temp credentials — distribute via WhatsApp, "
                     "then SHRED this file. Never paste into chat.\n")
            fh.write("email\tname\ttemp_password\n")
            for login, name, pw in creds:
                fh.write("%s\t%s\t%s\n" % (login, name, pw))
        os.chmod(PW_FILE, 0o600)

    env.cr.commit()
    print("\nAPPLIED: %d users created, %d bot.user mappings created, "
          "%d credentials written." % (n_users, n_bots, len(creds)))
    print("Credentials file (0600): %s" % PW_FILE)
    print("Retrieve on the HOST terminal (NOT chat):")
    print("   docker compose exec odoo cat %s" % PW_FILE)
    print("   docker compose exec odoo shred -u %s   # after distributing"
          % PW_FILE)
    print("Passwords were NOT printed here by design.")
