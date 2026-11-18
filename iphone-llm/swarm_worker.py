# Swarm worker agent for moswalk pipeline-parallel inference.
#
# Each worker owns a contiguous slice of transformer layers.
# It receives an activation tensor from the previous agent,
# runs its layers forward, and sends the output to the next agent.
#
# Transport abstraction: LocalTransport (in-process queue, for simulation)
# maps 1:1 to RemoteTransport (TCP socket / Multipeer Connectivity on iOS).

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

import torch
import torch.nn as nn

from swarm_config import ShardConfig, SwarmConfig


# ---------------------------------------------------------------------------
# Transport protocol — swappable for local sim vs real network
# ---------------------------------------------------------------------------

@runtime_checkable
class Transport(Protocol):
    def send(self, agent_id: int, tensor: torch.Tensor) -> None: ...
    def recv(self, agent_id: int, timeout: float = 5.0) -> torch.Tensor: ...


class LocalTransport:
    """In-process transport using per-agent queues (unit testing / simulation)."""

    def __init__(self, n_agents: int):
        self._queues: dict[int, queue.Queue] = {i: queue.Queue() for i in range(n_agents)}

    def send(self, agent_id: int, tensor: torch.Tensor) -> None:
        self._queues[agent_id].put(tensor.detach().clone())

    def recv(self, agent_id: int, timeout: float = 5.0) -> torch.Tensor:
        return self._queues[agent_id].get(timeout=timeout)


class TcpTransport:
    """
    TCP socket transport for distributed deployment.
    Serialises tensors as raw float16 bytes prefixed with a 4-byte length header.

    On iOS this is replaced by MultipeerConnectivity which handles discovery
    and P2P WiFi setup automatically — the send/recv interface is identical.
    """

    def __init__(self, host: str, port: int, is_server: bool = False):
        import socket, struct
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if is_server:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.bind((host, port))
            self._sock.listen(1)
            self._conn, _ = self._sock.accept()
        else:
            self._sock.connect((host, port))
            self._conn = self._sock
        self._struct = struct

    def send(self, _agent_id: int, tensor: torch.Tensor) -> None:
        data = tensor.to(torch.float16).numpy().tobytes()
        self._conn.sendall(self._struct.pack(">I", len(data)) + data)

    def recv(self, _agent_id: int, timeout: float = 5.0) -> torch.Tensor:
        import numpy as np
        header = self._conn.recv(4)
        length = self._struct.unpack(">I", header)[0]
        buf = bytearray()
        while len(buf) < length:
            chunk = self._conn.recv(length - len(buf))
            buf.extend(chunk)
        arr = np.frombuffer(bytes(buf), dtype=np.float16).copy()
        return torch.from_numpy(arr)


# ---------------------------------------------------------------------------
# Worker agent
# ---------------------------------------------------------------------------

@dataclass
class WorkerStats:
    tokens_processed: int = 0
    total_compute_ms: float = 0.0
    total_wait_ms: float = 0.0

    @property
    def avg_compute_ms(self) -> float:
        return self.total_compute_ms / max(1, self.tokens_processed)

    @property
    def avg_wait_ms(self) -> float:
        return self.total_wait_ms / max(1, self.tokens_processed)


class SwarmWorker:
    """
    Owns a slice of transformer layers [shard.layer_start, shard.layer_end).
    Runs in a background thread, pulling activations from the transport,
    computing forward passes, and pushing results to the next agent.

    Args:
        shard:     Which layers this worker owns.
        blocks:    nn.ModuleList containing exactly shard.n_layers blocks.
        rope_freqs: Pre-computed RoPE cache (shared reference).
        transport:  Send/recv transport.
        swarm_cfg:  Global swarm topology (to know next-agent id).
    """

    def __init__(
        self,
        shard: ShardConfig,
        blocks: nn.ModuleList,
        rope_freqs: torch.Tensor,
        transport: Transport,
        swarm_cfg: SwarmConfig,
    ):
        assert len(blocks) == shard.n_layers, (
            f"Expected {shard.n_layers} blocks, got {len(blocks)}"
        )
        self.shard = shard
        self.blocks = blocks
        self.rope_freqs = rope_freqs
        self.transport = transport
        self.swarm_cfg = swarm_cfg
        self.stats = WorkerStats()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._kv_caches: list[tuple[Optional[torch.Tensor], Optional[torch.Tensor]]] = [
            (None, None) for _ in range(shard.n_layers)
        ]

    @property
    def next_agent_id(self) -> Optional[int]:
        """ID of the agent that should receive our output activation."""
        n = self.swarm_cfg.n_agents
        if self.shard.agent_id < n - 1:
            return self.shard.agent_id + 1
        return None  # last worker sends back to coordinator via a special channel

    def reset_kv_cache(self):
        self._kv_caches = [(None, None)] * self.shard.n_layers

    def _run_one_token(self, x: torch.Tensor, use_cache: bool = True) -> torch.Tensor:
        """Run a single (b=1, s=1) activation through this shard's layers."""
        t0 = time.perf_counter()
        with torch.no_grad():
            for i, block in enumerate(self.blocks):
                x = block(x, self.rope_freqs, use_cache=use_cache)
        self.stats.total_compute_ms += (time.perf_counter() - t0) * 1000
        return x

    def _serve_loop(self):
        """Background loop: recv → compute → send."""
        while not self._stop_event.is_set():
            try:
                t_wait = time.perf_counter()
                act = self.transport.recv(self.shard.agent_id, timeout=0.1)
                self.stats.total_wait_ms += (time.perf_counter() - t_wait) * 1000
            except queue.Empty:
                continue

            # Reshape flat bytes back to (1, 1, emb_dim)
            act = act.view(1, 1, self.swarm_cfg.emb_dim).to(torch.float32)
            out = self._run_one_token(act)
            self.stats.tokens_processed += 1

            next_id = self.next_agent_id
            if next_id is not None:
                self.transport.send(next_id, out.to(torch.float16).view(-1))
            else:
                # Last worker: send to coordinator's result channel (id = n_agents)
                self.transport.send(self.swarm_cfg.n_agents, out.to(torch.float16).view(-1))

    def start(self):
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._serve_loop, daemon=True, name=f"worker-{self.shard.agent_id}")
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def __repr__(self) -> str:
        return (f"SwarmWorker(agent={self.shard.agent_id}, "
                f"layers={self.shard.layer_start}–{self.shard.layer_end - 1}, "
                f"tokens={self.stats.tokens_processed})")


# ---------------------------------------------------------------------------
# Factory: build workers from a full model + swarm config
# ---------------------------------------------------------------------------

def build_workers(
    model,             # MoswalkLLM instance
    swarm_cfg: SwarmConfig,
    transport: Transport,
) -> list[SwarmWorker]:
    """
    Slice model.blocks into per-shard workers.
    The coordinator shard is excluded (it manages embedding + first shard inline).
    Returns workers for agent_id >= 1 (pure pipeline workers).
    """
    workers = []
    for shard in swarm_cfg.shards:
        if shard.role == "coordinator":
            continue  # coordinator runs inline
        shard_blocks = nn.ModuleList(
            list(model.blocks[shard.layer_start:shard.layer_end])
        )
        w = SwarmWorker(
            shard=shard,
            blocks=shard_blocks,
            rope_freqs=model.rope_freqs,
            transport=transport,
            swarm_cfg=swarm_cfg,
        )
        workers.append(w)
    return workers
