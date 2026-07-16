# pantocraft // — Flywheel Intelligence Archive
#
# SQLite-backed job archive. Every completed consultation writes here.
# This is the compounding moat: the archive enriches every future query.
#
# "The competitive moat is not the technology. It is the archive.
#  Six months of real job data, properly captured, creates an objection
#  prediction engine no competitor can replicate without starting six months ago."
#  — NYC AEC Expediting System Blueprint
#
# Schema mirrors the Blueprint:
#   job_id, property{borough,block,lot,bbl,zoning,overlay,special_district},
#   filing{type,examiner_id,work_type,code_sections,filing_date,
#          first_objection_date,approval_date},
#   objections[{code,description,resolution_method,resolution_days,documentation}],
#   edge_conditions, outcome, confidence_score, lessons
#
# Mode A/B/C routing (Blueprint Layer 4, Step 4):
#   score < 0.40 → Mode C: immediate escalation, no filing proceeds
#   0.40 ≤ score < 0.80 → Mode B: specialist review required
#   score ≥ 0.80 → Mode A: prepare submission for operator approval
#
# Privacy: BBL and block/lot are stored. Client PII (owner name, contact)
# is NEVER stored here — only the engagement_id reference ties back to
# the encrypted client record in pantocraft/clients/.
#
# Security: database file chmod 600. Path is gitignored.

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Generator, Optional

_ARCHIVE_DIR = Path(__file__).parent
_DB_PATH = _ARCHIVE_DIR / "jobs.db"

# ---------------------------------------------------------------------------
# Mode A/B/C (Blueprint Layer 4 thresholds)
# ---------------------------------------------------------------------------

class FilingMode(Enum):
    MODE_A = "A"   # ≥ 0.80 — full automation, human review before submission
    MODE_B = "B"   # 0.40–0.79 — specialist review required
    MODE_C = "C"   # < 0.40 — immediate escalation, no filing proceeds


def classify_mode(confidence_score: float) -> FilingMode:
    if confidence_score >= 0.80:
        return FilingMode.MODE_A
    elif confidence_score >= 0.40:
        return FilingMode.MODE_B
    else:
        return FilingMode.MODE_C


# Confidence formula from Blueprint Layer 4:
# score = (examiner_approval_rate × filing_type_weight × (1 / dob_backlog_days)) / complexity_index
def compute_confidence(
    examiner_approval_rate: float,
    filing_type_weight: float,
    dob_backlog_days: int,
    complexity_index: float,
) -> float:
    if dob_backlog_days <= 0:
        dob_backlog_days = 1
    if complexity_index <= 0:
        complexity_index = 1.0
    raw = (examiner_approval_rate * filing_type_weight * (1.0 / dob_backlog_days)) / complexity_index
    return min(1.0, max(0.0, raw))


# ---------------------------------------------------------------------------
# Job record schema
# ---------------------------------------------------------------------------

@dataclass
class JobObjection:
    objection_code: str
    description: str
    resolution_method: str = ""
    resolution_days: int = 0
    documentation_used: list[str] = field(default_factory=list)


@dataclass
class JobRecord:
    """
    One completed (or active) job in the flywheel archive.
    Serialized to/from SQLite as JSON blobs.
    """
    # Identity
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    engagement_id: Optional[str] = None   # ties to session_log / client record
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # Property (public record — no PII)
    borough: str = ""
    block: str = ""
    lot: str = ""
    bbl: str = ""
    zoning_district: str = ""
    overlay: str = ""
    special_district: str = ""

    # Filing
    filing_type: str = ""          # NB | A1 | A2 | A3 | TR6 | etc.
    examiner_id: str = ""
    work_types: list[str] = field(default_factory=list)
    code_sections_cited: list[str] = field(default_factory=list)
    filing_date: Optional[str] = None         # YYYY-MM-DD
    first_objection_date: Optional[str] = None
    approval_date: Optional[str] = None

    # Objections
    objections: list[dict] = field(default_factory=list)  # list of JobObjection dicts

    # Edge conditions
    edge_conditions: list[str] = field(default_factory=list)

    # Outcome
    outcome: str = ""              # approved | objected | revised | escalated | withdrawn
    confidence_score: float = 0.0
    filing_mode: str = ""          # A | B | C

    # Compounding intelligence
    lessons: str = ""              # free-text, operator-curated

    # Metadata
    pathway_type: str = ""         # alteration_type_1, new_building, etc.
    agency_sequence: list[str] = field(default_factory=list)  # ["LPC","DOB","FDNY"]
    enforcement_context: str = ""  # current-administration | pre-2026-administration | etc.

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "JobRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

@contextmanager
def _db(readonly: bool = False) -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        if not readonly:
            conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup."""
    with _db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id          TEXT PRIMARY KEY,
                engagement_id   TEXT,
                bbl             TEXT,
                borough         TEXT,
                filing_type     TEXT,
                filing_mode     TEXT,
                examiner_id     TEXT,
                outcome         TEXT,
                confidence_score REAL,
                pathway_type    TEXT,
                enforcement_context TEXT,
                filing_date     TEXT,
                first_objection_date TEXT,
                approval_date   TEXT,
                created_at      REAL,
                updated_at      REAL,
                payload         TEXT    -- full JSON blob
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS objections (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id          TEXT NOT NULL,
                bbl             TEXT,
                objection_code  TEXT,
                description     TEXT,
                resolution_method TEXT,
                resolution_days INTEGER,
                documentation_used TEXT  -- JSON array
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_bbl ON jobs(bbl)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_examiner ON jobs(examiner_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_filing_type ON jobs(filing_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_objections_code ON objections(objection_code)")

    # chmod 600 — contains BBL + examiner data
    if _DB_PATH.exists():
        _DB_PATH.chmod(0o600)


def write_job(record: JobRecord) -> str:
    """
    Insert or replace a job record. Returns job_id.
    Automatically sets filing_mode from confidence_score.
    """
    if not record.filing_mode:
        record.filing_mode = classify_mode(record.confidence_score).value
    record.updated_at = time.time()

    init_db()
    payload = json.dumps(record.to_dict())

    with _db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO jobs
            (job_id, engagement_id, bbl, borough, filing_type, filing_mode,
             examiner_id, outcome, confidence_score, pathway_type,
             enforcement_context, filing_date, first_objection_date,
             approval_date, created_at, updated_at, payload)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            record.job_id, record.engagement_id, record.bbl, record.borough,
            record.filing_type, record.filing_mode, record.examiner_id,
            record.outcome, record.confidence_score, record.pathway_type,
            record.enforcement_context, record.filing_date,
            record.first_objection_date, record.approval_date,
            record.created_at, record.updated_at, payload,
        ))
        # Write objections to the flat table for fast queries
        for obj_dict in record.objections:
            conn.execute("""
                INSERT INTO objections
                (job_id, bbl, objection_code, description,
                 resolution_method, resolution_days, documentation_used)
                VALUES (?,?,?,?,?,?,?)
            """, (
                record.job_id, record.bbl,
                obj_dict.get("objection_code", ""),
                obj_dict.get("description", ""),
                obj_dict.get("resolution_method", ""),
                obj_dict.get("resolution_days", 0),
                json.dumps(obj_dict.get("documentation_used", [])),
            ))

    return record.job_id


def get_job(job_id: str) -> Optional[JobRecord]:
    init_db()
    with _db(readonly=True) as conn:
        row = conn.execute("SELECT payload FROM jobs WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        return None
    return JobRecord.from_dict(json.loads(row["payload"]))


def get_jobs_by_engagement(engagement_id: str) -> list[JobRecord]:
    """Return all jobs for an engagement_id, most recent first."""
    init_db()
    with _db(readonly=True) as conn:
        rows = conn.execute(
            "SELECT payload FROM jobs WHERE engagement_id=? ORDER BY created_at DESC",
            (engagement_id,),
        ).fetchall()
    return [JobRecord.from_dict(json.loads(r["payload"])) for r in rows]


def update_job_outcome(
    engagement_id: str,
    outcome: str,
    confidence_score: float = 0.0,
    lessons: str = "",
    examiner_id: str = "",
    approval_date: Optional[str] = None,
    objections: Optional[list[dict]] = None,
) -> Optional[str]:
    """
    Update the most recent pending job for an engagement with its real outcome.
    Returns job_id if found and updated, None if no matching job exists.
    Called by the OUTCOME queue protocol to close the flywheel loop.
    """
    jobs = get_jobs_by_engagement(engagement_id)
    if not jobs:
        return None
    # Prefer the most recent pending record; fall back to most recent overall
    rec = next((j for j in jobs if j.outcome == "pending"), jobs[0])
    rec.outcome = outcome
    rec.confidence_score = confidence_score
    if lessons:
        rec.lessons = lessons
    if examiner_id:
        rec.examiner_id = examiner_id
    if approval_date:
        rec.approval_date = approval_date
    if objections is not None:
        rec.objections = objections
    return write_job(rec)


# ---------------------------------------------------------------------------
# Archive query — the flywheel intelligence engine
# ---------------------------------------------------------------------------

@dataclass
class ArchiveQuery:
    """
    Query the job archive to inform a new filing.
    Returns historical objection rates, resolution methods, and confidence signal.
    """
    bbl: Optional[str] = None
    borough: Optional[str] = None
    filing_type: Optional[str] = None
    examiner_id: Optional[str] = None
    pathway_type: Optional[str] = None
    limit: int = 20


@dataclass
class ArchiveResult:
    matched_jobs: int
    objection_rate: float              # fraction of matched jobs with ≥1 objection
    most_common_objections: list[dict] # [{code, description, count, avg_resolution_days}]
    avg_approval_days: float
    examiner_approval_rate: Optional[float]  # if examiner_id filtered
    similar_jobs: list[dict]           # [{job_id, bbl, outcome, confidence_score, filing_date}]
    recommended_documentation: list[str]
    archive_confidence: float          # how much to trust this result (sample size signal)


def query_archive(q: ArchiveQuery) -> ArchiveResult:
    """
    Query archive by borough + filing_type + examiner_id combination.
    Returns historical patterns to inform confidence scoring and defensive documentation.
    """
    init_db()

    clauses = []
    params: list = []

    if q.bbl:
        clauses.append("bbl = ?")
        params.append(q.bbl)
    if q.borough:
        clauses.append("borough = ?")
        params.append(q.borough)
    if q.filing_type:
        clauses.append("filing_type = ?")
        params.append(q.filing_type)
    if q.examiner_id:
        clauses.append("examiner_id = ?")
        params.append(q.examiner_id)
    if q.pathway_type:
        clauses.append("pathway_type = ?")
        params.append(q.pathway_type)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT payload FROM jobs {where} ORDER BY created_at DESC LIMIT ?"
    params.append(q.limit)

    with _db(readonly=True) as conn:
        rows = conn.execute(sql, params).fetchall()

    if not rows:
        return ArchiveResult(
            matched_jobs=0,
            objection_rate=0.0,
            most_common_objections=[],
            avg_approval_days=0.0,
            examiner_approval_rate=None,
            similar_jobs=[],
            recommended_documentation=[],
            archive_confidence=0.0,
        )

    records = [JobRecord.from_dict(json.loads(r["payload"])) for r in rows]

    # Objection analysis
    jobs_with_objections = [r for r in records if r.objections]
    objection_rate = len(jobs_with_objections) / len(records)

    # Aggregate objection codes
    obj_counts: dict[str, dict] = {}
    for rec in records:
        for obj in rec.objections:
            code = obj.get("objection_code", "")
            if code not in obj_counts:
                obj_counts[code] = {
                    "code": code,
                    "description": obj.get("description", ""),
                    "count": 0,
                    "total_resolution_days": 0,
                    "documentation": [],
                }
            obj_counts[code]["count"] += 1
            obj_counts[code]["total_resolution_days"] += obj.get("resolution_days", 0)
            obj_counts[code]["documentation"].extend(obj.get("documentation_used", []))

    most_common = sorted(obj_counts.values(), key=lambda x: x["count"], reverse=True)[:5]
    for entry in most_common:
        n = entry["count"]
        entry["avg_resolution_days"] = round(entry["total_resolution_days"] / n, 1) if n else 0
        entry["documentation"] = list(dict.fromkeys(entry["documentation"]))  # dedupe
        del entry["total_resolution_days"]

    # Approval days
    approved = [r for r in records if r.approval_date and r.filing_date]
    avg_days = 0.0
    if approved:
        from datetime import date
        deltas = []
        for r in approved:
            try:
                d0 = date.fromisoformat(r.filing_date)
                d1 = date.fromisoformat(r.approval_date)
                deltas.append((d1 - d0).days)
            except (ValueError, TypeError):
                pass
        avg_days = sum(deltas) / len(deltas) if deltas else 0.0

    # Examiner-specific approval rate
    examiner_rate = None
    if q.examiner_id:
        examiner_jobs = [r for r in records if r.examiner_id == q.examiner_id]
        if examiner_jobs:
            approved_by = [r for r in examiner_jobs if r.outcome == "approved"]
            examiner_rate = len(approved_by) / len(examiner_jobs)

    # Recommended documentation from successful resolutions
    docs: list[str] = []
    for entry in most_common:
        docs.extend(entry.get("documentation", []))
    recommended = list(dict.fromkeys(docs))[:8]  # dedupe, top 8

    # Archive confidence: logarithmic sample size signal
    import math
    n = len(records)
    archive_confidence = min(0.95, math.log(n + 1) / math.log(51))  # 50 jobs → 0.95

    similar = [
        {
            "job_id": r.job_id[:8],
            "bbl": r.bbl,
            "outcome": r.outcome,
            "confidence_score": r.confidence_score,
            "filing_date": r.filing_date,
            "objection_count": len(r.objections),
        }
        for r in records[:5]
    ]

    return ArchiveResult(
        matched_jobs=n,
        objection_rate=round(objection_rate, 3),
        most_common_objections=most_common,
        avg_approval_days=round(avg_days, 1),
        examiner_approval_rate=round(examiner_rate, 3) if examiner_rate is not None else None,
        similar_jobs=similar,
        recommended_documentation=recommended,
        archive_confidence=round(archive_confidence, 3),
    )


def archive_summary_toon(q: ArchiveQuery) -> str:
    """
    TOON-format archive query result for LLM context injection.
    ~30% of the tokens of a full JSON dump.
    """
    r = query_archive(q)
    if r.matched_jobs == 0:
        label = f"filing:{q.filing_type or '?'} borough:{q.borough or '?'} examiner:{q.examiner_id or '?'}"
        return f"archive:0 {label}\nnext[] seed archive: enter first jobs manually via write_job()"

    mode_signal = classify_mode(r.examiner_approval_rate or 0.5).value if r.examiner_approval_rate else "?"
    lines = [
        f"archive:{r.matched_jobs} objection_rate:{r.objection_rate:.0%} "
        f"avg_approval:{r.avg_approval_days:.0f}d conf:{r.archive_confidence:.0%}",
    ]
    if r.examiner_approval_rate is not None:
        lines.append(f"examiner_rate:{r.examiner_approval_rate:.0%} → mode:{mode_signal}")
    if r.most_common_objections:
        lines.append("top_objections:")
        for obj in r.most_common_objections[:3]:
            lines.append(
                f"  {obj['code']:<12} count:{obj['count']} "
                f"avg_resolution:{obj['avg_resolution_days']}d"
            )
    if r.recommended_documentation:
        docs = " | ".join(r.recommended_documentation[:4])
        lines.append(f"recommended_docs: {docs}")
    if r.archive_confidence < 0.5:
        lines.append("sea_state:uncharted — archive signal directional, not prescriptive. Navigate with live instrument reads.")
    elif r.archive_confidence < 0.8:
        lines.append("sea_state:variable — archive shows pattern but conditions may differ. Verify examiner posture.")
    else:
        lines.append("sea_state:charted — strong archive signal. Known passage with documented conditions.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="pantocraft // flywheel archive")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("init", help="Initialize database")

    q_parser = sub.add_parser("query", help="Query archive")
    q_parser.add_argument("--borough", default=None)
    q_parser.add_argument("--filing-type", default=None)
    q_parser.add_argument("--examiner", default=None)
    q_parser.add_argument("--bbl", default=None)
    q_parser.add_argument("--toon", action="store_true", help="TOON format output")

    args = parser.parse_args()

    if args.cmd == "init":
        init_db()
        print(f"Archive initialized: {_DB_PATH}")

    elif args.cmd == "query":
        q = ArchiveQuery(
            borough=args.borough,
            filing_type=args.filing_type,
            examiner_id=args.examiner,
            bbl=args.bbl,
        )
        if args.toon:
            print(archive_summary_toon(q))
        else:
            import dataclasses
            r = query_archive(q)
            print(json.dumps(dataclasses.asdict(r), indent=2))

    else:
        parser.print_help()
