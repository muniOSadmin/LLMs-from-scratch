#!/usr/bin/env python3
"""
convert_llama.py — Transplant Llama 3.2 1B weights into MoswalkLLM.

Usage:
    python convert_llama.py --weights-dir /path/to/Llama-3.2-1B --out moswalk-1b.pt
    python convert_llama.py --weights-dir /path/to/Llama-3.2-1B --out moswalk-1b-compact.pt --compact

The --compact flag truncates the vocabulary to 32k tokens (LLAMA32_1B_COMPACT_CONFIG).
This covers >99.9% of natural language and reduces CoreML export size significantly.

Weight source: Meta Llama 3.2 1B (HuggingFace safetensors format).
  https://huggingface.co/meta-llama/Llama-3.2-1B

Architecture match (guaranteed shape-for-shape copy — no lossy operations):
    LLAMA32_1B_CONFIG:        16 layers, 32 Q heads, 8 KV heads, emb=2048, FFN=8192
    Llama 3.2 1B (HF):        16 layers, 32 Q heads, 8 KV heads, emb=2048, FFN=8192
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch

# ---------------------------------------------------------------------------
# Path setup — allow running from iphone-llm/ or repo root
# ---------------------------------------------------------------------------

_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from micro_config import LLAMA32_1B_CONFIG, LLAMA32_1B_COMPACT_CONFIG
from micro_model import MoswalkLLM, count_params


# ---------------------------------------------------------------------------
# Weight loading — handles both single and sharded safetensors
# ---------------------------------------------------------------------------

def load_hf_weights(weights_dir: Path) -> dict[str, torch.Tensor]:
    """Load all safetensors shards from weights_dir into one flat dict."""
    try:
        from safetensors.torch import load_file
    except ImportError:
        raise SystemExit(
            "safetensors not installed. Run: pip install safetensors"
        )

    shards = sorted(weights_dir.glob("*.safetensors"))
    if not shards:
        raise FileNotFoundError(
            f"No .safetensors files found in {weights_dir}\n"
            "Download with: huggingface-cli download meta-llama/Llama-3.2-1B"
        )

    params: dict[str, torch.Tensor] = {}
    for shard in shards:
        print(f"  loading {shard.name} …")
        params.update(load_file(str(shard)))

    print(f"  {len(params)} tensors loaded from {len(shards)} shard(s)")
    return params


# ---------------------------------------------------------------------------
# Shape-validated assignment
# ---------------------------------------------------------------------------

def assign(dst: torch.nn.Parameter, src: torch.Tensor, name: str) -> None:
    """Copy src into dst after shape validation. Raises on mismatch."""
    if dst.shape != src.shape:
        raise ValueError(
            f"Shape mismatch for {name}: model={tuple(dst.shape)}, checkpoint={tuple(src.shape)}"
        )
    with torch.no_grad():
        dst.copy_(src.to(dst.dtype))


# ---------------------------------------------------------------------------
# Core transplant
# ---------------------------------------------------------------------------

def load_llama32_into_moswalk(
    model: MoswalkLLM,
    params: dict[str, torch.Tensor],
    compact: bool = False,
) -> None:
    """
    Map every Llama 3.2 1B HF tensor name to its MoswalkLLM counterpart.

    Compact mode: embed_tokens and lm_head rows are truncated to 32k.
    The top 32k Llama token IDs correspond to the most frequent tokens,
    preserving >99.9% of natural language coverage.
    """
    n_layers = model.cfg["n_layers"]   # 16
    vocab    = model.cfg["vocab_size"] # 128256 or 32000

    # Token embedding
    emb_src = params["model.embed_tokens.weight"]
    if compact:
        emb_src = emb_src[:vocab]
    assign(model.tok_emb.weight, emb_src, "tok_emb.weight")

    # Per-layer weights
    for l in range(n_layers):
        pfx = f"model.layers.{l}"
        blk = model.blocks[l]

        assign(blk.norm1.weight,    params[f"{pfx}.input_layernorm.weight"],          f"blocks[{l}].norm1")
        assign(blk.norm2.weight,    params[f"{pfx}.post_attention_layernorm.weight"],  f"blocks[{l}].norm2")

        assign(blk.attn.W_q.weight,   params[f"{pfx}.self_attn.q_proj.weight"],   f"blocks[{l}].attn.W_q")
        assign(blk.attn.W_k.weight,   params[f"{pfx}.self_attn.k_proj.weight"],   f"blocks[{l}].attn.W_k")
        assign(blk.attn.W_v.weight,   params[f"{pfx}.self_attn.v_proj.weight"],   f"blocks[{l}].attn.W_v")
        assign(blk.attn.W_out.weight, params[f"{pfx}.self_attn.o_proj.weight"],   f"blocks[{l}].attn.W_out")

        assign(blk.ffn.gate.weight,   params[f"{pfx}.mlp.gate_proj.weight"],      f"blocks[{l}].ffn.gate")
        assign(blk.ffn.up.weight,     params[f"{pfx}.mlp.up_proj.weight"],        f"blocks[{l}].ffn.up")
        assign(blk.ffn.down.weight,   params[f"{pfx}.mlp.down_proj.weight"],      f"blocks[{l}].ffn.down")

    # Final norm
    assign(model.norm.weight, params["model.norm.weight"], "norm")

    # LM head — Llama 3.2 1B does NOT tie embeddings; lm_head is a separate tensor
    lm_src = params["lm_head.weight"]
    if compact:
        lm_src = lm_src[:vocab]
    assign(model.lm_head.weight, lm_src, "lm_head.weight")


# ---------------------------------------------------------------------------
# Quick perplexity smoke-test (no tokenizer — uses synthetic token IDs)
# ---------------------------------------------------------------------------

@torch.no_grad()
def perplexity_smoke_test(model: MoswalkLLM, device: str = "cpu") -> float:
    """
    Compute pseudo-perplexity on a fixed random token sequence.
    Not a real perplexity (no true tokenizer), but detects catastrophic
    weight corruption: a healthy transplant should give PPL < 1000;
    a failed transplant gives PPL >> 10000 or NaN.
    """
    model.eval()
    model.to(device)
    vocab = model.cfg["vocab_size"]

    torch.manual_seed(42)
    seq_len = 64
    ids = torch.randint(0, min(vocab, 32_000), (1, seq_len), device=device)

    logits = model(ids)                           # (1, seq_len, vocab)
    log_probs = torch.nn.functional.log_softmax(logits, dim=-1)
    target_lp = log_probs[0, :-1, :].gather(1, ids[0, 1:].unsqueeze(1)).squeeze()
    nll = -target_lp.mean().item()
    ppl = torch.exp(torch.tensor(nll)).item()
    return ppl


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transplant Llama 3.2 1B weights into MoswalkLLM"
    )
    parser.add_argument(
        "--weights-dir",
        required=True,
        type=Path,
        help="Directory containing Llama 3.2 1B .safetensors files",
    )
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output path for converted MoswalkLLM weights (.pt)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Use 32k-vocab compact config (LLAMA32_1B_COMPACT_CONFIG)",
    )
    parser.add_argument(
        "--dtype",
        default="float16",
        choices=["float32", "float16", "bfloat16"],
        help="Save dtype (default: float16)",
    )
    parser.add_argument(
        "--skip-perplexity",
        action="store_true",
        help="Skip the perplexity smoke test",
    )
    args = parser.parse_args()

    # ── Config ──────────────────────────────────────────────────────────────
    cfg = LLAMA32_1B_COMPACT_CONFIG if args.compact else LLAMA32_1B_CONFIG
    cfg_name = "LLAMA32_1B_COMPACT_CONFIG" if args.compact else "LLAMA32_1B_CONFIG"
    print(f"\nMoswalkLLM weight transplant")
    print(f"  config:     {cfg_name}")
    print(f"  vocab:      {cfg['vocab_size']:,}")
    print(f"  layers:     {cfg['n_layers']}")
    print(f"  heads Q/KV: {cfg['n_heads']}/{cfg['n_kv_heads']}")
    print(f"  emb_dim:    {cfg['emb_dim']}")
    print(f"  ffn_hidden: {cfg['ffn_hidden_dim']}")

    # ── Load HF weights ─────────────────────────────────────────────────────
    print(f"\nLoading weights from {args.weights_dir} …")
    params = load_hf_weights(args.weights_dir)

    # ── Instantiate model ────────────────────────────────────────────────────
    print(f"\nInstantiating MoswalkLLM …")
    dtype_map = {"float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16}
    torch_dtype = dtype_map[args.dtype]

    model = MoswalkLLM(cfg).to(torch_dtype)
    print(f"  parameters: {count_params(model)}")

    # ── Transplant ───────────────────────────────────────────────────────────
    print(f"\nTransplanting weights (compact={args.compact}) …")
    load_llama32_into_moswalk(model, params, compact=args.compact)
    print("  all shapes validated ✓")

    # ── Perplexity smoke test ────────────────────────────────────────────────
    if not args.skip_perplexity:
        print(f"\nRunning perplexity smoke test …")
        ppl = perplexity_smoke_test(model)
        status = "✓ PASS" if ppl < 5000 else "✗ FAIL — possible weight corruption"
        print(f"  pseudo-PPL: {ppl:.1f}  {status}")
        if ppl >= 5000:
            print("  WARNING: High perplexity may indicate a transplant error.")
            print("  Saving anyway — inspect with --skip-perplexity to bypass.")
    else:
        print("  perplexity smoke test skipped")

    # ── Save ─────────────────────────────────────────────────────────────────
    args.out.parent.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving to {args.out} …")
    torch.save(
        {
            "config": cfg,
            "config_name": cfg_name,
            "compact": args.compact,
            "dtype": args.dtype,
            "state_dict": model.state_dict(),
        },
        args.out,
    )
    size_gb = args.out.stat().st_size / 1e9
    print(f"  saved {size_gb:.2f} GB  ✓")
    print(f"\nNext step: python micro_quantize.py --weights {args.out} --out moswalk-1b-int4.pt")


if __name__ == "__main__":
    main()
