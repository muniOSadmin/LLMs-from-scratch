# Swarm topology configuration for moswalk multi-agent inference.
#
# Defines how transformer layers are partitioned across N worker agents,
# communication buffer sizes, and the two inference modes:
#   - PIPELINE: contiguous layer ranges across devices (multi-device throughput)
#   - SPECULATIVE: draft + verify on separate devices (single/dual device speedup)

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SwarmMode(Enum):
    PIPELINE    = "pipeline"     # layer shards across N devices
    SPECULATIVE = "speculative"  # draft model + verify model
    HYBRID      = "hybrid"       # speculative draft on coord + pipeline verify workers


@dataclass
class ShardConfig:
    """Describes a single agent's layer ownership."""
    agent_id: int
    layer_start: int    # inclusive
    layer_end: int      # exclusive
    role: str           # "coordinator" | "worker"

    @property
    def n_layers(self) -> int:
        return self.layer_end - self.layer_start

    def __repr__(self) -> str:
        return (f"Shard(agent={self.agent_id}, role={self.role}, "
                f"layers={self.layer_start}–{self.layer_end - 1})")


@dataclass
class SwarmConfig:
    n_agents: int
    mode: SwarmMode
    total_layers: int            # from model config (e.g. 24)
    emb_dim: int                 # activation tensor width (e.g. 2048)
    draft_layers: int = 4        # layers in draft model (SPECULATIVE / HYBRID)
    speculative_k: int = 5       # tokens generated speculatively per verify step
    # Network
    coordinator_host: str = "localhost"
    base_port: int = 7860        # coordinator listens here; workers on base_port+i
    activation_dtype: str = "float16"  # dtype for inter-agent tensors
    max_batch_tokens: int = 1    # decode step batch size (1 = token-by-token)

    # Derived shard assignments (populated by build_shards())
    shards: list[ShardConfig] = field(default_factory=list)

    def __post_init__(self):
        if not self.shards:
            self.shards = self.build_shards()

    def build_shards(self) -> list[ShardConfig]:
        """Partition layers evenly across agents for PIPELINE mode."""
        shards = []
        if self.mode == SwarmMode.SPECULATIVE:
            # Agent 0 = coordinator (embedding + draft + LM head)
            # Agent 1 = verifier (full model layers)
            shards.append(ShardConfig(0, 0, self.draft_layers, "coordinator"))
            shards.append(ShardConfig(1, 0, self.total_layers, "worker"))
            return shards

        # PIPELINE and HYBRID: divide full-model layers across agents
        # Coordinator (agent 0) owns first shard + embedding + LM head
        layers_per_agent = self.total_layers // self.n_agents
        remainder = self.total_layers % self.n_agents
        start = 0
        for i in range(self.n_agents):
            extra = 1 if i < remainder else 0
            end = start + layers_per_agent + extra
            role = "coordinator" if i == 0 else "worker"
            shards.append(ShardConfig(i, start, end, role))
            start = end
        return shards

    @property
    def activation_bytes_per_token(self) -> int:
        """Size of the hidden-state tensor passed between agents (bytes)."""
        dtype_bytes = 2 if self.activation_dtype == "float16" else 4
        return self.emb_dim * dtype_bytes  # (1, 1, emb_dim)

    def summary(self) -> str:
        lines = [
            f"SwarmConfig  mode={self.mode.value}  agents={self.n_agents}",
            f"  total_layers={self.total_layers}  emb_dim={self.emb_dim}",
            f"  activation/token: {self.activation_bytes_per_token} bytes",
            "  Shards:",
        ]
        for s in self.shards:
            lines.append(f"    {s}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Pre-built topology factories
# ---------------------------------------------------------------------------

def single_device_speculative(model_cfg: dict) -> SwarmConfig:
    """Draft + verify on one device (simulated as 2 in-process agents)."""
    return SwarmConfig(
        n_agents=2,
        mode=SwarmMode.SPECULATIVE,
        total_layers=model_cfg["n_layers"],
        emb_dim=model_cfg["emb_dim"],
        draft_layers=4,
        speculative_k=5,
    )


def pipeline_2_device(model_cfg: dict) -> SwarmConfig:
    return SwarmConfig(
        n_agents=2,
        mode=SwarmMode.PIPELINE,
        total_layers=model_cfg["n_layers"],
        emb_dim=model_cfg["emb_dim"],
    )


def pipeline_4_device(model_cfg: dict) -> SwarmConfig:
    return SwarmConfig(
        n_agents=4,
        mode=SwarmMode.PIPELINE,
        total_layers=model_cfg["n_layers"],
        emb_dim=model_cfg["emb_dim"],
    )


def hybrid_4_device(model_cfg: dict) -> SwarmConfig:
    """Speculative draft on coordinator + 3 pipeline workers for verify."""
    return SwarmConfig(
        n_agents=4,
        mode=SwarmMode.HYBRID,
        total_layers=model_cfg["n_layers"],
        emb_dim=model_cfg["emb_dim"],
        draft_layers=4,
        speculative_k=5,
    )


# ---------------------------------------------------------------------------
# Quick print
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path as _Path
    _dir = str(_Path(__file__).parent)
    if _dir not in sys.path:
        sys.path.insert(0, _dir)
    from micro_config import MICRO_1B_CONFIG as CFG

    for factory, label in [
        (single_device_speculative, "Single-device speculative"),
        (pipeline_2_device,         "2-device pipeline"),
        (pipeline_4_device,         "4-device pipeline"),
        (hybrid_4_device,           "4-device hybrid"),
    ]:
        cfg = factory(CFG)
        print(f"\n{'='*55}")
        print(f"  {label}")
        print('='*55)
        print(cfg.summary())
