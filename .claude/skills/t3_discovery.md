# Skill: T3 Discovery — Unknown Agency Resolution

## Purpose

When `AgencyNavigator` cannot resolve a required permit or approval through
`permit_pathways.yaml` (Engine 1) or `agencies.yaml` (Engine 2), this skill
surfaces a **provisional pattern** using NYC's T3 (third-tier) discovery
process: informal pre-application meetings, OATH mediation, and inter-agency
coordination letters.

Invoke this skill when:
- A `PathwayResult` has `confidence < 0.70`
- An agency code appears in `conditions` but has no matching pathway
- A project type is not in `permit_pathways.yaml` (e.g., telecom, rooftop solar,
  private street demapping, below-grade fuel tanks)
- The navigator returns zero steps for a flagged condition

---

## Discovery Protocol

### Step 1 — Identify the gap

Determine which condition or agency is unresolved:

```python
result = nav.resolve(pathway_type, conditions)
if result.confidence < 0.70:
    unresolved = [s for s in result.steps if s.confidence < 0.70]
    # surface each to T3 discovery
```

Flag format:
```
T3_DISCOVERY_REQUIRED
  agency: <code or "UNKNOWN">
  trigger: <condition string from trigger_scanner>
  reason: <why standard pathway doesn't cover it>
  provisional_path: <see below>
```

---

### Step 2 — Provisional path by category

#### Category A — NYC agency, no pathway mapped

1. **Pre-application meeting** (PAM): Available at DOB, LPC, DEP, DCP. Free.
   File via agency portal. Timeline: 3–6 weeks for scheduling.
2. **OATH mediation** (ECB violations blocking permit): File OATH hearing
   request. Agency code: `OATH`. Timeline: 4–8 weeks.
3. **Inter-agency coordination letter**: When two agencies both claim
   jurisdiction (common: DOT + DEP for street-level excavation, LPC + DOB for
   landmark alterations). Draft as joint pre-application to both simultaneously.
   Flag: `escalation_risk: high` if agencies report to different Deputy Mayors.

#### Category B — State-level agency (NYS HCR, NYSDEC, NYSDOT)

These are **not in `agencies.yaml`** by design (OTI registry is NYC-only).
Route to NYS Office of General Services pre-application or SEQR determination.

```
T3_SURFACE: NYS_LEVEL
  agency: NYS HCR  # rent regulation — always NYS, not NYC
  path: NYS HCR APPS portal (apps.hcr.ny.gov)
  law: Rent Stabilization Law § 26-514
  note: Do not confuse with HPD (NYC) — different jurisdiction entirely
```

#### Category C — Federal overlay (FEMA, FTA, FAA)

Rare but load-bearing. Triggers:
- `flood_zone_ae: true` or `flood_zone_ve: true` → FEMA LOMA/LOMR may be
  required before DOB permit
- Transit-adjacent properties → FTA Section 4(f) consultation
- Helipad / rooftop telecom → FAA obstruction evaluation (Form 7460-1)

```
T3_SURFACE: FEDERAL_OVERLAY
  agency: FEMA
  path: FEMA MT-EZ application or LOMR-F
  prerequisite_for: DOB new building / major alteration in AE/VE zone
```

#### Category D — Quasi-judicial / variance required

Use when standard zoning does not permit the proposed use and a variance or
special permit is needed:

```
T3_SURFACE: QUASI_JUDICIAL
  agency: BSA        # variance / special permit
  or
  agency: DCP        # zoning text amendment (rare, months to years)
  law: ZR § 72-21 (BSA variance criteria — five findings required)
  note: BSA has no reports_to in org chart — quasi-judicial; no escalation chain
```

---

### Step 3 — Output format

Always return a structured result, never free-form prose:

```python
{
  "t3_flag": True,
  "category": "A" | "B" | "C" | "D",
  "agency": "<code>",
  "provisional_path": "<one sentence>",
  "law_citation": "<statute or ZR section>",
  "portal": "<URL or office name>",
  "timeline_note": "<realistic range>",
  "escalation_risk": "low" | "medium" | "high",
  "licensed_professional_required": True,  # always True for T3
  "information_not_advice": True            # NY S7263 framing — always True
}
```

---

## Invariants

- **Never guess an agency code.** If not in `agencies.yaml` and not a known
  NYS/federal body, return `agency: "UNKNOWN"` and surface for human review.
- **Never skip the licensed-professional flag.** T3 paths are precisely where
  professional judgment is required — unlicensed advice on variances, SEQR, or
  FEMA overlays is the highest liability surface.
- **`information_not_advice` is always True here.** T3 discovery produces
  provisional patterns, not approved strategies. A PE, RA, or attorney must
  validate before any filing.
- **Log every T3 event to `AgenticLog`.** Use `log.warning("t3_discovery",
  "unknown agency", {...})`. These are the cases that improve the kernel over time.
- **Do not add T3 results to `permit_pathways.yaml`** until validated by at
  least one real project outcome. Provisional ≠ canonical.

---

## Example — Rooftop solar + Con Edison interconnection

```
conditions = {"Enclosure structure requires electrical or anchoring"}
pathway_type = "alteration_type_2"

# AgencyNavigator returns: DOB only (standard A2)
# Missing: Con Edison interconnection, NYC DEP noise (inverter), potential FAA
# if building > 200ft

T3_DISCOVERY_REQUIRED
  agency: "Con Edison" (not in agencies.yaml — private utility, not city agency)
  trigger: "Enclosure structure requires electrical or anchoring"
  category: C (federal overlay if building > 200ft) / A (DEP noise)
  provisional_path:
    1. Con Edison Interconnection Application (utility, not city)
    2. DEP noise permit if inverter dB > threshold
    3. FAA Form 7460-1 if structure adds height above 200ft AGL
  escalation_risk: medium
  note: "SECURITY: Con Edison interconnection application will include system
         specs and grid connection point — do not store in public repo"
```

---

## When to escalate to human review

Immediately surface to the licensed professional in the loop when:
- Category D (variance) — BSA five-finding test requires RA/attorney judgment
- Any federal overlay — FEMA, FTA, FAA have strict procedural requirements
- `escalation_risk: high` — two Deputy Mayor chains in conflict
- Project involves landmark structure (LPC + DOB joint jurisdiction)
- Rent-stabilized building with capital work (NYS HCR jurisdiction, not city)
