"""
moswalk-kernel — agency_navigator

Two-engine pathway resolver:
  Engine 1 — Canonical law: reads permit_pathways.yaml
  Engine 2 — OTI org chart: reads agencies/agencies.yaml (falls back to iphone-llm/agencies.yaml)

Given a pathway_type + TriggerResult, returns an ordered list of agency steps
sorted by topological dependency (sequential_after), with educational metadata
from agencies.yaml attached to each step.

This is the "by the book" layer. It encodes only what is formally mandated.
No professional strategy. No edge weights. That belongs in pantocraft //.

Source authorities:
  NYC Building Code 2022, NYC Zoning Resolution, agency-specific rules
  NYC OTI agency registry (data.cityofnewyork.us/d/t3jq-9nkf/ — April 2026)

Usage:
    from moswalk-kernel.agencies.agency_navigator import AgencyNavigator
    nav = AgencyNavigator()
    steps = nav.resolve("alteration_type_2", trigger_result)
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

# Path resolution: anchored to __file__, works from any cwd.
# parents[0] = moswalk-kernel/agencies/
# parents[1] = moswalk-kernel/            ← kernel root
# parents[2] = repo root (LLMs-from-scratch/)
_KERNEL   = Path(__file__).parents[1]   # moswalk-kernel/
_REPO     = _KERNEL.parent              # repo root
_PATHWAYS = _KERNEL / "compliance" / "permit_pathways.yaml"
# agencies.yaml canonical location: moswalk-kernel/agencies/agencies.yaml (preferred)
# fallback: iphone-llm/agencies.yaml (legacy — kept for backward compat with sim layer)
_AGENCIES_PRIMARY  = _KERNEL / "agencies" / "agencies.yaml"
_AGENCIES_FALLBACK = _REPO / "iphone-llm" / "agencies.yaml"
_AGENCIES = _AGENCIES_PRIMARY if _AGENCIES_PRIMARY.exists() else _AGENCIES_FALLBACK


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AgencyStep:
    """
    Single resolved step in a permit pathway.
    Combines permit_pathways.yaml data with OTI org chart metadata.
    """
    code: str
    role: str
    sequential_after: list[str]
    blocking: bool
    confidence: float
    estimated_days: int
    notes: str

    # From agencies.yaml (OTI registry)
    full_name: str = ""
    agency_type: str = ""
    reports_to_dm: str = ""
    has_public_portal: bool = False
    principal_officer_title: str = ""

    # Resolution state
    is_conditional: bool = False
    triggered_by: str = ""
    is_optimizable: bool = False   # pantocraft // can accelerate this step

    def to_dict(self) -> dict:
        return {
            "code":             self.code,
            "role":             self.role,
            "sequential_after": self.sequential_after,
            "blocking":         self.blocking,
            "confidence":       self.confidence,
            "estimated_days":   self.estimated_days,
            "notes":            self.notes,
            "full_name":        self.full_name,
            "reports_to_dm":    self.reports_to_dm,
            "is_conditional":   self.is_conditional,
            "triggered_by":     self.triggered_by,
            "status":           "READY",
        }


@dataclass
class PathwayResult:
    """Full resolved pathway for a project type + property flags."""
    pathway_type: str
    description: str
    dob_filing_type: Optional[str]
    steps: list[AgencyStep]
    critical_path_days: int = 0
    has_hard_blockers: bool = False
    warnings: list[str] = field(default_factory=list)

    def critical_path(self) -> list[AgencyStep]:
        return [s for s in self.steps if s.blocking]

    def critical_days(self) -> int:
        return sum(s.estimated_days for s in self.critical_path())

    def parallel_days(self) -> int:
        """Non-blocking steps that can run concurrently with the critical path."""
        parallel = [s for s in self.steps if not s.blocking]
        return max((s.estimated_days for s in parallel), default=0)

    def total_calendar_days(self) -> int:
        return max(self.critical_days(), self.parallel_days())

    def summary_table(self) -> str:
        lines = [
            f"{'STATUS':<8} {'AGENCY':<14} {'ROLE':<14} {'DAYS':>5} {'BLOCKING':<10} {'SEQ AFTER'}",
            "-" * 80,
        ]
        for s in self.steps:
            seq = ", ".join(s.sequential_after) if s.sequential_after else "—"
            blocking_str = "BLOCKING" if s.blocking else "parallel"
            lines.append(
                f"{'READY':<8} {s.code:<14} {s.role:<14} {s.estimated_days:>5} "
                f"{blocking_str:<10} {seq}"
            )
        lines += [
            "-" * 80,
            f"Critical path: ~{self.critical_days()} days  |  "
            f"Total calendar: ~{self.total_calendar_days()} days",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Loader helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_agency_index(agencies_yaml: dict) -> dict[str, dict]:
    """Build code → agency metadata dict from agencies.yaml."""
    index: dict[str, dict] = {}
    for agency in agencies_yaml.get("agencies", []):
        code = agency.get("code", "")
        if code:
            index[code] = agency
        for alt in agency.get("alt_names", []):
            index[alt] = agency
    return index


# ---------------------------------------------------------------------------
# Condition matcher
# ---------------------------------------------------------------------------

def _condition_matches(condition_str: str, active_conditions: frozenset[str]) -> bool:
    """
    Case-insensitive substring match.
    permit_pathways.yaml conditions are human-readable English phrases.
    trigger_scanner.py produces matching strings.
    """
    cl = condition_str.lower()
    for active in active_conditions:
        if cl in active.lower() or active.lower() in cl:
            return True
    return False


# ---------------------------------------------------------------------------
# Topological sort (resolves sequential_after dependencies)
# ---------------------------------------------------------------------------

def _topological_sort(steps: list[AgencyStep]) -> list[AgencyStep]:
    """
    Sort agency steps so that no step appears before its sequential_after deps.
    Steps with no deps come first; ties broken by estimated_days (ascending).
    """
    code_map = {s.code: s for s in steps}
    visited: set[str] = set()
    result: list[AgencyStep] = []

    def visit(code: str):
        if code in visited:
            return
        visited.add(code)
        step = code_map.get(code)
        if step is None:
            return
        for dep in step.sequential_after:
            visit(dep)
        result.append(step)

    for step in sorted(steps, key=lambda s: s.estimated_days):
        visit(step.code)

    return result


# ---------------------------------------------------------------------------
# Main navigator
# ---------------------------------------------------------------------------

class AgencyNavigator:
    """
    Two-engine pathway resolver.

    Engine 1 — permit_pathways.yaml: canonical agency sequences + conditions
    Engine 2 — agencies.yaml: OTI org chart metadata attached to each step
    """

    def __init__(
        self,
        pathways_yaml: Optional[Path] = None,
        agencies_yaml: Optional[Path] = None,
    ):
        pw_path  = pathways_yaml or _PATHWAYS
        ag_path  = agencies_yaml or _AGENCIES
        self._pathways = _load_yaml(pw_path)["pathways"]
        self._agencies = _build_agency_index(_load_yaml(ag_path))

    def available_pathway_types(self) -> list[str]:
        return list(self._pathways.keys())

    def resolve(
        self,
        pathway_type: str,
        conditions: "frozenset[str] | set[str] | None" = None,
    ) -> PathwayResult:
        """
        Resolve the full agency pathway for pathway_type + active conditions.

        pathway_type must be one of the keys in permit_pathways.yaml:
            new_building | alteration_type_1 | alteration_type_2 |
            alteration_type_3 | fisp_facade | sidewalk_cafe |
            adu_legalization | place_of_assembly

        conditions: frozenset[str] from TriggerResult.conditions
        """
        if pathway_type not in self._pathways:
            available = ", ".join(self.available_pathway_types())
            raise ValueError(
                f"Unknown pathway_type '{pathway_type}'. "
                f"Available: {available}"
            )

        if conditions is None:
            conditions = frozenset()

        pw = self._pathways[pathway_type]
        description   = pw.get("description", "")
        dob_filing    = pw.get("dob_filing_type")
        warnings: list[str] = []

        steps: list[AgencyStep] = []

        # ── Engine 1a: mandatory agencies ──────────────────────────────────
        for raw in pw.get("agencies", []):
            step = self._build_step(raw, is_conditional=False, triggered_by="")
            if step.confidence < 0.70:
                warnings.append(
                    f"{step.code}: confidence {step.confidence:.0%} — data may be stale. "
                    "Verify before relying on this step."
                )
            steps.append(step)

        # ── Engine 1b: conditional agencies ────────────────────────────────
        # inject_before: when a conditional agency must precede a base agency
        # (e.g. LPC before DOB for landmark properties), collect those constraints
        # and patch the target base agency's sequential_after after dedup.
        inject_constraints: list[tuple[str, str]] = []  # (conditional_code, target_code)

        for conditional in pw.get("conditional_agencies", []):
            cond_str = conditional.get("condition", "")
            if _condition_matches(cond_str, conditions):
                raw_agency = conditional.get("add_agency", {})
                step = self._build_step(
                    raw_agency,
                    is_conditional=True,
                    triggered_by=cond_str,
                )
                if step.confidence < 0.70:
                    warnings.append(
                        f"{step.code} (conditional): confidence {step.confidence:.0%} — flag as stale."
                    )
                steps.append(step)
                for target in raw_agency.get("inject_before", []):
                    inject_constraints.append((step.code, target))

        # ── Deduplication: keep highest-confidence copy of each agency code ─
        seen: dict[str, AgencyStep] = {}
        for step in steps:
            if step.code not in seen or step.confidence > seen[step.code].confidence:
                seen[step.code] = step
        steps = list(seen.values())

        # ── Apply inject_before constraints ─────────────────────────────────
        # For each (conditional_code → target_code) pair, add conditional_code
        # to target's sequential_after so the topological sort places it first.
        code_map = {s.code: s for s in steps}
        for cond_code, target_code in inject_constraints:
            target = code_map.get(target_code)
            if target and cond_code not in target.sequential_after:
                target.sequential_after = list(target.sequential_after) + [cond_code]

        # ── Engine 2: attach OTI org chart metadata ─────────────────────────
        for step in steps:
            meta = self._agencies.get(step.code) or self._agencies.get(step.full_name)
            if meta:
                step.full_name              = meta.get("name", step.code)
                step.agency_type            = meta.get("type", "")
                step.reports_to_dm          = meta.get("reports_to_dm", "")
                step.has_public_portal      = bool(meta.get("has_public_portal", False))
                step.principal_officer_title = meta.get("principal_officer_title", "")

        # ── Topological sort ────────────────────────────────────────────────
        ordered = _topological_sort(steps)

        # ── Hard blocker detection ──────────────────────────────────────────
        has_blockers = any(
            "INELIGIBLE" in s.notes.upper() or s.estimated_days == 0
            for s in ordered
            if s.blocking and s.is_conditional
        )

        critical_days = sum(s.estimated_days for s in ordered if s.blocking)

        return PathwayResult(
            pathway_type=pathway_type,
            description=description,
            dob_filing_type=dob_filing,
            steps=ordered,
            critical_path_days=critical_days,
            has_hard_blockers=has_blockers,
            warnings=warnings,
        )

    def _build_step(self, raw: dict, is_conditional: bool, triggered_by: str) -> AgencyStep:
        return AgencyStep(
            code=raw.get("code", "UNKNOWN"),
            role=raw.get("role", ""),
            sequential_after=raw.get("sequential_after", []),
            blocking=raw.get("blocking", True),
            confidence=float(raw.get("confidence", 0.70)),
            estimated_days=int(
                raw.get("estimated_days", 0)
                or raw.get("typical_days", 0)
            ),
            notes=raw.get("notes", ""),
            is_conditional=is_conditional,
            triggered_by=triggered_by,
        )

    def explain_agency(self, code: str) -> str:
        """Return OTI org chart metadata for a given agency code."""
        meta = self._agencies.get(code)
        if not meta:
            return f"{code}: not found in OTI registry."
        lines = [
            f"{code} — {meta.get('name', code)}",
            f"  Type:      {meta.get('type', 'unknown')}",
            f"  Reports to: {meta.get('reports_to_dm', 'N/A')}",
            f"  Portal:    {'yes' if meta.get('has_public_portal') else 'no'}",
        ]
        return "\n".join(lines)

    def escalation_chain(self, codes: list[str]) -> list[str]:
        """
        Return the set of Deputy Mayor chains involved.
        Multiple chains = escalation risk (requires two DM sign-offs).
        """
        chains: set[str] = set()
        for code in codes:
            meta = self._agencies.get(code)
            if meta:
                dm = meta.get("reports_to_dm", "")
                if dm:
                    chains.add(dm)
        return sorted(chains)


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from property.trigger_scanner import scan

    nav = AgencyNavigator()
    print("Available pathway types:", nav.available_pathway_types())
    print()

    # SIM-001: A2 alteration, LPC historic district
    trigger = scan({
        "landmarked": True,
        "landmark_type": "historic_district",
        "year_built": 1895,
        "open_violations": 0,
        "stories": 3,
        "zoning_district": "R6B",
    })
    result = nav.resolve("alteration_type_2", trigger.conditions)
    print(f"SIM-001 — {result.description}")
    print(result.summary_table())
    if result.warnings:
        print("Warnings:", result.warnings)
    print()

    # SIM-002: ADU, flood zone AE
    trigger2 = scan({
        "flood_zone": "AE",
        "open_violations": 2,
        "zoning_district": "R3-2",
        "occupied_before_2024": True,
    })
    result2 = nav.resolve("adu_legalization", trigger2.conditions)
    print(f"SIM-002 — {result2.description}")
    print(result2.summary_table())
    print("Blockers:", trigger2.blocker_flags())
