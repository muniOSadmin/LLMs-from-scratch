# MoswalkLLM — ~1.1B parameter causal LM for iPhone 17 Pro (ANE / CoreML)
#
# Architecture: GQA + SWA + SwiGLU + RMSNorm + RoPE + tied embeddings
# Designed to export cleanly to CoreML (static shapes, no dynamic control flow).

import math
import torch
import torch.nn as nn
import torch.nn.functional as F
from micro_config import MICRO_1B_CONFIG


# ---------------------------------------------------------------------------
# RMSNorm
# ---------------------------------------------------------------------------

class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-5):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        rms = x.pow(2).mean(dim=-1, keepdim=True).add(self.eps).sqrt()
        return self.weight * (x / rms)


# ---------------------------------------------------------------------------
# Rotary Position Embedding (RoPE)
# ---------------------------------------------------------------------------

def build_rope_freqs(head_dim: int, max_seq_len: int, theta: float = 10_000.0) -> torch.Tensor:
    """Returns (max_seq_len, head_dim/2, 2) cos/sin cache."""
    half = head_dim // 2
    freqs = 1.0 / (theta ** (torch.arange(0, half, dtype=torch.float32) / half))
    t = torch.arange(max_seq_len, dtype=torch.float32)
    freqs = torch.outer(t, freqs)               # (seq, half)
    return torch.stack([freqs.cos(), freqs.sin()], dim=-1)  # (seq, half, 2)


def apply_rope(x: torch.Tensor, freqs: torch.Tensor) -> torch.Tensor:
    """
    x: (batch, heads, seq, head_dim)
    freqs: (seq, head_dim/2, 2)  — cos/sin
    """
    b, h, s, d = x.shape
    half = d // 2
    x1 = x[..., :half]
    x2 = x[..., half:]
    cos = freqs[:s, :, 0].unsqueeze(0).unsqueeze(0)  # (1, 1, s, half)
    sin = freqs[:s, :, 1].unsqueeze(0).unsqueeze(0)
    rotated = torch.cat([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1)
    return rotated


# ---------------------------------------------------------------------------
# Grouped-Query Attention with SWA and KV cache
# ---------------------------------------------------------------------------

class MicroAttention(nn.Module):
    def __init__(self, cfg: dict):
        super().__init__()
        self.n_heads     = cfg["n_heads"]
        self.n_kv_heads  = cfg["n_kv_heads"]
        self.head_dim    = cfg["emb_dim"] // cfg["n_heads"]
        self.group_size  = self.n_heads // self.n_kv_heads
        self.window      = cfg["sliding_window"]
        d = cfg["emb_dim"]
        kv_dim = self.n_kv_heads * self.head_dim

        self.W_q   = nn.Linear(d, d,      bias=cfg["qkv_bias"])
        self.W_k   = nn.Linear(d, kv_dim, bias=cfg["qkv_bias"])
        self.W_v   = nn.Linear(d, kv_dim, bias=cfg["qkv_bias"])
        self.W_out = nn.Linear(d, d,      bias=False)

        # KV cache (populated during autoregressive decode)
        self.register_buffer("cache_k", None, persistent=False)
        self.register_buffer("cache_v", None, persistent=False)
        self._cache_pos = 0

    def forward(
        self,
        x: torch.Tensor,
        rope_freqs: torch.Tensor,
        use_cache: bool = False,
    ) -> torch.Tensor:
        b, s, _ = x.shape
        h, kv_h, hd = self.n_heads, self.n_kv_heads, self.head_dim

        q = self.W_q(x).view(b, s, h,    hd).transpose(1, 2)  # (b, h, s, hd)
        k = self.W_k(x).view(b, s, kv_h, hd).transpose(1, 2)
        v = self.W_v(x).view(b, s, kv_h, hd).transpose(1, 2)

        q = apply_rope(q, rope_freqs)
        k = apply_rope(k, rope_freqs)

        if use_cache:
            if self.cache_k is None:
                self.cache_k, self.cache_v = k, v
            else:
                self.cache_k = torch.cat([self.cache_k, k], dim=2)
                self.cache_v = torch.cat([self.cache_v, v], dim=2)
            k, v = self.cache_k, self.cache_v

        # Expand KV heads to match Q heads (GQA)
        k = k.repeat_interleave(self.group_size, dim=1)  # (b, h, seq_k, hd)
        v = v.repeat_interleave(self.group_size, dim=1)

        seq_k = k.shape[2]
        attn = torch.matmul(q, k.transpose(2, 3)) / math.sqrt(hd)  # (b, h, s, seq_k)

        # Causal mask
        causal = torch.ones(s, seq_k, dtype=torch.bool, device=x.device).tril(seq_k - s)
        causal = causal.unsqueeze(0).unsqueeze(0)

        # Sliding window mask (only attend to last `window` tokens)
        if self.window is not None:
            q_idx = torch.arange(seq_k - s, seq_k, device=x.device).unsqueeze(1)  # (s, 1)
            k_idx = torch.arange(seq_k, device=x.device).unsqueeze(0)              # (1, seq_k)
            swa_mask = (q_idx - k_idx) < self.window                               # (s, seq_k)
            swa_mask = swa_mask.unsqueeze(0).unsqueeze(0)
            causal = causal & swa_mask

        attn = attn.masked_fill(~causal, float("-inf"))
        attn = F.softmax(attn, dim=-1)
        out = torch.matmul(attn, v)                        # (b, h, s, hd)
        out = out.transpose(1, 2).reshape(b, s, h * hd)   # (b, s, d)
        return self.W_out(out)

    def reset_cache(self):
        self.cache_k = None
        self.cache_v = None
        self._cache_pos = 0


# ---------------------------------------------------------------------------
# SwiGLU Feed-Forward Network
# ---------------------------------------------------------------------------

class SwiGLU(nn.Module):
    """FFN with SwiGLU activation: output = (gate * SiLU(up)) projected down."""

    def __init__(self, emb_dim: int, hidden_dim: int):
        super().__init__()
        self.gate = nn.Linear(emb_dim, hidden_dim, bias=False)
        self.up   = nn.Linear(emb_dim, hidden_dim, bias=False)
        self.down = nn.Linear(hidden_dim, emb_dim, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.down(F.silu(self.gate(x)) * self.up(x))


# ---------------------------------------------------------------------------
# Transformer Block
# ---------------------------------------------------------------------------

class MicroBlock(nn.Module):
    def __init__(self, cfg: dict):
        super().__init__()
        self.norm1 = RMSNorm(cfg["emb_dim"], cfg["rms_norm_eps"])
        self.attn  = MicroAttention(cfg)
        self.norm2 = RMSNorm(cfg["emb_dim"], cfg["rms_norm_eps"])
        self.ffn   = SwiGLU(cfg["emb_dim"], cfg["ffn_hidden_dim"])

    def forward(self, x: torch.Tensor, rope_freqs: torch.Tensor, use_cache: bool = False):
        x = x + self.attn(self.norm1(x), rope_freqs, use_cache=use_cache)
        x = x + self.ffn(self.norm2(x))
        return x


# ---------------------------------------------------------------------------
# Full MoswalkLLM
# ---------------------------------------------------------------------------

class MoswalkLLM(nn.Module):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.tok_emb = nn.Embedding(cfg["vocab_size"], cfg["emb_dim"])
        self.blocks  = nn.ModuleList([MicroBlock(cfg) for _ in range(cfg["n_layers"])])
        self.norm    = RMSNorm(cfg["emb_dim"], cfg["rms_norm_eps"])
        self.lm_head = nn.Linear(cfg["emb_dim"], cfg["vocab_size"], bias=False)

        if cfg.get("tie_embeddings", True):
            self.lm_head.weight = self.tok_emb.weight

        head_dim = cfg["emb_dim"] // cfg["n_heads"]
        self.register_buffer(
            "rope_freqs",
            build_rope_freqs(head_dim, cfg["context_length"], cfg["rope_theta"]),
            persistent=False,
        )
        self._init_weights()

    def _init_weights(self):
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.normal_(module.weight, mean=0.0, std=0.02)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
            elif isinstance(module, nn.Embedding):
                nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(self, idx: torch.Tensor, use_cache: bool = False) -> torch.Tensor:
        b, s = idx.shape
        x = self.tok_emb(idx)
        for block in self.blocks:
            x = block(x, self.rope_freqs, use_cache=use_cache)
        x = self.norm(x)
        return self.lm_head(x)  # (b, s, vocab_size)

    def reset_cache(self):
        for block in self.blocks:
            block.attn.reset_cache()

    @torch.no_grad()
    def generate(
        self,
        idx: torch.Tensor,
        max_new_tokens: int,
        temperature: float = 1.0,
        top_k: int = 50,
    ) -> torch.Tensor:
        self.reset_cache()
        # Prefill
        logits = self(idx, use_cache=True)
        for _ in range(max_new_tokens):
            logits_last = logits[:, -1, :]  # (b, vocab)
            if temperature != 1.0:
                logits_last = logits_last / temperature
            if top_k > 0:
                v, _ = torch.topk(logits_last, min(top_k, logits_last.size(-1)))
                logits_last[logits_last < v[:, [-1]]] = float("-inf")
            probs = F.softmax(logits_last, dim=-1)
            next_tok = torch.multinomial(probs, num_samples=1)
            idx = torch.cat([idx, next_tok], dim=1)
            logits = self(next_tok, use_cache=True)
        return idx


# ---------------------------------------------------------------------------
# Parameter count helper
# ---------------------------------------------------------------------------

def count_params(model: nn.Module) -> str:
    n = sum(p.numel() for p in model.parameters())
    if n >= 1e9:
        return f"{n / 1e9:.2f}B"
    return f"{n / 1e6:.1f}M"


if __name__ == "__main__":
    from micro_config import MICRO_TINY_CONFIG, MICRO_1B_CONFIG

    print("=== Tiny smoke test ===")
    model = MoswalkLLM(MICRO_TINY_CONFIG)
    x = torch.randint(0, MICRO_TINY_CONFIG["vocab_size"], (2, 16))
    logits = model(x)
    assert logits.shape == (2, 16, MICRO_TINY_CONFIG["vocab_size"])
    print(f"Forward pass OK | params: {count_params(model)}")

    print("\n=== 1B config param count ===")
    model_1b = MoswalkLLM(MICRO_1B_CONFIG)
    print(f"MoswalkLLM 1B params: {count_params(model_1b)}")
    fp16_gb = sum(p.numel() for p in model_1b.parameters()) * 2 / 1e9
    int4_gb = fp16_gb / 4
    print(f"FP16 size: {fp16_gb:.2f} GB")
    print(f"INT4 size: {int4_gb:.2f} GB  ← target on-device model")
