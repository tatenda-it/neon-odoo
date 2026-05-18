# P5.M11 — Robin walkthrough script

Target length: 5-10 minutes. Recorder: any team member with screen-cap
software (OBS / QuickTime / Loom / Windows Game Bar). Output: MP4 suitable
for WhatsApp share with Robin.

Setup before recording:

- Browser at `https://crm.neonhiring.com` (clear cookies first so the
  first frame is the login screen).
- Three test credentials ready: `p2m75_mgr`, `p2m75_lead`, `p2m75_crew`,
  all using password `test123`.
- Window sized for 1280x720 minimum so the dashboard tiles render at
  their intended responsive width.

## Script

### 1. Open (10-15s)

> "Hi Robin — quick walkthrough of the new Workshop Inventory section
> in the Odoo CRM. This went live earlier today on production at
> `crm.neonhiring.com`. It runs **alongside** the existing PHP workshop
> system at `neonhiring.com/workshop/` — both are operational. The PHP
> system stays in charge of real data; this Odoo module is for the
> team to familiarise themselves before the Phase 11 cutover when we
> migrate data across and retire PHP."

### 2. Login as manager (30s)

- Enter `p2m75_mgr` / `test123` and log in.
- Note: *"This is a synthetic test account for the walkthrough. You'd
  log in with your normal `robin@neonhiring.co.zw` account in actual
  use — it has the same permissions as this test account."*

### 3. Workshop menu tour (45-60s)

- Click the **Workshop** menu in the top bar.
- Hover slowly over each submenu so all eight are visible:
  - Overview (new — the dashboard)
  - Equipment Units
  - Categories
  - Reservations
  - Movements
  - Pending Transfers
  - Stock Takes
  - Repair Orders
  - Incidents
- Comment: *"All eight sub-screens, each backed by its own model. The
  Overview tile dashboard at the top is the new single-glance landing
  page."*

### 4. Open Workshop > Overview (1-2 minutes)

- Click **Overview**.
- Pause on the rendered dashboard. Point out:
  - The two groups: **Inventory Snapshot** and **Attention Needed**.
  - All 10 tiles render with their FontAwesome icons.
  - The **Last updated** timestamp at the top.
  - The **Refresh** button.
- Walk through each tile briefly (~10s each):
  - Active Units, Units Out, Reservations — 7 Days, Pending Transfers,
    Late Returns.
  - Equipment Conflicts, Stock Discrepancies, Repair Orders, Incidents
    (red border), High-Impact — 30 Days (red border).
- Important caveat: *"Every tile shows zero counts right now — that's
  expected. Production workshop data still lives in the PHP system.
  The Phase 11 cutover will import existing equipment, reservations,
  and incident history; at that point these counters start tracking
  real workshop activity."*

### 5. Drill-through demo (45s)

- Click **Active Units**.
- The filtered list view opens — point out it would normally show all
  equipment in `active` state. Right now: empty.
- Comment: *"Click any tile to drill into the underlying records, same
  pattern across all 10 tiles. So the dashboard is a navigation hub as
  well as a status overview."*
- Click back to **Workshop > Overview**.

### 6. Lead Tech role demo (45s)

- Log out via the user menu top-right.
- Log in as `p2m75_lead` / `test123`.
- Open **Workshop > Overview** — confirm the dashboard renders
  identically.
- Comment: *"Lead Tech role has the same dashboard visibility as
  manager. Both can monitor the full workshop state."*

### 7. Crew-tier security demo (45s)

- Log out, log in as `p2m75_crew` / `test123`.
- Show the top menu bar — **Workshop is NOT visible** to this user.
- Comment: *"Crew-tier users don't see the Workshop menu at all.
  Multiple security layers ensure that even direct URLs are rejected
  — a crew user calling the dashboard endpoint via any means receives
  an Access Denied response. The dashboard is gated to Manager and
  Lead Tech only."*

### 8. Closing summary (30s)

- Log out.
- Summarise:
  - *"That's the Phase 5 build complete and live in production. Phase 6
    will add the Training System next. Phase 11 will handle the PHP →
    Odoo workshop data cutover and retire the old system at that
    point."*
  - *"Let us know any questions or feedback. We're proceeding to Phase
    6 build now; we can pause that any time if you'd like changes here
    first."*

## Post-recording

- Save to `/opt/neon-odoo/deploy_walkthroughs/` on Hetzner if uploading
  from there, or to a local working directory otherwise.
- Filename convention: `P5M11_robin_walkthrough_<YYYYMMDD>_v1.mp4`.
- Share via WhatsApp to Robin with a short text:
  > "Hi Robin — Phase 5 (Workshop Inventory) is now live in production
  > alongside the existing PHP system. 5-min walkthrough of what's
  > there: <link>. Workshop data is empty until the Phase 11 cutover;
  > this is just for familiarisation. Any questions, let us know."
- Note the date sent in the master plan progress doc.

## Robin acceptance criteria

This walkthrough is informational, not a sign-off gate. Robin's
acceptance — if/when given — closes P5.M11 formally. Until then the
deploy stands as "live pending signoff" per the M11 deploy log.
