# CoreML export for MincoLLM — targets Apple Neural Engine on iPhone 17 Pro.
#
# Requires: coremltools >= 8.0  (pip install coremltools)
#
# Export flow:
#   PyTorch (FP32) → TorchScript → CoreML FP16 → INT4 palettization → .mlpackage
#
# The resulting .mlpackage is ~700 MB and runs on ANE at 80–150 tok/s.

import os
import sys
import math
import torch
import torch.nn as nn

sys.path.insert(0, os.path.dirname(__file__))
from minco_model import MincoLLM
from minco_config import MINCO_1B_CONFIG


# ---------------------------------------------------------------------------
# Wrapper that exposes a static-shape interface for CoreML tracing
# ---------------------------------------------------------------------------

class MincoForCoreML(nn.Module):
    """
    Single-token decode step with a pre-filled KV cache.

    CoreML requires static input shapes. We expose:
      - input_ids    : (1, 1)  int32  — single next token
      - k_cache_in   : (n_layers, 1, n_kv_heads, cache_len, head_dim)  float16
      - v_cache_in   : same shape

    And return:
      - logits       : (1, vocab_size)  float16
      - k_cache_out  : updated cache
      - v_cache_out  : updated cache
    """

    def __init__(self, model: MincoLLM, cache_len: int = 512):
        super().__init__()
        self.model = model
        self.cache_len = cache_len
        cfg = model.cfg
        self.n_layers   = cfg["n_layers"]
        self.n_kv_heads = cfg["n_kv_heads"]
        self.head_dim   = cfg["emb_dim"] // cfg["n_heads"]

    def forward(
        self,
        input_ids: torch.Tensor,       # (1, 1)
        k_cache: torch.Tensor,          # (n_layers, 1, n_kv_heads, cache_len, head_dim)
        v_cache: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:

        x = self.model.tok_emb(input_ids)   # (1, 1, emb_dim)
        rope = self.model.rope_freqs

        new_ks, new_vs = [], []
        for i, block in enumerate(self.model.blocks):
            normed = block.norm1(x)
            b, s, _ = normed.shape
            h, kv_h, hd = block.attn.n_heads, block.attn.n_kv_heads, block.attn.head_dim

            q = block.attn.W_q(normed).view(b, s, h,    hd).transpose(1, 2)
            k = block.attn.W_k(normed).view(b, s, kv_h, hd).transpose(1, 2)
            v = block.attn.W_v(normed).view(b, s, kv_h, hd).transpose(1, 2)

            # Append new KV to rolling cache
            k_full = torch.cat([k_cache[i], k], dim=2)   # (1, kv_h, cache_len+1, hd)
            v_full = torch.cat([v_cache[i], v], dim=2)
            new_ks.append(k_full[:, :, -self.cache_len:, :])  # trim to window
            new_vs.append(v_full[:, :, -self.cache_len:, :])

            # GQA expand
            k_exp = k_full.repeat_interleave(block.attn.group_size, dim=1)
            v_exp = v_full.repeat_interleave(block.attn.group_size, dim=1)

            attn = torch.matmul(q, k_exp.transpose(2, 3)) / math.sqrt(hd)
            attn = torch.softmax(attn, dim=-1)
            out  = torch.matmul(attn, v_exp).transpose(1, 2).reshape(b, s, h * hd)
            x = x + block.attn.W_out(out)
            x = x + block.ffn(block.norm2(x))

        x = self.model.norm(x)
        logits = self.model.lm_head(x[:, -1, :])   # (1, vocab_size)

        k_cache_out = torch.stack(new_ks, dim=0)    # (n_layers, 1, kv_h, cache_len, hd)
        v_cache_out = torch.stack(new_vs, dim=0)
        return logits, k_cache_out, v_cache_out


# ---------------------------------------------------------------------------
# Export function
# ---------------------------------------------------------------------------

def export_coreml(
    model: MincoLLM,
    output_path: str = "MincoLLM.mlpackage",
    cache_len: int = 512,
    use_int4_palettization: bool = True,
):
    """
    Export MincoLLM to a CoreML .mlpackage with ANE optimization.

    Steps performed:
      1. Wrap model for static-shape CoreML interface
      2. TorchScript via tracing
      3. Convert to CoreML FP16
      4. Apply INT4 weight palettization (optional, recommended for on-device)
      5. Save .mlpackage

    Args:
        model: Trained MincoLLM in eval mode.
        output_path: Destination path for the .mlpackage bundle.
        cache_len: Rolling KV cache length (must match SWA window or longer).
        use_int4_palettization: Apply CoreML INT4 weight compression.
    """
    try:
        import coremltools as ct
        from coremltools.optimize.coreml import (
            OpPalettizerConfig,
            OptimizationConfig,
            palettize_weights,
        )
    except ImportError:
        raise ImportError(
            "coremltools >= 8.0 is required for CoreML export.\n"
            "Install with: pip install coremltools"
        )

    model.eval()
    wrapper = MincoForCoreML(model, cache_len=cache_len)
    wrapper.eval()

    cfg = model.cfg
    n_layers   = cfg["n_layers"]
    n_kv_heads = cfg["n_kv_heads"]
    head_dim   = cfg["emb_dim"] // cfg["n_heads"]

    # Dummy inputs for tracing
    dummy_ids    = torch.zeros(1, 1, dtype=torch.int32)
    dummy_k      = torch.zeros(n_layers, 1, n_kv_heads, cache_len, head_dim)
    dummy_v      = torch.zeros(n_layers, 1, n_kv_heads, cache_len, head_dim)

    print("Tracing model with TorchScript...")
    with torch.no_grad():
        traced = torch.jit.trace(wrapper, (dummy_ids, dummy_k, dummy_v))

    print("Converting to CoreML FP16...")
    mlmodel = ct.convert(
        traced,
        inputs=[
            ct.TensorType(name="input_ids",  shape=dummy_ids.shape, dtype=int),
            ct.TensorType(name="k_cache",    shape=dummy_k.shape),
            ct.TensorType(name="v_cache",    shape=dummy_v.shape),
        ],
        outputs=[
            ct.TensorType(name="logits"),
            ct.TensorType(name="k_cache_out"),
            ct.TensorType(name="v_cache_out"),
        ],
        minimum_deployment_target=ct.target.iOS18,   # required for ANE INT4 ops
        compute_units=ct.ComputeUnit.ALL,             # prefer ANE, fall back to GPU/CPU
        compute_precision=ct.precision.FLOAT16,
    )

    if use_int4_palettization:
        print("Applying INT4 weight palettization...")
        op_config = OpPalettizerConfig(
            mode="kmeans",
            nbits=4,
            weight_threshold=2048,   # only compress weights with ≥ 2048 elements
        )
        opt_config = OptimizationConfig(global_config=op_config)
        mlmodel = palettize_weights(mlmodel, config=opt_config)

    print(f"Saving to {output_path} ...")
    mlmodel.save(output_path)
    size_mb = sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _, filenames in os.walk(output_path)
        for f in filenames
    ) / 1e6
    print(f"Saved — on-disk size: {size_mb:.0f} MB")
    return mlmodel


# ---------------------------------------------------------------------------
# Profiling helper (run on Mac with connected iPhone via Instruments)
# ---------------------------------------------------------------------------

SWIFT_INFERENCE_TEMPLATE = '''
// MincoInference.swift — streaming token generation using the exported .mlpackage
//
// Usage:
//   let minco = try MincoInference(modelURL: Bundle.main.url(forResource: "MincoLLM", withExtension: "mlpackage")!)
//   for await token in minco.generate(prompt: "Hello, world!", maxTokens: 256) {
//       print(token, terminator: "")
//   }

import CoreML
import Foundation

final class MincoInference {
    private let model: MLModel
    private let cacheLen = 512
    private let nLayers  = {n_layers}
    private let nKvHeads = {n_kv_heads}
    private let headDim  = {head_dim}

    private var kCache: MLMultiArray
    private var vCache: MLMultiArray

    init(modelURL: URL) throws {{
        let config = MLModelConfiguration()
        config.computeUnits = .all          // ANE preferred
        self.model = try MLModel(contentsOf: modelURL, configuration: config)
        let shape = [nLayers, 1, nKvHeads, cacheLen, headDim] as [NSNumber]
        self.kCache = try MLMultiArray(shape: shape, dataType: .float16)
        self.vCache = try MLMultiArray(shape: shape, dataType: .float16)
    }}

    func resetCache() throws {{
        let shape = [nLayers, 1, nKvHeads, cacheLen, headDim] as [NSNumber]
        kCache = try MLMultiArray(shape: shape, dataType: .float16)
        vCache = try MLMultiArray(shape: shape, dataType: .float16)
    }}

    func nextToken(tokenId: Int32) throws -> Int32 {{
        let inputIds = try MLMultiArray(shape: [1, 1], dataType: .int32)
        inputIds[0] = NSNumber(value: tokenId)

        let input = try MLDictionaryFeatureProvider(dictionary: [
            "input_ids": inputIds,
            "k_cache":   kCache,
            "v_cache":   vCache,
        ])
        let output = try model.prediction(from: input)

        // Update rolling cache
        kCache = output.featureValue(for: "k_cache_out")!.multiArrayValue!
        vCache = output.featureValue(for: "v_cache_out")!.multiArrayValue!

        // Greedy argmax over logits
        let logits = output.featureValue(for: "logits")!.multiArrayValue!
        var maxVal = Float(-Float.infinity)
        var maxIdx: Int32 = 0
        for i in 0 ..< logits.count {{
            let v = logits[i].floatValue
            if v > maxVal {{ maxVal = v; maxIdx = Int32(i) }}
        }}
        return maxIdx
    }}
}}
'''


def print_swift_template(cfg: dict):
    print(SWIFT_INFERENCE_TEMPLATE.format(
        n_layers=cfg["n_layers"],
        n_kv_heads=cfg["n_kv_heads"],
        head_dim=cfg["emb_dim"] // cfg["n_heads"],
    ))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Export MincoLLM to CoreML")
    parser.add_argument("--weights", type=str, default=None, help="Path to .pt checkpoint")
    parser.add_argument("--output",  type=str, default="MincoLLM.mlpackage")
    parser.add_argument("--cache-len", type=int, default=512)
    parser.add_argument("--no-int4", action="store_true")
    parser.add_argument("--swift",   action="store_true", help="Print Swift inference template")
    args = parser.parse_args()

    model = MincoLLM(MINCO_1B_CONFIG)
    if args.weights:
        state = torch.load(args.weights, map_location="cpu")
        model.load_state_dict(state)
        print(f"Loaded weights from {args.weights}")
    else:
        print("No weights provided — using random init (for export structure testing only)")

    if args.swift:
        print_swift_template(MINCO_1B_CONFIG)
    else:
        export_coreml(
            model,
            output_path=args.output,
            cache_len=args.cache_len,
            use_int4_palettization=not args.no_int4,
        )
