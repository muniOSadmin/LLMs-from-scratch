# skill: agency_pattern_navigator

Compose the full, ordered, dependency-resolved agency pathway for a NYC
construction or alteration project. Two-engine: canonical law (permit_pathways.yaml)
+ OTI org chart (agencies.yaml). Output educates AND enables.

## When to invoke

Use this skill when:
- A user describes a project and wants to know the full regulatory pathway
- You have a TriggerResult from property_trigger_scanner and need the agency sequence
- A SimClient agent needs to run its project through the kernel
- pantocraft // is assembling a ConsultResult to optimize and present

## Two-engine composition

**Engine 1 — Canonical law** (permit_pathways.yaml):
Reads the legally mandated agency sequences. Evaluates conditional_agencies
against the active trigger conditions. Topological-sorts on sequential_after.
This engine never makes assumptions — it reads the law.

**Engine 2 — OTI org chart** (agencies.yaml):
Attaches Deputy Mayor chain, agency type, portal availability, and officer title
to each step. Identifies cross-DM escalation risk when multiple chains are involved.

## Step 1: Determine pathway_type

Map project description to pathway_type:

| Project description | pathway_type |
|---|---|
| New building, vacant lot, full demo + rebuild | `new_building` |
| Change of use, new CO, egress change | `alteration_type_1` |
| Rooftop addition, structural work, multiple work types | `alteration_type_2` |
| Single plumbing/HVAC/minor work | `alteration_type_3` |
| Façade inspection, LL11 FISP cycle | `fisp_facade` |
| Sidewalk café, revocable consent, outdoor seating | `sidewalk_cafe` |
| Basement/cellar apartment legalization | `adu_legalization` |
| Assembly use, > 74 occupants, community facility | `place_of_assembly` |

If ambiguous: ask. If multi-type (e.g., gut reno + solar): resolve primary
pathway first, then layer secondaries. Do NOT blend pathways — each gets its
own resolution pass.

## Step 2: Run the navigator

```python
from moswalk_kernel.agencies.agency_navigator import AgencyNavigator
from moswalk_kernel.property.trigger_scanner import TriggerResult

nav = AgencyNavigator()
result = nav.resolve(pathway_type, trigger_result.conditions)

print(result.summary_table())
print(f"Critical path: {result.critical_days()} days")
print(f"Total calendar: {result.total_calendar_days()} days")
```

## Step 3: Output format

```
PROJECT: {description}
FILING TYPE: {dob_filing_type}
PATHWAY: {pathway_type}

Agency Pathway ({n} agencies):
─────────────────────────────────────────────────────────────────
STATUS   AGENCY         ROLE           DAYS  BLOCKING  SEQ AFTER
READY    LPC            approval         45  BLOCKING  —
READY    DOB            primary          45  BLOCKING  —
READY    FDNY           approval         21  BLOCKING  DOB
READY    NYC DOT        approval         14  parallel  —
─────────────────────────────────────────────────────────────────
Critical path: ~90 days  |  Total calendar: ~90 days

BLOCKERS:
  ⛔ LPC historic_district: Certificate of Appropriateness required BEFORE DOB
     permits exterior work (Admin Code §25-305). Sequence: LPC → DOB.

ESCALATION:
  ⚠ DOB (Housing DM) + NYC DOT (Operations DM) — two Deputy Mayor chains.
    Cross-DM escalation requires two sign-off paths if disputes arise.

EDUCATIONAL:
  DOB: Department of Buildings. Primary permit authority. Pro Cert available.
  LPC: Landmarks Preservation Commission. 10–90 day approval depending on track.
  [etc.]
```

## Step 4: Educational overlay

After presenting the pathway, always append:
```
What this means in plain English:
  1. [first step in human terms]
  2. [second step]
  ...

What to do RIGHT NOW:
  → [most urgent first action, no jargon]
```

Use moswalk_kernel.agencies.educational.explain_pathway(steps) for agency descriptions.
Use moswalk_kernel.agencies.educational.explain(code) for individual agency detail.

## Multi-pathway composition (complex projects)

For projects spanning multiple pathway types (e.g., SIM-007: gut reno + solar):

1. Identify the PRIMARY pathway (highest DOB filing type: NB > A1 > A2 > A3)
2. Resolve primary pathway fully with all conditions
3. For each secondary pathway: run resolve() and MERGE steps:
   - Deduplicate by agency code (keep highest confidence)
   - Extend sequential_after chains if secondary steps depend on primary approval
4. Re-sort topologically
5. Flag: "Multi-pathway project — verify with DOB Pre-Filing Meeting before submitting"

## T3 discovery (unknown agencies)

If a project condition doesn't match any conditional_agencies entry in permit_pathways.yaml,
invoke the `t3_discovery` skill:
- Input: condition description in plain English
- Output: provisional agency pattern with confidence < 0.70
- Always surface to user with stale flag: "T3 provisional — verify before relying"

## Confidence thresholds

| Confidence | Meaning | Action |
|---|---|---|
| 1.0 | Codified in law | Present as authoritative |
| 0.9+ | Well-established practice | Present normally |
| 0.70–0.89 | Common but variable | Note "typical" not "required" |
| < 0.70 | Stale or provisional | Flag prominently, do not proceed |

## What pantocraft // does NEXT

AgencyNavigator output feeds directly into pantocraft // PathwayOptimizer:
- Each AgencyStep with is_optimizable=True can be accelerated by a professional track
- edge_weights.yaml provides speed_multiplier per track per agency
- PathwayOptimizer.optimize() returns OptimizedPathway with days_saved

The kernel never applies optimization. It only tells you what the law requires.
pantocraft // tells you how to do it faster within the law.

## Invariants (never violate)

- NEVER reorder steps that violate sequential_after dependencies
- NEVER mark a blocking=True step as optional
- NEVER apply professional strategy (edge weights) in this skill — that is pantocraft //
- NEVER present confidence < 0.70 steps without a stale flag
- ALWAYS include law citations for blocking conditions
- ALWAYS check escalation_chain() for cross-DM risk
