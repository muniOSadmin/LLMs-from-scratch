# pantocraft //

**Sovereign AI for NYC building professionals.**
Navigate the municipal landscape with deftness, precision, and total privacy.

---

## Two Layers. One Symbiosis.

```
┌─────────────────────────────────────────────────────────────────┐
│                     pantocraft //                               │
│                                                                 │
│  Professional intelligence layer — PROPRIETARY                  │
│  Real clients · Edge weights · Pathway optimization             │
│  Encrypted intake · Field API · Timing strategy                 │
│  Licensed-professional-in-the-loop requirement                  │
│                                                                 │
│  pantocraft/                                                    │
│    intake/client_intake.py   ← AES encrypted, SHIELD compliant │
│    inference/edge_weights.yaml ← professional tracks + risks    │
│    inference/pathway_optimizer.py ← fastest legal route         │
│    field/mobile_api.py       ← iPhone umbilical cord            │
├─────────────────────────────────────────────────────────────────┤
│                     moswalk-kernel                              │
│                                                                 │
│  Open-source core — APACHE 2.0 — free to fork, self-host       │
│  Deterministic · Transparent · Canonical                        │
│  Anyone can use it. No lock-in. No cloud required.              │
│                                                                 │
│  moswalk-kernel/                                                │
│    agencies/agencies.yaml     ← 139 NYC orgs (OTI registry)    │
│    compliance/permit_pathways.yaml ← canonical agency sequences │
│    property/bbl_resolver.py   ← offline address → BBL          │
│    sim/                       ← 8 simulated client projects     │
└─────────────────────────────────────────────────────────────────┘
                              │
                    iPhone 17 Pro (ANE)
                    MoswalkLLM 1.1B INT4
                    Tailscale mesh
                    Always sovereign
```

---

## What moswalk-kernel Knows

The law. Exactly what the law says.

- Which agencies apply to which project types
- Mandatory sequences (LPC before DOB for landmark exteriors)
- Blocking conditions (flood zone = ADU ineligible)
- All 139 active NYC agencies, their reporting chains, their portals
- Canonical DOB filing types: NB, A1, A2, A3, TR6, PA

This is public knowledge, codified and structured.
**Anyone can fork it. Anyone can build on it.**

---

## What pantocraft // Knows

How the system actually works.

- LPC XCNE: 3-5 days instead of 45. Most architects don't know this track exists.
- DOB Professional Certification: permit at end of data entry — effectively immediate.
- Directive 14: architect self-inspects, eliminates DOB inspection queue.
- LPC FasTrack: 10-business-day guarantee for interior work.
- BSA Pre-Determination: get BSA's position in 6 weeks before spending $50K on a variance app.
- Pre-negotiating Community Board: file for more than you need; concede strategically.
- OATH default judgment avoidance: appear with correction evidence, reduce fine by 60-80%.
- DEP asbestos scope containment: survey only the disturbed area, not the whole building.
- DOB Q1 filing optimization: plan examination queues are shortest January-March.
- LPC hearing calendar targeting: missing the 30-day deadline = 30 days lost.

**None of this is secret. All of it is formal, documented, legal.**
The knowledge is just expensive. Expediters charge $3,000-$15,000/engagement to apply it.
pantocraft // encodes it, scores it, and delivers it in the field.

---

## The Professional Judgment Standard

Every pantocraft // output is **regulatory information retrieval**, not professional advice.

- The kernel surfaces what the code requires.
- pantocraft // surfaces what formal professional tracks are available.
- A licensed RA, PE, expediter, or attorney is the responsible professional on every engagement.
- pantocraft // is their tool, not their replacement.

This framing is not just ethical — it is legally necessary.
**NY Senate Bill S7263 (March 2026):** pending legislation that would create liability for
AI that provides outputs constituting unauthorized practice of a licensed profession.
A disclaimer alone does not waive liability under S7263.
The licensed-professional-in-the-loop requirement is load-bearing.

---

## Privacy Architecture

```
ENCRYPTED (pantocraft // only — never in kernel, never in repo):
  Client name, contact, financial details, project description
  Stored: AES-256 Fernet, key in OS Keychain (iOS Keychain on iPhone)
  NY SHIELD Act compliant — written security policy required

PUBLIC RECORD (kernel layer — open, no PII):
  BBL, address, zoning district, building class, year built
  Source: PLUTO v25v4, NYC Open Data, DOB NOW
  Safe to log, safe to route through kernel

SEPARATION INVARIANT:
  Public property data (BBL, PLUTO) is NEVER stored in the same
  data store as client PII. Two stores, two keys, two access paths.
```

---

## Mobile Command Center

The iPhone 17 Pro is the **umbilical cord**.

```
Field professional → pantocraft // field_api → quick_consult(bbl, question)
                          ↓
              BBL resolution (python-geosupport, offline)
                          ↓
              PLUTO property data (local SQLite cache)
                          ↓
          moswalk-kernel: agency_graph → permit_pathways
                          ↓
       pantocraft //: edge_weights → pathway_optimizer
                          ↓
          MoswalkLLM 1.1B INT4 → generate(prompt)
                          ↓
              ConsultResult → iPhone display
```

Everything runs on-device. Tailscale mesh activates when Wi-Fi is available
to offload heavier reasoning to Mac Desktop (Qwen2.5-Coder-14B Q4).
No query leaves the mesh. No client data leaves the device.

---

## Simulated Clients (Test Layer)

8 simulated NYC client projects in `iphone-llm/sim/clients/`:

| ID | Borough | Project | Complexity |
|----|---------|---------|------------|
| SIM-001 | Brooklyn | Rooftop deck (LPC historic) | Medium |
| SIM-002 | Queens | Basement ADU — flood zone blocker | High |
| SIM-003 | Manhattan | Sidewalk café (OATH first) | Medium |
| SIM-004 | Bronx | Ground-floor conversion (asbestos) | Medium |
| SIM-005 | Staten Island | New construction — FAR edge case | Low |
| SIM-006 | Manhattan | FISP Cycle 9 façade (LL11) | Low/Urgent |
| SIM-007 | Brooklyn | Gut reno + solar — most complex | High |
| SIM-008 | Harlem | Community facility + BSA variance | Very High |

These are the training and validation layer for pantocraft //'s inference.
Real client engagements under pantocraft // follow the same schema —
encrypted, local, never pushed to remote.

---

## What's Missing (Be Honest)

- `convert_llama.py` — Day 1 debt. No real model weights yet. All inference is structure, not meaning.
- `property_trigger_scanner` — the BBL → agency flag scan. Pending.
- `agency_pattern_navigator` — the skill that composes multi-agency pathways. Pending.
- iOS app — SwiftUI, MultipeerConnectivity shim. Day 4 work, not started.
- Neo4j BBL graph — defined, not built.
- Perplexity baseline — quantization validated structurally, not empirically.
- No tests, no CI.

---

## Open Source Commitment

`moswalk-kernel` is **Apache 2.0** — permanently free, permanently open.
No version clauses, no future license changes, no cloud lock-in.
Fork it. Run it. Build your own professional layer on top.
The only thing we ask: don't remove the attribution.

`pantocraft //` is proprietary. It is the service layer, not the knowledge layer.
The knowledge — agencies, pathways, sequencing rules — is always open.
The professional intelligence — edge weights, timing, optimization — is how we earn the fee.

---

*pantocraft // · Built on moswalk-kernel · Sovereign AI · NYC*
*Not legal advice. Not architectural advice. A licensed professional is always in the loop.*
