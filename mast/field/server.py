#!/usr/bin/env python3
# MAST // — FieldAPI HTTP Server
#
# Runs on the Mac Inference node. iPhone calls this over Tailscale.
# Thin HTTP wrapper around FieldAPI.consult() — no business logic here.
#
# Start:
#   python mast/field/server.py
#   python mast/field/server.py --host 0.0.0.0 --port 7430
#
# Tailscale cron (keep alive):
#   @reboot cd /path/to/repo && python mast/field/server.py >> /var/log/moswalk-server.log 2>&1
#
# Security: listens on Tailscale interface only (100.x.x.x).
# NEVER expose on 0.0.0.0 without explicit firewall rules.
# All traffic is WireGuard-encrypted end-to-end by Tailscale.

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_ROOT       = Path(__file__).parents[2]
_PANTOCRAFT = Path(__file__).parent.parent

for p in [str(_ROOT / "moswalk-kernel"), str(_PANTOCRAFT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# Token auth — read shared secret from SwarmConfig.json or env var
# Set MOSWALK_SERVER_TOKEN env var on the Mac, and put the same value in the
# iOS app's SwarmConfig.json as "server_token". Leave unset to skip auth
# (acceptable on a trusted Tailscale network, required for TestFlight builds).
# ---------------------------------------------------------------------------

def _load_server_token() -> str | None:
    """Return the expected bearer token, or None if auth is disabled."""
    env_val = os.environ.get("MOSWALK_SERVER_TOKEN", "").strip()
    if env_val:
        return env_val
    cfg_path = _PANTOCRAFT / "field" / "SwarmConfig.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            return cfg.get("server_token") or None
        except Exception:
            pass
    return None

_SERVER_TOKEN: str | None = None  # populated at startup

try:
    from field.mobile_api import FieldAPI, ConsultResult
    _FIELD_AVAILABLE = True
except ImportError:
    _FIELD_AVAILABLE = False

try:
    from archive.flywheel import ArchiveQuery, archive_summary_toon, query_archive, compute_voyage_confidence
    _ARCHIVE_AVAILABLE = True
except ImportError:
    _ARCHIVE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Request/response helpers
# ---------------------------------------------------------------------------

def _bbl_borough(bbl: str) -> str:
    mapping = {"1": "Manhattan", "2": "Bronx", "3": "Brooklyn", "4": "Queens", "5": "Staten Island"}
    parts = bbl.replace(" ", "-").split("-")
    return mapping.get(parts[0], "unknown") if parts else "unknown"


def _consult_result_to_dict(result) -> dict:
    """Convert ConsultResult to JSON-serializable dict matching Swift Codable keys."""
    return {
        "engagement_id":    result.engagement_id,
        "bbl":              result.bbl,
        "address":          result.address,
        "project_type":     result.project_type,
        "agency_pathway":   result.agency_pathway,
        "critical_path_days": result.critical_path_days,
        "optimized_days":   result.optimized_days,
        "days_saved":       result.days_saved,
        "escalation_flags": result.escalation_flags,
        "MAST_flags": result.MAST_flags,
        "overall_confidence": result.overall_confidence,
        "stale_agencies":   result.stale_agencies,
        "hep_payload":      None,  # populated below if HEP fired
        "query_ms":         result.query_ms,
    }


def _handle_consult(body_bytes: bytes) -> tuple[int, dict]:
    """POST /consult — body: ConsultRequest JSON from iOS client."""
    try:
        req = json.loads(body_bytes)
    except json.JSONDecodeError as e:
        return 400, {"error": f"Invalid JSON: {e}"}

    bbl          = req.get("bbl", "")
    address      = req.get("address", bbl)
    engagement_id = req.get("engagementId", f"API-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}")
    project      = req.get("project", "")
    filing_type  = req.get("filingType", "A2")
    flags        = req.get("flags", {}) or {}

    if not bbl:
        return 400, {"error": "bbl is required"}

    # Normalize Swift camelCase flags → snake_case
    normalized_flags = {
        "landmarked":        flags.get("landmarked", False),
        "landmark_type":     flags.get("landmarkType"),
        "year_built":        flags.get("yearBuilt"),
        "flood_zone":        flags.get("floodZone"),
        "open_violations":   flags.get("openViolations", 0),
    }

    # Archive query for voyage_confidence
    archive_result = None
    if _ARCHIVE_AVAILABLE:
        try:
            q = ArchiveQuery(bbl=bbl, borough=_bbl_borough(bbl), filing_type=filing_type)
            archive_result = query_archive(q)
        except Exception:
            pass

    if not _FIELD_AVAILABLE:
        return 503, {"error": "moswalk-kernel not available on this node"}

    try:
        api = FieldAPI()
        result = api.consult(
            engagement_id=engagement_id,
            bbl=bbl,
            address=address,
            borough=_bbl_borough(bbl),
            project_type=project,
            dob_filing_type=filing_type,
            property_flags=normalized_flags,
            archive_result=archive_result,
        )
    except Exception as e:
        return 500, {"error": str(e)}

    payload = _consult_result_to_dict(result)

    # HEP check — emit if escalation needed
    try:
        from agentic.hep import build_hep, write_hep, HEPTriggerType
        if result.escalation_flags or result.overall_confidence < 0.80:
            affects_landmark = any(
                kw in f.lower()
                for f in result.escalation_flags
                for kw in ("landmark", "lpc")
            )
            trigger = HEPTriggerType.LANDMARK if affects_landmark else HEPTriggerType.CONFIDENCE
            hep = build_hep(
                proposed_action="consult_output_delivery",
                confidence=result.overall_confidence,
                bbl=bbl,
                address=address,
                engagement_id=engagement_id,
                pathway_type=filing_type.lower(),
                agency_steps=[s.get("code", "") for s in result.agency_pathway],
                conditions=result.escalation_flags,
                affects_landmark=affects_landmark,
                trigger_type=trigger,
            )
            write_hep(hep)
            payload["hep_payload"] = {
                "trace_id":             hep.trace_id,
                "tier":                 hep.tier,
                "trigger_type":         hep.trigger_type,
                "trigger_detail":       hep.trigger_detail,
                "filing_mode":          hep.filing_mode,
                "sla_label":            hep.sla_label,
                "proposed_action":      hep.proposed_action,
                "affects_landmark":     hep.affects_landmark,
                "information_not_advice": hep.information_not_advice,
                "options":              hep.options,
            }
    except Exception:
        pass

    return 200, payload


def _handle_archive_signal(query_string: str) -> tuple[int, str]:
    """GET /archive/signal?bbl=…&filing_type=…"""
    if not _ARCHIVE_AVAILABLE:
        return 503, "archive module unavailable"
    qs = parse_qs(query_string)
    bbl         = (qs.get("bbl", [""]))[0]
    filing_type = (qs.get("filing_type", ["A2"]))[0]
    q = ArchiveQuery(bbl=bbl, borough=_bbl_borough(bbl), filing_type=filing_type)
    return 200, archive_summary_toon(q)


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class MoswalkHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"[{ts}] {fmt % args}")

    def _check_auth(self) -> bool:
        """Return True if request is authorized (or auth is disabled)."""
        if not _SERVER_TOKEN:
            return True
        auth = self.headers.get("X-Moswalk-Token", "").strip()
        return auth == _SERVER_TOKEN

    def do_GET(self):
        if not self._check_auth():
            self._json(401, {"error": "unauthorized"})
            return
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/health":
            self._json(200, {
                "status": "ok",
                "kernel": _FIELD_AVAILABLE,
                "archive": _ARCHIVE_AVAILABLE,
                "ts": time.time(),
            })
        elif path == "/archive/signal":
            code, text = _handle_archive_signal(parsed.query)
            self._text(code, text)
        else:
            self._json(404, {"error": f"unknown path: {path}"})

    def do_POST(self):
        if not self._check_auth():
            self._json(401, {"error": "unauthorized"})
            return
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        if path == "/consult":
            code, data = _handle_consult(body)
            self._json(code, data)
        else:
            self._json(404, {"error": f"unknown path: {path}"})

    def _json(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, code: int, text: str):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="moswalk // FieldAPI HTTP server")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address. Use Tailscale IP (100.x.x.x) for mesh access.")
    parser.add_argument("--port", type=int, default=7430)
    args = parser.parse_args()

    _SERVER_TOKEN = _load_server_token()

    print(f"moswalk // server starting on {args.host}:{args.port}")
    print(f"  kernel:  {'available' if _FIELD_AVAILABLE else 'NOT AVAILABLE'}")
    print(f"  archive: {'available' if _ARCHIVE_AVAILABLE else 'NOT AVAILABLE'}")
    print(f"  auth:    {'X-Moswalk-Token required' if _SERVER_TOKEN else 'DISABLED (Tailscale-only network assumed)'}")
    print(f"  endpoints: GET /health  POST /consult  GET /archive/signal")
    print()

    server = HTTPServer((args.host, args.port), MoswalkHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nserver stopped")
