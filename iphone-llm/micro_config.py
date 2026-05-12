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
