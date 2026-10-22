"""
pantocraft // — agentic session logger

Private, structured log of every skill invocation, field query, and
agentic decision made through pantocraft //.

Why private: agentic logs may reference engagement IDs, property flags
(which combined with timing can be re-identifying), optimization tracks
applied, and confidence decisions made on behalf of a licensed professional.
None of this belongs in a public repo or a cloud log.

Storage:
  pantocraft/agentic/sessions/YYYY-MM-DD_HHMMSS_<engagement_id>.jsonl
  One JSON line per event. Append-only. Never overwrite.

gitignore:
  pantocraft/agentic/sessions/  ← all sessions excluded from repo
  pantocraft/agentic/*.log      ← any raw log files excluded

Security:
  - No client PII in session logs — use engagement_id reference only
  - No raw prompt text (may contain client context) — log structure, not content
  - No PLUTO/BBL data tagged to client_id in same file — separation invariant
  - Log files chmod 600 on creation

Usage:
    log = AgenticLog(engagement_id="SIM-001")
    log.skill_start("property_trigger_scanner", {"bbl": "3-00783-0001"})
    log.skill_end("property_trigger_scanner", result_summary="3 conditions triggered")
    log.decision("LPC condition triggered — routing to LPC track", confidence=0.95)
    log.warning("Stale data: confidence < 0.70 on OATH step")
    log.flush()
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_HERE      = Path(__file__).parent
_SESSIONS  = _HERE / "sessions"


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

@dataclass
class AgenticEvent:
    ts: str                         # ISO 8601 UTC
    event_type: str                 # skill_start | skill_end | decision | warning | query | error
    engagement_id: str
    skill: Optional[str] = None
    summary: str = ""
    confidence: Optional[float] = None
    flags: list[str] = field(default_factory=list)

    def as_jsonl(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class AgenticLog:
    """
    Append-only event log for one pantocraft // engagement session.

    One log file per engagement. Multiple skill invocations per file.
    Safe to instantiate multiple times for same engagement_id — appends.
    """

    def __init__(
        self,
        engagement_id: str,
        sessions_dir: Optional[Path] = None,
    ):
        self.engagement_id = engagement_id
        self._dir = sessions_dir or _SESSIONS
        self._dir.mkdir(parents=True, exist_ok=True)

        # File named by engagement_id hash (no PII in filename)
        import hashlib
        _hash = hashlib.sha256(engagement_id.encode()).hexdigest()[:12]
        self._path = self._dir / f"{_hash}.jsonl"

        self._events: list[AgenticEvent] = []

        # Touch the file with correct permissions on first creation
        if not self._path.exists():
            self._path.touch(mode=0o600)

    def skill_start(self, skill_name: str, inputs: Optional[dict] = None) -> None:
        flags = [f"input:{k}" for k in (inputs or {}).keys()]
        self._append(AgenticEvent(
            ts=_now(),
            event_type="skill_start",
            engagement_id=self.engagement_id,
            skill=skill_name,
            summary=f"Started {skill_name}",
            flags=flags,
        ))

    def skill_end(self, skill_name: str, result_summary: str = "", confidence: Optional[float] = None) -> None:
        self._append(AgenticEvent(
            ts=_now(),
            event_type="skill_end",
            engagement_id=self.engagement_id,
            skill=skill_name,
            summary=result_summary,
            confidence=confidence,
        ))

    def decision(self, summary: str, confidence: Optional[float] = None, flags: Optional[list[str]] = None) -> None:
        self._append(AgenticEvent(
            ts=_now(),
            event_type="decision",
            engagement_id=self.engagement_id,
            summary=summary,
            confidence=confidence,
            flags=flags or [],
        ))

    def warning(self, message: str, flags: Optional[list[str]] = None) -> None:
        self._append(AgenticEvent(
            ts=_now(),
            event_type="warning",
            engagement_id=self.engagement_id,
            summary=message,
            flags=flags or [],
        ))

    def query(self, pathway_type: str, conditions_count: int, step_count: int) -> None:
        self._append(AgenticEvent(
            ts=_now(),
            event_type="query",
            engagement_id=self.engagement_id,
            summary=f"Resolved {pathway_type}: {step_count} steps, {conditions_count} conditions",
            flags=[f"pathway:{pathway_type}"],
        ))

    def error(self, message: str) -> None:
        self._append(AgenticEvent(
            ts=_now(),
            event_type="error",
            engagement_id=self.engagement_id,
            summary=message,
        ))

    def flush(self) -> Path:
        """Write all buffered events to disk. Called automatically on __del__."""
        if not self._events:
            return self._path
        with open(self._path, "a", encoding="utf-8") as f:
            for ev in self._events:
                f.write(ev.as_jsonl() + "\n")
        os.chmod(self._path, 0o600)
        self._events.clear()
        return self._path

    def _append(self, event: AgenticEvent) -> None:
        self._events.append(event)

    def __del__(self):
        try:
            self.flush()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Reader — for audit and review
# ---------------------------------------------------------------------------

def read_session(engagement_id: str, sessions_dir: Optional[Path] = None) -> list[AgenticEvent]:
    """Read all events for an engagement_id."""
    import hashlib
    _dir = sessions_dir or _SESSIONS
    _hash = hashlib.sha256(engagement_id.encode()).hexdigest()[:12]
    path = _dir / f"{_hash}.jsonl"
    if not path.exists():
        return []
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(AgenticEvent(**json.loads(line)))
    return events


def audit_session(engagement_id: str, sessions_dir: Optional[Path] = None) -> str:
    """Return a readable audit trail for an engagement."""
    events = read_session(engagement_id, sessions_dir)
    if not events:
        return f"No session log found for {engagement_id}"
    lines = [f"Agentic audit — {engagement_id}", f"Events: {len(events)}", ""]
    for ev in events:
        conf_str = f"  conf={ev.confidence:.0%}" if ev.confidence is not None else ""
        flag_str = f"  [{', '.join(ev.flags)}]" if ev.flags else ""
        lines.append(f"{ev.ts}  {ev.event_type:<14} {ev.summary[:80]}{conf_str}{flag_str}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI audit tool
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python session_log.py <engagement_id>")
        print("       python session_log.py --list")
        sys.exit(0)
    if sys.argv[1] == "--list":
        _SESSIONS.mkdir(parents=True, exist_ok=True)
        files = list(_SESSIONS.glob("*.jsonl"))
        if not files:
            print("No session logs found.")
        else:
            for f in sorted(files):
                count = sum(1 for _ in open(f))
                print(f"{f.name}  {count} events")
    else:
        print(audit_session(sys.argv[1]))
