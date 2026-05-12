# MoswalkLLM — iPhone 17 Pro Production Roadmap
**Platform: moswalk | Target: production in 5 days**

Skip pre-training entirely. Use Llama 3.2 1B (Apache 2.0) as the base weight donor,
re-skin into MoswalkLLM's architecture, quantize, export to CoreML, and ship.
Multi-agent swarm inference splits the model across N iPhones via Apple Multipeer
Connectivity for near-zero latency at scale.

---

## Hardware Budget

| Resource | Available | Reserved (OS + App) | LLM Budget |
|---|---|---|---|
| RAM | 8 GB | ~2.5 GB | **~5.5 GB** |
| Storage | 2 TB | — | All model tiers |
| ANE | ~38 TOPS (A19 Pro) | — | primary compute |
| GPU | 6-core Apple GPU | — | prefill / fallback |
| P2P WiFi (swarm) | ~1 Gbps | — | inter-device activations |

**Runtime footprint (INT4, 1.1B, swarm-1 / single device):**

| Component | Size |
|---|---|
| Model weights INT4 | ~700 MB |
| KV cache (GQA, 4096 ctx) | ~256 MB |
| Activation buffers | ~128 MB |
| CoreML runtime | ~200 MB |
| **Total** | **~1.3 GB** |

---

## 5-Day Sprint

### Day 1 — Weight Acquisition + Architecture Alignment
- [ ] Download `meta-llama/Llama-3.2-1B` (HuggingFace, Apache 2.0)
- [ ] Map Llama 3.2 weights → `MoswalkLLM` state dict (`micro_model.py` is already compatible: RMSNorm, RoPE, GQA, SwiGLU)
- [ ] Run `python micro_model.py` smoke test with transplanted weights
- [ ] Validate perplexity on 500 WikiText-103 tokens (target < 12)

**Weight mapping script:** `python convert_llama.py --hf-model meta-llama/Llama-3.2-1B --out weights/moswalk_1b_fp16.pt`

### Day 2 — Quantization + Baseline Benchmark
- [ ] INT4 group-wise PTQ via `micro_quantize.py` (group_size=128)
- [ ] Measure PPL degradation (target: < 0.5 vs FP16)
- [ ] Benchmark on M-series Mac (proxy for A19 Pro ANE)
- [ ] Export CoreML FP16 baseline via `micro_export.py`

### Day 3 — CoreML INT4 + Swarm Sharding
- [ ] Apply CoreML INT4 palettization → `MoswalkLLM.mlpackage` (~700 MB)
- [ ] Profile on-device: latency, peak RAM, thermal (Instruments)
- [ ] Partition model into swarm shards: `python swarm_inference.py --build-shards --n-agents 4`
- [ ] Export per-shard `.mlpackage` files for pipeline-parallel deployment

### Day 4 — iOS App + Swarm Integration
- [ ] Integrate `MoswalkLLM.mlpackage` into Xcode project
- [ ] Wire Swift `MicroInference` wrapper (streaming `AsyncStream<String>`)
- [ ] Implement `SwarmSession` (Multipeer Connectivity coordinator + workers)
- [ ] Test single-device generation: target > 80 tok/s
- [ ] Test 4-device swarm: target > 200 tok/s combined throughput

### Day 5 — Production Hardening + Ship
- [ ] Stress test: 1 000 generations, measure p95 latency
- [ ] Thermal throttle detection + graceful degradation (drop to single-device)
- [ ] TestFlight build + internal QA
- [ ] App Store submission

---

## Swarm Inference Architecture

```
┌─────────────────── moswalk Swarm ──────────────────────────────────┐
│                                                                     │
│   iPhone A (Coordinator)          iPhone B / C / D (Workers)       │
│   ┌──────────────────────┐        ┌──────────────────────────┐     │
│   │  Tokenizer           │        │  Layer Shard  (layers    │     │
│   │  Embedding           │──act──▶│  6–11 / 12–17 / 18–23)  │     │
│   │  Layers 0–5          │◀─act──│  GQA + SWA + SwiGLU      │     │
│   │  LM Head + Sampler   │        │  Local KV cache          │     │
│   └──────────────────────┘        └──────────────────────────┘     │
│                                                                     │
│   Transport: Apple Multipeer Connectivity (P2P WiFi, ~1 Gbps)      │
│   Activation tensor per boundary: (1, 1, 2048) FP16 = 4 KB/token  │
│   Round-trip overhead per token: < 1 ms on local P2P WiFi         │
└─────────────────────────────────────────────────────────────────────┘
```

### Two Swarm Modes

**Mode A — Pipeline Parallel (multi-device, max throughput)**
- Each device owns a contiguous range of transformer layers
- Activations streamed token-by-token between devices
- Throughput scales with number of devices (batch pipelining)
- 4 devices × 6 layers each → ~3× throughput vs single device

**Mode B — Speculative Decoding (single or dual device)**
- **Draft agent**: MoswalkLLM-300M (4 layers, ~250 MB INT4) generates K=5 tokens speculatively
- **Verify agent**: MoswalkLLM-1B validates all K tokens in one parallel forward pass
- Accept/reject per token, resample on first rejection
- Expected speedup: **3–4×** token throughput at same quality

### Combined mode (4+ devices)
```
Device 1 (Coordinator): Draft model + layers 0-5  + verify head
Device 2: Layers 6-11
Device 3: Layers 12-17
Device 4: Layers 18-23
```

---

## Performance Targets

| Mode | Devices | Decode tok/s | First-token latency |
|---|---|---|---|
| Single device | 1 | > 80 | < 500 ms |
| Speculative (single) | 1 | > 240 | < 500 ms |
| Pipeline parallel | 2 | > 140 | < 600 ms |
| Pipeline parallel | 4 | > 280 | < 800 ms |
| Speculative + pipeline | 4 | > 400 | < 800 ms |

---

## Model Configuration

```python
MICRO_1B_CONFIG = {
    "vocab_size":       32_000,
    "context_length":   4_096,
    "emb_dim":          2_048,
    "n_heads":          16,        # query heads
    "n_kv_heads":       4,         # GQA 4:1
    "n_layers":         24,
    "ffn_hidden_dim":   5_504,     # SwiGLU
    "sliding_window":   512,
    "rope_theta":       500_000.0, # Llama 3.2 uses 500k
    "rms_norm_eps":     1e-5,
    "drop_rate":        0.0,
    "qkv_bias":         False,
    "tie_embeddings":   True,
}

MICRO_DRAFT_CONFIG = {            # speculative draft model
    **MICRO_1B_CONFIG,
    "n_layers":         4,
    "emb_dim":          1_024,
    "n_heads":          8,
    "n_kv_heads":       2,
    "ffn_hidden_dim":   2_752,
}
```

---

## Architecture vs Base GPT

| Feature | Base GPT (ch04) | MoswalkLLM |
|---|---|---|
| Attention | MHA | **GQA** (4× smaller KV cache) |
| Context | Full O(n²) | **SWA** window=512 |
| FFN | GELU | **SwiGLU** |
| Norm | LayerNorm | **RMSNorm** |
| Position | Learned abs | **RoPE** (θ=500k) |
| Inference | Single device | **Multi-agent swarm** |
| Decoding | Autoregressive | **Speculative** (3–4× faster) |

---

## File Structure

```
iphone-llm/
├── ROADMAP.md
├── micro_config.py          ← model configs (1B + draft)
├── micro_model.py           ← MoswalkLLM (GQA+SWA+SwiGLU+RMSNorm+RoPE)
├── micro_quantize.py        ← INT4 group-wise PTQ
├── micro_export.py          ← CoreML .mlpackage export
├── convert_llama.py         ← Llama 3.2 → MoswalkLLM weight map (Day 1)
├── swarm_config.py          ← swarm topology + shard assignments
├── swarm_worker.py          ← worker agent (owns layer shard + local KV)
├── swarm_coordinator.py     ← orchestrator (tokenizer + draft + sampler)
└── swarm_inference.py       ← unified engine (local sim + distributed)
```

---

## Key Dependencies

```
torch>=2.3
transformers>=4.45    # weight download + conversion
coremltools>=8.0      # CoreML export
sentencepiece         # tokenizer
```

iOS (Swift):
```
MultipeerConnectivity  # P2P swarm transport (built into iOS)
CoreML                 # model inference (built into iOS)
```
