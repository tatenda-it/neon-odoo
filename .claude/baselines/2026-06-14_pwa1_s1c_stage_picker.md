# Baseline: pwa1 S1c stage-picker RED (pre-existing, NOT WA-12.7)

Date: 2026-06-14, during the WA-12 quote-by-template + date-fixes build.

## Symptom
pwa1_interactive 7/9 (crash at S1c). S1c: a move_stage with an empty target on a
lead at the LOWEST crm.stage expects a <=3-button stage picker; got no buttons
(`last("buttons")` None) -> the UNGUARDED line ~221 `b["buttons"][0]` raises
`TypeError: 'NoneType' object is not subscriptable` -> run aborts at 7/9.

## Root cause (NOT this build)
- Code path: neon_channels/models/wa_copilot.py `_maybe_stage_picker` /
  `_forward_stages` / move_stage dispatch — the Copilot lane.
- This build's diff touches ZERO Copilot/CRM/move_stage/crm.stage code (it is
  neon_finance quote/report/settings + neon_crew_comms WA-12 only). So S1c's
  behaviour is byte-identical to before this build.
- Environmental: the local DB has 12 crm.stage rows (org pipeline seed:
  neon_crm_extensions/data/crm_stages.xml + neon_jobs/data/crm_stage_data.xml).
  `_maybe_stage_picker` emits ONLY when `2 <= len(forward) <= 3`. With
  move_stage("") the dispatch likely returns ok / a non-"stage" error so the
  picker guard (line 745/747) returns None -> no buttons -> S1c's unguarded tap
  crashes. The 4 "Gemini chat failed: API key not configured" warnings are the
  keyless-Gemini-primary local fallback (param=google, ai_keys_google unset),
  present all session.

## Disposition
- NOT a regression from WA-12.7. Does not test this build's code.
- pwa1 test fragility: S1c assumes a small CRM (<=3 forward stages) + has an
  unguarded `b["buttons"][0]` (line ~221). Fix candidates (separate, LOW):
  (a) guard line 221 on `b`; (b) S1c create the lead near the END of the pipeline
  so exactly 2-3 forward stages exist; (c) accept the >3 case (list, not buttons).
- The keyless-Gemini-local angle is the same class as the prod outage; the
  whatsapp_provider_key flip + Gemini key are the live fix (separate track).
