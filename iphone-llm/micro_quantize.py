# INT4 group-wise post-training quantization for MoswalkLLM.
#
# Strategy:
#   - Weights: INT4, group_size=128 (one scale + zero_point per group)
#   - Activations: FP16 (dequantize weights before matmul)
#   - KV cache: FP16 (quality-sensitive)
#
# This gives ~4× compression vs FP16, targeting ~700 MB on-device.

import torch
import torch.nn as nn
from dataclasses import dataclass
from typing import Optional


@dataclass
class QuantConfig:
    group_size: int = 128   # weights per quantization group
    bits: int = 4           # 4-bit weights (0–15)
    symmetric: bool = False # asymmetric is slightly better for LLMs


# ---------------------------------------------------------------------------
# Core quantization primitives
# ---------------------------------------------------------------------------

def quantize_tensor(
    w: torch.Tensor,
    cfg: QuantConfig,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """
    Quantize a 2-D weight matrix to INT4 (stored as uint8, packed 2-per-byte).

    Returns:
        q_w     : (rows, cols//2)  uint8 — packed INT4 (two weights per byte)
        scales  : (rows, n_groups) float16
        zeros   : (rows, n_groups) float16  — zero points
    """
    assert w.dim() == 2, "Only 2-D weight matrices are supported"
    rows, cols = w.shape
    gs = cfg.group_size
    assert cols % gs == 0, f"cols ({cols}) must be divisible by group_size ({gs})"
    n_groups = cols // gs

    w = w.float()
    w_groups = w.view(rows, n_groups, gs)       # (rows, n_groups, gs)

    if cfg.symmetric:
        max_abs = w_groups.abs().amax(dim=-1, keepdim=True)  # (rows, n_groups, 1)
        scales = max_abs / 7.0                                # INT4 range [-8, 7] → use [-7, 7]
        zeros = torch.zeros_like(scales)
        q = (w_groups / scales.clamp(min=1e-8)).round().clamp(-8, 7) + 8  # shift to [0, 15]
    else:
        w_min = w_groups.amin(dim=-1, keepdim=True)
        w_max = w_groups.amax(dim=-1, keepdim=True)
        scales = (w_max - w_min) / 15.0
        zeros = w_min
        q = ((w_groups - zeros) / scales.clamp(min=1e-8)).round().clamp(0, 15)

    q = q.to(torch.uint8).view(rows, n_groups, gs)   # (rows, n_groups, gs)
    scales = scales.squeeze(-1).to(torch.float16)     # (rows, n_groups)
    zeros  = zeros.squeeze(-1).to(torch.float16)

    # Pack two INT4 values into one uint8 byte
    q_flat = q.view(rows, -1)          # (rows, n_groups*gs) == (rows, cols)
    lo = q_flat[:, 0::2]               # even indices
    hi = q_flat[:, 1::2]               # odd indices
    q_packed = (lo | (hi << 4)).to(torch.uint8)  # (rows, cols//2)

    return q_packed, scales, zeros


def dequantize_tensor(
    q_packed: torch.Tensor,
    scales: torch.Tensor,
    zeros: torch.Tensor,
    cfg: QuantConfig,
    out_dtype: torch.dtype = torch.float16,
) -> torch.Tensor:
    """Reconstruct FP16 weights from packed INT4."""
    rows, half_cols = q_packed.shape
    cols = half_cols * 2
    gs = cfg.group_size
    n_groups = cols // gs

    lo = (q_packed & 0x0F).to(torch.float32)          # (rows, cols//2)
    hi = ((q_packed >> 4) & 0x0F).to(torch.float32)

    q_flat = torch.empty(rows, cols, dtype=torch.float32, device=q_packed.device)
    q_flat[:, 0::2] = lo
    q_flat[:, 1::2] = hi

    q_groups = q_flat.view(rows, n_groups, gs)
    s = scales.to(torch.float32).unsqueeze(-1)          # (rows, n_groups, 1)
    z = zeros.to(torch.float32).unsqueeze(-1)
    w = q_groups * s + z
    return w.view(rows, cols).to(out_dtype)


# ---------------------------------------------------------------------------
# Quantized Linear layer
# ---------------------------------------------------------------------------

class QuantizedLinear(nn.Module):
    """Drop-in replacement for nn.Linear with INT4 weights."""

    def __init__(
        self,
        in_features: int,
        out_features: int,
        bias: bool = False,
        q_cfg: Optional[QuantConfig] = None,
    ):
        super().__init__()
        self.in_features  = in_features
        self.out_features = out_features
        self.q_cfg = q_cfg or QuantConfig()

        gs = self.q_cfg.group_size
        n_groups = in_features // gs
        half_in = in_features // 2

        # Packed INT4 weights: (out_features, in_features // 2)
        self.register_buffer("q_weight", torch.zeros(out_features, half_in, dtype=torch.uint8))
        self.register_buffer("scales",   torch.ones(out_features, n_groups, dtype=torch.float16))
        self.register_buffer("zeros",    torch.zeros(out_features, n_groups, dtype=torch.float16))

        if bias:
            self.bias = nn.Parameter(torch.zeros(out_features))
        else:
            self.bias = None

    @classmethod
    def from_linear(cls, linear: nn.Linear, q_cfg: Optional[QuantConfig] = None) -> "QuantizedLinear":
        cfg = q_cfg or QuantConfig()
        ql = cls(linear.in_features, linear.out_features, bias=linear.bias is not None, q_cfg=cfg)
        q_packed, scales, zeros = quantize_tensor(linear.weight.data, cfg)
        ql.q_weight.copy_(q_packed)
        ql.scales.copy_(scales)
        ql.zeros.copy_(zeros)
        if linear.bias is not None:
            ql.bias = nn.Parameter(linear.bias.data.clone())
        return ql

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        w = dequantize_tensor(self.q_weight, self.scales, self.zeros, self.q_cfg, out_dtype=x.dtype)
        return nn.functional.linear(x, w, self.bias)

    def extra_repr(self) -> str:
        return (f"in={self.in_features}, out={self.out_features}, "
                f"bits={self.q_cfg.bits}, group_size={self.q_cfg.group_size}")


# ---------------------------------------------------------------------------
# Model-level quantization
# ---------------------------------------------------------------------------

def quantize_model(model: nn.Module, q_cfg: Optional[QuantConfig] = None) -> nn.Module:
    """
    Replace all nn.Linear layers (except lm_head / embeddings) with QuantizedLinear.
    Operates in-place and returns the model.
    """
    cfg = q_cfg or QuantConfig()
    for name, module in list(model.named_modules()):
        parent_name, _, child_name = name.rpartition(".")
        if not isinstance(module, nn.Linear):
            continue
        # Skip the LM head — tied to embedding, quantizing it hurts vocab quality
        if child_name == "lm_head" or name.endswith("lm_head"):
            continue
        parent = model.get_submodule(parent_name) if parent_name else model
        ql = QuantizedLinear.from_linear(module, cfg)
        setattr(parent, child_name, ql)
    return model


# ---------------------------------------------------------------------------
# Quantization quality evaluation
# ---------------------------------------------------------------------------

@torch.no_grad()
def measure_quantization_error(linear: nn.Linear, q_cfg: Optional[QuantConfig] = None) -> dict:
    """Return per-layer error statistics for a single nn.Linear."""
    cfg = q_cfg or QuantConfig()
    w = linear.weight.data.float()
    q_packed, scales, zeros = quantize_tensor(w, cfg)
    w_hat = dequantize_tensor(q_packed, scales, zeros, cfg, out_dtype=torch.float32)
    err = (w - w_hat).abs()
    return {
        "mean_abs_error": err.mean().item(),
        "max_abs_error":  err.max().item(),
        "rel_error":      (err / w.abs().clamp(min=1e-8)).mean().item(),
    }


# ---------------------------------------------------------------------------
# Memory footprint helper
# ---------------------------------------------------------------------------

def quantized_size_bytes(model: nn.Module) -> int:
    total = 0
    for module in model.modules():
        if isinstance(module, QuantizedLinear):
            total += module.q_weight.numel()       # 1 byte per 2 weights (packed INT4)
            total += module.scales.numel() * 2     # FP16
            total += module.zeros.numel()  * 2     # FP16
        elif isinstance(module, nn.Parameter):
            total += module.numel() * module.element_size()
    return total


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from micro_model import MoswalkLLM, count_params
    from micro_config import MICRO_TINY_CONFIG

    print("=== Quantization smoke test ===")
    cfg = QuantConfig(group_size=64, bits=4)

    # Round-trip test on a single linear layer
    lin = nn.Linear(256, 512, bias=False)
    nn.init.normal_(lin.weight)
    q_packed, scales, zeros = quantize_tensor(lin.weight.data, cfg)
    w_hat = dequantize_tensor(q_packed, scales, zeros, cfg)
    err = (lin.weight.data - w_hat).abs()
    print(f"Round-trip mean abs error: {err.mean():.6f} (max: {err.max():.6f})")

    # Full model quantization
    model = MoswalkLLM(MICRO_TINY_CONFIG)
    print(f"\nBefore quantization: {count_params(model)} params")
    fp16_bytes = sum(p.numel() * 2 for p in model.parameters())
    print(f"FP16 size: {fp16_bytes / 1e6:.1f} MB")

    model = quantize_model(model, cfg)
    q_bytes = quantized_size_bytes(model)
    print(f"INT4 size: {q_bytes / 1e6:.1f} MB  ({fp16_bytes / q_bytes:.1f}× compression)")

    # Verify forward pass still works
    x = torch.randint(0, MICRO_TINY_CONFIG["vocab_size"], (1, 8))
    out = model(x)
    assert out.shape == (1, 8, MICRO_TINY_CONFIG["vocab_size"])
    print("Quantized forward pass OK")
