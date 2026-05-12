# pantocraft // — mobile field API
#
# The umbilical cord: iPhone 17 Pro ↔ pantocraft // ↔ moswalk-kernel
#
# This module is the single entry point for field queries.
# On iPhone it runs via the CoreML swarm coordinator.
# On Mac mesh nodes it runs via standard Python over Tailscale.
#
# Query flow:
#   field_query(bbl_or_address, question) →
#     BBL resolution (python-geosupport or Geoclient API) →
#     PLUTO property data lookup →
#     moswalk-kernel: property_trigger_scan → agency_graph →
#     pantocraft // pathway_optimizer →
#     ConsultResult (structured + prompt for LLM generation)
#
# Privacy: BBL and address are sent to kernel. Client PII is never
# included in the query path — only the engagement_id reference.
#
# Security: all inter-node traffic is Tailscale-encrypted (WireGuard).
# No plaintext over local network. No external API calls in offline mode.

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import time

# Paths
_ROOT       = Path(__file__).parents[2]
_KERNEL     = _ROOT / "moswalk-kernel"
_PANTOCRAFT = Path(__file__).parent.parent

for p in [str(_KERNEL), str(_PANTOCRAFT)]:
    if p not in sys.path:
        sys.path.insert(0, p)


@dataclass
class ConsultResult:
    """
    Structured result from a field consultation.
    Returned to iOS UI for display and to LLM for generation.
    """
    engagement_id: str
    bbl: str
    address: str
    project_type: str

    # Kernel output
    agency_pathway: list[dict] = field(default_factory=list)
    critical_path_days: int = 0
    escalation_flags: list[str] = field(default_factory=list)

    # pantocraft // optimization
    optimized_days: int = 0
    days_saved: int = 0
    optimization_tracks: list[str] = field(default_factory=list)
    pantocraft_flags: list[str] = field(default_factory=list)

    # Confidence and data freshness
    overall_confidence: float = 0.0
    stale_agencies: list[str] = field(default_factory=list)

    # LLM prompt (for moswalk coordinator.generate())
    llm_prompt: str = ""

    # Timing
    query_ms: float = 0.0

    def display_summary(self) -> str:
        lines = [
            f"pantocraft // Field Consultation",
            f"BBL: {self.bbl}  |  {self.address}",
            f"Project: {self.project_type}",
            f"",
            f"Agency pathway ({len(self.agency_pathway)} agencies):",
        ]
        for s in self.agency_pathway:
            lines.append(
                f"  {s.get('status','?'):<8} {s.get('code','?'):<12} ~{s.get('estimated_days',0)}d"
            )
        lines += [
            f"",
            f"Standard critical path: ~{self.critical_path_days} days",
            f"Optimized:              ~{self.optimized_days} days  (saves ~{self.days_saved} days)",
        ]
        if self.optimization_tracks:
            lines.append(f"Tracks: {', '.join(self.optimization_tracks)}")
        if self.escalation_flags or self.pantocraft_flags:
            lines.append("\nFlags:")
            for f in self.escalation_flags + self.pantocraft_flags:
                lines.append(f"  ⚑ {f[:100]}")
        lines.append(f"\n⚖  Information only. Licensed professional sign-off required.")
        return "\n".join(lines)

    def to_llm_context(self) -> str:
        """Compact context string for prepending to LLM generation prompt."""
        flags_str = "; ".join(self.escalation_flags[:3]) if self.escalation_flags else "none"
        return (
            f"Property: {self.address} (BBL {self.bbl})\n"
            f"Project: {self.project_type}\n"
            f"Critical path: ~{self.critical_path_days}d standard / ~{self.optimized_days}d optimized\n"
            f"Key flags: {flags_str}\n"
            f"Agencies: {', '.join(s.get('code','') for s in self.agency_pathway)}\n"
        )


class FieldAPI:
    """
    Main entry point for pantocraft // field queries.
    Coordinates kernel + optimizer + optional LLM generation.
    """

    def __init__(
        self,
        pathways_yaml: Optional[Path] = None,
        edge_weights_yaml: Optional[Path] = None,
        offline: bool = True,
    ):
        self.offline = offline

        # Lazy imports to allow running without full stack
        self._pathways_yaml = pathways_yaml or (_KERNEL / "compliance" / "permit_pathways.yaml")
        self._edge_weights_yaml = edge_weights_yaml or (_PANTOCRAFT / "inference" / "edge_weights.yaml")

        self._optimizer = None  # lazy load

    def _get_optimizer(self):
        if self._optimizer is None:
            from inference.pathway_optimizer import PathwayOptimizer
            self._optimizer = PathwayOptimizer(self._edge_weights_yaml)
        return self._optimizer

    def consult(
        self,
        engagement_id: str,
        bbl: str,
        address: str,
        borough: str,
        project_type: str,
        dob_filing_type: str,
        property_flags: Optional[dict] = None,
        agency_steps: Optional[list[dict]] = None,
    ) -> ConsultResult:
        """
        Primary field consultation entry point.

        agency_steps: pre-resolved agency pathway from kernel AgencyGraph.
        If not provided, a minimal stub is returned (full integration
        requires sim_runner / swarm coordinator pipeline).
        """
        t0 = time.perf_counter()
        property_flags = property_flags or {}

        if agency_steps is None:
            # Stub: requires kernel property_trigger_scanner (pending implementation)
            agency_steps = self._stub_pathway(dob_filing_type)

        # Compute kernel metrics
        blocking = [s for s in agency_steps if s.get("blocking")]
        critical_days = sum(s.get("estimated_days", 0) for s in blocking)
        stale = [s["code"] for s in agency_steps if s.get("confidence", 1.0) < 0.70]
        escalation = self._escalation_flags(agency_steps, property_flags)

        # pantocraft // optimization
        opt = self._get_optimizer()
        optimized = opt.optimize(
            client_id=engagement_id,
            project_type=project_type,
            agency_steps=agency_steps,
            project_flags=property_flags,
        )

        tracks = [s.speed_track for s in optimized.steps if s.is_optimized and s.speed_track]

        # Build LLM prompt
        llm_prompt = self._build_llm_prompt(
            address, bbl, project_type, agency_steps, escalation, property_flags
        )

        result = ConsultResult(
            engagement_id=engagement_id,
            bbl=bbl,
            address=address,
            project_type=project_type,
            agency_pathway=agency_steps,
            critical_path_days=critical_days,
            escalation_flags=escalation,
            optimized_days=optimized.optimized_critical_days,
            days_saved=optimized.total_savings_days,
            optimization_tracks=tracks,
            pantocraft_flags=optimized.flags,
            overall_confidence=min((s.get("confidence", 1.0) for s in agency_steps), default=1.0),
            stale_agencies=stale,
            llm_prompt=llm_prompt,
            query_ms=round((time.perf_counter() - t0) * 1000, 2),
        )
        return result

    def _escalation_flags(self, steps: list[dict], flags: dict) -> list[str]:
        codes = {s["code"] for s in steps}
        out = []
        if "DOB" in codes and "NYC DOT" in codes:
            out.append("Cross-DM escalation: DOB (Housing DM) + NYC DOT (Operations DM) — two Deputy Mayor chains.")
        if "BSA" in codes:
            out.append("BSA: quasi-judicial, no reports_to. File Pre-Determination before full variance app.")
        if flags.get("flood_zone") in ("AE", "VE"):
            out.append(f"Flood zone {flags['flood_zone']}: ADU pilot INELIGIBLE. Flood-resistant construction mandatory.")
        if flags.get("landmarked"):
            out.append(f"Landmark ({flags.get('landmark_type','unknown')}): LPC approval before DOB permits exterior work.")
        if flags.get("active_violations", 0) > 0:
            out.append(f"{flags['active_violations']} open violation(s): resolve at OATH before A1 filing.")
        return out

    def _build_llm_prompt(
        self,
        address: str,
        bbl: str,
        project_type: str,
        steps: list[dict],
        flags: list[str],
        property_flags: dict,
    ) -> str:
        agency_list = ", ".join(s["code"] for s in steps)
        flag_lines = "\n".join(f"  - {f}" for f in flags) or "  - None"
        return (
            f"moswalk consultation — pantocraft // field query\n"
            f"Property: {address} (BBL {bbl})\n"
            f"Project: {project_type}\n"
            f"Agencies: {agency_list}\n"
            f"Flags:\n{flag_lines}\n\n"
            f"Question: What are the key regulatory steps, sequencing requirements, "
            f"and risks for this project? What should the client do first?"
        )

    def _stub_pathway(self, dob_filing_type: str) -> list[dict]:
        """Minimal stub when kernel property_trigger_scanner is not yet implemented."""
        return [{
            "code": "DOB",
            "role": "primary",
            "status": "READY",
            "blocking": True,
            "sequential_after": [],
            "estimated_days": 45,
            "confidence": 0.90,
            "notes": f"DOB {dob_filing_type} filing — full pathway requires property_trigger_scanner (pending).",
        }]


# ---------------------------------------------------------------------------
# iPhone-ready quick-consult helper
# ---------------------------------------------------------------------------

def quick_consult(
    bbl: str,
    project_description: str,
    dob_filing_type: str = "A2",
    offline: bool = True,
) -> str:
    """
    One-line field API for iPhone shortcut / Siri integration.
    Returns display_summary string.
    """
    api = FieldAPI(offline=offline)
    result = api.consult(
        engagement_id="FIELD-QUERY",
        bbl=bbl,
        address=bbl,
        borough="unknown",
        project_type=project_description,
        dob_filing_type=dob_filing_type,
    )
    return result.display_summary()


if __name__ == "__main__":
    print(quick_consult(
        bbl="3-00783-0001",
        project_description="Open rooftop deck addition — Park Slope brownstone",
        dob_filing_type="A2",
    ))
