"""
moswalk-kernel — property_trigger_scanner

Pure, deterministic function: property flags → set of triggered conditions.
These condition strings map directly to permit_pathways.yaml conditional_agencies[].condition.

No LLM. No external calls. Input is a dict of PLUTO/DOB flags.
Output is a frozenset of condition strings + a structured TriggerResult.

Condition strings are the canonical matching surface between:
  trigger_scanner.py (this file) → agency_navigator.py (pathway resolver)

They are intentionally human-readable — they appear in educational output.

Source authorities:
  NYC Zoning Resolution (ZR) §§ 23-00 through 74-99
  NYC Building Code (BC) 2022 §§ 28-101 et seq.
  NYC Administrative Code (Ad Code)
  FEMA FIRM flood maps (effective 2013, revised 2024)
  HPD Local Law 18/2024 (ADU Pilot Program)
  DOB Local Law 11/1998 as amended (FISP / Façade Inspection)
  DEP 15 RCNY §§ 1-17 (asbestos)
  OATH Ad Code § 28-201 (ECB violations)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class TriggerResult:
    """
    Output of scan(). Carries the conditions for agency resolution,
    plus structured educational flags for display.
    """
    conditions: frozenset[str]

    # Structured flags (also returned individually for FieldAPI)
    landmarked: bool = False
    landmark_type: Optional[str] = None       # "individual" | "interior" | "scenic" | "historic_district"
    flood_zone: Optional[str] = None          # "AE" | "VE" | "X" | None
    pre_1987: bool = False
    open_violations: int = 0
    stories: int = 0
    lot_area_sqft: int = 0
    rent_stabilized: bool = False
    zoning_district: str = ""
    adu_pilot_eligible: bool = False           # HPD ADU pilot program (LL18/2024)
    asbestos_survey_required: bool = False
    fisp_required: bool = False               # FISP / LL11 mandatory (> 6 stories)
    mapped_street_adjacent: bool = False
    occupied_before_2024: bool = False

    def blocker_flags(self) -> list[str]:
        """Return conditions that are hard blockers before filing."""
        blockers = []
        if self.flood_zone in ("AE", "VE"):
            blockers.append(
                f"FLOOD ZONE {self.flood_zone}: ADU pilot INELIGIBLE (Local Law 18/2024 §3). "
                "Flood-resistant construction mandatory per NYC BC Appendix G."
            )
        if self.open_violations > 0:
            blockers.append(
                f"{self.open_violations} open ECB violation(s) must be resolved at OATH "
                "(Ad Code §28-201) before most DOB filings are accepted."
            )
        if self.landmarked:
            lt = self.landmark_type or "landmark"
            blockers.append(
                f"LPC {lt}: Certificate of Appropriateness required BEFORE DOB permits any "
                "exterior work (Ad Code §25-305). Sequence: LPC → DOB."
            )
        return blockers

    def educational_flags(self) -> list[str]:
        """Return plain-English context flags for the field UI."""
        notes = []
        if self.pre_1987 and self.asbestos_survey_required:
            notes.append(
                "Pre-1987 construction: asbestos survey by DEP-certified inspector required "
                "BEFORE any demolition or disturbance (15 RCNY §1-17). Notify DEP ≥7 days prior."
            )
        if self.fisp_required:
            notes.append(
                f"{self.stories}-story building: FISP/LL11 façade inspection mandatory every 5 years. "
                "If UNSAFE: sidewalk shed required immediately. TR6 report due within 60 days. "
                "Non-filing fine: $1,000/month (1 RCNY §103-04)."
            )
        if self.rent_stabilized:
            notes.append(
                "Rent-stabilized building: MCI (Major Capital Improvement) approval from HPD "
                "required if rent increase sought. Tenant notification required (RSL §26-511)."
            )
        if self.adu_pilot_eligible:
            notes.append(
                "Property may qualify for HPD ADU Pilot Program (Local Law 18/2024). "
                "Informal units occupied before April 20, 2024 may be legalized with pilot protections."
            )
        if self.mapped_street_adjacent:
            notes.append(
                "Adjacent to mapped/unmapped street: DCP City Map amendment may be required. "
                "CEQR environmental review triggered if site > 20,000 sq ft (6 RCNY §6-01)."
            )
        return notes


# ---------------------------------------------------------------------------
# Core scanner
# ---------------------------------------------------------------------------

def scan(flags: dict) -> TriggerResult:
    """
    Convert raw property flags (from PLUTO, DOB NOW, or user input) into
    a TriggerResult with conditions that drive permit_pathways.yaml resolution.

    flags dict keys (all optional — scanner is tolerant of missing fields):
        landmarked          bool
        landmark_type       str  "individual" | "interior" | "scenic" | "historic_district"
        flood_zone          str  "AE" | "VE" | "X" | None
        year_built          int
        open_violations     int
        stories             int
        lot_area_sqft       int
        rent_stabilized     bool
        zoning_district     str   e.g. "R6B", "M1-1", "C6-4"
        building_class      str   e.g. "D4", "A5"
        occupied_before_2024  bool  (ADU pilot: unit occupied before April 20, 2024)
        mapped_street_adjacent bool
        has_active_a1       bool  (existing A1 permit in DOB NOW)
        community_district  str   e.g. "BK-06"
        borough             str   "Manhattan" | "Brooklyn" | "Queens" | "Bronx" | "Staten Island"
    """

    g = flags  # short alias

    landmarked    = bool(g.get("landmarked", False))
    landmark_type = g.get("landmark_type")
    flood_zone    = g.get("flood_zone")          # "AE", "VE", "X", or None
    year_built    = int(g.get("year_built", 0))
    open_viol     = int(g.get("open_violations", 0))
    stories       = int(g.get("stories", 0))
    lot_area      = int(g.get("lot_area_sqft", 0))
    rent_stab     = bool(g.get("rent_stabilized", False))
    zoning        = g.get("zoning_district", "")
    occ_before    = bool(g.get("occupied_before_2024", False))
    mapped_st     = bool(g.get("mapped_street_adjacent", False))

    # Derived flags
    pre_1987      = year_built > 0 and year_built < 1987
    asbestos_req  = pre_1987   # conservative: any pre-1987 = survey required
    fisp_req      = stories > 6
    adu_eligible  = (
        occ_before
        and flood_zone not in ("AE", "VE")
        and zoning.startswith("R")      # residential zoning required
    )

    # ── Build condition strings ─────────────────────────────────────────────
    # These strings must match permit_pathways.yaml conditional_agencies[].condition
    # exactly (case-insensitive substring match in agency_navigator.py).

    conditions: set[str] = set()

    if landmarked:
        conditions.add("Landmark building or within historic district")
    if flood_zone in ("AE", "VE"):
        conditions.add("Flood zone AE or VE")
    if pre_1987:
        conditions.add("Pre-1987 construction AND gut renovation or demolition of interior")
    if open_viol > 0:
        conditions.add("Open ECB/DOB violations on record")
        conditions.add("Open violations")
    if lot_area > 20_000 or mapped_st:
        conditions.add("Site > 20,000 sq ft or involves mapped street")
    if rent_stab:
        conditions.add("Rent-stabilized building AND building-wide capital work")
    if stories > 6:
        conditions.add("Enclosure structure requires electrical or anchoring")  # sidewalk cafe special
    if zoning.startswith("C") or zoning.startswith("M"):
        # commercial/manufacturing zones typically require parking analysis
        conditions.add("Residential change of use requiring parking per ZR")
    if flood_zone in ("AE", "VE") and occ_before:
        # explicit ADU ineligibility flag
        conditions.add("Flood zone AE or VE")  # already added above

    return TriggerResult(
        conditions=frozenset(conditions),
        landmarked=landmarked,
        landmark_type=landmark_type,
        flood_zone=flood_zone,
        pre_1987=pre_1987,
        open_violations=open_viol,
        stories=stories,
        lot_area_sqft=lot_area,
        rent_stabilized=rent_stab,
        zoning_district=zoning,
        adu_pilot_eligible=adu_eligible,
        asbestos_survey_required=asbestos_req,
        fisp_required=fisp_req,
        mapped_street_adjacent=mapped_st,
        occupied_before_2024=occ_before,
    )


# ---------------------------------------------------------------------------
# PLUTO-to-flags mapper
# ---------------------------------------------------------------------------

def from_pluto_row(row: dict) -> dict:
    """
    Map a PLUTO v25v4 CSV row (or Socrata API response dict) to the
    flags dict expected by scan().

    Key PLUTO fields used:
        LandUse, BldgClass, ZoneDist1, NumFloors, LotArea,
        YearBuilt, FloodZone, LandMarked, HistDist, OwnerType
    """

    year_raw = row.get("YearBuilt", "0")
    try:
        year = int(year_raw)
    except (ValueError, TypeError):
        year = 0

    floors_raw = row.get("NumFloors", "0")
    try:
        floors = int(float(floors_raw))
    except (ValueError, TypeError):
        floors = 0

    lot_raw = row.get("LotArea", "0")
    try:
        lot_area = int(float(lot_raw))
    except (ValueError, TypeError):
        lot_area = 0

    # PLUTO landmark field: "Y" = individual, "" = none; HistDist = district name
    pluto_lm  = str(row.get("LandMarked", "")).strip().upper()
    hist_dist = str(row.get("HistDist", "")).strip()
    is_lm     = (pluto_lm == "Y") or bool(hist_dist)
    lm_type   = None
    if pluto_lm == "Y":
        lm_type = "individual"
    elif hist_dist:
        lm_type = "historic_district"

    # PLUTO FloodZone: "AE", "VE", "X", "0.2 PCT ANNUAL CHANCE", etc.
    pluto_fz = str(row.get("FloodZone", "")).strip().upper()
    if "AE" in pluto_fz:
        flood_zone = "AE"
    elif "VE" in pluto_fz:
        flood_zone = "VE"
    elif "X" in pluto_fz:
        flood_zone = "X"
    else:
        flood_zone = None

    # OwnerType R = rent-regulated (rough proxy; verify with HPD HPDRP)
    owner_type = str(row.get("OwnerType", "")).strip().upper()
    rent_stab  = owner_type == "R"

    return {
        "landmarked":     is_lm,
        "landmark_type":  lm_type,
        "flood_zone":     flood_zone,
        "year_built":     year,
        "stories":        floors,
        "lot_area_sqft":  lot_area,
        "rent_stabilized": rent_stab,
        "zoning_district": str(row.get("ZoneDist1", "")).strip(),
        "building_class":  str(row.get("BldgClass", "")).strip(),
    }


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # SIM-001: Brooklyn Park Slope brownstone, LPC historic district
    sim_001 = scan({
        "landmarked":    True,
        "landmark_type": "historic_district",
        "flood_zone":    None,
        "year_built":    1895,
        "open_violations": 0,
        "stories":       3,
        "lot_area_sqft": 2_000,
        "rent_stabilized": False,
        "zoning_district": "R6B",
    })
    print("SIM-001 conditions:", sorted(sim_001.conditions))
    print("  blockers:", sim_001.blocker_flags())
    print()

    # SIM-002: Queens ADU, flood zone AE
    sim_002 = scan({
        "landmarked":    False,
        "flood_zone":    "AE",
        "year_built":    1963,
        "open_violations": 2,
        "stories":       2,
        "lot_area_sqft": 3_500,
        "rent_stabilized": False,
        "zoning_district": "R3-2",
        "occupied_before_2024": True,
    })
    print("SIM-002 conditions:", sorted(sim_002.conditions))
    print("  blockers:", sim_002.blocker_flags())
    print()

    # SIM-006: Manhattan FISP UNSAFE
    sim_006 = scan({
        "stories":       8,
        "year_built":    1930,
        "open_violations": 0,
    })
    print("SIM-006 conditions:", sorted(sim_006.conditions))
    print("  fisp_required:", sim_006.fisp_required)
    print("  educational:", sim_006.educational_flags())
