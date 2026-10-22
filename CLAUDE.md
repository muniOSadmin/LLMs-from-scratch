# moswalk — Claude Code Session Brief

## What this project is

**moswalk** is a sovereign, local-first AI consultation platform for NYC building and
regulatory work. It runs on an Apple hardware mesh with the iPhone 17 Pro as the
mobile command center. No cloud dependencies. All data stays local.

This repo (`LLMs-from-scratch`) is being extended with `iphone-llm/` — the MicroLLM
and multi-agent swarm inference engine that powers the moswalk mobile node.

---

## Hardware topology

| Node | Machine | Role | Model |
|---|---|---|---|
| Archival | MacBook Air 2014 (i7, 8GB) | BIS mirror, 2TB LaCie backup | None |
| Sifting | MacBook Air 2020 M1 (8GB) | Headless crawl, Firecrawl Docker | Phi-4 Mini 3.8B |
| Inference | Mac Desktop 2021 M1 (16GB) | Planner agent, zoning reasoning | Qwen2.5-Coder-14B Q4 |
| **Mobile** | **iPhone 17 Pro (8GB, 2TB)** | **UI + field retrieval** | **MicroLLM 1.1B INT4** |

Network: Tailscale mesh, VPN on Demand for iOS. All traffic encrypted, no public endpoints.

---

## Active branch

`claude/llm-iphone-17-pro-KuHhU` → PR #1

---

## Architecture principle (fat skills / thin harness)

```
FAT SKILLS  (.claude/skills/)          ← 90% of value; encode domain knowledge
    agency_pattern_navigator            ← two-engine composition, directed graph
    property_trigger_scanner            ← BBL → PLUTO flags → agency set
    t3_discovery                        ← unknown agency → provisional pattern
    premortem                           ← stress-test any plan before shipping

THIN HARNESS  (iphone-llm/*.py)        ← ~200 lines each; JSON in, text out
    swarm_coordinator.py                ← orchestrator + speculative decoding
    swarm_worker.py                     ← layer-shard worker agent
    swarm_config.py                     ← topology: pipeline / speculative / hybrid
    micro_model.py                      ← MicroLLM: GQA + SWA + SwiGLU + RMSNorm
    micro_quantize.py                   ← INT4 group-wise PTQ
    micro_export.py                     ← CoreML .mlpackage export

DETERMINISTIC FOUNDATION               ← never changes with model upgrades
    iphone-llm/agencies.yaml           ← 139 active NYC orgs (OTI, April 2026)
    Neo4j property graph               ← BBL + property flags
    DOB BIS / DOB NOW API
    PLUTO + ACRIS
```

**Push intelligence up into skills. Push execution down into deterministic tooling.
Keep the harness thin.**

---

## Current phase: Day 3 complete / Day 4 + Vault OS shipped

| Day | Focus | Status |
|---|---|---|
| 1 | Llama 3.2 1B weight transplant → MicroLLM | `convert_llama.py` written ✓ — run blocked on HF token |
| 2 | INT4 quantization + perplexity validation | `micro_quantize.py` done ✓ — run blocked on Day 1 weights |
| 3 | CoreML export + swarm sharding | all code done ✓ — 40/40 smoke tests passing |
| 3+ | Vault OS (queue/pulse/constitution) | `queue_processor.py` + `pulse.py` + `MOSWALK.md` ✓ |
| 4 | iOS app + swarm integration | pending |
| 5 | Production hardening + TestFlight | pending |

## Vault OS — how to use it

Drop a file in `pantocraft/queue/` → run `python pantocraft/queue_processor.py` → output in `pantocraft/generated/`

```
CONSULT-3-00783-0001-A2.md    → full field consultation (bbl/address/flags in body)
RESEARCH-adu-flood-zone.md    → regulatory research brief
PREMORTEM-brooklyn-a1.md      → premortem analysis (project/scope/concerns in body)
INTAKE-cyril-vault-os.md      → intelligence intake Q1–Q4 filter
```

Daily pulse (run on Inference node or manually):
```
python pantocraft/pulse.py    → reads session_log + HEP escalations → generated/briefings/
```

Update `pantocraft/vault/MOSWALK.md` → Active Engagements + Weekly Focus each session.

---

## iphone-llm/ file inventory

```
iphone-llm/
├── ROADMAP.md           ← 5-day sprint + swarm architecture
├── agencies.yaml        ← 139 active NYC orgs (OTI, April 2026) — deterministic foundation
├── convert_llama.py     ← Llama 3.2 1B HF → MoswalkLLM weight transplant (needs HF token)
├── micro_config.py      ← 5 configs: MICRO_1B, MICRO_TINY, MICRO_DRAFT, LLAMA32_1B, LLAMA32_1B_COMPACT
├── micro_model.py       ← MoswalkLLM (GQA+SWA+SwiGLU+RMSNorm+RoPE)
├── micro_quantize.py    ← INT4 group-wise PTQ + QuantizedLinear
├── micro_export.py      ← CoreML .mlpackage + Swift inference template
├── swarm_config.py      ← SwarmConfig, ShardConfig, 4 topology factories
├── swarm_worker.py      ← SwarmWorker, LocalTransport, TcpTransport
├── swarm_coordinator.py ← pipeline + speculative decoding orchestrator ✓
├── swarm_inference.py   ← unified entry point: from_checkpoint, from_random, CLI ✓
└── sim/                 ← 8 NYC client simulation scenarios

moswalk-kernel/
├── agencies/
│   ├── agencies.yaml         ← primary copy (fallback: iphone-llm/agencies.yaml)
│   ├── agency_navigator.py   ← two-engine resolver + inject_before ordering ✓
│   └── educational.py        ← plain-text agency education (11 agencies) ✓
├── compliance/
│   └── permit_pathways.yaml  ← 8 pathway types, conditions normalized ✓
└── property/
    └── trigger_scanner.py    ← PLUTO v25v4 → TriggerResult (LandmkFlag fixed) ✓

pantocraft/
├── agentic/session_log.py    ← private append-only JSONL log, chmod 600 ✓
├── agentic/hep.py            ← HEP v1: Mode A/B/C, tier 1/2/3, hard-stop list, SLA ✓
├── archive/flywheel.py       ← SQLite job archive: voyage_confidence, objection history ✓
├── prompts/intake_pipeline.py ← 8 Claude API prompt templates (address→brief) ✓
├── field/mobile_api.py       ← FieldAPI, kernel wired, TOON output ✓
├── vault/MOSWALK.md          ← business constitution (read by every workflow) ✓
├── queue_processor.py        ← QUEUE watcher: CONSULT/RESEARCH/PREMORTEM/INTAKE ✓
├── pulse.py                  ← daily engagement pulse (session_log + HEP scan) ✓
├── queue/                    ← drop request files here (gitignored contents)
├── generated/                ← outputs land here (gitignored contents)
├── inference/pathway_optimizer.py
└── intake/client_intake.py   ← encrypted client PII, NY SHIELD Act compliant ✓

.claude/skills/               ← 5/5 complete ✓
├── agency_pattern_navigator.md
├── property_trigger_scanner.md
├── t3_discovery.md
├── premortem.md
└── intelligence_intake.md    ← repeatable process for article/PDF influxes

tests/
└── test_smoke.py             ← 40/40 passing ✓
```

---

## Key agency registry facts (from agencies.yaml)

- DOT is registered as **NYC DOT** — use `NYC DOT` or `NYC_DOT` as the code
- EDC is **NYCEDC** in the registry — not `EDC`
- HCR (rent regulation) is **NYS-level**, not in NYC registry → separate T3 surface
- ECB violations are heard by **OATH** (reports to Chief Counsel to the Mayor)
- DOB and LPC both report to **Deputy Mayor for Housing and Planning**
- DEP, DOT, FDNY report to **Deputy Mayor for Operations** — different escalation chain
- BSA has no `reports_to` in the org chart — it is quasi-judicial

---

## What NOT to do

- Do not hardcode agency codes in Python — reference `agencies.yaml`
- Do not conflate rule_confidence (the chart) with voyage_confidence (the sea state)
- Do not treat Mode C as a stop — it is the highest-attention navigation state; the operator sets the course
- Do not assume agencies are parallel by default — check `sequential_after`
- Do not train MicroLLM from scratch — transplant Llama 3.2 1B weights (Day 1)
- Do not push sensitive data (property owner PII, client BBLs) to remote
- Do not load all skills simultaneously — trigger-specific lazy loading only (5 skills max active)
- Do not ignore session quality degradation mid-session: if Claude stops following
  rules without explanation, start a fresh session (token inflation is a known issue
  in Claude Code; long sessions dilute CLAUDE.md instructions silently)

---

## Blocked on (external — no code action possible)

- **HuggingFace token + local storage**: needed to run `convert_llama.py` and
  validate real weights. All downstream Day 1-2 items (quant, PPL, CoreML) unblock
  once this is resolved.
- **Mac with Xcode 16**: needed for CoreML `.mlpackage` export and on-device profiling.
- **iPhone 17 Pro hardware**: needed for on-device latency / thermal tests.

## Next session — Day 4

SwiftUI iOS app scaffold:
1. `iphone-llm/ios/MoswalkApp.swift` — BBL input, project type picker
2. `iphone-llm/ios/MicroInference.swift` — CoreML wrapper (`AsyncStream<String>`)
3. `iphone-llm/ios/SwarmSession.swift` — MultipeerConnectivity coordinator
4. Wire `FieldAPI` → SwiftUI (Python ↔ Swift bridge or full Swift port)
