"""
swarm_inference.py — MoswalkLLM inference entry point

The public-facing API for all MoswalkLLM generation on any node in the mesh:
  - iPhone 17 Pro: CoreML model, single-device pipeline
  - Mac Desktop:   PyTorch, speculative or hybrid swarm
  - Mac Air M1:    PyTorch, layer-shard worker

Usage (Python):
    from swarm_inference import MoswalkInference
    engine = MoswalkInference.from_checkpoint("moswalk-1b-int4.pt")
    response = engine.generate("What permits do I need for a rooftop deck?")

Usage (CLI):
    python swarm_inference.py --checkpoint moswalk-1b-int4.pt --prompt "..."
    python swarm_inference.py --checkpoint moswalk-1b-int4.pt --interactive

Usage (field quick-consult, no tokenizer):
    python swarm_inference.py --checkpoint moswalk-1b-int4.pt --token-ids "1 2 3 4 5"
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import torch

_HERE = Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from micro_config import (
    LLAMA32_1B_CONFIG, LLAMA32_1B_COMPACT_CONFIG,
    MICRO_1B_CONFIG, MICRO_DRAFT_CONFIG, MICRO_TINY_CONFIG,
)
from micro_model import MoswalkLLM
from swarm_config import SwarmConfig, single_device_speculative, pipeline_2_device
from swarm_coordinator import SwarmCoordinator


# ---------------------------------------------------------------------------
# Inference result
# ---------------------------------------------------------------------------

@dataclass
class InferenceResult:
    prompt_tokens: int
    generated_tokens: int
    elapsed_ms: float
    token_ids: list[int]
    text: str = ""          # populated if tokenizer is available

    @property
    def tokens_per_second(self) -> float:
        if self.elapsed_ms <= 0:
            return 0.0
        return self.generated_tokens / (self.elapsed_ms / 1000)

    def summary(self) -> str:
        return (
            f"Generated {self.generated_tokens} tokens in {self.elapsed_ms:.0f}ms "
            f"({self.tokens_per_second:.1f} tok/s)"
        )


# ---------------------------------------------------------------------------
# Tokenizer shim — optional; falls back to token ID passthrough
# ---------------------------------------------------------------------------

class TokenizerShim:
    """
    Thin wrapper that tries sentencepiece (Llama tokenizer), then falls back
    to integer passthrough when no tokenizer model is available.
    """

    def __init__(self, model_path: Optional[Path] = None):
        self._sp = None
        if model_path and model_path.exists():
            try:
                import sentencepiece as spm
                self._sp = spm.SentencePieceProcessor()
                self._sp.Load(str(model_path))
            except ImportError:
                pass

    @property
    def available(self) -> bool:
        return self._sp is not None

    def encode(self, text: str) -> list[int]:
        if self._sp:
            return self._sp.Encode(text)
        raise RuntimeError(
            "No tokenizer available. Pass --token-ids instead of --prompt, "
            "or install sentencepiece and provide --tokenizer path."
        )

    def decode(self, ids: list[int]) -> str:
        if self._sp:
            return self._sp.Decode(ids)
        return " ".join(str(i) for i in ids)

    def bos_id(self) -> int:
        return self._sp.bos_id() if self._sp else 1

    def eos_id(self) -> int:
        return self._sp.eos_id() if self._sp else 2


# ---------------------------------------------------------------------------
# Main inference engine
# ---------------------------------------------------------------------------

class MoswalkInference:
    """
    Unified inference engine for all swarm topologies.

    Single-device (iPhone, Mac Air):
        coordinator runs all blocks in-process.

    Speculative (Mac Desktop):
        draft model proposes k tokens, verifier accepts/rejects.
        Draft model = MICRO_TINY_CONFIG (fast); Verifier = full 1B.

    Pipeline (mesh):
        coordinator owns first shard, workers own remaining shards.
        Requires active workers on the network.
    """

    def __init__(
        self,
        model: MoswalkLLM,
        coordinator: SwarmCoordinator,
        tokenizer: TokenizerShim,
        device: str = "cpu",
    ):
        self.model       = model
        self.coordinator = coordinator
        self.tokenizer   = tokenizer
        self.device      = device

    @classmethod
    def from_checkpoint(
        cls,
        checkpoint_path: Path,
        topology: str = "single",
        tokenizer_path: Optional[Path] = None,
        device: Optional[str] = None,
    ) -> "MoswalkInference":
        """
        Load a saved checkpoint (from convert_llama.py or micro_quantize.py).

        topology: "single" | "speculative" | "pipeline"
        """
        if device is None:
            if torch.backends.mps.is_available():
                device = "mps"       # Apple Silicon (Mac)
            elif torch.cuda.is_available():
                device = "cuda"
            else:
                device = "cpu"

        checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
        cfg        = checkpoint.get("config", LLAMA32_1B_CONFIG)
        state_dict = checkpoint["state_dict"]

        model = MoswalkLLM(cfg)
        model.load_state_dict(state_dict, strict=True)
        model.to(device)
        model.eval()

        # Build swarm config
        if topology == "speculative":
            swarm_cfg = single_device_speculative(cfg)
        else:
            swarm_cfg = single_device_speculative(cfg)  # single: still use speculative topology in-process

        coordinator, _ = SwarmCoordinator.from_model(model, swarm_cfg)
        tokenizer = TokenizerShim(tokenizer_path)

        return cls(model, coordinator, tokenizer, device)

    @classmethod
    def from_random(
        cls,
        config_name: str = "tiny",
        device: str = "cpu",
    ) -> "MoswalkInference":
        """
        Smoke-test mode: random weights, no checkpoint required.
        config_name: "tiny" | "draft" | "micro_1b" | "llama32_1b" | "llama32_compact"
        """
        cfg_map = {
            "tiny":            MICRO_TINY_CONFIG,
            "draft":           MICRO_DRAFT_CONFIG,
            "micro_1b":        MICRO_1B_CONFIG,
            "llama32_1b":      LLAMA32_1B_CONFIG,
            "llama32_compact": LLAMA32_1B_COMPACT_CONFIG,
        }
        cfg = cfg_map.get(config_name, MICRO_TINY_CONFIG)
        model = MoswalkLLM(cfg).to(device)
        model.eval()
        swarm_cfg = single_device_speculative(cfg)
        coordinator, _ = SwarmCoordinator.from_model(model, swarm_cfg)
        return cls(model, coordinator, TokenizerShim(), device)

    @torch.no_grad()
    def generate(
        self,
        prompt: str,
        max_new_tokens: int = 200,
        temperature: float = 0.7,
        top_k: int = 40,
    ) -> InferenceResult:
        """Generate from a text prompt. Requires tokenizer."""
        if not self.tokenizer.available:
            raise RuntimeError("Tokenizer not available — use generate_from_ids() instead.")
        ids = self.tokenizer.encode(prompt)
        return self.generate_from_ids(ids, max_new_tokens, temperature, top_k)

    @torch.no_grad()
    def generate_from_ids(
        self,
        prompt_ids: list[int],
        max_new_tokens: int = 200,
        temperature: float = 0.7,
        top_k: int = 40,
    ) -> InferenceResult:
        """Generate from a list of token IDs."""
        device = next(self.model.parameters()).device
        ids_tensor = torch.tensor([prompt_ids], dtype=torch.long, device=device)

        t0 = time.perf_counter()
        out = self.coordinator.generate(
            prompt_ids=ids_tensor,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_k=top_k,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000

        generated = out[0, len(prompt_ids):].tolist()
        text = self.tokenizer.decode(generated) if self.tokenizer.available else ""

        return InferenceResult(
            prompt_tokens=len(prompt_ids),
            generated_tokens=len(generated),
            elapsed_ms=elapsed_ms,
            token_ids=generated,
            text=text,
        )


# ---------------------------------------------------------------------------
# Interactive REPL (field mode — on-device)
# ---------------------------------------------------------------------------

def interactive_loop(engine: MoswalkInference, max_new_tokens: int, temperature: float):
    print("moswalk // field inference — type a question, blank line to quit")
    print(f"Device: {engine.device}  |  Tokenizer: {'yes' if engine.tokenizer.available else 'no (pass --token-ids)'}")
    print()
    while True:
        try:
            prompt = input("moswalk> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break
        if not prompt:
            break
        if not engine.tokenizer.available:
            print("No tokenizer — enter token IDs (space-separated):")
            raw = input("ids> ").strip()
            if not raw:
                continue
            ids = [int(x) for x in raw.split()]
            result = engine.generate_from_ids(ids, max_new_tokens, temperature)
        else:
            result = engine.generate(prompt, max_new_tokens, temperature)
        print()
        if result.text:
            print(result.text)
        else:
            print("Token IDs:", result.token_ids)
        print()
        print(result.summary())
        print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="MoswalkLLM inference entry point")
    parser.add_argument("--checkpoint", type=Path, help="Path to .pt checkpoint")
    parser.add_argument("--tokenizer",  type=Path, help="Path to tokenizer.model (sentencepiece)")
    parser.add_argument("--topology",   default="single", choices=["single", "speculative", "pipeline"])
    parser.add_argument("--device",     default=None, help="cpu | mps | cuda")
    parser.add_argument("--prompt",     type=str, help="Text prompt (requires tokenizer)")
    parser.add_argument("--token-ids",  type=str, help="Space-separated token IDs")
    parser.add_argument("--max-tokens", type=int, default=200)
    parser.add_argument("--temperature",type=float, default=0.7)
    parser.add_argument("--top-k",      type=int, default=40)
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--smoke-test",  action="store_true", help="Random weights, no checkpoint needed")
    parser.add_argument("--config",      default="tiny", help="Config for --smoke-test")
    args = parser.parse_args()

    if args.smoke_test:
        print(f"Smoke test: config={args.config}, device={args.device or 'cpu'}")
        engine = MoswalkInference.from_random(args.config, device=args.device or "cpu")
        ids = [1, 2, 3, 4, 5, 6, 7, 8]
        result = engine.generate_from_ids(ids, max_new_tokens=20)
        print(f"Generated {result.generated_tokens} tokens")
        print(result.summary())
        return

    if not args.checkpoint:
        parser.error("--checkpoint is required (or use --smoke-test)")

    print(f"Loading checkpoint: {args.checkpoint}")
    engine = MoswalkInference.from_checkpoint(
        args.checkpoint,
        topology=args.topology,
        tokenizer_path=args.tokenizer,
        device=args.device,
    )
    print(f"Loaded. Device: {engine.device}  Topology: {args.topology}")
    print()

    if args.interactive:
        interactive_loop(engine, args.max_tokens, args.temperature)
        return

    if args.prompt:
        result = engine.generate(args.prompt, args.max_tokens, args.temperature, args.top_k)
    elif args.token_ids:
        ids = [int(x) for x in args.token_ids.split()]
        result = engine.generate_from_ids(ids, args.max_tokens, args.temperature, args.top_k)
    else:
        parser.error("Provide --prompt, --token-ids, or --interactive")

    if result.text:
        print(result.text)
    else:
        print("Token IDs:", result.token_ids)
    print()
    print(result.summary())


if __name__ == "__main__":
    main()
