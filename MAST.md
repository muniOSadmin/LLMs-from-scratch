# MAST

MAST is where a building idea meets the city that has to approve it.

Every project in New York crosses the same terrain: 139 agencies, a century of code,
and the judgment of whoever reviews the file that week. Most tools treat that terrain
as paperwork to get through. MAST treats it as part of the design. The rules shape a
project the way light, structure and budget do, and they are most useful early, while
the idea can still change.

MAST works for everyone who moves a building from intent to occupancy: owners with a
plan, the architects and engineers who draw it, the expediters who carry it through,
and the agencies who review it. Each sees the same picture: what the law requires, in
what order, how long the passage is likely to take, and where it is uncertain.

---

## Two Layers

```
MAST ──────────────────────────── client-facing platform (proprietary)
  intake/       encrypted client records, NY SHIELD Act compliant
  inference/    professional tracks, pathway optimizer
  archive/      flywheel: every finished job sharpens the next estimate
  agentic/      HEP: the surface where human judgment takes the helm
  field/        API and server for the iPhone app
        │
mos ───────────────────────────── engine (moswalk)
  moswalk-kernel/   open core, Apache 2.0: agencies, pathways, property flags
  iphone-llm/       MicroLLM 1.1B INT4, swarm inference, iOS app
        │
mesh ──────────────────────────── iPhone 17 Pro · Mac Inference · Mac Sifting · Archival
                                  Tailscale, encrypted end to end, no public endpoints
```

**mos** is the engine. It knows the law and runs on hardware we control.
**MAST** is the practice built on it: the judgment, the timing, the craft.

---

## The Chart: what mos knows

The law, exactly as written.

- Which agencies apply to which project types
- Mandatory sequences (LPC before DOB for landmarks; DEP asbestos clearance before DOB for pre-1987 buildings)
- Blocking conditions (a flood zone makes a basement ADU ineligible)
- All 139 active NYC agencies, their reporting chains and their portals
- DOB filing types: NB, A1, A2, A3, TR6, PA

This is public knowledge, codified and structured. Anyone can fork it and build on it.

---

## The Passage: what MAST adds

How the system actually moves.

- LPC XCNE: 3–5 days instead of 45, for work that qualifies.
- DOB Professional Certification: a permit at the end of data entry.
- Directive 14: the architect self-inspects, skipping the DOB inspection queue.
- LPC FasTrack: a 10-business-day review for eligible interior work.
- BSA Pre-Determination: learn BSA's position in six weeks before funding a variance application.
- Community Board strategy: ask for more than you need; concede deliberately.
- OATH: appear with correction evidence instead of defaulting.
- DEP asbestos scope: survey the disturbed area, not the whole building.
- DOB timing: plan examination queues run shortest January to March.
- LPC calendar: one missed 30-day deadline costs a month.

None of this is secret. All of it is formal, documented and legal. It has simply been
expensive to know. MAST encodes it, scores it, and puts it in the hands of the people
doing the work, on site, while decisions are still open.

---

## Reading the Sea

Nothing about a live project is fully determined before it starts. MAST reads two
instruments and never confuses them.

- **rule_confidence** is the chart. How certain a legal requirement is. Codified law
  reads 1.0 and does not move.
- **voyage_confidence** is the sea state. How smooth this particular passage is likely
  to be, drawn from the archive: examiner history, backlog, site conditions. It changes
  with every job that finishes.

Three states follow from the sea state:

| Mode | voyage_confidence | Meaning |
|---|---|---|
| A | ≥ 0.80 | Charted water. Prepare the submission for review. |
| B | 0.40–0.79 | Variable. A specialist reads the conditions first. |
| C | < 0.40 | All hands. The operator takes the helm directly. |

Mode C is not a stop. It is the state that gets the most attention. When the system
reaches the edge of what it knows, it raises a HEP payload, an instrument reading for
the professional, and the professional sets the course.

---

## The Professional Judgment Standard

Every MAST output is **regulatory information**, not professional advice.

- mos surfaces what the code requires.
- MAST surfaces which formal professional tracks are available.
- A licensed RA, PE, expediter or attorney is the responsible professional on every engagement.
- MAST is their instrument, not their replacement.

This is an ethical position and a legal one. **NY Senate Bill S7263 (March 2026)** would
create liability for AI output that amounts to unauthorized practice of a licensed
profession, and a disclaimer alone does not waive it. Keeping a licensed professional
in the loop is load-bearing.

---

## Privacy Architecture

```
ENCRYPTED (MAST only, never in mos, never in the repo):
  Client name, contact, financial details, project description
  AES-256 Fernet, key in the OS Keychain (iOS Keychain on iPhone)
  NY SHIELD Act compliant, written security policy required

PUBLIC RECORD (mos layer, open, no PII):
  BBL, address, zoning district, building class, year built
  Sources: PLUTO v25v4, NYC Open Data, DOB NOW

SEPARATION INVARIANT:
  Public property data is NEVER stored alongside client PII.
  Two stores, two keys, two access paths.
```

---

## In the Field

The iPhone 17 Pro is the front of the system: a building question asked on site,
answered on site.

```
Professional on site → MAST field API → consult(bbl, filing type, flags)
                           ↓
             BBL resolution + PLUTO property flags
                           ↓
             mos: agency graph → permit pathways      (the chart)
                           ↓
             MAST: archive → pathway optimizer        (the passage)
                           ↓
             HEP when the sea state calls for a human
                           ↓
             ConsultResult → iPhone
```

Off the mesh, the app still applies the legal sequencing rules on the device. On the
mesh, heavier reasoning runs on the Mac Inference node. No query leaves the mesh and no
client data leaves the device.

---

## The Front Door

Three interactions from a question to a free, honest answer.

```
01  Where          address or BBL, borough
02  What           one tap: interior, façade, new unit, new building, small work, FISP
03  The building   era, landmark, flood zone ("Not sure" is a valid answer)
        ↓
    The pathway    agencies in legal order, days standard vs. with professional tracks,
                   open questions named rather than guessed
        ↓
    Ways forward   i.   keep the brief (free)
                   ii.  formal speed tracks this project may qualify for
                   iii. work with MAST: a licensed professional carries the file
```

`mast/web/index.html`, served at `/` by `mast/field/server.py`. One file, no external
assets, nothing loaded from a CDN.

**Design direction.** Domus for the editorial voice: a masthead, oversized grotesk
headlines, italic serif decks, numbered sections and thin rules on warm paper.
Archigram for the optimism: capsule controls, hard offset shadows, primary yellow, cyan
and red, halftone texture, and a walking pod. The agency sequence draws as a chain of
plug-in capsules, a small Walking City.

---

## Simulated Projects

Eight simulated NYC projects in `iphone-llm/sim/clients/` train and test the system:

| ID | Borough | Project | Complexity |
|----|---------|---------|------------|
| SIM-001 | Brooklyn | Rooftop deck (LPC historic) | Medium |
| SIM-002 | Queens | Basement ADU, flood zone blocker | High |
| SIM-003 | Manhattan | Sidewalk café (OATH first) | Medium |
| SIM-004 | Bronx | Ground-floor conversion (asbestos) | Medium |
| SIM-005 | Staten Island | New construction, FAR edge case | Low |
| SIM-006 | Manhattan | FISP Cycle 9 façade (LL11) | Low / Urgent |
| SIM-007 | Brooklyn | Gut renovation + solar | High |
| SIM-008 | Harlem | Community facility + BSA variance | Very High |

Real engagements follow the same schema: encrypted, local, never pushed to a remote.

---

## Where It Stands

Built:
- mos kernel: agencies, permit pathways, property trigger scanner
- Five domain skills (agency navigation, property triggers, unknown-agency discovery, premortem, intake)
- MAST platform: HEP escalation, flywheel archive (SQLite, optional Supabase sync), pathway optimizer, queue processor, daily pulse
- Field server with token auth, verified end to end
- iOS app scaffold: consult, results, settings, mesh health, offline fallback

Not yet:
- Real model weights. The MicroLLM structure is complete; the Llama 3.2 1B weight transfer waits on a Hugging Face token.
- CoreML export and on-device profiling (needs Xcode 16 and the iPhone).
- Mac Inference node setup, so the app can reach the server over Tailscale.
- Engagement history view in the app.
- Neo4j property graph (designed, not built).

---

## Open Core

`moswalk-kernel` is **Apache 2.0**: permanently free and open, with no version clauses
and no cloud lock-in. Fork it, run it, build your own practice on top. Keep the
attribution.

MAST is proprietary. The knowledge (agencies, pathways, sequencing rules) is always
open. The practice (professional tracks, timing, optimization, the archive) is what
MAST brings.

---

*MAST · built on mos · New York*
*Not legal advice. Not architectural advice. A licensed professional is always in the loop.*
