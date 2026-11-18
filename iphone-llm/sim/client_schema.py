# Simulated NYC client project schema for moswalk regulatory testing.
#
# Each client represents a realistic NYC property owner or professional
# with a specific construction/renovation project and known regulatory pathway.
# BBLs are real NYC lots; project details are synthetic but typologically accurate.
#
# Data sources used to ground these scenarios:
#   - PLUTO v25v4 (NYCPlanning/db-pluto) for zoning, building class, year built
#   - DOB NOW Socrata SODA API for permit type patterns and cost ranges
#   - agencies.yaml (139 active NYC orgs) for agency codes
#   - NYC Geoclient API schema for BBL resolution
#   - ACRIS for ownership context

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import yaml
from pathlib import Path


class Borough(str, Enum):
    MANHATTAN    = "Manhattan"
    BROOKLYN     = "Brooklyn"
    QUEENS       = "Queens"
    BRONX        = "Bronx"
    STATEN_ISLAND = "Staten Island"

    @property
    def code(self) -> int:
        return {"Manhattan": 1, "Brooklyn": 3, "Queens": 4,
                "Bronx": 2, "Staten Island": 5}[self.value]


class ClientType(str, Enum):
    HOMEOWNER      = "homeowner"
    LANDLORD       = "landlord"
    DEVELOPER      = "developer"
    BUSINESS_OWNER = "business_owner"
    CONDO_BOARD    = "condo_board"
    NONPROFIT      = "nonprofit"
    EXPEDITER      = "expediter"


class ProjectScope(str, Enum):
    NEW_BUILDING    = "NB"     # DOB NB filing
    ALT_TYPE_1      = "A1"     # Major alteration (change of use/egress/occupancy)
    ALT_TYPE_2      = "A2"     # Multiple types of work
    ALT_TYPE_3      = "A3"     # Minor alteration (single work type)
    DEMOLITION      = "DM"
    PLACE_OF_ASSEMBLY = "PA"


class EscalationRisk(str, Enum):
    NONE   = "none"
    LOW    = "low"
    MEDIUM = "medium"
    HIGH   = "high"


@dataclass
class AgencyRequirement:
    """One agency's role in a project's regulatory pathway."""
    code: str                          # from agencies.yaml
    role: str                          # primary | approval | notification | inspection
    sequential_after: list[str] = field(default_factory=list)  # codes that must resolve first
    blocking: bool = False             # if True and unresolved, halt all downstream
    estimated_days: int = 30           # median calendar days to resolution
    confidence: float = 0.85          # 0–1; <0.70 triggers stale flag
    notes: str = ""


@dataclass
class PropertyFlags:
    """PLUTO-derived and regulatory flags that trigger agency requirements."""
    landmarked: bool = False
    landmark_type: Optional[str] = None      # individual | interior | scenic | historic_district
    flood_zone: Optional[str] = None         # AE | AO | X | VE
    rent_stabilized: bool = False
    hpd_registered: bool = False
    within_subway_easement: bool = False     # 90-ft rule: triggers NYC Transit review
    active_violations: int = 0              # open DOB/ECB violations on record
    c_of_o_mismatch: bool = False           # actual use != CO use — triggers A1 minimum
    special_purpose_district: Optional[str] = None  # e.g., "Special Hudson Yards"
    waterfront: bool = False
    asbestos_survey_required: bool = False  # pre-1987 construction + gut reno


@dataclass
class SimProperty:
    bbl: str                  # Borough-Block-Lot e.g. "3-00783-0001"
    address: str
    borough: Borough
    zoning_district: str      # e.g. "R6B", "C4-4D", "M1-1"
    building_class: str       # DOF building class e.g. "A5", "D4", "R4"
    year_built: int
    stories: int
    residential_units: int
    gross_sq_ft: int
    flags: PropertyFlags = field(default_factory=PropertyFlags)


@dataclass
class SimProject:
    type: str                 # human-readable e.g. "Rooftop deck addition"
    description: str
    estimated_cost_usd: int
    scope: ProjectScope
    agencies: list[AgencyRequirement] = field(default_factory=list)
    escalation_risk: EscalationRisk = EscalationRisk.LOW
    total_estimated_days: int = 0        # sum of critical path (not parallel)
    analyst_notes: list[str] = field(default_factory=list)

    def critical_path_days(self) -> int:
        """Sum of blocking agencies in sequence (conservative estimate)."""
        blocking = [a for a in self.agencies if a.blocking]
        return sum(a.estimated_days for a in blocking)


@dataclass
class SimClient:
    client_id: str
    name: str                 # anonymized / synthetic
    client_type: ClientType
    property: SimProperty
    project: SimProject
    data_sources: list[str] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path) -> "SimClient":
        with open(path) as f:
            raw = yaml.safe_load(f)

        prop_raw = raw["property"]
        flags = PropertyFlags(**prop_raw.get("flags", {}))
        prop = SimProperty(
            bbl=prop_raw["bbl"],
            address=prop_raw["address"],
            borough=Borough(prop_raw["borough"]),
            zoning_district=prop_raw["zoning_district"],
            building_class=prop_raw["building_class"],
            year_built=prop_raw["year_built"],
            stories=prop_raw["stories"],
            residential_units=prop_raw["residential_units"],
            gross_sq_ft=prop_raw["gross_sq_ft"],
            flags=flags,
        )

        proj_raw = raw["project"]
        agencies = [AgencyRequirement(**a) for a in proj_raw.get("agencies", [])]
        proj = SimProject(
            type=proj_raw["type"],
            description=proj_raw["description"],
            estimated_cost_usd=proj_raw["estimated_cost_usd"],
            scope=ProjectScope(proj_raw["scope"]),
            agencies=agencies,
            escalation_risk=EscalationRisk(proj_raw.get("escalation_risk", "low")),
            analyst_notes=proj_raw.get("analyst_notes", []),
        )
        proj.total_estimated_days = proj.critical_path_days()

        return cls(
            client_id=raw["client_id"],
            name=raw["name"],
            client_type=ClientType(raw["client_type"]),
            property=prop,
            project=proj,
            data_sources=raw.get("data_sources", []),
        )

    def prompt(self) -> str:
        """Build a moswalk consultation prompt for this client."""
        f = self.property.flags
        flag_lines = []
        if f.landmarked:
            flag_lines.append(f"  - Building is landmarked ({f.landmark_type})")
        if f.flood_zone:
            flag_lines.append(f"  - Flood zone: {f.flood_zone}")
        if f.rent_stabilized:
            flag_lines.append("  - Rent-stabilized units present")
        if f.active_violations > 0:
            flag_lines.append(f"  - {f.active_violations} open DOB/ECB violation(s) on record")
        if f.c_of_o_mismatch:
            flag_lines.append("  - Certificate of Occupancy mismatch (actual use ≠ CO)")
        if f.within_subway_easement:
            flag_lines.append("  - Within 90-ft subway easement (NYC Transit review required)")
        if f.asbestos_survey_required:
            flag_lines.append("  - Pre-1987 construction — asbestos survey required before gut reno")

        flags_section = "\n".join(flag_lines) if flag_lines else "  - No special flags"

        return f"""moswalk consultation request
Client: {self.name} ({self.client_type.value})
Property: {self.property.address}, {self.property.borough.value}
BBL: {self.property.bbl}
Zoning: {self.property.zoning_district} | Class: {self.property.building_class}
Built: {self.property.year_built} | Stories: {self.property.stories} | Units: {self.property.residential_units}

Project: {self.project.type}
Scope: DOB filing type {self.project.scope.value}
Estimated cost: ${self.project.estimated_cost_usd:,}

Description: {self.project.description}

Property flags:
{flags_section}

Question: What agencies do I need to file with, in what order, and what are the key risks?"""


def load_all_clients(sim_dir: Path = None) -> list[SimClient]:
    if sim_dir is None:
        sim_dir = Path(__file__).parent / "clients"
    return [SimClient.from_yaml(p) for p in sorted(sim_dir.glob("*.yaml"))]
