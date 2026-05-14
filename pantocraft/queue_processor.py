# pantocraft // — Queue Processor
#
# Watches pantocraft/queue/ for request files and routes them to the correct
# handler. Output lands in pantocraft/generated/. Processed files move to
# pantocraft/queue/processed/ — never deleted (audit trail).
#
# Trigger patterns (filename → handler):
#   CONSULT-[bbl]-[filing_type].md  → field consultation via FieldAPI
#   RESEARCH-[topic].md             → regulatory research brief
#   PREMORTEM-[project].md          → premortem analysis
#   INTAKE-[source].md              → intelligence intake filter (Q1–Q4)
#
# Run modes:
#   python queue_processor.py           → process all pending, exit
#   python queue_processor.py --watch   → watch folder, process on new file
#
# Tailscale cron: every 30 min on Inference node
#   */30 * * * * cd /path/to/repo && python pantocraft/queue_processor.py

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT       = Path(__file__).parents[1]
_PANTOCRAFT = Path(__file__).parent
_QUEUE      = _PANTOCRAFT / "queue"
_PROCESSED  = _QUEUE / "processed"
_GENERATED  = _PANTOCRAFT / "generated"
_VAULT      = _PANTOCRAFT / "vault" / "MOSWALK.md"

for p in [str(_ROOT / "moswalk-kernel"), str(_PANTOCRAFT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from field.mobile_api import FieldAPI
    _FIELD_AVAILABLE = True
except ImportError:
    _FIELD_AVAILABLE = False

try:
    from agentic.hep import hep_from_pathway_result, write_hep, classify_filing_mode
    from agentic.session_log import AgenticLog
    _AGENTIC_AVAILABLE = True
except ImportError:
    _AGENTIC_AVAILABLE = False

try:
    from archive.flywheel import JobRecord, write_job, archive_summary_toon, ArchiveQuery
    _ARCHIVE_AVAILABLE = True
except ImportError:
    _ARCHIVE_AVAILABLE = False


# ---------------------------------------------------------------------------
# File routing
# ---------------------------------------------------------------------------

_PROTOCOL_RE = re.compile(
    r"^(CONSULT|RESEARCH|PREMORTEM|INTAKE)-(.+)\.md$",
    re.IGNORECASE,
)


def route(path: Path) -> str:
    """Process a single queue file. Returns output path."""
    m = _PROTOCOL_RE.match(path.name)
    if not m:
        return _skip(path, f"filename doesn't match any protocol: {path.name}")

    protocol  = m.group(1).upper()
    subject   = m.group(2)
    body      = path.read_text(encoding="utf-8").strip()
    date_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if protocol == "CONSULT":
        out = _handle_consult(subject, body, date_str)
    elif protocol == "RESEARCH":
        out = _handle_research(subject, body, date_str)
    elif protocol == "PREMORTEM":
        out = _handle_premortem(subject, body, date_str)
    elif protocol == "INTAKE":
        out = _handle_intake(subject, body, date_str)
    else:
        return _skip(path, f"unknown protocol: {protocol}")

    _archive(path)
    print(f"  ✓  {path.name}  →  {out}")
    return str(out)


def _archive(path: Path) -> None:
    _PROCESSED.mkdir(exist_ok=True)
    dest = _PROCESSED / f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{path.name}"
    path.rename(dest)


def _skip(path: Path, reason: str) -> str:
    print(f"  ⊘  {path.name}: {reason}")
    return ""


# ---------------------------------------------------------------------------
# CONSULT handler
# ---------------------------------------------------------------------------

def _handle_consult(subject: str, body: str, date_str: str) -> Path:
    """
    CONSULT-[bbl]-[filing_type].md

    File format (YAML-lite):
      bbl: 3-00783-0001
      address: 123 Main St Brooklyn
      engagement_id: ENG-001          # optional, generated if absent
      project: rooftop deck addition
      filing_type: A2                 # NB|A1|A2|A3|TR6 (can also come from filename)
      flags:                          # optional PLUTO flags
        landmarked: true
        year_built: 1895
        flood_zone: null
        open_violations: 0
    """
    params = _parse_kv(body)
    bbl            = params.get("bbl", subject.replace("-", " ", 1))
    address        = params.get("address", bbl)
    engagement_id  = params.get("engagement_id") or f"QUEUE-{date_str}-{_slug(bbl)}"
    project        = params.get("project", "")
    # filing_type from body or from filename suffix
    parts          = subject.split("-")
    filing_type    = params.get("filing_type") or (parts[-1].upper() if len(parts) > 1 else "A2")
    flags          = params.get("flags", {}) or {}
    if isinstance(flags, str):
        flags = {}

    moswalk_ctx = _read_vault()

    # --- Archive query (flywheel intelligence) ---
    archive_signal = ""
    if _ARCHIVE_AVAILABLE:
        borough = _bbl_borough(bbl)
        q = ArchiveQuery(bbl=bbl, borough=borough, filing_type=filing_type)
        archive_signal = archive_summary_toon(q)

    # --- Kernel resolve ---
    out_lines: list[str] = [
        f"# Consultation — {bbl}",
        f"Generated: {date_str}  |  engagement: {engagement_id}",
        f"Project: {project}  |  Filing: {filing_type}",
        "",
    ]

    if archive_signal:
        out_lines += ["## Archive Signal", "```", archive_signal, "```", ""]

    if _FIELD_AVAILABLE:
        try:
            api = FieldAPI()
            result = api.consult(
                engagement_id=engagement_id,
                bbl=bbl,
                address=address,
                borough=_bbl_borough(bbl),
                project_type=project,
                dob_filing_type=filing_type,
                property_flags=flags,
            )
            out_lines.append(result.display_summary(educational=True))
            out_lines.append("")
            out_lines.append("## LLM Context (for generation)")
            out_lines.append("```")
            out_lines.append(result.to_llm_context())
            out_lines.append("```")

            # HEP check
            if _AGENTIC_AVAILABLE and hasattr(result, 'agency_pathway'):
                from agencies.agency_navigator import PathwayResult, AgencyStep
                # Emit HEP if escalation flags present or confidence low
                if result.escalation_flags or result.overall_confidence < 0.80:
                    out_lines.append("")
                    out_lines.append("## HEP Escalation")
                    out_lines.append(f"Flags: {'; '.join(result.escalation_flags[:3])}")
                    out_lines.append(f"Confidence: {result.overall_confidence:.0%}")
                    out_lines.append("→ Review pantocraft/agentic/escalations/ for HEP payload.")

        except Exception as e:
            out_lines.append(f"FieldAPI error: {e}")
            out_lines.append("")
            out_lines.append(_fallback_consult(bbl, filing_type, flags))
    else:
        out_lines.append(_fallback_consult(bbl, filing_type, flags))

    out_lines += [
        "",
        "---",
        f"moswalk context: {_vault_identity(moswalk_ctx)}",
        "⚖  Information only. Licensed professional sign-off required. NY S7263.",
    ]

    out_path = _GENERATED / "consultations" / f"{date_str}-{_slug(bbl)}-{filing_type.lower()}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out_lines), encoding="utf-8")

    # --- Seed flywheel archive (stub record — operator updates outcome/lessons) ---
    if _ARCHIVE_AVAILABLE:
        try:
            # Parse borough from bbl
            borough = _bbl_borough(bbl)
            # Derive block/lot from BBL if formatted as B-BBBBB-LLLL
            parts_bbl = bbl.replace(" ", "-").split("-")
            block = parts_bbl[1] if len(parts_bbl) > 1 else ""
            lot   = parts_bbl[2] if len(parts_bbl) > 2 else ""

            rec = JobRecord(
                engagement_id=engagement_id,
                bbl=bbl,
                borough=borough,
                block=block,
                lot=lot,
                filing_type=filing_type.upper(),
                work_types=[project] if project else [],
                outcome="pending",
                confidence_score=0.0,  # updated by operator once result is known
                pathway_type=filing_type.lower(),
                enforcement_context="current-administration",
            )
            write_job(rec)
        except Exception:
            pass  # archive write is non-blocking; never fail the consultation

    return out_path


def _fallback_consult(bbl: str, filing_type: str, flags: dict) -> str:
    lines = [
        f"## Deterministic Summary (kernel offline)",
        f"BBL: {bbl}  |  Filing: {filing_type}",
        f"Flags: {json.dumps(flags, default=str)[:200]}",
        "",
        "Primary agency: DOB (all filings require DOB review)",
        "Confidence: 0.70 (stub — install moswalk-kernel for full pathway)",
        "",
        "⚑ Cannot resolve full agency pathway — moswalk-kernel not on path.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# RESEARCH handler
# ---------------------------------------------------------------------------

def _handle_research(subject: str, body: str, date_str: str) -> Path:
    """
    RESEARCH-[topic].md

    File format: any text — questions, context, specific angles to investigate.
    Processor reads MOSWALK.md + agencies.yaml + permit_pathways.yaml and
    produces a structured regulatory research brief.
    """
    moswalk_ctx = _read_vault()

    # Pull relevant agency data if kernel available
    agency_hits: list[str] = []
    if _FIELD_AVAILABLE:
        try:
            from agencies.agency_navigator import AgencyNavigator
            nav = AgencyNavigator()
            topic_lower = (subject + " " + body).lower()
            # Simple keyword match against available pathways
            for pt in nav.available_pathway_types():
                if any(kw in topic_lower for kw in [pt.replace("_", " "), pt.replace("_", "")]):
                    result = nav.resolve(pt, frozenset())
                    agency_hits.append(f"Pathway `{pt}`: " + " → ".join(s.code for s in result.steps))
        except Exception:
            pass

    slug = _slug(subject)
    out_lines = [
        f"# Research Brief — {subject.replace('-', ' ').title()}",
        f"Generated: {date_str}",
        "",
        "## Request",
        body,
        "",
        "## Regulatory Context",
        f"Platform: {_vault_identity(moswalk_ctx)}",
    ]

    if agency_hits:
        out_lines += ["", "## Relevant Agency Pathways (deterministic kernel)"]
        out_lines += [f"- {h}" for h in agency_hits]

    out_lines += [
        "",
        "## Research Findings",
        "← LLM synthesis goes here when swarm coordinator is wired. →",
        "← Until then: check agencies.yaml and permit_pathways.yaml directly. →",
        "",
        "## Key Questions Remaining",
        "- [ ] (add after research)",
        "",
        "## Recommended Actions",
        "- [ ] (add after research)",
        "",
        "---",
        "⚖  Information only. Licensed professional sign-off required. NY S7263.",
    ]

    out_path = _GENERATED / "briefings" / f"{date_str}-{slug}-research.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# PREMORTEM handler
# ---------------------------------------------------------------------------

def _handle_premortem(subject: str, body: str, date_str: str) -> Path:
    """
    PREMORTEM-[project].md

    File format:
      project: [description]
      scope: [what's being planned]
      concerns: [specific risks to examine — optional]
    """
    params = _parse_kv(body)
    project  = params.get("project", subject.replace("-", " "))
    scope    = params.get("scope", "")
    concerns = params.get("concerns", "")
    freetext = body if not params else ""

    slug = _slug(subject)
    out_lines = [
        f"# Premortem — {project}",
        f"Generated: {date_str}",
        "",
        "## What We're Stress-Testing",
        scope or freetext or "(see project description)",
        "",
        "## Phase 1 — Failure Modes Inventory",
        "",
        "### Sequencing failures",
        "- [ ] Agency out of order (sequential_after violated)?",
        "- [ ] LPC filing triggered but scheduled after DOB?",
        "- [ ] BSA Pre-Determination skipped?",
        "",
        "### Staleness failures",
        "- [ ] Any agency step with confidence < 0.70?",
        "- [ ] Local Law changes since PLUTO v25v4 (April 2026)?",
        "- [ ] agencies.yaml last validated?",
        "",
        "### Jurisdiction failures",
        "- [ ] NYS HCR involvement missed (rent-stabilized building)?",
        "- [ ] Federal overlay missed (flood zone + FEMA requirements)?",
        "- [ ] ACRIS recording path required but not in pathway?",
        "",
        "### Liability failures",
        "- [ ] HEP tier assigned correctly?",
        "- [ ] information_not_advice framing explicit in all client output?",
        "- [ ] Licensed professional in loop for tier-3 actions?",
        "",
        "### Technical failures",
        "- [ ] PLUTO flag mapping correct (LandmkFlag not LandMarked)?",
        "- [ ] Confidence scores propagated to all steps?",
        "- [ ] Session log flushed before node handoff?",
        "",
        "## Phase 2 — Severity × Likelihood",
        "| Failure | Severity | Likelihood | Mitigation |",
        "|---|---|---|---|",
        "| (fill after Phase 1) | | | |",
        "",
        "## Phase 3 — Go / No-Go / Conditional",
        "Decision: **[GO | NO-GO | CONDITIONAL GO]**",
        "",
        "Conditions (if Conditional Go):",
        "- [ ] (list conditions)",
    ]

    if concerns:
        out_lines += ["", "## Specific Concerns Raised", concerns]

    out_lines += [
        "",
        "---",
        "⚖  Information only. Licensed professional sign-off required. NY S7263.",
    ]

    out_path = _GENERATED / "briefings" / f"{date_str}-{slug}-premortem.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# INTAKE handler
# ---------------------------------------------------------------------------

def _handle_intake(subject: str, body: str, date_str: str) -> Path:
    """
    INTAKE-[source].md

    File format: paste the article/PDF content.
    Applies Q1–Q4 intelligence intake filter and writes a signal report.
    """
    slug = _slug(subject)
    word_count = len(body.split())

    out_lines = [
        f"# Intelligence Intake — {subject.replace('-', ' ').title()}",
        f"Generated: {date_str}  |  Source length: ~{word_count} words",
        "",
        "## Raw Signal",
        f"> {body[:400]}{'...' if len(body) > 400 else ''}",
        "",
        "## Q1–Q4 Filter",
        "",
        "**Q1 — Legal/sequencing invariant?**",
        "→ (does this change permit_pathways.yaml or agency sequencing rules?)",
        "[ ] Yes — update permit_pathways.yaml and rules/ immediately",
        "[ ] No — continue",
        "",
        "**Q2 — Architectural validation/invalidation?**",
        "→ (does this validate or challenge a core moswalk architectural choice?)",
        "[ ] Yes — log decision in session_log, add to council brief",
        "[ ] No — continue",
        "",
        "**Q3 — New mechanism moswalk doesn't have?**",
        "→ (new pattern, tool, or approach that addresses a real pain point?)",
        "[ ] Yes — add to roadmap with unbloat test",
        "[ ] No — continue",
        "",
        "**Q4 — Output/format/UX improvement?**",
        "→ (makes client output, agent communication, or internal tooling better?)",
        "[ ] Yes — queue as format improvement",
        "[ ] No — discard",
        "",
        "## Signal Report",
        f"SOURCE: {subject}",
        "SIGNAL: (one sentence)",
        "RELEVANT_TO: (moswalk component)",
        "VERDICT: validated | gap | partial | discard",
        "ACTION: (specific file to change OR roadmap item OR none)",
        "UNBLOAT_TEST: (what does adding this replace or reduce?)",
        "",
        "---",
        "← Complete this report. File in council-brief.html Batch N when done. →",
    ]

    out_path = _GENERATED / "briefings" / f"{date_str}-{slug}-intake.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Vault / helpers
# ---------------------------------------------------------------------------

def _read_vault() -> str:
    if _VAULT.exists():
        return _VAULT.read_text(encoding="utf-8")
    return ""


def _vault_identity(ctx: str) -> str:
    for line in ctx.splitlines():
        if line.startswith("Platform:"):
            return line[len("Platform:"):].strip()
    return "moswalk"


def _parse_kv(text: str) -> dict:
    """Parse simple key: value pairs from file body. Handles nested flags: block."""
    result: dict = {}
    current_key = None
    in_flags = False
    flags_dict: dict = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if in_flags:
            if ":" in line and not line.startswith("-"):
                k, _, v = line.partition(":")
                v = v.strip()
                flags_dict[k.strip()] = _coerce(v)
            else:
                in_flags = False
        if ":" in line and not in_flags:
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "flags":
                in_flags = True
                current_key = "flags"
            else:
                result[k] = _coerce(v) if v else ""
                current_key = k

    if flags_dict:
        result["flags"] = flags_dict
    return result


def _coerce(v: str):
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no", "null", "none", ""):
        return False if v.lower() in ("false", "no") else None
    try:
        return int(v)
    except ValueError:
        pass
    return v


def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "-", s).strip("-").lower()[:40]


def _bbl_borough(bbl: str) -> str:
    mapping = {"1": "Manhattan", "2": "Bronx", "3": "Brooklyn", "4": "Queens", "5": "Staten Island"}
    parts = bbl.replace(" ", "-").split("-")
    return mapping.get(parts[0], "unknown") if parts else "unknown"


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_once() -> int:
    _QUEUE.mkdir(exist_ok=True)
    pending = sorted(_QUEUE.glob("*.md"))
    if not pending:
        print("queue: empty — nothing to process")
        return 0
    print(f"queue: {len(pending)} file(s) to process")
    count = 0
    for f in pending:
        try:
            out = route(f)
            if out:
                count += 1
        except Exception as e:
            print(f"  ✗  {f.name}: {e}")
    print(f"queue: processed {count}/{len(pending)}")
    return count


def watch(interval: int = 30) -> None:
    print(f"queue: watching {_QUEUE} every {interval}s — Ctrl+C to stop")
    seen: set[str] = set()
    while True:
        pending = [f for f in sorted(_QUEUE.glob("*.md")) if f.name not in seen]
        for f in pending:
            seen.add(f.name)
            try:
                route(f)
            except Exception as e:
                print(f"  ✗  {f.name}: {e}")
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="pantocraft // queue processor")
    parser.add_argument("--watch", action="store_true", help="Watch folder continuously")
    parser.add_argument("--interval", type=int, default=30, help="Watch interval in seconds")
    args = parser.parse_args()

    if args.watch:
        watch(args.interval)
    else:
        run_once()
