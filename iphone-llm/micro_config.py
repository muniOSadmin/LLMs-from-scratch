# MoswalkLLM configuration — tuned for iPhone 17 Pro (8 GB RAM, ANE)

MICRO_1B_CONFIG = {
    "vocab_size":       32_000,
    "context_length":   4_096,
    "emb_dim":          2_048,
    "n_heads":          16,        # query heads
    "n_kv_heads":       4,         # GQA: 4 KV heads shared across 16 Q heads
    "n_layers":         24,
    "ffn_hidden_dim":   5_504,     # SwiGLU: ceil(8/3 * emb_dim) rounded to 64
    "sliding_window":   512,       # SWA window; None → full attention
    "rope_theta":       10_000.0,
    "rms_norm_eps":     1e-5,
    "drop_rate":        0.0,
    "qkv_bias":         False,
    "tie_embeddings":   True,      # share token emb and LM head weights
}

# Llama 3.2 1B exact architecture — for direct weight transplant via convert_llama.py.
# Shape-for-shape compatible with Meta's released safetensors weights.
# Use this config when loading pretrained weights; MICRO_1B_CONFIG requires training.
LLAMA32_1B_CONFIG = {
    "vocab_size":       128_256,   # Llama 3.2 tokenizer vocabulary
    "context_length":   4_096,     # use 4k at inference; model was trained at 131k
    "emb_dim":          2_048,
    "n_heads":          32,        # query heads (Llama 3.2 1B)
    "n_kv_heads":       8,         # GQA: 8 KV heads shared across 32 Q heads
    "n_layers":         16,        # Llama 3.2 1B has 16 layers (not 24)
    "ffn_hidden_dim":   8_192,     # SwiGLU gate/up hidden dim
    "sliding_window":   None,      # full attention (Llama 3.2 1B has no SWA)
    "rope_theta":       500_000.0, # Llama 3.2 1B uses 500k RoPE base
    "rms_norm_eps":     1e-5,
    "drop_rate":        0.0,
    "qkv_bias":         False,
    "tie_embeddings":   False,     # Llama 3.2 1B does NOT tie embeddings
}

# Compact Llama 3.2 1B — vocab truncated to 32k for smaller CoreML export.
# Covers the top 32k Llama tokens (>99.9% of natural language usage).
# Use convert_llama.py --compact to produce this variant.
LLAMA32_1B_COMPACT_CONFIG = {
    "vocab_size":       32_000,
    "context_length":   4_096,
    "emb_dim":          2_048,
    "n_heads":          32,
    "n_kv_heads":       8,
    "n_layers":         16,
    "ffn_hidden_dim":   8_192,
    "sliding_window":   None,
    "rope_theta":       500_000.0,
    "rms_norm_eps":     1e-5,
    "drop_rate":        0.0,
    "qkv_bias":         False,
    "tie_embeddings":   False,
}

# Smoke-test config (fits on a laptop CPU for development)
MICRO_TINY_CONFIG = {
    "vocab_size":       4_096,
    "context_length":   512,
    "emb_dim":          256,
    "n_heads":          8,
    "n_kv_heads":       2,
    "n_layers":         4,
    "ffn_hidden_dim":   688,       # ceil(8/3 * 256) rounded to 16
    "sliding_window":   64,
    "rope_theta":       10_000.0,
    "rms_norm_eps":     1e-5,
    "drop_rate":        0.0,
    "qkv_bias":         False,
    "tie_embeddings":   True,
}
