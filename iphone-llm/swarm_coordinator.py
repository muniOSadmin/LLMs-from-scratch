# Swarm coordinator for moswalk multi-agent inference.
#
# The coordinator is always agent 0. It owns:
#   - Token embedding
#   - Its assigned layer shard (first N layers in PIPELINE/HYBRID; draft layers in SPECULATIVE)
#   - Final RMSNorm + LM head
#   - Temperature / top-k sampler
#
# Pipeline mode:  embed → local shard → send act → ... → recv act → norm → lm_head → sample
# Speculative:    draft k tokens with local draft layers → send to verifier → accept/reject loop
# Hybrid:         speculative draft on coordinator + pipeline workers as verifier shards

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

from swarm_config import SwarmConfig, SwarmMode
from swarm_worker import Transport, LocalTransport, SwarmWorker, build_workers


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@dataclass
class CoordinatorStats:
    tokens_generated: int = 0
    draft_tokens: int = 0          # SPECULATIVE: tokens proposed by draft
    accepted_tokens: int = 0       # SPECULATIVE: tokens accepted by verifier
    total_ms: float = 0.0

    @property
    def tokens_per_sec(self) -> float:
        return self.tokens_generated / max(1e-6, self.total_ms / 1000)

    @property
    def acceptance_rate(self) -> float:
        if self.draft_tokens == 0:
            return 0.0
        return self.accepted_tokens / self.draft_tokens


# ---------------------------------------------------------------------------
# Sampler
# ---------------------------------------------------------------------------

def _sample(logits: torch.Tensor, temperature: float, top_k: int) -> torch.Tensor:
    """Sample next token from (1, vocab) logits. Returns (1, 1) int64 tensor."""
    if temperature != 1.0:
        logits = logits / temperature
    if top_k > 0:
        v, _ = torch.topk(logits, min(top_k, logits.size(-1)))
        logits = logits.masked_fill(logits < v[:, [-1]], float("-inf"))
    probs = F.softmax(logits, dim=-1)
    return torch.multinomial(probs, num_samples=1)


# ---------------------------------------------------------------------------
# SwarmCoordinator
# ---------------------------------------------------------------------------

class SwarmCoordinator:
    """
    Orchestrates the full inference loop across all swarm agents.

    In PIPELINE mode each token flows:
      coordinator embed → coord shard → worker 1 → ... → last worker → coord lm_head

    In SPECULATIVE mode:
      coordinator draft → k candidate tokens → verifier validates in one pass → accept/reject

    In HYBRID mode:
      coordinator runs speculative draft; pipeline workers act as joint verifier shards.
    """

    def __init__(
        self,
        model,                 # MoswalkLLM — coordinator takes ownership of its shard
        swarm_cfg: SwarmConfig,
        transport: Transport,
    ):
        self.cfg = swarm_cfg
        self.transport = transport
        self.stats = CoordinatorStats()

        coord_shard = swarm_cfg.shards[0]
        assert coord_shard.role == "coordinator"

        # Shared model components
        self.tok_emb    = model.tok_emb
        self.norm       = model.norm
        self.lm_head    = model.lm_head
        self.rope_freqs = model.rope_freqs

        # Coordinator's own layer shard
        self.blocks = nn.ModuleList(
            list(model.blocks[coord_shard.layer_start:coord_shard.layer_end])
        )
        self._coord_shard = coord_shard

        # Result channel: last worker sends to queue id = n_agents
        self._result_channel = swarm_cfg.n_agents

        # SPECULATIVE / HYBRID: keep a full-copy of blocks for verifier reference
        # (in single-device sim the verifier is another SwarmWorker running in-process)
        self._all_blocks = model.blocks  # kept alive for speculative verify path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _embed(self, idx: torch.Tensor) -> torch.Tensor:
        """Token ids → hidden states.  idx: (1, s)"""
        return self.tok_emb(idx)  # (1, s, emb_dim)

    def _run_coord_shard(self, x: torch.Tensor, use_cache: bool = True) -> torch.Tensor:
        """Forward pass through coordinator's own layer shard."""
        with torch.no_grad():
            for block in self.blocks:
                x = block(x, self.rope_freqs, use_cache=use_cache)
        return x

    def _logits_from_act(self, act: torch.Tensor) -> torch.Tensor:
        """norm + lm_head on a (1, 1, emb_dim) activation → (1, vocab)."""
        with torch.no_grad():
            return self.lm_head(self.norm(act))[:, -1, :]  # (1, vocab)

    def _send_to_workers(self, act: torch.Tensor) -> None:
        """Send coordinator shard output to worker agent 1."""
        payload = act.to(torch.float16).view(-1)
        self.transport.send(1, payload)

    def _recv_from_last_worker(self, timeout: float = 5.0) -> torch.Tensor:
        """Receive final activation from the last pipeline worker."""
        flat = self.transport.recv(self._result_channel, timeout=timeout)
        return flat.view(1, 1, self.cfg.emb_dim).to(torch.float32)

    # ------------------------------------------------------------------
    # Pipeline inference (one token step)
    # ------------------------------------------------------------------

    def _pipeline_step(self, x: torch.Tensor) -> torch.Tensor:
        """
        Run one decode step in PIPELINE mode.
        x: (1, 1, emb_dim) — embedding of the current token.
        Returns: (1, vocab) logits.
        """
        act = self._run_coord_shard(x)
        if self.cfg.n_agents > 1:
            self._send_to_workers(act)
            act = self._recv_from_last_worker()
        return self._logits_from_act(act)

    # ------------------------------------------------------------------
    # Speculative inference helpers
    # ------------------------------------------------------------------

    def _draft_k_tokens(
        self,
        x: torch.Tensor,
        k: int,
        temperature: float,
        top_k: int,
    ) -> tuple[list[torch.Tensor], list[torch.Tensor]]:
        """
        Run the draft model (coordinator's layers only) autoregressively for k steps.
        Returns (draft_token_ids, draft_logits_list).
        x: (1, 1, emb_dim) embedding of the last accepted token.
        """
        draft_ids: list[torch.Tensor] = []
        draft_logits: list[torch.Tensor] = []
        cur = x
        with torch.no_grad():
            for _ in range(k):
                act = self._run_coord_shard(cur, use_cache=True)
                logits = self._logits_from_act(act)
                tok = _sample(logits, temperature, top_k)  # (1, 1)
                draft_ids.append(tok)
                draft_logits.append(logits)
                cur = self.tok_emb(tok)  # embed next draft token
        return draft_ids, draft_logits

    def _verify_draft(
        self,
        prefix_act: torch.Tensor,
        draft_ids: list[torch.Tensor],
    ) -> list[torch.Tensor]:
        """
        Run the verifier (full model, agent 1) on the draft sequence.
        In single-device sim this runs the full block list directly.
        Returns list of (1, vocab) logits, one per draft position + 1 bonus.
        """
        # Build token sequence for verify pass: prefix embeds + draft tokens
        draft_tensor = torch.cat(draft_ids, dim=1)  # (1, k)
        x = torch.cat([prefix_act, self.tok_emb(draft_tensor)], dim=1)  # (1, k+1?, emb_dim)

        # For SPECULATIVE mode with n_agents=2 in local sim: run all blocks
        with torch.no_grad():
            for block in self._all_blocks:
                x = block(x, self.rope_freqs, use_cache=False)
        x = self.norm(x)
        logits = self.lm_head(x)  # (1, seq, vocab)
        return [logits[:, i, :] for i in range(logits.size(1))]

    def _accept_reject(
        self,
        draft_ids: list[torch.Tensor],
        draft_logits: list[torch.Tensor],
        verify_logits: list[torch.Tensor],
        temperature: float,
        top_k: int,
    ) -> tuple[list[torch.Tensor], int]:
        """
        Classic speculative decoding accept/reject.
        Returns (accepted token ids, n_accepted).
        """
        accepted: list[torch.Tensor] = []
        k = len(draft_ids)

        for i in range(k):
            d_tok = draft_ids[i].item()
            p = F.softmax(verify_logits[i] / max(temperature, 1e-6), dim=-1)
            q = F.softmax(draft_logits[i] / max(temperature, 1e-6), dim=-1)
            ratio = (p[0, d_tok] / q[0, d_tok].clamp(min=1e-9)).clamp(max=1.0)
            if torch.rand(1).item() < ratio.item():
                accepted.append(draft_ids[i])
            else:
                # Rejection: sample correction token and stop
                correction_probs = (p - q).clamp(min=0)
                correction_probs = correction_probs / correction_probs.sum()
                correction = torch.multinomial(correction_probs, num_samples=1)  # (1, 1)
                accepted.append(correction)
                self.stats.draft_tokens += k
                self.stats.accepted_tokens += len(accepted) - 1  # last is correction
                return accepted, len(accepted)

        # All k accepted — sample bonus token from verifier's k+1 position
        bonus = _sample(verify_logits[k], temperature, top_k)
        accepted.append(bonus)
        self.stats.draft_tokens += k
        self.stats.accepted_tokens += k
        return accepted, k + 1  # k accepted + 1 bonus

    # ------------------------------------------------------------------
    # Public generate API
    # ------------------------------------------------------------------

    @torch.no_grad()
    def generate(
        self,
        prompt_ids: torch.Tensor,
        max_new_tokens: int,
        temperature: float = 1.0,
        top_k: int = 50,
    ) -> torch.Tensor:
        """
        Generate max_new_tokens tokens from a prompt.
        prompt_ids: (1, prompt_len) int64
        Returns: (1, prompt_len + generated) int64
        """
        t0 = time.perf_counter()
        mode = self.cfg.mode

        # Prefill: embed and run through all shard layers (no KV cache warming needed
        # for workers — they receive activations token by token in decode)
        x = self._embed(prompt_ids)  # (1, prompt_len, emb_dim)
        act = self._run_coord_shard(x, use_cache=True)

        if mode == SwarmMode.PIPELINE and self.cfg.n_agents > 1:
            # In pipeline mode prefill sends full sequence activation to workers.
            # Workers are expected to be running their serve loops.
            self._send_to_workers(act[:, -1:, :])
            act = self._recv_from_last_worker()
        else:
            act = act[:, -1:, :]  # keep only last position

        ids = prompt_ids.clone()

        if mode == SwarmMode.SPECULATIVE:
            ids = self._generate_speculative(ids, act, max_new_tokens, temperature, top_k)
        else:
            ids = self._generate_pipeline(ids, act, max_new_tokens, temperature, top_k)

        self.stats.total_ms += (time.perf_counter() - t0) * 1000
        return ids

    def _generate_pipeline(
        self,
        ids: torch.Tensor,
        act: torch.Tensor,
        max_new_tokens: int,
        temperature: float,
        top_k: int,
    ) -> torch.Tensor:
        for _ in range(max_new_tokens):
            logits = self._logits_from_act(act)
            next_tok = _sample(logits, temperature, top_k)  # (1, 1)
            ids = torch.cat([ids, next_tok], dim=1)
            self.stats.tokens_generated += 1

            # Embed and forward the new token
            x = self.tok_emb(next_tok)  # (1, 1, emb_dim)
            act = self._run_coord_shard(x, use_cache=True)
            if self.cfg.n_agents > 1:
                self._send_to_workers(act)
                act = self._recv_from_last_worker()

        return ids

    def _generate_speculative(
        self,
        ids: torch.Tensor,
        act: torch.Tensor,
        max_new_tokens: int,
        temperature: float,
        top_k: int,
    ) -> torch.Tensor:
        k = self.cfg.speculative_k
        generated = 0

        while generated < max_new_tokens:
            remaining = max_new_tokens - generated
            draft_k = min(k, remaining)

            # Draft: coordinator runs its (draft) layers autoregressively
            x_start = act  # (1, 1, emb_dim)
            draft_ids, draft_logits = self._draft_k_tokens(
                x_start, draft_k, temperature, top_k
            )

            # Verify: run full model on draft sequence
            verify_logits = self._verify_draft(x_start, draft_ids)

            # Accept/reject
            accepted, n_accepted = self._accept_reject(
                draft_ids, draft_logits, verify_logits, temperature, top_k
            )

            for tok in accepted:
                if generated >= max_new_tokens:
                    break
                ids = torch.cat([ids, tok], dim=1)
                generated += 1
                self.stats.tokens_generated += 1

            # Update act to embedding of last accepted token
            last_tok = accepted[min(n_accepted, len(accepted)) - 1]
            act = self.tok_emb(last_tok)  # (1, 1, emb_dim)

        return ids

    # ------------------------------------------------------------------
    # Convenience: build coordinator + workers from a model
    # ------------------------------------------------------------------

    @classmethod
    def from_model(
        cls,
        model,
        swarm_cfg: SwarmConfig,
        transport: Optional[Transport] = None,
    ) -> tuple["SwarmCoordinator", list[SwarmWorker]]:
        """
        Factory that splits a MoswalkLLM into coordinator + workers.
        Returns (coordinator, workers) — caller must call worker.start() for each worker.
        """
        if transport is None:
            transport = LocalTransport(swarm_cfg.n_agents + 1)
        coordinator = cls(model, swarm_cfg, transport)
        workers = build_workers(model, swarm_cfg, transport)
        return coordinator, workers

    def summary(self) -> str:
        return (
            f"CoordinatorStats | generated={self.stats.tokens_generated} "
            f"tok/s={self.stats.tokens_per_sec:.1f} "
            f"accept_rate={self.stats.acceptance_rate:.2%} "
            f"total_ms={self.stats.total_ms:.1f}"
        )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path as _Path
    _dir = str(_Path(__file__).parent)
    if _dir not in sys.path:
        sys.path.insert(0, _dir)
    from micro_config import MICRO_TINY_CONFIG as CFG
    from micro_model import MoswalkLLM
    from swarm_config import single_device_speculative, pipeline_2_device

    print("=== Pipeline 2-agent smoke test ===")
    model = MoswalkLLM(CFG)
    pipe_cfg = pipeline_2_device(CFG)
    transport = LocalTransport(pipe_cfg.n_agents + 1)
    coord, workers = SwarmCoordinator.from_model(model, pipe_cfg, transport)

    for w in workers:
        w.start()

    prompt = torch.randint(0, CFG["vocab_size"], (1, 8))
    out = coord.generate(prompt, max_new_tokens=10, temperature=1.0, top_k=20)
    print(f"  Input shape: {prompt.shape}  Output shape: {out.shape}")
    print(f"  {coord.summary()}")

    for w in workers:
        w.stop()

    print("\n=== Speculative single-device smoke test ===")
    model2 = MoswalkLLM(CFG)
    spec_cfg = single_device_speculative(CFG)
    coord2, _ = SwarmCoordinator.from_model(model2, spec_cfg)

    out2 = coord2.generate(prompt, max_new_tokens=10, temperature=1.0, top_k=20)
    print(f"  Input shape: {prompt.shape}  Output shape: {out2.shape}")
    print(f"  {coord2.summary()}")
    print("\nAll smoke tests passed.")
