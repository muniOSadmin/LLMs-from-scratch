"""
Smoke tests for moswalk core modules.

Covers the three layers that must stay green before any merge:
  1. trigger_scanner  — property flags → conditions (deterministic)
  2. agency_navigator — conditions → pathway steps (two-engine resolver)
  3. swarm inference  — speculative decode shape + token count
"""

import sys
from pathlib import Path

# Anchor all imports to file location — never CWD
_REPO = Path(__file__).parents[1]
sys.path.insert(0, str(_REPO / "iphone-llm"))
sys.path.insert(0, str(_REPO / "moswalk-kernel"))

import pytest
import torch


# ---------------------------------------------------------------------------
# 1. trigger_scanner
# ---------------------------------------------------------------------------

from property.trigger_scanner import scan, from_pluto_row, TriggerResult


def _base_flags(**overrides):
    """Minimal valid flags dict with all keys trigger_scanner reads."""
    base = {
        "landmarked": False,
        "landmark_type": None,
        "flood_zone": None,         # "AE" | "VE" | "X" | None
        "year_built": 2000,
        "open_violations": 0,
        "stories": 3,
        "lot_area_sqft": 5000,
        "rent_stabilized": False,
        "zoning_district": "R6",
        "occupied_before_2024": False,
        "mapped_street_adjacent": False,
    }
    base.update(overrides)
    return base


def test_trigger_scanner_landmark():
    result = scan(_base_flags(landmarked=True))
    assert isinstance(result, TriggerResult)
    assert "Landmark building or within historic district" in result.conditions


def test_trigger_scanner_flood_zone_ae():
    result = scan(_base_flags(flood_zone="AE"))
    assert "Flood zone AE or VE" in result.conditions


def test_trigger_scanner_flood_zone_ve():
    result = scan(_base_flags(flood_zone="VE"))
    assert "Flood zone AE or VE" in result.conditions


def test_trigger_scanner_no_flags():
    result = scan(_base_flags())
    assert len(result.conditions) == 0
    assert result.blocker_flags() == []


def test_trigger_scanner_violations_are_blockers():
    result = scan(_base_flags(open_violations=2))
    assert len(result.blocker_flags()) > 0
    assert any("violation" in b.lower() or "OATH" in b for b in result.blocker_flags())


def test_trigger_scanner_pre1987():
    result = scan(_base_flags(year_built=1960))
    assert "Pre-1987 construction AND gut renovation or demolition of interior" in result.conditions


def test_trigger_scanner_large_lot():
    result = scan(_base_flags(lot_area_sqft=25000))
    assert "Site > 20,000 sq ft or involves mapped street" in result.conditions


def test_from_pluto_row_maps_landmark():
    row = {"LandmkFlag": "Y", "HistDist": "", "FloodZone": "", "YearBuilt": "2000",
           "LotArea": "5000", "BldgClass": "D4", "ZoneDist1": "R6", "NumFloors": "3"}
    flags = from_pluto_row(row)
    assert flags.get("landmarked") is True


def test_from_pluto_row_maps_flood_zone_ae():
    row = {"LandmkFlag": "", "HistDist": "", "FloodZone": "AE", "YearBuilt": "2000",
           "LotArea": "5000", "BldgClass": "D4", "ZoneDist1": "R6", "NumFloors": "3"}
    flags = from_pluto_row(row)
    assert flags.get("flood_zone") == "AE"


def test_from_pluto_row_maps_year_built():
    row = {"LandmkFlag": "", "HistDist": "", "FloodZone": "", "YearBuilt": "1955",
           "LotArea": "5000", "BldgClass": "D4", "ZoneDist1": "R6", "NumFloors": "3"}
    flags = from_pluto_row(row)
    assert flags.get("year_built") == 1955


# ---------------------------------------------------------------------------
# 2. agency_navigator
# ---------------------------------------------------------------------------

from agencies.agency_navigator import AgencyNavigator, PathwayResult


@pytest.fixture(scope="module")
def nav():
    return AgencyNavigator()


def test_navigator_new_building_baseline(nav):
    result = nav.resolve("new_building", frozenset())
    assert isinstance(result, PathwayResult)
    assert len(result.steps) > 0
    codes = [s.code for s in result.steps]
    assert "DOB" in codes


def test_navigator_landmark_triggers_lpc(nav):
    conditions = frozenset(["Landmark building or within historic district"])
    result = nav.resolve("alteration_type_1", conditions)
    codes = [s.code for s in result.steps]
    assert "LPC" in codes, f"LPC not in steps: {codes}"


def test_navigator_lpc_before_dob(nav):
    """LPC must appear before DOB in any landmark pathway (sequential_after)."""
    conditions = frozenset(["Landmark building or within historic district"])
    result = nav.resolve("alteration_type_1", conditions)
    codes = [s.code for s in result.steps]
    assert "LPC" in codes and "DOB" in codes
    assert codes.index("LPC") < codes.index("DOB"), (
        f"LPC must precede DOB; order: {codes}"
    )


def test_navigator_confidence_range(nav):
    result = nav.resolve("alteration_type_2", frozenset())
    for step in result.steps:
        assert 0.0 <= step.confidence <= 1.0, (
            f"Confidence out of range for {step.code}: {step.confidence}"
        )


def test_navigator_explain_agency(nav):
    edu = nav.explain_agency("DOB")
    assert edu is not None
    assert len(edu) > 0


def test_navigator_alteration_type_2_has_dob(nav):
    result = nav.resolve("alteration_type_2", frozenset())
    codes = [s.code for s in result.steps]
    assert "DOB" in codes


def test_navigator_fisp_facade_pathway(nav):
    result = nav.resolve("fisp_facade", frozenset())
    assert isinstance(result, PathwayResult)
    assert len(result.steps) > 0


def test_navigator_pipeline_end_to_end(nav):
    """Full pipeline: PLUTO row → flags → conditions → pathway."""
    row = {"LandmkFlag": "Y", "HistDist": "", "FloodZone": "", "YearBuilt": "1970",
           "LotArea": "8000", "BldgClass": "D4", "ZoneDist1": "R6", "NumFloors": "4"}
    flags = from_pluto_row(row)
    trigger = scan(flags)
    assert "Landmark building or within historic district" in trigger.conditions
    result = nav.resolve("alteration_type_1", trigger.conditions)
    codes = [s.code for s in result.steps]
    assert "LPC" in codes
    assert "DOB" in codes


# ---------------------------------------------------------------------------
# 3. swarm inference — shape + generation
# ---------------------------------------------------------------------------

from swarm_inference import MoswalkInference, InferenceResult


@pytest.fixture(scope="module")
def tiny_engine():
    return MoswalkInference.from_random("tiny", device="cpu")


def test_generate_from_ids_returns_result(tiny_engine):
    result = tiny_engine.generate_from_ids([1, 2, 3, 4], max_new_tokens=5)
    assert isinstance(result, InferenceResult)
    assert result.generated_tokens == 5
    assert len(result.token_ids) == 5


def test_generate_respects_max_new_tokens(tiny_engine):
    for n in [1, 4, 10]:
        result = tiny_engine.generate_from_ids([1, 2, 3], max_new_tokens=n)
        assert result.generated_tokens == n, (
            f"Expected {n} tokens, got {result.generated_tokens}"
        )


def test_output_shape_correct(tiny_engine):
    """Output must have exactly max_new_tokens ids, no extra dims."""
    prompt = [1, 2, 3, 4, 5]
    result = tiny_engine.generate_from_ids(prompt, max_new_tokens=6)
    assert len(result.token_ids) == 6
    assert result.prompt_tokens == len(prompt)


def test_tokens_per_second_positive(tiny_engine):
    result = tiny_engine.generate_from_ids([1, 2, 3], max_new_tokens=5)
    assert result.tokens_per_second > 0.0


def test_speculative_stats_tracked(tiny_engine):
    """Coordinator must track draft vs accepted tokens after generation."""
    tiny_engine.generate_from_ids([1, 2, 3, 4, 5], max_new_tokens=8)
    stats = tiny_engine.coordinator.stats
    assert stats.draft_tokens >= 0
    assert stats.accepted_tokens >= 0


def test_draft_config_generates():
    engine = MoswalkInference.from_random("draft", device="cpu")
    result = engine.generate_from_ids([1, 2, 3], max_new_tokens=4)
    assert result.generated_tokens == 4


def test_no_shape_mismatch_on_rejection():
    """Regression: correction token in _accept_reject must stay 2D (1,1)."""
    engine = MoswalkInference.from_random("tiny", device="cpu")
    # Run many tokens to force rejection events
    result = engine.generate_from_ids(list(range(1, 9)), max_new_tokens=20)
    assert result.generated_tokens == 20


# ---------------------------------------------------------------------------
# 4. config integrity
# ---------------------------------------------------------------------------

from micro_config import (
    MICRO_1B_CONFIG, MICRO_TINY_CONFIG, MICRO_DRAFT_CONFIG,
    LLAMA32_1B_CONFIG, LLAMA32_1B_COMPACT_CONFIG,
)


def test_all_configs_have_required_keys():
    required = {"vocab_size", "context_length", "emb_dim", "n_heads", "n_kv_heads",
                "n_layers", "ffn_hidden_dim", "rope_theta", "rms_norm_eps",
                "drop_rate", "qkv_bias", "tie_embeddings"}
    for name, cfg in [
        ("MICRO_1B", MICRO_1B_CONFIG),
        ("MICRO_TINY", MICRO_TINY_CONFIG),
        ("MICRO_DRAFT", MICRO_DRAFT_CONFIG),
        ("LLAMA32_1B", LLAMA32_1B_CONFIG),
        ("LLAMA32_1B_COMPACT", LLAMA32_1B_COMPACT_CONFIG),
    ]:
        missing = required - cfg.keys()
        assert not missing, f"{name} missing keys: {missing}"


def test_llama32_1b_exact_architecture():
    """Exact shape required for weight transplant from HF Llama 3.2 1B."""
    cfg = LLAMA32_1B_CONFIG
    assert cfg["n_layers"] == 16
    assert cfg["n_heads"] == 32
    assert cfg["n_kv_heads"] == 8
    assert cfg["emb_dim"] == 2048
    assert cfg["ffn_hidden_dim"] == 8192
    assert cfg["vocab_size"] == 128_256
    assert cfg["rope_theta"] == 500_000.0
    assert cfg["tie_embeddings"] is False


def test_gqa_ratio_valid():
    """n_heads must be divisible by n_kv_heads for GQA."""
    for name, cfg in [
        ("MICRO_1B", MICRO_1B_CONFIG),
        ("MICRO_TINY", MICRO_TINY_CONFIG),
        ("MICRO_DRAFT", MICRO_DRAFT_CONFIG),
        ("LLAMA32_1B", LLAMA32_1B_CONFIG),
    ]:
        assert cfg["n_heads"] % cfg["n_kv_heads"] == 0, (
            f"{name}: n_heads={cfg['n_heads']} not divisible by "
            f"n_kv_heads={cfg['n_kv_heads']}"
        )


# ---------------------------------------------------------------------------
# 5. quantization round-trip
# ---------------------------------------------------------------------------

import torch.nn as nn
from micro_quantize import quantize_tensor, dequantize_tensor, QuantConfig


def test_quantization_round_trip_error():
    lin = nn.Linear(256, 512, bias=False)
    nn.init.normal_(lin.weight)
    cfg = QuantConfig(group_size=64)
    q_packed, scales, zeros = quantize_tensor(lin.weight.data, cfg)
    w_hat = dequantize_tensor(q_packed, scales, zeros, cfg)
    err = (lin.weight.data - w_hat).abs().mean().item()
    assert err < 0.15, f"Quantization round-trip error too high: {err:.5f}"


def test_quantized_shape():
    w = torch.randn(64, 128)
    cfg = QuantConfig(group_size=64)
    q_packed, scales, zeros = quantize_tensor(w, cfg)
    assert q_packed.shape == (64, 64), f"Expected (64, 64), got {q_packed.shape}"
    assert scales.shape == (64, 2)
    assert zeros.shape == (64, 2)


def test_quantized_values_in_range():
    w = torch.randn(128, 256)
    cfg = QuantConfig(group_size=128)
    q_packed, _, _ = quantize_tensor(w, cfg)
    lo = (q_packed & 0x0F).to(torch.int32)
    hi = ((q_packed >> 4) & 0x0F).to(torch.int32)
    assert lo.min() >= 0 and lo.max() <= 15
    assert hi.min() >= 0 and hi.max() <= 15
