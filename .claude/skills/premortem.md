# Skill: Premortem — Stress-Test Any Plan Before Shipping

## Purpose

Run this skill before committing to any plan, filing strategy, code
architecture decision, or client-facing output. A premortem imagines the plan
has already failed and works backwards to find why.

This is not a veto mechanism. It is a forcing function to surface hidden
assumptions, sequencing risks, and liability exposure before they manifest in
the field.

Invoke when:
- A `PathwayResult` is about to be shown to a client
- A new code module is about to be merged to `main`
- A filing strategy involves multiple agencies with `sequential_after` chains
- Confidence on any step is < 0.80
- Any T3 discovery result is being promoted to a canonical pathway
- A swarm topology or inference config change is being deployed

---

## Protocol

### Phase 1 — Failure modes inventory (2 minutes)

Ask: "It is 90 days from now. This plan failed. What went wrong?"

Work through these categories in order:

**Sequencing failure**
- Was `sequential_after` respected? Did DOB file before LPC cleared?
- Did a `blocking: true` step get skipped because confidence was 0.85 and it
  looked safe?
- Did two agencies with different Deputy Mayor chains get treated as parallel?

**Data staleness**
- Is any condition based on PLUTO data older than the current version (v25v4)?
- Has a Local Law changed the sequencing since `permit_pathways.yaml` was last
  updated?
- Is the `confidence` score still valid or was it set during an earlier sprint?

**Scope creep / undisclosed scope**
- Did the property turn out to have open violations not surfaced in the initial
  scan?
- Was there a rent-stabilized unit that changed the entire agency set?
- Did the client add scope ("oh and also the roof") after the pathway was set?

**Jurisdiction mismatch**
- Was an NYS-level agency (HCR) accidentally routed through the NYC pathway?
- Was a federal overlay (FEMA, FAA) required but not flagged?
- Was BSA required but the project went straight to DOB variance?

**Professional liability exposure**
- Did any output cross from "information" to "advice" without a licensed
  professional in the loop?
- Was the `information_not_advice` flag suppressed anywhere?
- Did a T3 provisional pattern get treated as a canonical approved strategy?

**Technical failure (code / inference)**
- Did a shape mismatch in the swarm coordinator silently produce wrong tokens?
- Did the INT4 quantized model hit a PPL spike on a domain-specific term?
- Did a `sys.path` injection cause the wrong `agencies.yaml` to load?
- Did the session log fail to write (permissions, disk full) and lose an audit
  trail?

---

### Phase 2 — Severity scoring

For each failure mode found, assign:

```
severity:  critical | high | medium | low
likelihood: likely | possible | unlikely
mitigated_by: <existing safeguard or "NONE">
```

**Critical** = filing rejected, permit voided, liability exposure, client data
exposed, or app store rejection  
**High** = project delayed > 30 days, rework required, wrong agency engaged  
**Medium** = embarrassment, extra coordination, cost overrun  
**Low** = minor annoyance, cosmetic, easily corrected  

---

### Phase 3 — Go / No-Go decision

**Go** if:
- No critical unmitigated failures
- All `blocking: true` steps confirmed in sequence
- Licensed professional has reviewed any T3 or confidence < 0.80 step
- `information_not_advice: True` on all client-facing output

**No-Go** if:
- Any critical unmitigated failure exists
- `sequential_after` chain is broken
- Client data (BBL, PII) would be exposed in output or logs
- Provisional T3 pattern is being treated as canonical

**Conditional Go** if:
- High severity but mitigated by explicit client sign-off
- Confidence < 0.80 but licensed professional is explicitly in loop
- T3 pattern is labeled provisional and a PE/RA is reviewing

---

## Output format

```python
{
  "premortem_result": "go" | "no_go" | "conditional_go",
  "failure_modes": [
    {
      "category": "sequencing | staleness | scope | jurisdiction | liability | technical",
      "description": "<one sentence>",
      "severity": "critical | high | medium | low",
      "likelihood": "likely | possible | unlikely",
      "mitigated_by": "<safeguard or NONE>"
    }
  ],
  "blockers": ["<list of go/no-go blockers if no_go or conditional>"],
  "conditions": ["<list of conditions for conditional_go>"],
  "information_not_advice": True  # always
}
```

---

## Premortem templates by context

### Filing strategy premortem

```
Plan: Submit A1 filing for landmark building in flood zone AE
Failure modes to check:
  1. LPC pre-approval not obtained before DOB submission → REJECTED at intake
  2. FEMA LOMA not resolved → DOB will not issue permit in AE zone
  3. PLUTO flood_zone data stale → missed the overlay entirely
  4. Confidence = 0.72 on DEP step → possible missed stormwater requirement
Result: NO-GO until LPC clears and FEMA status confirmed
```

### Code architecture premortem

```
Plan: Merge swarm_coordinator.py speculative path changes
Failure modes to check:
  1. Shape mismatch in _accept_reject → silent wrong-dimension cat (happened once)
  2. _verify_draft runs all blocks in-process — distributed path untested
  3. draft_layers=4 but MICRO_TINY_CONFIG only has 4 total → draft == full model
  4. sys.path still points to CWD in any __main__ block → wrong module loaded
Result: GO after smoke test confirms shape and tok/s
```

### Client output premortem

```
Plan: Return PathwayResult to client for Manhattan landmark gut reno
Failure modes to check:
  1. LPC step missing from A2 pathway (condition string mismatch — was bug, now fixed)
  2. HCR step missing if building has rent-stabilized units (NYS, not in kernel)
  3. "information_not_advice" not in response header → liability exposure
  4. BBL in session log output → must not appear in any log written to disk
Result: CONDITIONAL GO — add HCR T3 surface, confirm info_not_advice header
```

---

## Invariants

- **Run before every client-facing pathway result.** Not optional.
- **Run before every merge to main that touches `permit_pathways.yaml`.** A
  wrong confidence score or missing `sequential_after` is a silent bug that
  propagates to every future engagement.
- **Log premortem results to `AgenticLog`** using `log.decision("premortem",
  result, failure_modes)`. These are your audit trail.
- **Never suppress a critical failure mode** because the client is impatient or
  the deadline is today. The cost of a rejected DOB filing or LPC violation
  exceeds any schedule pressure.
- **A premortem that finds nothing is suspicious.** Either the plan is
  unusually simple or the premortem was not thorough. Re-examine.
