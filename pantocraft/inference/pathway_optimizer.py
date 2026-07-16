# pantocraft // — pathway optimizer
#
# Takes a moswalk-kernel agency pathway and applies edge weights to produce
# an optimized consultation: fastest legal route, risks surfaced, professional
# tracks identified.
#
# LEGAL: All outputs are regulatory information retrieval, not professional advice.
# A licensed professional (RA, PE, expediter, attorney) must validate all
# recommendations before client action. Required per NY S7263 risk framework.

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import yaml

# Kernel import (moswalk-kernel must be on path)
_KERNEL = Path(__file__).parents[2] / "moswalk-kernel"
if str(_KERNEL) not in sys.path:
    sys.path.insert(0, str(_KERNEL))

_PANTOCRAFT = Path(__file__).parent
_EDGE_WEIGHTS_PATH = _PANTOCRAFT / "edge_weights.yaml"


@dataclass
class OptimizedStep:
    agency_code: str
    standard_days: int
    optimized_days: int
    speed_track: Optional[str]
    speed_multiplier: float
    professional_note: str
    risk: str
    confidence: float
    is_optimized: bool

    @property
    def days_saved(self) -> int:
        return self.standard_days - self.optimized_days

    @property
    def risk_level(self) -> str:
        if self.confidence >= 0.90:
            return "LOW"
        elif self.confidence >= 0.75:
            return "MEDIUM"
        return "HIGH"


@dataclass
class OptimizedPathway:
    client_id: str
    project_type: str
    steps: list[OptimizedStep] = field(default_factory=list)
    standard_critical_days: int = 0
    optimized_critical_days: int = 0
    total_savings_days: int = 0
    flags: list[str] = field(default_factory=list)
    legal_disclaimer: str = (
        "INFORMATION ONLY — not legal, architectural, or professional advice. "
        "A licensed professional must review before any action. "
        "pantocraft // is decision support, not decision making."
    )

    def summary(self) -> str:
        lines = [
            f"pantocraft // Optimized Pathway — {self.client_id}",
            f"Project: {self.project_type}",
            f"Standard timeline: ~{self.standard_critical_days} days",
            f"Optimized timeline: ~{self.optimized_critical_days} days",
            f"Potential savings: ~{self.total_savings_days} days",
            "",
            "STEPS:",
        ]
        for s in self.steps:
            tag = f"  [{s.speed_track}]" if s.is_optimized else "  [standard]"
            lines.append(
                f"  {s.agency_code:<12} {s.standard_days:>3}d → {s.optimized_days:>3}d"
                f"{tag}  risk={s.risk_level}  conf={s.confidence:.0%}"
            )
            if s.is_optimized:
                lines.append(f"    → {s.professional_note[:120]}…"
                             if len(s.professional_note) > 120
                             else f"    → {s.professional_note}")

        if self.flags:
            lines.append("\nFLAGS:")
            for f in self.flags:
                lines.append(f"  ⚑ {f}")

        lines.extend(["", f"⚖  {self.legal_disclaimer}"])
        return "\n".join(lines)


class PathwayOptimizer:
    """
    Applies pantocraft // edge weights to a kernel agency pathway.
    Produces an optimized consultation with professional tracks surfaced.
    """

    def __init__(self, edge_weights_path: Path = _EDGE_WEIGHTS_PATH):
        with open(edge_weights_path) as f:
            raw = yaml.safe_load(f)
        # Index by agency code → list of applicable tracks
        self._weights: dict[str, list[dict]] = {}
        for w in raw.get("edge_weights", []):
            code = w["agency"]
            self._weights.setdefault(code, []).append(w)

    def optimize(
        self,
        client_id: str,
        project_type: str,
        agency_steps: list[dict],
        project_flags: Optional[dict] = None,
    ) -> OptimizedPathway:
        """
        agency_steps: list of dicts from AgencyGraph.resolve() in sim_runner
        project_flags: PropertyFlags dict for conditional track eligibility
        """
        project_flags = project_flags or {}
        optimized_steps: list[OptimizedStep] = []
        standard_critical = 0
        optimized_critical = 0
        pathway_flags: list[str] = []

        for step in agency_steps:
            if step["status"] in ("BLOCKED", "STUCK"):
                continue

            code = step["code"]
            standard_days = step["estimated_days"]
            best_track = self._best_track(code, step, project_flags)

            if best_track:
                opt_days = max(1, int(standard_days / best_track["speed_multiplier"]))
                os = OptimizedStep(
                    agency_code=code,
                    standard_days=standard_days,
                    optimized_days=opt_days,
                    speed_track=best_track["track"],
                    speed_multiplier=best_track["speed_multiplier"],
                    professional_note=best_track["professional_note"].strip(),
                    risk=best_track["risk"].strip(),
                    confidence=best_track["confidence"],
                    is_optimized=True,
                )
            else:
                os = OptimizedStep(
                    agency_code=code,
                    standard_days=standard_days,
                    optimized_days=standard_days,
                    speed_track=None,
                    speed_multiplier=1.0,
                    professional_note="Standard review — no optimization track identified.",
                    risk="No additional risk beyond standard process.",
                    confidence=step["confidence"],
                    is_optimized=False,
                )

            optimized_steps.append(os)

            if step["blocking"]:
                standard_critical += standard_days
                optimized_critical += os.optimized_days

        # Surface specific flags
        self._add_pathway_flags(agency_steps, project_flags, pathway_flags)

        result = OptimizedPathway(
            client_id=client_id,
            project_type=project_type,
            steps=optimized_steps,
            standard_critical_days=standard_critical,
            optimized_critical_days=optimized_critical,
            total_savings_days=standard_critical - optimized_critical,
            flags=pathway_flags,
        )
        return result

    def _best_track(
        self,
        code: str,
        step: dict,
        flags: dict,
    ) -> Optional[dict]:
        """Return the highest speed_multiplier applicable track for this agency step."""
        candidates = self._weights.get(code, [])
        eligible = []
        for w in candidates:
            # Basic eligibility: confidence must be reasonable and speed must help
            if w["confidence"] >= 0.65 and w["speed_multiplier"] > 1.0:
                eligible.append(w)
        if not eligible:
            return None
        return max(eligible, key=lambda w: w["speed_multiplier"])

    def _add_pathway_flags(
        self,
        agency_steps: list[dict],
        project_flags: dict,
        out_flags: list[str],
    ) -> None:
        codes = {s["code"] for s in agency_steps}

        # NY S7263 compliance flag — always surface
        out_flags.append(
            "NY S7263 (pending 2026): All outputs are regulatory information, not professional advice. "
            "Licensed professional sign-off required before client action."
        )

        # SHIELD Act — if client data stored
        out_flags.append(
            "NY SHIELD Act: Client project data must be encrypted at rest. "
            "Do not store owner PII and public BBL data in the same store."
        )

        # Cross-DM escalation
        if "DOB" in codes and "NYC DOT" in codes:
            out_flags.append(
                "ESCALATION RISK: DOB (Housing & Planning DM) and NYC DOT (Operations DM) "
                "are in different Deputy Mayor chains. Cross-DM conflicts require two DM sign-offs."
            )

        # BSA warning
        if "BSA" in codes:
            out_flags.append(
                "BSA is quasi-judicial (no reports_to). File Pre-Determination in DOB NOW "
                "before investing in full variance application (saves 4-6 months if unfavorable)."
            )

        # Flood zone
        if project_flags.get("flood_zone") in ("AE", "VE"):
            out_flags.append(
                f"FLOOD ZONE {project_flags['flood_zone']}: ADU pilot program INELIGIBLE. "
                "Flood-resistant construction mandatory (NYC BC Appendix G). "
                "Consider FEMA LOMA if lot elevation is above BFE."
            )

        # Asbestos
        if project_flags.get("asbestos_survey_required"):
            out_flags.append(
                "PRE-1987 CONSTRUCTION: Asbestos survey required before ANY demolition. "
                "Limit survey scope to disturbed area only — saves cost and time. "
                "DEP-certified inspector required (not the contractor)."
            )

        # Stale confidence
        stale = [s["code"] for s in agency_steps if s.get("confidence", 1.0) < 0.70]
        if stale:
            out_flags.append(
                f"STALE DATA: Confidence < 0.70 for {stale}. "
                "Verify against current agency rules before advising client."
            )
