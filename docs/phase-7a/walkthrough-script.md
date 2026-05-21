# Phase 7a Walkthrough Script — Robin

**Meeting:** Phase 7a sign-off + decisions
**Audience:** Robin (MD)
**Lead:** Tatenda
**Duration:** 90–120 min (offer break at 60 min mark)
**Pre-read:** None expected — walk Robin through live

This is a script, not a slide deck. Tatenda drives a working Odoo instance + the docs in two browser tabs; Robin watches, asks, decides. Three decisions need Robin's call by end of meeting: Phase 7a sign-off, ACL group mapping, Phase 7b open questions.

---

## Opening Framing (5 min)

**What Tatenda says at the start:**

> "What I'm showing you today is Phase 7a — the training and certification system we built over the last few weeks. It's the biggest module since Workshop. Twelve milestones, all the core surfaces, all working.
>
> There are three things I need from you in this meeting:
>
> 1. **Sign-off on what we built** — does it match what you wanted?
> 2. **Your call on a security finding** I caught during the pre-deploy check last night — I'll explain
> 3. **Your input on Phase 7b design** — onboarding and the crew self-service portal
>
> Estimated time is 90 to 120 minutes. If you want a break around the 60-minute mark, just say. And if we run short, we can split: demo today, decisions tomorrow."

**Why open this way:** sets a clear three-decision agenda, names the timebox, acknowledges Robin's time. No surprises later.

---

## Pre-walkthrough Setup (Tatenda solo, 5 min before Robin arrives)

Checklist — tick each off before opening the door:

- [ ] Local Odoo running at `localhost:8069`
- [ ] Logged in as Robin's account (`robin@neonhiring.co.zw`, admin) so the demo matches what Robin sees in real use
- [ ] Browser zoom at 100% or 110% (comfortable for both of you)
- [ ] Notifications muted — no Slack pings mid-demo
- [ ] This script open on phone or second monitor (not on the demo screen)
- [ ] `docs/phase-7b/schema-sketch.md` open in another tab (for decision point 2)
- [ ] Coffee, water, paper + pen for capturing Robin's decisions
- [ ] Phase 7a status doc open in a third tab: `docs/phase-7a/chrome-session-1-pre-deploy.md` (for the polish acknowledgement section)

---

## Part 1 — Phase 7a Demo (30–45 min)

### 1.1 Apps Switcher — Training is now an app (~3 min)

**WHAT to show:** click the apps grid icon top-left. Point to "Neon Training" alongside Workshop and Operations.

**WHAT to say:**

> "Until last week, training and certifications lived in a spreadsheet and in people's heads. Now it's a proper Neon app — same status as Workshop, same status as Operations. Anyone with the right access sees this icon when they log in."

Mention the placeholder icon proactively before Robin asks:

> "You'll notice the icon is a generic purple cube. That's a placeholder — Phase 12 polish item. We'll design a proper training/certification icon once Phase 7a is live."

**Anticipated Q&A:**

- *"Why does it look generic?"*
  > "Custom icon is on the Phase 12 polish list. We're shipping the system that works first, the visuals second."

- *"Can everyone see this app?"*
  > "Depends on their tier. You see it because you're admin. Crew see it but with fewer menus inside. We'll cover who sees what when we hit the ACL section — that's part of decision point 1."

### 1.2 Training Compliance Dashboard (~5 min)

**WHAT to show:** click "Neon Training" → lands on Dashboard.

**WHAT to say:**

> "This is the starting view for anyone with training access. Four card groups:
>
> 1. **Active Certifications by Category** — total and broken down by Equipment, Role Tier, Safety, Soft Skill.
> 2. **Expiring Soon** — 30, 60, 90 day forecast. Cumulative — the 60-day count includes the 30-day count.
> 3. **Workflow Health** — pending verification queue and recent cross-competency observations.
> 4. **Gate Fires by Tier** — info, warn, block. We'll see Gate Log later; this is the at-a-glance summary.
>
> Every counter is clickable — drills you into the filtered list. Counts recompute every time you open this view, so it's always current."

Walk through each card visually. Hover over a drill-through link to show the wording.

**Anticipated Q&A:**

- *"Why are all the counts zero?"*
  > "This is local dev — no real cert data yet. When we deploy to prod, we'll backfill from existing crew certs. You've probably got 30 to 40 active certs across the team — we'll see them here."

- *"Can I get this as a weekly email?"*
  > "Not yet — that's Phase 9, WhatsApp and email integration. The data is here; we just need to wire the delivery."

- *"What's a Gate Fire?"*
  > "Defer to the Gate Log section in a few minutes — easier to show than describe."

### 1.3 Find Qualified User (~5 min)

**WHAT to show:** click "Find Qualified User" → wizard opens as a modal.

**WHAT to say:**

> "This is the answer to the question you've asked me a hundred times: 'who can run MA3 console on Friday's job?' or 'who's certified to drive the 5-ton?'.
>
> Pick the cert types you need on the left. Set a minimum level if it matters — Basic, Standard, Expert for tiered certs. The soft filters on the right let you include people whose cert is still pending verification, or people who've demonstrated cross-competency without a formal cert.
>
> Hit Search. Result is a list of crew members who match all criteria."

Demo the wizard shell. Pick a cert type, walk through the level dropdown adapting. Don't run a real search (no data) — just show the input flow.

**Anticipated Q&A:**

- *"Does it know if they're already booked?"*
  > "Not yet — that's a Phase 8 integration with the job calendar. For now it tells you WHO is qualified; you check availability against the calendar separately. Phase 8 will let you ask 'who is qualified AND free on Friday'."

- *"Can I filter by experience level?"*
  > "Yes — Required Level. For equipment certs, you can ask for Standard or Expert. For driver licences, you can pick a specific class."

- *"What if nobody's qualified?"*
  > "Empty result. That's a signal — either time to train someone up, or hire externally. We can build a workflow around that later if it becomes a regular thing."

### 1.4 Certifications Form + M3 Dynamic Widget (~10 min) ⭐ KEY DEMO

This is the showpiece — slow down here.

**WHAT to show:** Certifications menu → click + New → walk through the empty form.

**WHAT to say:**

> "This is the actual cert record. One per cert per person. Has everything tied together: the person, the cert type, the level, when they got it, when it expires, who signed it off, attachments for the certificate PDF or photo."

Click the **Certification Type** field. Pick **MA3 Console**. Pause here — this is the moment.

> "Watch what happens when I pick MA3 Console.
>
> The system auto-fills the Category as Equipment. It sets the Level Mode to 'Tiered (3 levels)'. And the Level dropdown — look — now only shows Basic, Standard, Expert. Only the options that make sense for an equipment cert.
>
> Now watch this." [Change the cert type to **English Language**.] "Different cert type, different level scale. Now Level shows just Pass — binary. Because language proficiency at Neon is a Self+Peer cert, not a tiered one.
>
> Pick Lead Tech." [Change again.] "Now Level shows Lead Tech, Tech, Runner, Driver — a custom scale specific to that cert.
>
> Form adapts to the cert. No invalid combinations possible."

Show the **state pipeline** at the top: Draft → Pending Verification → Active.

**WHAT to say about the state pipeline:**

> "Here's the cert lifecycle. Self-upload by the holder starts in Draft. They submit for verification — pipeline advances to Pending Verification. The right sign-off authority gets a notification. They verify the attachment — cert becomes Active. After the expiry date passes, a daily cron moves it to Expired automatically."

**Anticipated Q&A:**

- *"Who decides who signs off?"*
  > "It's a property of the cert type. Look at MA3 Console — sign-off authority is Lead Tech, meaning Ranganai. Class 5 Driver Licence — External Trainer, because the licensing body issues it. Lead Tech role itself — OD/MD, meaning you or Munashe."

- *"Can I edit a cert after it's verified?"*
  > "Active certs are mostly read-only — the audit trail matters. To correct a mistake, you create a new cert with the right data and the old one gets superseded. Or admin can suspend the cert and re-verify."

- *"What if someone uploads a fake certificate?"*
  > "That's why verification is by sign-off authority, not self-attestation. Ranganai looks at the actual attachment. External certs ideally include the issuing body's reference number on the document. We're not solving for fraud — we're solving for 'we lost track of who has what.'"

- *"How does this connect to our existing employee records?"*
  > "Each cert links to a `res.users` record — the same user record as their Odoo login. No duplication. If a person isn't in Odoo yet, we create them as part of onboarding — that's Phase 7b."

### 1.5 Cert Types — Seed Data Review (~5 min)

**WHAT to show:** Configuration → Certification Types → switch to kanban view, grouped by category.

**WHAT to say:**

> "This is the master list — what we recognise as a cert in the system. We seeded 32 types across the four categories: Equipment, Role Tier, Safety, Soft Skill."

Pan across the categories. Call out specifics Robin will recognise:

- **Equipment** — MA3 Console, MA2 Console, ChamSys MagicQ, Avolites Tiger Touch, DiGiCo (audio), LED Wall, Truss Climbing (Prolyte)
- **Role Tier** — Driver, Lead Tech, Runner, Tech (the four crew tiers)
- **Safety** — Class 2/3/4/5 Driver Licences (with ZTSC as issuing body), PSV Endorsement, Electrical Live Mains (with ZERA), Fire Safety Indoor, Fire Safety Outdoor, First Aid
- **Soft Skill** — Cash Handling, Client-Facing Comfort, Leadership, Photography/Videography, language certs (English, Ndebele)

**Anticipated Q&A:**

- *"Where did this list come from?"*
  > "We built it from our actual gear and roles. Ranganai's input was the equipment side — what consoles we own, what training he expects on each. Yours and Munashe's input was the soft-skill side. Anything missing? We can add it — we'll capture that during the meeting."

- *"Can I add a new cert type myself?"*
  > "Yes — Configuration menu, click + New. Admin can add anytime."

- *"Why is English a cert? Everyone speaks English."*
  > "It's a proficiency cert for client-facing roles — Basic, Conversational, Fluent. Useful when we're matching crew to specific clients, especially corporate gigs where presentation matters. Same applies to Ndebele."

- *"What about welding? Rigging?"* (or any specific cert)
  > [Capture in notes. Don't add during the meeting — risk of typos and breaking the demo. Add post-walkthrough, batch.]

### 1.6 Brief Tour — Remaining Surfaces (~10 min)

Cover quickly — these are supporting surfaces, not showpieces. Don't dwell.

**Cross-Competencies** (kanban view, M6):

> "This records when someone outside their primary role demonstrated competency in another. Example: a Tech runs Lead Tech for an evening because the Lead Tech was sick. We record that here — observation by an admin, dated, linked to the event. After three demonstrations of the same competency, it can be promoted to a proper role-tier certification. Robin's data-analytics framing — capture the informal stuff so we can formalise it."

**Gate Log** (list view, M9):

> "This is the audit log for the three-tier gating system. Whenever someone tried to assign crew to a job where they don't have the required certs, the system fires here. Three tiers:
>
> - Info — sales rep assigns Bob to Lead Tech role, Bob doesn't have MA3. Toast notification, log entry. Saves silently.
> - Warn — quote moves to Accepted with the same crew. Wizard pops up asking the sales rep WHY they're proceeding. Reason logged.
> - Block — event tries to start with the same crew. Wizard blocks the transition unless an admin overrides with a reason. Hardest gate.
>
> All three log entries land here. Searchable by tier, by event, by date. Useful for spotting patterns — like 'we keep starting events with unqualified runners — we need to train more runners'."

**Reports submenu** (M12.1):

> "Three printable reports. Expiring Soon — 90-day forecast for renewal planning. Compliance Roster — Safety category grouped by regulatory body (ZIMRA, ZERA, ZTSC, etc.) for compliance requests. Cross-Competency Log — quarterly run for training-plan input."

**Configuration menu** (M1):

> "Master data. Categories and Types — what we just covered. Most admin work is here only at setup; once the seed is right, you rarely touch it."

---

## Part 2 — Polish Acknowledgment (3–5 min)

**Why upfront:** Robin will spot most of these herself. Better to acknowledge before she asks — shows ownership, not deflection.

**WHAT to say:**

> "Before we move to decisions, I want to be upfront about six things I know need polish. None of them are blockers — they're Phase 12 work. Let me list them so you've seen the list, then we move on."

List briefly with the screen still on a dashboard or cert form:

1. Pagination shows "1 / 1" on the dashboard — visual debug-leak from the way the system materialises the dashboard record. Cosmetic only.
2. Drill-through buttons on the dashboard wrap awkwardly — line break in odd places.
3. Dashboard whitespace between counter rows is loose — should be tighter.
4. Cert form shows "User" field twice — header and Person section. Duplicate display, not a real issue.
5. State pipeline only shows three states (Draft → Pending Verification → Active). Suspended and Expired are valid states but don't appear in the visual indicator.
6. Verify button shows even on Draft cert — admin role-based visibility nuance to be tightened.

**WHAT to say:**

> "These are tracked. We'll address them in a focused polish sprint after Phase 7a is live and stable. Same sprint we'll do the proper Training app icon. None of them affect functionality."

**Anticipated Q&A:**

- *"Why didn't you fix them already?"*
  > "Engineering trade-off. Every one of these needs more than a 10-line fix. The pagination one in particular needs custom OWL component work — that's the new JavaScript framework Odoo uses. Better to ship the working version and polish in a focused sprint than delay deploy for cosmetic items."

- *"How long is the polish sprint?"*
  > "Phase 12 is roughly a week — these six items plus the icon plus any new items that surface during Phase 7b. We'll plan it after Phase 7b ships."

---

## Part 3 — Decision Point 1: Production ACL Finding (15–20 min) ⚠️

This is the biggest decision item. Don't rush.

**WHAT to say (opening):**

> "Last night during the pre-deploy walkthrough, I caught something on production that needs your call. It's not a security breach, but it's not how we want it either. Let me walk you through it."

Pause. Read the room. If Robin looks alarmed, soften:

> "Nothing's broken. The system works. I just want to clean it up before we add more users."

### Explain the finding

> "Right now, every internal user on production has four implicit groups they don't really need:
>
> 1. **Basic Pricelists** — Odoo's pricelist feature, used for tiered pricing per customer segment
> 2. **Mail Template Editor** — lets the user edit the email templates that go out to clients
> 3. **Multi Currencies** — shows USD/ZiG side-by-side in pricing fields
> 4. **Technical Features** — this is the concerning one. It's developer mode. Anyone with this can see internal field names, the technical settings menu, model definitions, raw debug toolbars."

> "It's universal — all 16 users on prod have all four. Same on local dev. It got set up during Phase 1 or Phase 2 — probably someone clicked through a Settings wizard and accepted the defaults. Never recorded in code, so it's been silent."

> "Last night when I created the test user for crew onboarding — Arnold M — they got it too. That's what surfaced this. I reverted Arnold immediately, but the bigger issue is: every new user we create inherits these. Including the nine crew we're about to onboard."

> "We need to clean this up before adding more users. That means deciding **who genuinely needs each of these four groups**."

If possible, show: Settings → Users & Companies → Groups → Internal User → Implied Groups tab. The four groups are visible there in the UI. Visual proof.

### Get Robin's call per group

For each group, walk through:

#### Technical Features (`base.group_no_one`)

> "This is developer mode. Field XML IDs, technical menu, debug toolbar, model browser."
>
> "**My recommendation: Robin, Munashe, Tatenda only.** Nobody else. Crew should NOT have this — they could accidentally enable debug mode and break workflows. Sales shouldn't have it — clutters their interface."
>
> "Your call?"

Capture answer in the table below.

#### Multi Currencies (`base.group_multi_currency`)

> "USD and ZiG side-by-side in pricing fields. Quotes show both currencies."
>
> "**My recommendation: anyone who touches pricing.** That's Robin, Munashe, Tatenda, Kudzaiishe as bookkeeper, finance approvers, sales reps quoting in both currencies."
>
> "Crew don't see invoices or quotes, so they don't need this."
>
> "Your call?"

#### Pricelists (`product.group_product_pricelist`)

> "Different rate cards for different customer segments. Used in quoting."
>
> "**My recommendation: same as Multi Currencies** — Robin, Munashe, Tatenda, Kudzaiishe, finance, sales."
>
> "Your call?"

#### Mail Template Editor (`mail.group_mail_template_editor`)

> "Lets the user edit the email templates that go out to clients. Risky if everyone can — wrong wording goes out, hard to track who changed what."
>
> "**My recommendation: Tatenda only.** Or Tatenda + you with final approval on changes. Sales reps and crew should not be editing templates."
>
> "Your call?"

### Capture decisions

**Robin's decisions table** (fill in during the meeting):

| Group | Who keeps it (Robin's decision) |
|---|---|
| Technical Features (`base.group_no_one`) | |
| Multi Currencies (`base.group_multi_currency`) | |
| Pricelists (`product.group_product_pricelist`) | |
| Mail Template Editor (`mail.group_mail_template_editor`) | |

### Closing the ACL section

**WHAT to say:**

> "With these decisions, I write a migration tonight or tomorrow. The migration does two things:
>
> 1. Removes the four groups from `base.group_user`'s implied list — so new users don't auto-inherit them
> 2. For each existing user, applies your tier mapping — they end up with only what they should have
>
> We deploy Phase 7a and the ACL fix together. Then I resume the crew onboarding for the nine paused users, and they get clean groups from creation."

**Anticipated Q&A:**

- *"Can't we just leave it?"*
  > "We could, but every new user we add gets it — including the nine crew we already started onboarding. They'd have developer mode. Better to fix once than perpetuate."

- *"What if I'm wrong and someone needs Multi Currencies later?"*
  > "I add them via Settings → Users. One-line grant. Easy to add per-user; hard to undo at scale, which is why we want the default narrowed first."

- *"Is the migration risky?"*
  > "Small. It touches `base.group_user.implied_ids` — four removals — and then per-user updates based on your mapping. We test on local first. Worst case is rollback — we have a backup point before deploy."

- *"How do I see this group state after the migration?"*
  > "Same place I just showed you — Settings → Users & Companies → Groups. You'll see the four groups have fewer members."

---

## Part 4 — Decision Point 2: Phase 7b Schema Review (20–30 min)

**WHAT to say (opening):**

> "Now let me walk you through what Phase 7b looks like — crew onboarding and the self-service portal. I drafted a design based on our conversations. I want your input on specific decisions before we build, so we don't get four milestones in and find out you wanted something different."

Open `docs/phase-7b/schema-sketch.md` in the browser or IDE.

### 4a. The 6-stage onboarding workflow (~5 min)

Show section 3 of the sketch — the ASCII state-machine diagram.

**WHAT to say:**

> "Four states a candidate moves through. Candidate → Cert Collection → Probationary → Active.
>
> - **Candidate**: we have their name, contact info, role they're being hired for. No certs collected yet.
> - **Cert Collection**: a requirement template has been applied based on their intended role. They — or their manager — upload the certs they need. Each one goes through Pending Verification → Active as the sign-off authority verifies them.
> - **Probationary**: all required certs are verified. They can be assigned to jobs, but only as Runner or shadow tier — not their full intended role yet. We watch them across a few real jobs.
> - **Active**: probationary period complete. Full crew tier per their certified roles."

> "There's a fifth path: **Admin Skip Onboarding**. Any state → Active in one click, with a written reason. Audit log entry. We need this for the nine crew we already have — they're already trained, we just need them in the system. We click Skip nine times in five minutes."

### 4b. The 8 open questions (~15–20 min)

For each question, present the default + ask Robin. Capture answers as you go.

#### Q1. Probationary period length

> "Default: **3 jobs.** That's about a month of work at our typical rhythm — they've seen load-in, event, strike, return across different rigs."
>
> "Should it be 5? Or measure in days instead of jobs?"

**Robin's answer:** ____________________

#### Q2. Admin override authority

> "Default: **managers + admin tier.** That's you, Munashe, Ranganai when we onboard him, and Tatenda for dev purposes."
>
> "Should Ranganai be able to skip onboarding for someone? Or only you and Munashe?"

**Robin's answer:** ____________________

#### Q3. WhatsApp notifications

> "Default: **trigger points coded, actual sends deferred to Phase 9.** That means when someone hits a milestone — onboarding complete, cert expired, gate fired — the system knows but doesn't send WhatsApp yet."
>
> "When we DO build WhatsApp in Phase 9, who should get notified for each event? Six trigger points in the sketch — let's walk through them quickly."

Walk through section 9 of the sketch.

**Robin's answer:** ____________________

#### Q4. Required cert matrix

> "This is the big one. Section 7 of the sketch — for each role, what certs they must have to be Active."

Walk through the table row by row:

> "Driver: any one driver licence (Class 2, 3, 4, 5, or PSV) + Fire Safety + Vehicle Safety Briefing."
>
> "Lead Tech: Lead Tech role-tier cert + Electrical Live Mains + at least two equipment certs from MA2, MA3, Tiger Touch, MagicQ, DiGiCo, LED Wall, Truss."
>
> "Tech: Tech role-tier cert + at least one equipment cert + Fire Safety."
>
> "Runner: Runner role-tier cert + Fire Safety."

> "Any of those wrong? Anything missing? This is the bar a new hire needs to clear to be considered Active."

**Robin's answer per row:** ____________________

#### Q5. Portal layout direction

> "Default: **responsive — works on phone and desktop**. Crew use phones mostly. Managers use desktops."
>
> "Crew use phones, right? They're not sitting at a workshop computer most of the time."

**Robin's answer:** ____________________

#### Q6. Initial password policy

> "Default: **`Neon2026!` as a shared starter password, with users forced to change on first login.** Same as the existing crew onboarding plan we paused last night."
>
> "Same as that, or different?"

**Robin's answer:** ____________________

#### Q7. Audit log SUPERUSER bypass

> "Default: **log everything, no exceptions.** Even cron-driven auto-transitions get an audit entry."
>
> "If the system auto-promotes someone from probationary to active because they completed three jobs, you want to see that in the log, right?"

**Robin's answer:** ____________________

#### Q8. Manual Promote-to-Active path

> "Default: **button available to managers.** Lets you promote someone early — before they hit the probationary jobs target — if you know they're ready (e.g., they have prior production experience elsewhere)."
>
> "Want that override path? Or always require the three jobs?"

**Robin's answer:** ____________________

### Closing the 7b section

**WHAT to say:**

> "With your answers, I update the sketch with the final decisions. Then we know exactly what we're building when we start Phase 7b after deploy."

---

## Part 5 — Decision Point 3: Deploy Approval (5 min)

**WHAT to say:**

> "So to recap what we've decided today:
>
> 1. **Phase 7a as you saw it** — approved? [Pause for Robin's yes]
> 2. **ACL fix per your group mapping** — I write the migration based on the table we filled in
> 3. **Phase 7b design** — I update the sketch with your input on the eight questions
>
> My plan for the next few days:
>
> 1. **Tonight or tomorrow:** write the ACL migration based on your mapping. Test on local.
> 2. **Day after:** deploy Phase 7a + ACL migration together to production. We take a backup first — standard for any production deploy.
> 3. **Same day, post-deploy:** resume the crew onboarding for the nine users. Click Skip Onboarding for each — five minutes total. They get the right groups from creation.
> 4. **Start of next week:** begin Phase 7b build. Two to three weeks at our usual cadence.
>
> Sound good?"

**Anticipated Q&A:**

- *"What's the deploy risk?"*
  > "Phase 7a is feature-complete and tested locally. We've already run the migration framework on dev — pre-deploy fix #2 and #3 last night were both `-u` upgrade tests. The ACL migration is smaller — touches `base.group_user`'s implied list, four removals, plus per-user updates per your mapping. We have a backup before deploy. Worst case rollback to pre-deploy state."

- *"How will the team know about the new system?"*
  > "Phase 7b includes WhatsApp notifications for crew when they hit onboarding milestones. For the admin/sales tier — you'll show them, or I do a team training session before Phase 7b ships. Probably a 30-minute walkthrough."

- *"When does Ranganai come in?"*
  > "Once Phase 7b is live, we add Ranganai as the first onboarding through the new system — he becomes the test case. He'll need Lead Tech cert, Electrical Live Mains, several equipment certs. After his onboarding completes, he's the sign-off authority for all equipment certs going forward."

---

## Wrap (5 min)

**Tatenda's closing:**

> "Thanks for the time, Robin. I'll send you a written summary in chat right after this — the four ACL group decisions and the eight Phase 7b decisions, so we both have the same record.
>
> Tentative deploy is [day]. I'll send a calendar hold for the deploy window."

---

## Post-walkthrough Checklist (Tatenda's TODO after meeting)

Run through these within an hour of the meeting while it's fresh:

- [ ] Send Robin a chat message summarising the four ACL decisions + eight Phase 7b decisions
- [ ] Update `docs/phase-7b/schema-sketch.md` with Robin's answers on the eight open questions — replace each "(Robin to confirm at walkthrough)" tag with the locked answer
- [ ] Write the ACL migration prompt for Claude Code based on Robin's group mapping (one prompt, follows the per-tier table)
- [ ] Update memory `project_phase7a_status.md`: append a "WALKTHROUGH RESULT" section with date, decisions captured, deploy date set
- [ ] Update memory `MEMORY.md`: Phase 7a status one-liner reflects walkthrough closed + deploy date set
- [ ] Schedule deploy: create calendar hold, decide on backup window
- [ ] Notify Munashe (and Tatenda's calendar): deploy is happening on [date]
- [ ] If Robin flagged new cert types during section 1.5, capture them in a notes file under `docs/phase-7a/` for the post-deploy data-add pass

---

## Appendix A — Quick Reference for the Meeting

### URLs to have open in tabs before Robin arrives

| Tab | URL | Purpose |
|---|---|---|
| 1 (active during demo) | `http://localhost:8069/web` | Apps switcher landing |
| 2 (open in background) | `docs/phase-7b/schema-sketch.md` (open in VS Code or browser) | Decision point 2 |
| 3 (open in background) | `docs/phase-7a/chrome-session-1-pre-deploy.md` | Polish acknowledgement reference |
| 4 (Tatenda's script) | This file on phone or second monitor | Don't show Robin |

### Key Odoo deep-links (paste into address bar mid-demo)

These bypass menu navigation when you want to jump to a specific surface:

- Cert list (form view ready): `http://localhost:8069/web#action=neon_training.neon_training_certification_action`
- Cert type kanban: `http://localhost:8069/web#action=neon_training.neon_training_certification_type_action`
- Cross-competencies: `http://localhost:8069/web#action=neon_training.neon_training_cross_competency_action`
- Gate log: `http://localhost:8069/web#action=neon_training.assignment_gate_log_action`
- Settings groups: `http://localhost:8069/odoo/settings/users` (then Groups tab)

(URLs use action xmlids rather than numeric IDs so they survive across DB instances.)

### Phrases that work mid-demo

- "What you're looking at is..."
- "The reason we built it this way is..."
- "Let me show you a specific example"
- "Pause me if anything's unclear"
- "I need your call on this one"
- "Phase 12 polish — tracking, not blocking"

### Phrases to avoid

- Technical jargon without explanation: "Odoo," "ORM," "ACL," "implied_ids," "groups_id," "context flag," "migration script" (use plain English equivalents)
- "It's complicated" without explaining WHY
- "Trust me" — always show the evidence
- "It just works" — explain HOW it works

### If Robin asks about deploy timing during the demo

Park the question. Say: "Let me finish the demo, then we'll cover deploy as decision point 3. About 30 minutes from now."

### If a surface is broken during the demo

Don't panic. Say: "That's odd — let me jump to a different example." Move on. Capture the bug in your notes, address post-walkthrough. Don't debug live in front of Robin.

### Energy management

- 30 minutes in: offer water
- 60 minutes in: offer break
- 90 minutes in: ask "shall we wrap and continue tomorrow, or push through?"

---

## Appendix B — What NOT to cover

To keep the meeting under 2 hours, deliberately skip:

- **Technical architecture** of the gating system (M9 hook patterns, sudo escalation, FK lifecycle). Robin doesn't need this. The Gate Log surface is enough.
- **The five Phase 11 CLAUDE.md amendment candidates** from the pre-deploy session. Process-improvement; not user-facing.
- **The four reference docs** produced during pre-deploy. Internal craft documentation; not Robin's concern.
- **Production deploy mechanics** (Docker, migrations, post-init hooks). Cover the timeline and risk, not the steps.
- **The browser smoke harness**. Internal QA tooling; Robin doesn't care that we have 1045/1047 regression coverage.

If Robin asks about any of these — answer briefly, then steer back to the demo.

---

## Appendix C — Reading Robin

Signals to watch for:

- **Robin says "make a decision"** when pressed → she's tired or confident in your judgement; capture the decision and move on
- **Robin asks "what would you do?"** → she's testing your judgement; give your honest recommendation
- **Robin gets quiet during a feature** → she's processing; pause, don't fill the silence with more demo
- **Robin asks the same question twice** → the first answer didn't land; rephrase the second time
- **Robin's phone rings and she answers** → break point; pause demo, drink water, resume when she's back

If Robin is enthusiastic about a feature, lean in:

- "Want to see another example?" "Want me to add a real cert to test?" — let her drive
- Don't rush past the parts that energise her

If Robin is skeptical:

- "What's the concern?" — name it, address it directly
- Don't dismiss; don't oversell

End of script.
