# Simulation runner for moswalk client projects.
#
# Drives each simulated client through the agency graph:
#   load client YAML → build consultation prompt → run agency pathway analysis
#   → generate report → flag risks and sequencing violations
#
# In production: coordinator.generate(tokenize(client.prompt())) provides
# the LLM response. In sim mode (no model weights): the runner uses the
# deterministic agency graph alone and produces a structured text report.
#
# Privacy: client YAMLs contain synthetic data only. BBLs are real NYC lots
# but all names, ownership, and project details are simulated.
# Security: do not log raw prompts to disk in production — they may contain
# client-supplied PII from field intake.

from __future__ import annotations

import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from client_schema import (
    AgencyRequirement, EscalationRisk, ProjectScope,
    SimClient, load_all_clients,
)


# ---------------------------------------------------------------------------
# Agency graph resolver
# ---------------------------------------------------------------------------

class AgencyGraph:
    """
    Resolves the agency pathway for a client project.
    Enforces sequential_after and blocking constraints from client YAML.
    Mirrors the rules in .claude/rules/agency-sequencing.md.
    """

    def __init__(self, agencies: list[AgencyRequirement]):
        self.agencies = {a.code: a for a in agencies}
        self._resolved: set[str] = set()
        self._blocked:  set[str] = set()

    def resolve(self) -> list[dict]:
        """
        Topological resolution of the agency pathway.
        Returns ordered list of agency steps with status annotations.
        """
        steps = []
        remaining = list(self.agencies.values())
        max_iters = len(remaining) * 2

        for _ in range(max_iters):
            if not remaining:
                break
            progress = False
            for agency in list(remaining):
                # Check if all sequential_after dependencies are resolved
                deps = agency.sequential_after
                unresolved_deps = [d for d in deps if d not in self._resolved]
                blocked_deps    = [d for d in deps if d in self._blocked]

                if blocked_deps:
                    # A blocking dependency failed — this agency is blocked
                    self._blocked.add(agency.code)
                    remaining.remove(agency)
                    steps.append(self._step(agency, "BLOCKED",
                        f"Blocked: dependency {blocked_deps[0]} is unresolved/blocking"))
                    progress = True
                    continue

                if unresolved_deps:
                    continue  # wait for dependencies

                # All deps resolved — this agency is ready
                status = self._evaluate(agency)
                steps.append(self._step(agency, status))
                if status == "READY":
                    self._resolved.add(agency.code)
                elif agency.blocking:
                    self._blocked.add(agency.code)
                remaining.remove(agency)
                progress = True

            if not progress:
                # Cycle detected or unresolvable — mark remaining as STUCK
                for agency in remaining:
                    steps.append(self._step(agency, "STUCK", "Dependency cycle or missing agency"))
                break

        return steps

    def _evaluate(self, agency: AgencyRequirement) -> str:
        """Determine status for a ready agency."""
        if agency.confidence < 0.70:
            return "STALE"      # agency-sequencing rule: surface stale flag
        return "READY"

    def _step(self, agency: AgencyRequirement, status: str, override_note: str = "") -> dict:
        return {
            "code":            agency.code,
            "role":            agency.role,
            "status":          status,
            "blocking":        agency.blocking,
            "sequential_after": agency.sequential_after,
            "estimated_days":  agency.estimated_days,
            "confidence":      agency.confidence,
            "notes":           override_note or agency.notes.strip(),
        }

    @property
    def critical_path_days(self) -> int:
        """Sum days for blocking agencies in resolution order."""
        return sum(
            a.estimated_days for a in self.agencies.values()
            if a.blocking
        )

    def escalation_flags(self, client: SimClient) -> list[str]:
        """
        Apply cross-agency escalation rules per agency-sequencing.md:
        - DOB (Housing DM) vs DOT (Operations DM) conflict → high risk
        - confidence < 0.70 → stale flag
        - blocking unresolved → halt signal
        """
        flags = []
        codes = set(self.agencies.keys())

        if "DOB" in codes and "NYC DOT" in codes:
            flags.append(
                "ESCALATION: DOB reports to Deputy Mayor for Housing & Planning; "
                "NYC DOT reports to Deputy Mayor for Operations. "
                "Conflicts require two separate Deputy Mayor sign-offs — flag as escalation_risk: high."
            )

        stale = [a.code for a in self.agencies.values() if a.confidence < 0.70]
        if stale:
            flags.append(f"STALE DATA: Confidence < 0.70 for {stale}. "
                         "Do not proceed silently — surface to client for verification.")

        blocking_codes = [a.code for a in self.agencies.values() if a.blocking]
        if blocking_codes:
            flags.append(f"BLOCKING AGENCIES: {blocking_codes}. "
                         "If any remain unresolved, all downstream agencies halt.")

        if client.project.escalation_risk in (EscalationRisk.HIGH, EscalationRisk.MEDIUM):
            flags.append(f"Project-level escalation risk: {client.project.escalation_risk.value.upper()}")

        return flags


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------

def run_client(client: SimClient, verbose: bool = True) -> dict:
    """
    Run a single client through the agency graph and produce a consultation report.
    Returns structured report dict.
    """
    t0 = time.perf_counter()

    graph = AgencyGraph(client.project.agencies)
    steps = graph.resolve()
    esc_flags = graph.escalation_flags(client)

    duration_ms = (time.perf_counter() - t0) * 1000

    report = {
        "client_id":          client.client_id,
        "client_name":        client.name,
        "client_type":        client.client_type.value,
        "property": {
            "address":        client.property.address,
            "borough":        client.property.borough.value,
            "bbl":            client.property.bbl,
            "zoning":         client.property.zoning_district,
            "year_built":     client.property.year_built,
        },
        "project": {
            "type":           client.project.type,
            "scope":          client.project.scope.value,
            "estimated_cost": f"${client.project.estimated_cost_usd:,}",
            "escalation_risk": client.project.escalation_risk.value,
        },
        "agency_pathway":     steps,
        "critical_path_days": graph.critical_path_days,
        "escalation_flags":   esc_flags,
        "analyst_notes":      client.project.analyst_notes,
        "property_flags": {
            k: v for k, v in vars(client.property.flags).items()
            if v not in (False, None, 0)
        },
        "prompt_preview":     client.prompt()[:400] + "…",
        "sim_duration_ms":    round(duration_ms, 2),
    }

    if verbose:
        _print_report(report)

    return report


def _print_report(r: dict) -> None:
    sep = "─" * 68
    print(f"\n{sep}")
    print(f"  {r['client_id']} — {r['client_name']} ({r['client_type']})")
    print(f"  {r['property']['address']}  [{r['property']['bbl']}]")
    print(f"  {r['project']['type']} · DOB-{r['project']['scope']} · {r['project']['estimated_cost']}")
    print(sep)

    print("\n  AGENCY PATHWAY:")
    for s in r["agency_pathway"]:
        blocking_tag = " [BLOCKING]" if s["blocking"] else ""
        stale_tag    = " ⚠ STALE"   if s["status"] == "STALE" else ""
        seq_tag      = f" (after: {', '.join(s['sequential_after'])})" if s["sequential_after"] else ""
        print(f"    {s['status']:<8}  {s['code']:<12} {s['role']:<14} "
              f"~{s['estimated_days']:>3}d  conf={s['confidence']:.0%}"
              f"{blocking_tag}{stale_tag}{seq_tag}")

    print(f"\n  Critical path: ~{r['critical_path_days']} days")
    print(f"  Escalation risk: {r['project']['escalation_risk'].upper()}")

    if r["escalation_flags"]:
        print("\n  ⚠ ESCALATION FLAGS:")
        for f in r["escalation_flags"]:
            print(f"    · {f}")

    if r["property_flags"]:
        print("\n  PROPERTY FLAGS:")
        for k, v in r["property_flags"].items():
            print(f"    {k}: {v}")

    if r["analyst_notes"]:
        print("\n  ANALYST NOTES:")
        for n in r["analyst_notes"]:
            print(f"    → {n}")

    print()


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_all(
    sim_dir: Optional[Path] = None,
    save_reports: bool = True,
    verbose: bool = True,
) -> list[dict]:
    """
    Load all client YAMLs and run each through the agency graph.
    Optionally saves JSON reports to sim/reports/.
    """
    if sim_dir is None:
        sim_dir = Path(__file__).parent

    clients = load_all_clients(sim_dir / "clients")
    reports = []

    print(f"moswalk Simulation Runner")
    print(f"Loading {len(clients)} client projects from {sim_dir / 'clients'}")
    print(f"{'='*68}")

    for client in clients:
        report = run_client(client, verbose=verbose)
        reports.append(report)

        if save_reports:
            out_dir = sim_dir / "reports"
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / f"{client.client_id}.json"
            with open(out_path, "w") as f:
                json.dump(report, f, indent=2)

    # Summary table
    print(f"\n{'='*68}")
    print(f"  SIMULATION SUMMARY — {len(clients)} clients")
    print(f"  {'ID':<10} {'Risk':<8} {'Days':<6} {'Agencies':<10} {'Cost'}")
    print(f"  {'-'*60}")
    for r in reports:
        n_agencies = len(r["agency_pathway"])
        print(f"  {r['client_id']:<10} {r['project']['escalation_risk']:<8} "
              f"{r['critical_path_days']:<6} {n_agencies:<10} {r['project']['estimated_cost']}")

    total_cost = sum(
        c.project.estimated_cost_usd for c in clients
    )
    print(f"\n  Total simulated project value: ${total_cost:,}")
    print(f"  Average critical path: "
          f"{sum(r['critical_path_days'] for r in reports) // len(reports)} days")

    return reports


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))

    verbose = "--quiet" not in sys.argv
    save    = "--no-save" not in sys.argv

    reports = run_all(verbose=verbose, save_reports=save)
    print(f"\nDone. {len(reports)} reports generated.")
