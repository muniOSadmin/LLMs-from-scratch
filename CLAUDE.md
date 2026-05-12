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

## Current phase: Day 3 of 5-day sprint

| Day | Focus | Status |
|---|---|---|
| 1 | Llama 3.2 1B weight transplant → MicroLLM | pending `convert_llama.py` |
| 2 | INT4 quantization + perplexity validation | `micro_quantize.py` done |
| 3 | CoreML export + swarm sharding | `micro_export.py` done; swarm in progress |
| 4 | iOS app + swarm integration | pending |
| 5 | Production hardening + TestFlight | pending |

---

## iphone-llm/ file inventory

```
iphone-llm/
├── ROADMAP.md           ← 5-day sprint + swarm architecture
├── agencies.yaml        ← 139 active NYC orgs (deterministic foundation)
├── micro_config.py      ← MICRO_1B_CONFIG + MICRO_DRAFT_CONFIG
├── micro_model.py       ← MicroLLM (GQA+SWA+SwiGLU+RMSNorm+RoPE)
├── micro_quantize.py    ← INT4 group-wise PTQ + QuantizedLinear
├── micro_export.py      ← CoreML .mlpackage + Swift inference template
├── swarm_config.py      ← SwarmConfig, ShardConfig, 4 topology factories
├── swarm_worker.py      ← SwarmWorker, LocalTransport, TcpTransport
├── swarm_coordinator.py ← IN PROGRESS
└── swarm_inference.py   ← PENDING
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
- Do not assume `confidence=1.0` on any pattern — Local Laws change sequencing
- Do not assume agencies are parallel by default — check `sequential_after`
- Do not train MicroLLM from scratch — transplant Llama 3.2 1B weights (Day 1)
- Do not push sensitive data (property owner PII, client BBLs) to remote

---

## Next action for this session

Check `iphone-llm/swarm_coordinator.py` — implement the orchestrator with:
1. Token embedding + first-shard layers inline
2. Speculative decoding loop (draft model → verify model)
3. Pipeline mode: feed activation to next worker via transport
4. LM head + sampler on coordinator
