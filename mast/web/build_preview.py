#!/usr/bin/env python3
# Builds a self-contained preview of the front door for phone beta testing.
#
# The preview runs where /consult is unreachable (e.g. a hosted Artifact), so it
# answers from snapshot.json: the real server's output for every flag combination
# the page can send. No archive data is used (it can hold client BBLs) and nothing
# is written to the HEP escalations or session logs while building.
#
#   python mast/web/build_preview.py <out_dir>
#   → <out_dir>/index.html  <out_dir>/snapshot.json

from __future__ import annotations

import importlib.util
import itertools
import json
import re
import sys
from pathlib import Path

_WEB = Path(__file__).parent
_MAST = _WEB.parent

# The page's projects and answers, mirrored exactly (see PROJECTS / ERA_YEAR in index.html).
PROJECTS = [
    ("A2", "interior alteration"), ("A2", "exterior alteration"), ("A1", "change of use"),
    ("NB", "new building"), ("A3", "minor alteration"), ("TR6", "facade inspection"),
]
YEARS = [1920, 1960, 2000, None]
LANDMARKS = [(True, "individual"), (True, "historic_district"), (False, None), (None, None)]
FLOODS = ["AE", None]
KEEP = ("critical_path_days", "optimized_days", "days_saved", "overall_confidence",
        "stale_agencies", "escalation_flags", "track_details")
STEP_KEEP = ("code", "full_name", "estimated_days", "triggered_by", "blocking")


def key(filing, project, year, landmarked, ltype, flood):
    part = lambda v: "-" if v is None else str(v).lower()
    return "|".join([filing, project, part(year), part(landmarked), part(ltype), part(flood)])


def load_server():
    spec = importlib.util.spec_from_file_location("mast_server", _MAST / "field" / "server.py")
    server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(server)
    server._ARCHIVE_AVAILABLE = False

    import agentic.hep as hep
    import agentic.session_log as session_log

    class _NoLog:
        def __init__(self, *a, **k): pass
        def __getattr__(self, _name): return lambda *a, **k: None

    hep.write_hep = lambda *a, **k: None
    session_log.AgenticLog = _NoLog
    return server


def snapshot(server) -> dict:
    out = {}
    for (filing, project), year, (landmarked, ltype), flood in itertools.product(PROJECTS, YEARS, LANDMARKS, FLOODS):
        flags = {}
        if year is not None: flags["yearBuilt"] = year
        if landmarked is not None: flags["landmarked"] = landmarked
        if ltype is not None: flags["landmarkType"] = ltype
        if flood is not None: flags["floodZone"] = flood
        body = json.dumps({"address": "preview", "borough": "Brooklyn", "project": project,
                           "filingType": filing, "flags": flags}).encode()
        code, payload = server._handle_consult(body)
        if code != 200:
            raise SystemExit(f"engine returned {code} for {filing} {project} {flags}: {payload}")
        entry = {k: payload[k] for k in KEEP}
        entry["agency_pathway"] = [{k: s.get(k) for k in STEP_KEEP} for s in payload["agency_pathway"]]
        out[key(filing, project, year, landmarked, ltype, flood)] = entry
    return out


PREVIEW_HOOK = """<script>
window.MAST_NO_PRINT = true;
(function () {
  var cache = null;
  function part(v) { return v === undefined || v === null ? "-" : String(v).toLowerCase(); }
  window.MAST_OFFLINE = function (req) {
    var f = req.flags || {};
    var k = [req.filingType, req.project, part(f.yearBuilt), part(f.landmarked), part(f.landmarkType), part(f.floodZone)].join("|");
    cache = cache || fetch("snapshot.json").then(function (r) { if (!r.ok) throw new Error("Preview data missing"); return r.json(); });
    return cache.then(function (all) {
      var d = all[k];
      if (!d) throw new Error("No preview answer for this combination");
      var t = new Date(), pad = function (n) { return String(n).padStart(2, "0"); };
      return Object.assign({ engagement_id: "BETA-" + t.getFullYear() + pad(t.getMonth() + 1) + pad(t.getDate()) + "-" + pad(t.getHours()) + pad(t.getMinutes()) + pad(t.getSeconds()) }, d);
    });
  };
})();
</script>
"""


def page() -> str:
    html = (_WEB / "index.html").read_text()
    head = re.search(r"<head>(.*?)</head>", html, re.S).group(1)
    body = re.search(r"<body>(.*?)</body>", html, re.S).group(1)
    head = re.sub(r'<meta charset[^>]*>\s*|<meta name="viewport"[^>]*>\s*', "", head)
    head = head.replace("<title>MAST</title>", "<title>MAST Front Door</title>")
    # The host pads :root by the phone's safe areas; size to it rather than the raw viewport.
    head = head.replace("    height: 100vh; height: 100dvh;\n", "    height: 100%;\n")
    body = body.replace("<span>New York</span>", "<span>New York · Beta</span>", 1)
    first_script = body.index("<script>")
    return head.strip() + "\n" + body[:first_script] + PREVIEW_HOOK + body[first_script:]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: build_preview.py <out_dir>")
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    data = snapshot(load_server())
    (out / "snapshot.json").write_text(json.dumps(data, separators=(",", ":")))
    (out / "index.html").write_text(page())
    print(f"{len(data)} combinations → {out}/snapshot.json ({(out / 'snapshot.json').stat().st_size // 1024} KB), index.html")
