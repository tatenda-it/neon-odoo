# Neon Events Elements — Sequencing Decisions

This file records deliberate deviations from the canonical Master
Implementation Brief Section 11 milestone ordering. Each deviation has
a date, rationale, and acknowledgement.

The Master Brief sequence is M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7 →
M8 → M9 → M10 → M11 → M12 → M13 → M14. Read those numbers as the
canonical reference; "M2" always means Master Brief M2 regardless of
when we actually do it.


## Deviation 1 — M14a brought forward (27 April 2026)

**Master Brief sequence:** M1 → M2 → M3 → M4 → M5 → M6 → ... → M14

**Actual sequence being followed:** M1 → M14a → M2 → M6 → ... → M14b

**What changed:** The hosting and deployment half of M14 ("M14a") is
being done immediately after M1, before M2 (channels) and M6 (Finance).
The Zoho cutover half ("M14b") remains the final milestone.

**Rationale:**
- M2 (channel integration) needs a real public HTTPS URL before
  WhatsApp / Meta webhooks can be tested end-to-end. Cloudflare Tunnel
  on local Docker would work as a development hack but is not a
  foundation we'd want to depend on long-term.
- M6 (Finance) confidentiality concerns are easier to manage on a
  controlled VPS with proper RBAC than on a developer workstation.
  Robin's Finance Phase 1 brief Section 26 explicitly identifies the
  developer-sees-restricted-data risk.
- Lisar and Munashe gain real system access months earlier with hosting
  done first. Even with an empty database, they can log in, learn the
  UI, and prepare for live use.

**Acknowledgement:** Robin agreed verbally on 27 April 2026.


## Deviation 2 — Zoho CRM migration deferred from M14a (27 April 2026)

**M14a v1.0 originally included §9** — Zoho CRM data migration as part
of going live.

**M14a v1.1 removes this from active scope.** §9 is preserved in the
tracker for traceability but marked deferred. Production goes live with
an empty database.

**Rationale:**
- Migration is a substantial sub-project on its own (3-5 working days
  minimum, often more)
- Mixing migration with hosting setup means M14a does not sign off
  until both are done — risk of perpetual "almost-done" state
- Lisar/Munashe can keep Zoho open in a second tab during the early
  weeks of using Odoo, manually re-entering on a per-need basis
- Migration becomes its own milestone once the team has a real workflow
  in Odoo

**Trade-off accepted:** Lisar and Munashe will retype client details
for the first weeks of go-live until migration happens.

**Acknowledgement:** Tatenda decided 27 April 2026; pending Robin
review.


## Deviation 3 — Oracle account ownership (28 April 2026)

**Original M14a v1.1 plan:** `cloud@neonhiring.co.zw` mailbox owns the
Oracle Cloud account.

**Actual outcome:** Munashe Goneso's personal Gmail address owns the
Oracle Cloud account.

**Why we deviated:** Oracle Cloud's anti-fraud rejected several signup
attempts using `cloud@neonhiring.co.zw` + Zimbabwe IP + the various
card combinations we tried. The combination that ultimately succeeded
was: Munashe's name + Munashe's Gmail + Munashe's South African bank
card + Munashe's phone for SMS. Oracle's anti-fraud is opaque, and
consistency across all signup details was apparently the key.

**Implications:**
- Account recovery requires Munashe's Gmail access
- All Oracle billing / security alerts go to Munashe's Gmail
- If Munashe is unavailable when the account needs admin attention, the
  recovery path runs through him
- Future ownership transfer (e.g. to a `cloud@neonhiring.co.zw`
  address) is possible but requires Oracle Support involvement

**Mitigation:**
- Budget alerts (set up 28 April 2026) email both Munashe AND Tatenda
  so issues are visible to both
- A future task in M14b (or earlier) will explore moving account
  ownership to a Neon-controlled address

**Acknowledgement:** Munashe consented to using his details to unblock
the signup; Robin and Tatenda agreed verbally on 28 April 2026.


## Deviation 4 — SSH access policy (28 April 2026)

**Master Brief default:** would have been just Tatenda (single
developer, single admin key).

**Actual decision:** Three SSH keys at root level:
- Tatenda's key (primary, day-to-day work)
- Munashe's key (account owner, emergency access)
- Robin's key (managing director, emergency access)

**Rationale:** Single key = single point of failure. If Tatenda's
laptop is lost, stolen, or compromised before keys are rotated, the
system is locked. Three keys spread the risk across three machines
and three people.

**Trade-off:** More paperwork (three keys to generate, distribute,
rotate). Robin and Munashe need to learn at least basic SSH key
generation. We accept this for the resilience benefit.

**Implementation:** Keys are generated fresh per user (Ed25519
algorithm). They are NOT reused from any existing context (e.g.
GitHub SSH keys). All three public keys go into the VM's
`/root/.ssh/authorized_keys` file at provisioning time.