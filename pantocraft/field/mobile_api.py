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

# moswalk-kernel: lazy imports for graceful degradation when kernel not on path
try:
    from property.trigger_scanner import scan as _trigger_scan, from_pluto_row as _from_pluto_row
    from agencies.agency_navigator import AgencyNavigator as _AgencyNavigator
    from agencies.educational import explain_pathway as _explain_pathway
    _KERNEL_AVAILABLE = True
    _navigator = _AgencyNavigator()
except ImportError:
    _KERNEL_AVAILABLE = False
    _navigator = None


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

    def display_summary(self, educational: bool = True) -> str:
        lines = [
            f"pantocraft // Field Consultation",
            f"BBL: {self.bbl}  |  {self.address}",
            f"Project: {self.project_type}",
            f"",
            f"Agency pathway ({len(self.agency_pathway)} agencies):",
        ]
        for s in self.agency_pathway:
            cond_tag = " [triggered]" if s.get("is_conditional") else ""
            seq = ", ".join(s.get("sequential_after", [])) or "—"
            lines.append(
                f"  {s.get('status','READY'):<8} {s.get('code','?'):<12} "
                f"~{s.get('estimated_days',0)}d  seq:{seq}{cond_tag}"
            )
        lines += [
            f"",
            f"Standard critical path: ~{self.critical_path_days} days",
            f"Optimized:              ~{self.optimized_days} days  (saves ~{self.days_saved} days)",
        ]
        if self.optimization_tracks:
            lines.append(f"Tracks: {', '.join(self.optimization_tracks)}")
        if self.stale_agencies:
            lines.append(f"\n⚠ Stale data (confidence < 70%): {', '.join(self.stale_agencies)} — verify before relying.")
        if self.escalation_flags or self.pantocraft_flags:
            lines.append("\nFlags:")
            for f in self.escalation_flags + self.pantocraft_flags:
                lines.append(f"  ⚑ {f[:120]}")
        if educational and _KERNEL_AVAILABLE:
            lines.append("\n── What each agency means ──")
            lines.append(_explain_pathway(self.agency_pathway, verbose=False))
        lines.append(f"\n⚖  Information only. Licensed professional sign-off required.")
        return "\n".join(lines)

    def to_llm_context(self) -> str:
        """TOON-format context for LLM generation (~40% fewer tokens than verbose form)."""
        # AXI: pre-computed aggregates inline, TOON key:val pairs, no redundant labels
        seq = "→".join(
            s.get("code", "") + ("*" if s.get("blocking") else "")
            for s in self.agency_pathway
        )
        n_agencies = len(self.agency_pathway)
        flags = self.escalation_flags[:2]
        flag_str = " | ".join(f[:80] for f in flags) if flags else "none"
        saves = f" save:~{self.days_saved}d" if self.days_saved > 0 else ""
        conf = f" conf:{self.overall_confidence:.0%}" if self.overall_confidence < 1.0 else ""
        return (
            f"prop:{self.address} bbl:{self.bbl}\n"
            f"type:{self.project_type} agencies:{n_agencies} "
            f"critical:~{self.critical_path_days}d opt:~{self.optimized_days}d{saves}{conf}\n"
            f"seq:{seq}\n"
            f"flags:{flag_str}\n"
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
            agency_steps = self._resolve_pathway(
                dob_filing_type, property_flags, bbl
            )

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

        # Private agentic log — no PII, no BBL-to-client linkage, no raw prompt
        try:
            from agentic.session_log import AgenticLog
            _log = AgenticLog(engagement_id)
            _log.query(
                pathway_type=dob_filing_type,
                conditions_count=len([s for s in agency_steps if s.get("is_conditional")]),
                step_count=len(agency_steps),
            )
            if stale:
                _log.warning(f"Stale agencies: {stale}", flags=[f"stale:{c}" for c in stale])
            if escalation:
                _log.decision("Escalation flags present", flags=["escalation"])
            if tracks:
                _log.decision(f"Optimization tracks applied: {tracks}", confidence=result.overall_confidence)
            _log.flush()
        except Exception:
            pass  # logging must never break field queries

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

    def _resolve_pathway(
        self,
        dob_filing_type: str,
        property_flags: dict,
        bbl: str,
    ) -> list[dict]:
        """
        Resolve the full agency pathway using moswalk-kernel when available,
        falling back to a minimal DOB-only stub if kernel is not on path.
        """
        if not _KERNEL_AVAILABLE or _navigator is None:
            return self._stub_pathway(dob_filing_type, bbl)

        # Map DOB filing type to kernel pathway_type
        filing_to_pathway = {
            "NB":  "new_building",
            "A1":  "alteration_type_1",
            "A2":  "alteration_type_2",
            "A3":  "alteration_type_3",
            "TR6": "fisp_facade",
            "PA":  "place_of_assembly",
        }
        pathway_type = filing_to_pathway.get(dob_filing_type.upper(), "alteration_type_2")

        # Run trigger scanner on property flags
        trigger_result = _trigger_scan(property_flags)

        # Resolve full pathway from kernel
        pathway = _navigator.resolve(pathway_type, trigger_result.conditions)

        # Convert AgencyStep objects to plain dicts (FieldAPI expects dicts)
        return [step.to_dict() for step in pathway.steps]

    def _stub_pathway(self, dob_filing_type: str, bbl: str = "") -> list[dict]:
        """Minimal DOB-only stub when moswalk-kernel is not available on this node."""
        return [{
            "code": "DOB",
            "role": "primary",
            "status": "READY",
            "blocking": True,
            "sequential_after": [],
            "estimated_days": 45,
            "confidence": 0.80,
            "notes": (
                f"DOB {dob_filing_type} filing. "
                "moswalk-kernel not available on this node — install kernel for full pathway. "
                f"BBL: {bbl}"
            ),
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
