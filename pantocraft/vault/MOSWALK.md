# pantocraft // — Business Constitution
# MOSWALK.md — read by every automated workflow before generating output.
# Precision here → business-specific output. Vagueness here → generic noise.
# Update: Active Engagements weekly. Weekly Focus every session.

## Navigation Principle
Determining a live pathway is not deterministic — it is navigating an ocean with
professional skill. The chart is exact (agencies.yaml, legal invariants at rule_confidence 1.0).
The ocean is live. Nothing is ever fully determined before departure.

The crew is always in control. Unknowns are sea conditions, not stops.
The HEP payload is an instrument reading — the operator sets the course from it.
Mode C (voyage confidence < 0.40) is not an alarm: it is the highest-attention state,
where the operator takes the helm directly. The voyage proceeds under professional skill.

Clients trust the crew. The system earns that trust by being honest about sea conditions,
not by pretending the ocean is calm when it isn't.

## Platform Identity
Platform: moswalk — sovereign, local-first AI consultation for NYC building and regulatory work
What we produce: structured regulatory consultation with HEP escalation surface
Who we serve: property owners, developers, architects navigating NYC regulatory complexity
How we operate: iPhone 17 Pro field node + Mac mesh (Sifting/Inference/Archival) over Tailscale
Legal framing: information not advice — NY S7263 pending 2026. Licensed professional in loop required on every engagement.

## Regulatory Scope
Primary: NYC DOB filings (NB, A1, A2, A3, TR6), LPC landmark approvals, FDNY life-safety, DEP, DOT, HPD
Secondary: BSA variances (quasi-judicial), OATH violation resolution, ACRIS recordings
Data foundations: PLUTO v25v4 (property flags), NYC OTI agency registry April 2026 (139 active agencies)
Out of scope: NYS HCR rent regulation (T3 surface — escalate to licensed professional), federal overlays

## Two Confidence Instruments
rule_confidence (permit_pathways.yaml):
  How certain is this legal requirement. The chart. Does not change with voyage conditions.
  1.0 = codified law. 0.9 = established practice. 0.7 = variable. <0.7 = stale bearing.

voyage_confidence (pantocraft/archive/flywheel.py):
  How smooth is this particular passage: examiner history, backlog, site conditions.
  Empirically derived from the archive. Live sea state. Changes with every job that completes.
  Mode A ≥ 0.80 | Mode B 0.40–0.79 | Mode C < 0.40 (all hands)

Both are read together. Neither alone is sufficient.

## Agency Sequencing Invariants
LPC always precedes DOB for any landmarked property or historic district — no exceptions
DEP ACP5 or ACP21 precedes DOB for any pre-1987 building — no exceptions
BSA requires Pre-Determination filing before variance application
OATH hears ECB violations — not ECB itself
DOB (Housing DM) + NYC DOT (Operations DM) = two Deputy Mayor chains — flag escalation risk
rule_confidence < 0.70 on any step → verify current agency posture before filing. Voyage proceeds with caution.

## Operating Rules
- Never delete files. Archive with YYYY-MM-DD timestamp prefix instead.
- Never send communication without human review. Draft only.
- Date-stamp all generated files: YYYY-MM-DD-[type]-[subject].md
- Log every write operation to pantocraft/agentic/sessions/
- When uncertain about sequencing: deposit in generated/briefings/ and flag for review.
- Escalate to HEP: anything involving landmark properties, HARD_STOP_ACTIONS, voyage_confidence < 0.60, or open violations
- HARD_STOP_ACTIONS: lpc_file_coa, lpc_file_cne, acris_record_deed, acris_record_mortgage,
  bsa_file_variance, bsa_file_special_permit, dob_submit_filing, dob_submit_permit, hpd_submit_registration

## Active Engagements
# Update this section each session. One line per active BBL engagement.
# Format: [engagement_id]: [BBL] [borough] [project_type] | Status: [ACTIVE|STALE|HEP_PENDING] | Next: [action]
# Example: ENG-001: 3-00783-0001 Brooklyn A2-rooftop | Status: ACTIVE | Next: LPC pre-app meeting

## HEP Pending Review
# List any HEP payloads awaiting licensed professional sign-off.
# Format: [trace_id] | Tier: [1|2|3] | SLA: [deadline] | Action: [proposed_action]

## Weekly Focus
# Update each session — weights every system action toward current priorities.
# What matters most this week for moswalk:

## Knowledge Architecture
Shared brain (exact episodic record — never semantic search):
  agencies.yaml         → 139 NYC agencies, OTI registry April 2026
  permit_pathways.yaml  → 8 pathway types, rule_confidence + inject_before sequencing
  flywheel.py           → job archive, voyage_confidence signal, examiner history
Private notebook (per-engagement, append-only, chmod 600):
  pantocraft/agentic/sessions/[engagement_id].jsonl
Escalation artifacts (HEP payloads, chmod 600):
  pantocraft/agentic/escalations/[trace_id].json
Generated outputs (consultation reports, briefings, research):
  pantocraft/generated/consultations/
  pantocraft/generated/briefings/
  pantocraft/generated/reports/

## Queue Protocols
Drop a file in pantocraft/queue/ to trigger async processing:
  CONSULT-[bbl]-[filing_type].md → field consultation → generated/consultations/
  RESEARCH-[topic].md            → regulatory research brief → generated/briefings/
  PREMORTEM-[project].md         → premortem analysis → generated/briefings/
  INTAKE-[source].md             → intelligence intake filter → generated/briefings/
  OUTCOME-[engagement_id].md     → close flywheel loop: write real outcome to archive

OUTCOME file format (closes the consultation → HEP → archive → flywheel cycle):
  engagement_id: QUEUE-2026-07-15-3-00783-0001
  outcome: approved | objected | revised | escalated | withdrawn
  confidence_score: 0.88   # actual passage confidence in hindsight
  examiner_id: SMITH-J
  approval_date: 2026-07-15
  lessons: one-sentence operator note on what drove the outcome

Processed files move to pantocraft/queue/processed/ — never deleted.
