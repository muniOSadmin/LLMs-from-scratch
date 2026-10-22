---
name: intelligence-intake
description: |
  Process an influx of external articles, PDFs, research, or technical posts
  and extract what is worthwhile for the moswalk platform. Use when the user
  says "process this article", "intake this PDF", "what does this mean for us",
  "work through this", or "is this relevant." Applies a structured filter to
  separate signal from noise, maps findings to moswalk's current architecture,
  and proposes the correct disposition without making any code changes until
  approved. Do NOT activate for general questions about the codebase.
---

## What this skill does

Processes external intelligence (articles, PDFs, X threads, research) and produces
a structured signal report + disposition proposal for the moswalk platform council.
It never changes code autonomously — it proposes, then waits for approval.

---

## Step 1 — Read and compress

Read the source fully. Extract the core claim in one sentence. Discard:
- General AI hype ("AI will change everything")
- Vendor marketing claims without benchmarks
- Anything not relevant to: harness architecture, NYC agency process, inference
  efficiency, knowledge representation, escalation/compliance, or output formats

---

## Step 2 — Apply the intake filter

For each signal extracted, run this filter in order:

```
Q1: Does this change a sequencing or legal invariant?
    YES → PRIORITY: IMMEDIATE — propose edit to permit_pathways.yaml or .claude/rules/
    NO  → continue

Q2: Does this validate or invalidate a core architectural choice?
    YES → VERDICT: validated | invalidated — log decision, no code change unless tests gap
    NO  → continue

Q3: Does this introduce a mechanism moswalk doesn't have?
    YES → run the UNBLOAT TEST, then propose roadmap item
    NO  → continue

Q4: Does this improve output, communication, or client-facing experience?
    YES → propose format/UX improvement (HTML rendering, skill update, etc.)
    NO  → discard or archive
```

**Unbloat test** (run before every "gap" disposition):
1. What specific pain does moswalk feel today without this mechanism?
2. What is the minimum implementation that addresses that pain?
3. Does adding this require removing something to stay lean?
4. Is there a simpler existing component that could be extended instead?

If the pain is hypothetical (not yet encountered), the disposition is "monitor, not build."

---

## Step 3 — Format the signal report

One block per signal extracted:

```
SOURCE: [title — author/publication]
DATE: [publication date if known]
SIGNAL: [one sentence — the core claim]
RELEVANT_TO: [which moswalk component(s)]
  - iphone-llm/  (inference engine, swarm, quantization)
  - moswalk-kernel/  (agencies, pathways, triggers)
  - pantocraft/  (field API, session log, intake, HEP)
  - .claude/  (CLAUDE.md, skills, rules, hooks)
  - architecture  (overall design principles)
VERDICT: validated | gap | partial | invalidated | discard
UNBLOAT_TEST: [passed | failed | n/a]
DISPOSITION:
  - validated: "Log in session_log. No code change."
  - gap: "Roadmap item: [name]. Priority: critical | high | medium | low.
          Blocker: [what must exist first, or 'none']."
  - partial: "Existing component [name] partially covers this. Proposed extension: [...]."
  - invalidated: "Requires change to [file]. Proposed edit: [...]."
  - discard: "Reason: [noise | not relevant | already covered]."
```

---

## Step 4 — Council summary

After all signals are processed, produce:

1. **Consensus signals** — claims that appeared in 2+ sources (highest confidence)
2. **Biggest validated gap** — the most load-bearing missing mechanism
3. **Immediate actions** — anything with no external blockers that addresses a real pain
4. **Things to watch but not build** — mechanisms that are correct but premature
5. **Things to discard** — explicitly named so the user doesn't revisit them

---

## Disposition rules

### Legal/sequencing invariants — always immediate
If a source cites a Local Law change, a new agency requirement, or a sequencing
change (e.g., LPC now requires pre-application before DOB for a new class of work),
this is not a roadmap item — it is an immediate edit to `permit_pathways.yaml` or
`.claude/rules/`. Run the smoke tests. Commit.

### Architecture validations — log, don't rebuild
If a source confirms the existing architecture is correct (e.g., shared brain = curated
team facts with graceful degradation), log the validation in session_log.py as a
`decision()` event. Do not rebuild what is already working.

### Format/UX signals — queue carefully
HTML over markdown, interactive diagrams, shareable links — these are high-value
but not urgent. Queue as a PathwayResult enhancement or client-brief template.
Do not rebuild the output layer mid-sprint.

### Missing mechanisms — unbloat test first
Before adding any new mechanism (hooks, HEP, idempotency ledger, Temporal,
Neo4j), run the unbloat test. If the pain is not yet named and felt, the disposition
is "monitor."

---

## Invariants

- **Never change code during intake.** This skill produces proposals only. The user
  approves before implementation.
- **Never classify vendor marketing as a signal.** "Cut permit times in half" is a
  claim, not a benchmark. Require cited evidence.
- **Cite the source for every signal.** No attribution = no signal.
- **Log every intake run.** Use `AgenticLog.decision("intelligence_intake", source, signal_count)`.
- **A clean intake that finds nothing actionable is correct.** Not every article
  changes the architecture. Confirm explicitly: "No actionable signals found. Reason: [...]."
