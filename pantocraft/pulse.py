# pantocraft // — Engagement Pulse
#
# Daily operating system pulse for pantocraft consultation work.
# Reads session_log files + HEP escalations + MOSWALK.md to produce
# a structured engagement pulse — equivalent to Cyril's "Daily Project Pulse"
# but built around BBL queries, regulatory pathways, and HEP SLA windows.
#
# Run daily at 6AM (Tailscale cron on Inference node):
#   0 6 * * * cd /path/to/repo && python pantocraft/pulse.py
#
# Run manually: python pantocraft/pulse.py [--days N] [--output PATH]

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ROOT       = Path(__file__).parents[1]
_PANTOCRAFT = Path(__file__).parent
_SESSIONS   = _PANTOCRAFT / "agentic" / "sessions"
_ESCALATIONS = _PANTOCRAFT / "agentic" / "escalations"
_VAULT      = _PANTOCRAFT / "vault" / "MOSWALK.md"
_GENERATED  = _PANTOCRAFT / "generated" / "briefings"

for p in [str(_ROOT / "moswalk-kernel"), str(_PANTOCRAFT)]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------------------------------------------------------------------
# Session log reader
# ---------------------------------------------------------------------------

def _read_sessions(since_days: int = 30) -> list[dict]:
    """
    Read all session JSONL files modified within the last N days.
    Returns list of engagement summaries: {engagement_id, last_event, event_count,
    has_warnings, has_decisions, last_pathway_type, last_step_count}.
    """
    if not _SESSIONS.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
    summaries: list[dict] = []

    for f in sorted(_SESSIONS.glob("*.jsonl")):
        try:
            stat = f.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                continue

            events = []
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

            if not events:
                continue

            last_event = events[-1]
            engagement_id = last_event.get("engagement_id", f.stem)

            # Derive metadata from event stream
            warnings   = [e for e in events if e.get("level") == "WARNING"]
            decisions  = [e for e in events if e.get("level") == "DECISION"]
            queries    = [e for e in events if e.get("level") == "QUERY"]
            last_query = queries[-1] if queries else {}

            summaries.append({
                "engagement_id":    engagement_id,
                "file":             f.name,
                "last_event_ts":    last_event.get("ts", 0),
                "last_event_type":  last_event.get("level", "?"),
                "event_count":      len(events),
                "has_warnings":     len(warnings) > 0,
                "warnings":         [w.get("message", "") for w in warnings[-2:]],
                "has_decisions":    len(decisions) > 0,
                "last_pathway":     last_query.get("pathway_type", ""),
                "last_step_count":  last_query.get("step_count", 0),
                "last_conditions":  last_query.get("conditions_count", 0),
                "modified_days_ago": (datetime.now(timezone.utc) - mtime).days,
                "mtime":            mtime,
            })
        except Exception:
            continue

    return sorted(summaries, key=lambda x: x["last_event_ts"], reverse=True)


# ---------------------------------------------------------------------------
# HEP escalation reader
# ---------------------------------------------------------------------------

def _read_hep_pending() -> list[dict]:
    """
    Read all HEP JSON files in escalations/.
    Returns list of {trace_id, tier, sla_seconds, proposed_action, bbl, created_at}.
    """
    if not _ESCALATIONS.exists():
        return []

    payloads: list[dict] = []
    for f in sorted(_ESCALATIONS.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            created = data.get("created_at", 0)
            age_h   = (datetime.now(timezone.utc).timestamp() - created) / 3600
            sla_h   = data.get("sla_seconds", 3600) / 3600
            payloads.append({
                "trace_id":         data.get("trace_id", f.stem),
                "tier":             data.get("tier", 2),
                "sla_seconds":      data.get("sla_seconds", 3600),
                "sla_hours":        sla_h,
                "age_hours":        age_h,
                "overdue":          age_h > sla_h,
                "proposed_action":  data.get("proposed_action", ""),
                "bbl":              data.get("bbl", ""),
                "trigger_type":     data.get("trigger_type", ""),
                "trigger_detail":   data.get("trigger_detail", ""),
                "confidence":       data.get("confidence", 0.0),
            })
        except Exception:
            continue

    return sorted(payloads, key=lambda x: (not x["overdue"], x["tier"]), reverse=True)


# ---------------------------------------------------------------------------
# Pulse generator
# ---------------------------------------------------------------------------

def generate_pulse(since_days: int = 7) -> str:
    date_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    now_ts    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sessions  = _read_sessions(since_days=since_days)
    hep_items = _read_hep_pending()

    # Classify sessions
    active  = [s for s in sessions if s["modified_days_ago"] <= 2]
    recent  = [s for s in sessions if 2 < s["modified_days_ago"] <= since_days]
    stale   = [s for s in sessions if s["modified_days_ago"] > 5]
    flagged = [s for s in sessions if s["has_warnings"]]

    vault_ctx = ""
    if _VAULT.exists():
        vault_ctx = _VAULT.read_text(encoding="utf-8")[:600]

    lines = [
        f"# Engagement Pulse — {date_str}",
        f"Generated: {now_ts}",
        f"Window: last {since_days} days",
        "",
    ]

    # ── Summary card ──────────────────────────────────────────────────────────
    hep_overdue = [h for h in hep_items if h["overdue"]]
    lines += [
        "## Status Summary",
        f"  active (≤2d):     {len(active):>3} engagement(s)",
        f"  recent (3–{since_days}d):   {len(recent):>3} engagement(s)",
        f"  stale (>5d):      {len(stale):>3} engagement(s)  {'⚑ NEEDS ATTENTION' if stale else ''}",
        f"  with warnings:    {len(flagged):>3} engagement(s)  {'⚑' if flagged else ''}",
        f"  HEP pending:      {len(hep_items):>3} escalation(s)  {'🔴 OVERDUE' if hep_overdue else ''}",
        "",
    ]

    # ── HEP escalations ───────────────────────────────────────────────────────
    if hep_items:
        lines.append("## HEP Escalations Pending Review")
        for h in hep_items[:10]:
            overdue_tag = "  ← OVERDUE" if h["overdue"] else f"  ({h['age_hours']:.1f}h / {h['sla_hours']:.0f}h SLA)"
            bbl_tag     = f"  BBL:{h['bbl']}" if h["bbl"] else ""
            lines.append(
                f"  TIER-{h['tier']} | {h['trace_id'][:16]}  "
                f"{h['proposed_action']:<30}{bbl_tag}{overdue_tag}"
            )
        lines.append("")

    # ── Active engagements ────────────────────────────────────────────────────
    if active:
        lines.append("## Active Engagements (≤2 days)")
        for s in active[:10]:
            warn_tag  = "  ⚑ warnings" if s["has_warnings"] else ""
            path_tag  = f"  [{s['last_pathway']}]" if s["last_pathway"] else ""
            steps_tag = f"  {s['last_step_count']}-step pathway" if s["last_step_count"] else ""
            lines.append(
                f"  {s['engagement_id']:<24}  {s['modified_days_ago']}d ago"
                f"{path_tag}{steps_tag}{warn_tag}"
            )
        lines.append("")

    # ── Stale engagements ─────────────────────────────────────────────────────
    if stale:
        lines.append("## Stale Engagements (>5 days — require attention)")
        for s in stale[:10]:
            warn_tag = "  ⚑ warnings present" if s["has_warnings"] else ""
            lines.append(
                f"  {s['engagement_id']:<24}  {s['modified_days_ago']}d since last event"
                f"  ({s['event_count']} events){warn_tag}"
            )
            for w in s["warnings"]:
                lines.append(f"    ↳ {w[:100]}")
        lines.append("")

    # ── Flagged warnings ──────────────────────────────────────────────────────
    if flagged and len(flagged) > len(stale):
        new_flagged = [f for f in flagged if f not in stale]
        if new_flagged:
            lines.append("## Engagements with Warnings (active)")
            for s in new_flagged[:5]:
                lines.append(f"  {s['engagement_id']:<24}  {s['modified_days_ago']}d ago")
                for w in s["warnings"]:
                    lines.append(f"    ↳ {w[:100]}")
            lines.append("")

    # ── Recommended next actions ──────────────────────────────────────────────
    lines.append("## Recommended Actions")
    if hep_overdue:
        for h in hep_overdue[:3]:
            lines.append(f"  ⚑ URGENT: Review TIER-{h['tier']} HEP {h['trace_id'][:16]} — OVERDUE by {h['age_hours'] - h['sla_hours']:.0f}h")
    if stale:
        for s in stale[:3]:
            lines.append(f"  → Resume or close: {s['engagement_id']}  ({s['modified_days_ago']}d stale)")
    if not sessions:
        lines.append("  → No recent engagements. Queue a CONSULT file to begin.")
    if not hep_items and not stale and active:
        lines.append("  → All active engagements current. Review generated/consultations/ for output.")
    lines.append("")

    # ── Context from MOSWALK.md ───────────────────────────────────────────────
    if vault_ctx:
        lines += [
            "## Platform Context (from MOSWALK.md)",
            "```",
            vault_ctx.strip()[:400],
            "```",
        ]

    lines += [
        "",
        "---",
        f"next[] check generated/briefings/ for any pending research or intake outputs",
        f"next[] update MOSWALK.md Active Engagements section if status changed",
        f"info[] information only — licensed professional required for any tier-3 action",
    ]

    return "\n".join(lines)


def write_pulse(since_days: int = 7, output: Path | None = None) -> Path:
    content   = generate_pulse(since_days=since_days)
    date_str  = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path  = output or (_GENERATED / f"{date_str}-engagement-pulse.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="pantocraft // daily engagement pulse")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days")
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    parser.add_argument("--print", action="store_true", dest="print_only", help="Print to stdout, don't write file")
    args = parser.parse_args()

    if args.print_only:
        print(generate_pulse(since_days=args.days))
    else:
        out = write_pulse(since_days=args.days, output=Path(args.output) if args.output else None)
        print(f"Pulse written: {out}")
        print()
        print(generate_pulse(since_days=args.days))
