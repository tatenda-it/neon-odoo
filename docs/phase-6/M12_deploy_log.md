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

**Walkthrough completed 20 May 2026 with Robin.** Decisions captured
below; behavioural fixes ship on hotfix branch `feat/p6-walkthrough-
fixes` and tag as `v17.0.7.9.1-phase6-walkthrough-fixes`.

### Item O — ZIMRA values

Decision: TIN + VAT populated, BPN SKIPPED (Robin: BPN permanently
outdated, leave null). Decided by Robin 20 May 2026.

- TIN `2002085185` → `res.company.x_zimra_tin`
- VAT `220397046` → `res.company.partner_id.vat` (standard Odoo)
- BPN: left null per instruction
- Vendor # `725004`: deferred to Phase 12 polish (PDF line + field
  rename `x_zimra_bpn` → `x_zimra_vendor_no`). The data currently
  sits in `x_zimra_bpn` on the production company record; Phase F
  E1 verifies the values match expectations without overwriting.

Implementation: Phase F.E1 (verify-only) + Phase F.C4 (PDF strip
removes BPN line).

### Item T — Credit hold enforcement

Decision: keep soft-warn (current state). No code change. Robin:
"banner + chatter is sufficient signal; don't add UserError friction
to action_submit_for_approval / action_accept / account.move.post".
Decided by Robin 20 May 2026.

Implementation: no work.

### Item Y — Sales tier event_job visibility

Decision: ADD cross-module record rule (option a from M11 polish
item). Sales tier reads `commercial.event.job` where they are the
salesperson on any linked `neon.finance.quote`. Decided by Robin
20 May 2026 — reverses Tatenda's M11 lean toward narrower scope;
Robin's framing: "the cost recovery banner is useful awareness for
the salesperson; show it".

Implementation: Phase F.C2 — ir.rule on `commercial.event.job` for
`group_neon_finance_sales` + ACL row in `neon_finance/security/
ir.model.access.csv`.

### Item V — Cash Flow Dashboard auto-land + OD/MD menu shortcut

Decision: BOTH halves. Decided by Robin 20 May 2026.

- Half 1 (top-level menu shortcut): Add a launcher-icon menu visible
  to `group_neon_finance_approver` (OD/MD: Robin + Munashe). Lands
  directly on Cash Flow Dashboard.
- Half 2 (auto-land for finance roles when opening Invoicing app):
  Set `res.users.action_id` on each user holding
  `group_neon_finance_bookkeeper` OR `group_neon_finance_approver`
  to point at the dashboard server action. Per-user write, no code
  commit — done as Phase F.E4 shell op.

Caveat (logged to project_phase6_status polish backlog + Phase 12):
new finance-role users added after deploy will NOT auto-inherit
`action_id`. Either Tatenda runs the snippet again, or Phase 12
adds an `_post_init_hook` / `groups.users` write trigger.

Implementation: Phase F.C3 (menu shortcut) + Phase F.E4 (per-user
action_id write).

### Item Z — SoD self-approval guard

Decision: REVERT. Decided by Robin 20 May 2026. Robin's family-
business trust model: "if I'm the salesperson and also the approver,
it's because I want to confirm my own quote went out. SoD is
appropriate for arms-length finance teams; it's friction here."

Reverses the predeploy fix shipped at `e2951ab`
(`fix(p6.predeploy): block self-approval and self-rejection of
quotes`).

Implementation: Phase F.C1 — remove the `salesperson_id ==
self.env.user` guard from `action_approve` + `action_reject`;
invert p6m4_smoke T832 + T833 from "blocked" to "succeeds".

### Item S — Auto-match payments by amount

Decision: stays deferred. Robin: "manual entry builds trust; revisit
in Phase 12 if Kudzi asks." No work for Phase F.

### Item K1 — Kudzi partner name correction

Decision: rename `res.partner.name` "Kudzai" → "Kudzaiishe". Decided
by Robin 20 May 2026 (Kudzi's preferred spelling). Phase F.E2 shell
op.

### Item K2 — Kudzi elevated groups review

Decision: strip Technical Features ONLY. Keep Multi Currencies +
Mail Template Editor. Decided by Robin 20 May 2026 (Option B
refinement: Kudzi needs MC for invoicing in USD/ZiG; MTE for
modifying email templates as Bookkeeper tooling).

Implementation: Phase F.E3 shell op — remove from `base.group_no_one`
only; verify `base.group_multi_currency` + `mail.group_mail_template
_editor` membership retained.

### Phase 7 forward-looking decisions (logged to Phase 7a polish backlog)

- **P7a custom KB confirmed**: Phase 7d build path locked. Not Phase
  F scope.
- **P7b Leadership Tier upgrade to tiered**: M3.1 fix-round, ~100 LOC.
  After Phase F closes.
- **P7c Client-facing Comfort upgrade to tiered**: M3.1 fix-round,
  same shape as P7b.
- **P7d Language tiering stays binary**: no work.

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
