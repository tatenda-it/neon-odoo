# P6.M12 — Hetzner deploy log (crm.neonhiring.com)

**Target:** neon_finance `17.0.7.9.0` (P6.M11 head at `76b7ff2`).
**Production currently at:** neon_finance `17.0.1.5.0` (Phase 1 only;
Phase 6 has never been on prod).
**Deploy window:** TBD with Robin.
**Operator:** Tatenda.
**Sign-off:** Robin (MD) + Kudzi (Bookkeeper).

> Fill in this log AS the deploy runs. Treat each section as a
> checklist; record outcome + timestamp before moving to the next.
> Mirror the P5.M11 deploy log structure
> (`docs/phase-5/M11_deploy_log.md`).

---

## 1. Pre-flight: production user state verification

**Why this comes first.** A previous visual tour found that on this
local DB the Administrator (uid=2) login carried Robin's email
(`robin@neonhiring.co.zw`) instead of `admin@neonhiring.com`. If
production has the same drift, the Phase 6 group assignments will
land on the wrong user account. **This MUST be resolved before
running `-u neon_finance` on production.**

**Steps:**

1. SSH to `crm.neonhiring.com`, open an Odoo shell against `neon_crm` DB:
   ```bash
   docker compose exec odoo odoo shell -d neon_crm --no-http
   ```
2. Verify `res.users` state:
   ```python
   admin = env.ref('base.user_admin')
   print('admin login:', admin.login)          # MUST be admin@neonhiring.com
   print('admin email:', admin.partner_id.email)
   for login in ['robin@neonhiring.co.zw',
                 'munashe@neonhiring.co.zw',
                 'lisar@neonhiring.co.zw',
                 'tatenda@neonhiring.co.zw',
                 'evrill@neonhiring.co.zw',
                 'kudzaiishe@neonhiring.co.zw']:
       u = env['res.users'].search([('login', '=', login)])
       print(login, '->', 'EXISTS' if u else 'MISSING')
   ```
3. Acceptance criteria:
   - Administrator (uid=2) login is `admin@neonhiring.com`
     (NOT any team member's email).
   - Robin has a separate user record with login `robin@neonhiring.co.zw`
     and `group_neon_finance_approver` membership.
   - Same check for: Munashe, Lisa, Tatenda, Evrill (Evy), Kudzi.

4. **If Administrator carries any team member's email:**
   - Rename Administrator login back to `admin@neonhiring.com`.
   - Create separate user records for affected team members.
   - Add appropriate `group_neon_finance_*` membership per the
     role matrix:
     - Robin (MD): `group_neon_finance_approver`
     - Munashe (Sales/Client Relations):
       `group_neon_finance_sales` + `group_neon_finance_approver`
     - Lisa (Production): `group_neon_jobs_lead_tech` /
       `group_neon_jobs_crew_leader` (operational, not finance)
     - Tatenda (Finance/Sales hybrid):
       `group_neon_finance_sales` + admin
     - Evy (Support / general): `group_neon_finance_sales` if
       quoting; otherwise `group_user`
     - Kudzi (Bookkeeper): `group_neon_finance_bookkeeper`

5. If state is already clean, record: `user-state pre-flight: OK`.

6. Document the final user/group state below before proceeding.

**Final production user/group state (recorded at deploy time):**

| Login | Name | Role | Groups | Notes |
|---|---|---|---|---|
| _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

---

## 2. Pre-deploy backup

- [ ] Database backup taken: `neon_crm-$(date +%F-%H%M).dump`
- [ ] Backup verified (size matches recent baseline, restoring is possible)
- [ ] Filestore tarball captured (if applicable)
- [ ] Backup location: _TBD_
- [ ] Restoration runbook reviewed: same as P5.M11 deploy log

---

## 3. Version bump + module upgrade

- [ ] `git pull` to head: `76b7ff2` (P6.M11)
- [ ] Confirm `neon_finance/__manifest__.py` version is `17.0.7.9.0`
- [ ] Run `docker compose run --rm odoo odoo -u neon_finance -d neon_crm --stop-after-init --no-http`
- [ ] Confirm upgrade clean (no ERROR / CRITICAL in tail)
- [ ] Force-recreate odoo container: `docker compose up -d --force-recreate odoo`
- [ ] Container healthy: `docker compose ps`

---

## 4. Post-deploy probe drift check

- [ ] Workshop Dashboard probe: `probe_workshop_dashboard.ps1` → expect 8/8 PASS
- [ ] Cash Flow Dashboard probe (P6.M10 polish item U): TBD if added before deploy
- [ ] If any probe FAILs, **STOP** and consult diagnostic before proceeding

---

## 5. Polish-item resolution decisions (Robin/Kudzi walkthrough)

The following polish items were deferred during Phase 6 build with the
note "Robin/Kudzi decides at M12 deploy." Capture the decision here
before going live:

- **Item O** (P6.M8): Populate `res.company.x_zimra_tin` + `x_zimra_bpn`
  for `base.main_company`. Decision: _TBD — Robin to provide values._

- **Item T** (P6.M9): `x_neon_credit_hold` enforcement policy.
  Decisions needed:
  - (a) Soft-warn (banner only, current state) vs hard-block (UserError)
  - (b) Which action point: `submit_for_approval`, `accept`, `move.post`,
    or all of these
  - (c) Approver bypass with justification, or `action_clear_credit_hold`
    as the only path?
  Decision: _TBD._

- **Item Y** (P6.M11): Sales tier visibility on `commercial.event.job`.
  Options: (a) add cross-module read so banner is reachable, OR (b) accept
  current narrower scope (sales sees via quote chain only).
  Decision: _TBD._

- **Item V** (P6.M10): Cash Flow Dashboard as auto-landing for Finance
  app users? Currently menu-only at sequence=4.
  Decision: _TBD._

- **Item S** (P6.M9): Auto-match payment by amount? Q21 confirmed
  manual-only initially. Decision now (post-trial):
  _TBD — defer to Phase 12 polish unless requested._

---

## 6. Robin / Kudzi walkthrough

Script (similar to P5.M11 acceptance video):

1. **Quote creation** (Tatenda → Robin)
   - Create a draft quote on a real event_job
   - Walk through pricing rule auto-fill + manual override
   - Submit for approval → Robin approves in real time
   - Mark sent → mark accepted → schedule materialises

2. **Invoice schedule walkthrough** (Tatenda → Kudzi)
   - Schedule list shows pending invoices
   - Click into one schedule → invoice details visible
   - Trigger Now for a future-dated schedule (Kudzi)
   - Payment registration via Register Payment wizard

3. **Cost-line entry** (Lisa → Kudzi)
   - Lisa records crew cost via Cost Lines menu
   - Verify TODO activity lands in Kudzi's inbox

4. **Cash Flow Dashboard** (Kudzi)
   - Open dashboard
   - Walk through the 6 tiles
   - Drill into Outstanding Receivables tile

5. **Cost recovery scenario** (Robin)
   - Open an incident with `is_client_caused=True`
   - Resolve as write-off
   - Approve the recovery invoice via the wizard

6. **Sign-off:** Robin records short acceptance video.

---

## 7. Tag the release

- [ ] `git tag -a v17.0.7.9.0-phase6-live -m "Phase 6 live on production"`
- [ ] `git push origin v17.0.7.9.0-phase6-live`

---

## 8. Phase 6 sign-off

- [ ] Robin acceptance: _signed (date)_
- [ ] Kudzi acceptance: _signed (date)_
- [ ] Production version on `crm.neonhiring.com` matches local head
- [ ] Phase 6 status memory updated to "deployed"
- [ ] Polish items P, Q, R, U-Z surfaced as Phase 11 candidates if not
      resolved during walkthrough
