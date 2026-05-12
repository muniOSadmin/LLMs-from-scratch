# MincoLLM — iPhone 17 Pro Roadmap

A mini causal LLM designed to run natively on iPhone 17 Pro (8 GB RAM, 2 TB storage)
using the Apple Neural Engine (ANE) via CoreML.

---

## 1. Hardware Budget

| Resource | Available | Reserved (OS + App) | LLM Budget |
|---|---|---|---|
| RAM | 8 GB | ~2.5 GB | **~5.5 GB** |
| Storage | 2 TB | — | Multiple model tiers |
| ANE | ~38 TOPS (A19 Pro) | — | primary compute |
| GPU | 6-core Apple GPU | — | fallback / prefill |

**RAM breakdown at inference (1.3B INT4 model):**

| Component | Size |
|---|---|
| Model weights (INT4) | ~700 MB |
| KV cache (4096 ctx, GQA) | ~256 MB |
| Activation buffers | ~128 MB |
| CoreML runtime overhead | ~200 MB |
| **Total** | **~1.3 GB** |

Leaves 4.2 GB free for the iOS app, UI, and other processes. Very comfortable.

---

## 2. Target Specs

| Property | Value |
|---|---|
| Parameters | **~1.1 B** |
| Architecture | Decoder-only Transformer |
| Attention | **Grouped-Query Attention (GQA)** — 16 Q heads / 4 KV heads |
| Context | **4096 tokens** with **Sliding Window Attention (SWA)** (window=512) |
| FFN | **SwiGLU** (gated linear unit) |
| Normalization | **RMSNorm** (no bias, faster on ANE) |
| Position encoding | **RoPE** (Rotary Position Embedding) |
| Quantization | **INT4** (group-wise, group_size=128) for weights; FP16 activations |
| Target throughput | **80–150 tokens/s** on ANE |
| Vocab | 32 000 (BPE, tiktoken-compatible) |

---

## 3. Model Configuration

```python
MINCO_1B_CONFIG = {
    "vocab_size":       32_000,
    "context_length":   4_096,
    "emb_dim":          2_048,
    "n_heads":          16,       # query heads
    "n_kv_heads":       4,        # key/value heads (GQA 4:1)
    "n_layers":         24,
    "ffn_hidden_dim":   5_504,    # SwiGLU: 8/3 * emb_dim, rounded to multiple of 64
    "sliding_window":   512,      # SWA window size
    "rope_theta":       10_000.0,
    "rms_norm_eps":     1e-5,
    "drop_rate":        0.0,      # disabled at inference
    "qkv_bias":         False,
}
```

**Parameter count breakdown:**

| Component | Params |
|---|---|
| Token embedding | 65.5 M |
| Per layer (× 24) | ~44 M |
| — GQA (Q+K+V+out) | ~10.5 M |
| — SwiGLU FFN (gate+up+down) | ~33.6 M |
| — RMSNorm (×2) | ~8 K |
| LM head (tied weights) | 0 (shared with embedding) |
| **Total** | **~1.12 B** |

---

## 4. Architecture Innovations (vs base GPT in this repo)

| Feature | Base GPT (ch04) | MincoLLM |
|---|---|---|
| Attention | MHA | **GQA** (4× smaller KV cache) |
| Context handling | Full attention | **SWA** (O(n·w) vs O(n²)) |
| FFN activation | GELU | **SwiGLU** (~10% better perplexity) |
| Normalization | LayerNorm | **RMSNorm** (no mean subtract, ANE-friendly) |
| Position encoding | Learned absolute | **RoPE** (length generalisation) |
| Tied embeddings | No | **Yes** (saves 65.5 M params) |
| Quantization | FP32/FP16 | **INT4** group-wise |

---

## 5. Training Roadmap

### Phase 1 — Prototype (Weeks 1–4)
- [ ] Implement `MincoLLM` architecture (`minco_model.py`)
- [ ] Verify forward pass, parameter count, memory estimates
- [ ] Train tiny smoke-test run on Shakespeare / OpenWebText subset
- [ ] Validate INT4 quantization accuracy on toy model

### Phase 2 — Pre-training (Weeks 5–16)
- [ ] Dataset: FineWeb-Edu (10B token subset, Apache 2.0)
- [ ] Tokenizer: train BPE with vocab_size=32 000 using `tiktoken` or `sentencepiece`
- [ ] Training hardware: 4× A100 80 GB (or equivalent cloud)
- [ ] Batch size: 2M tokens (gradient accumulation)
- [ ] Learning rate: cosine decay, peak 3e-4, warmup 2 000 steps
- [ ] Total tokens: ~100 B (Chinchilla-optimal for 1.1 B params)
- [ ] Mixed precision: BF16

### Phase 3 — Post-training (Weeks 17–20)
- [ ] Supervised fine-tuning (SFT) on instruction dataset (e.g. Alpaca-cleaned)
- [ ] Direct Preference Optimization (DPO) — lighter than RLHF, no reward model needed
- [ ] System prompt compression: short, fixed prefix cached on-device

### Phase 4 — Quantization & Export (Weeks 21–24)
- [ ] Apply INT4 group-wise quantization (`minco_quantize.py`)
- [ ] Measure perplexity degradation (target: < 0.5 PPL increase vs FP16)
- [ ] Export to CoreML via `coremltools` (`minco_export.py`)
- [ ] Profile on device: latency, memory, thermal
- [ ] Optimize for ANE: fuse ops, static shapes, `ct.ComputeUnit.ALL`

### Phase 5 — iOS Integration (Weeks 25–28)
- [ ] Package model as `.mlpackage`
- [ ] Build Swift inference wrapper (streaming tokens via `AsyncStream`)
- [ ] KV cache management in Swift (pre-allocate, ring-buffer for SWA)
- [ ] Implement on-device tokenizer (Swift port of BPE)
- [ ] UI: streaming chat interface

---

## 6. Quantization Strategy

```
FP16 weights  →  INT4 group-wise (group_size=128)
                 ├── scale per group (FP16)
                 └── zero_point per group (INT4)

Activations: FP16 throughout (ANE handles FP16 natively)
KV cache:    FP16 (quality-sensitive; can downgrade to INT8 if needed)
```

Expected model sizes:

| Precision | Size on disk | RAM at inference |
|---|---|---|
| FP32 | 4.5 GB | 4.5 GB |
| FP16 | 2.2 GB | 2.2 GB |
| INT8 | 1.1 GB | ~1.5 GB |
| **INT4** | **~700 MB** | **~1.3 GB** |

2 TB storage easily holds all tiers simultaneously for A/B testing.

---

## 7. Performance Targets

| Metric | Target | Notes |
|---|---|---|
| Prefill speed | > 500 tok/s | GPU-accelerated prompt processing |
| Decode speed | > 80 tok/s | ANE token-by-token generation |
| First-token latency | < 500 ms | for 256-token prompt |
| RAM at runtime | < 2 GB | leaves headroom for iOS |
| Model load time | < 3 s | from 2 TB NVMe |
| Perplexity (WikiText-103) | < 15 | quality bar |

---

## 8. File Structure

```
iphone-llm/
├── ROADMAP.md           ← this file
├── minco_config.py      ← model hyperparameters
├── minco_model.py       ← full model implementation (GQA + SWA + SwiGLU + RMSNorm + RoPE)
├── minco_quantize.py    ← INT4 group-wise quantization
├── minco_export.py      ← CoreML export via coremltools
└── minco_train.py       ← training loop (extends ch05 patterns)
```

---

## 9. Key Dependencies

```
torch>=2.3
coremltools>=8.0        # CoreML export
sentencepiece           # tokenizer training
datasets                # HuggingFace data loading
bitsandbytes            # INT4 quantization (training)
```

---

## 10. References

- GQA: `ch04/04_gqa/gpt_with_kv_gqa.py` (this repo)
- SWA: `ch04/06_swa/gpt_with_kv_swa.py` (this repo)
- MoE: `ch04/07_moe/gpt_with_kv_moe.py` (this repo, optional upgrade path)
- RoPE: Appendix D / Llama 3 reference (`pkg/llms_from_scratch/llama3.py`)
- CoreML docs: https://coremltools.readme.io
- FineWeb-Edu: HuggingFace `HuggingFaceFW/fineweb-edu`
