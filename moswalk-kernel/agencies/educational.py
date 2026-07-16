"""
moswalk-kernel — educational layer

Plain English explanations for every agency in the permit ecosystem.
The goal: move away from the fear of building.

Anyone — homeowner, architect student, first-time developer — should be able
to read this and understand WHAT each agency does, WHY they're involved in
their project, WHAT to actually file, and WHAT trips people up.

Structure per agency:
  what       — 2-sentence plain English description
  why        — why does this agency appear in a building permit path?
  how        — what do you actually do? where do you go?
  common_mistakes — what trips people up
  law_citation    — the actual statute or rule that creates the requirement
  portal     — public-facing URL (from agencies.yaml has_public_portal)
  filing_fee_note — typical cost range (filing fees, not professional fees)
  timeline_note   — realistic calendar expectation

These are reference data — they do not change with model updates.
Update when Local Laws or agency rules change.

Last verified: April 2026
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class AgencyEdu:
    code: str
    what: str
    why: str
    how: str
    common_mistakes: list[str]
    law_citation: str
    portal: str
    filing_fee_note: str
    timeline_note: str
    self_cert_available: bool = False
    self_cert_note: str = ""

    def plain_text(self, verbose: bool = False) -> str:
        lines = [
            f"═══ {self.code} ═══",
            f"What: {self.what}",
            f"Why:  {self.why}",
            f"How:  {self.how}",
        ]
        if verbose:
            if self.common_mistakes:
                lines.append("Common mistakes:")
                for m in self.common_mistakes:
                    lines.append(f"  ✗ {m}")
            lines += [
                f"Law:  {self.law_citation}",
                f"Portal: {self.portal}",
                f"Cost: {self.filing_fee_note}",
                f"Time: {self.timeline_note}",
            ]
            if self.self_cert_available:
                lines.append(f"Self-cert: {self.self_cert_note}")
        return "\n".join(lines)

    def one_liner(self) -> str:
        return f"{self.code}: {self.what.split('.')[0]}."


# ---------------------------------------------------------------------------
# The educational registry
# ---------------------------------------------------------------------------

AGENCY_EDU: dict[str, AgencyEdu] = {

    "DOB": AgencyEdu(
        code="DOB",
        what=(
            "The Department of Buildings enforces the NYC Building Code and Zoning Resolution. "
            "It reviews plans, issues building permits, and conducts inspections — it is the front door "
            "for almost every construction project in the city."
        ),
        why=(
            "DOB is involved because any structural, electrical, plumbing, or use-change work on a "
            "NYC property legally requires a DOB permit (NYC Admin Code §28-105.1). "
            "No permit = stop-work order, violation, and potential demolition requirement."
        ),
        how=(
            "File through DOB NOW: Build (dobnowasbuild.nyc.gov). Create an account, select your "
            "filing type (NB / A1 / A2 / A3 / TR6), upload drawings, pay fees. A licensed RA or PE "
            "must be the applicant of record. Plan examination is required for NB and A1; A2/A3 may "
            "qualify for Professional Certification (self-cert, no exam queue)."
        ),
        common_mistakes=[
            "Starting work before the permit is issued — triggers a Stop Work Order and a violation.",
            "Filing the wrong alteration type (A2 when A1 is required because the use changes).",
            "Missing the pre-filing meeting for NB filings — saves weeks of back-and-forth.",
            "Forgetting to resolve open ECB violations before filing — DOB won't accept new filings.",
            "Self-certifying work that doesn't qualify for Pro Cert — 25% audit rate; get it wrong and you owe corrections plus a violation.",
        ],
        law_citation="NYC Admin Code §28-105.1 (permit required); §28-104.7 (Professional Certification); 1 RCNY §101-07",
        portal="https://dobnowasbuild.nyc.gov",
        filing_fee_note="$280 base + $14/per $1,000 construction cost (A2 typical). NB: $280 + $38/per $1,000. No cap.",
        timeline_note="Pro Cert A2: 5–10 business days for permit. Plan exam A1: 3–12 months depending on complexity and queue.",
        self_cert_available=True,
        self_cert_note="Professional Certification (Pro Cert / Directive 14) available for A2/A3. Licensed RA or PE certifies compliance. ~25% of filings audited. Errors trigger full plan exam + potential violation.",
    ),

    "LPC": AgencyEdu(
        code="LPC",
        what=(
            "The Landmarks Preservation Commission protects 38,000+ individual landmarks, 146 historic "
            "districts, and 121 interior landmarks across the five boroughs. "
            "It must approve any exterior change to a designated property before DOB issues a permit."
        ),
        why=(
            "If your property is landmarked or in a historic district, LPC approval is legally required "
            "before DOB can issue any permit for exterior work (Admin Code §25-305). "
            "LPC does not review interior work unless the space is an Interior Landmark."
        ),
        how=(
            "File at LPC online (LPCApplication.nyc.gov). A licensed architect typically prepares the "
            "application. LPC staff review for minor work (staff-level, 10–15 business days). "
            "Larger changes go to a public hearing before the full Commission (60–90 days). "
            "Request a pre-application meeting — free, saves months. "
            "XCNE track (Expedited Certificate of No Effect): 3–5 business days for clearly non-visible work."
        ),
        common_mistakes=[
            "Starting exterior work without LPC approval — LPC can require you to undo all changes at your cost.",
            "Not checking whether the project is within a historic DISTRICT vs. individual landmark — different tracks.",
            "Missing the difference between staff approval (fast) and full Commission hearing (slow). Pre-app meeting clarifies this.",
            "Submitting insufficient drawings — LPC requires existing/proposed elevations showing context.",
            "Assuming DOB will catch it — DOB and LPC are separate systems; neither automatically notifies the other.",
        ],
        law_citation="NYC Admin Code §25-305 (Certificate of Appropriateness); §25-306 (Certificate of No Effect); 63 RCNY §2-01",
        portal="https://lpcapplication.nyc.gov",
        filing_fee_note="No filing fee for most LPC applications (funded by City). Expedited review: none. Rush: $500 optional.",
        timeline_note="Staff-level (CNE/staff approval): 10–15 business days. Full CoA with public hearing: 60–90 days. XCNE: 3–5 business days.",
        self_cert_available=False,
    ),

    "DEP": AgencyEdu(
        code="DEP",
        what=(
            "The Department of Environmental Protection manages the city's water supply, wastewater, "
            "and environmental protection programs including asbestos, noise, and air quality. "
            "For construction, DEP governs water/sewer connections, asbestos surveys, and stormwater."
        ),
        why=(
            "DEP is required when your project: (1) disturbs pre-1987 construction (asbestos survey), "
            "(2) adds a new water/sewer connection (tap-in application), or (3) involves significant "
            "impervious surface that triggers stormwater review. All three are legally mandated."
        ),
        how=(
            "Asbestos: hire a DEP-certified inspector (AHERA-accredited). Survey before any demo. "
            "File DEP notification online (nyc.gov/dep) ≥7 days before disturbing material. "
            "Water/sewer: file Water and Sewer Application (WSBS) for tap-in. "
            "DEP inspects the tap-in before DOB issues the foundation permit."
        ),
        common_mistakes=[
            "Starting demolition before the asbestos survey — criminal liability under 15 RCNY §1-17.",
            "Hiring a non-certified asbestos inspector — the survey is void; DEP will require a new one.",
            "Missing the 7-day pre-notification requirement — $10,000+ fine for each day of violation.",
            "Forgetting the water/sewer application — DEP approval is a prerequisite for the DOB foundation permit.",
        ],
        law_citation="15 RCNY §§1-17 (asbestos); Admin Code §24-136 (asbestos general); Admin Code §24-526 (water/sewer); NYC BC §§1008, 1009",
        portal="https://www.nyc.gov/dep",
        filing_fee_note="Asbestos survey: $1,500–$5,000 (varies by scope). DEP notification: $165. Water tap-in: $3,500–$25,000 depending on size.",
        timeline_note="Asbestos survey: 1–2 weeks. DEP notification approval: 7-day statutory wait. Water/sewer approval: 2–4 weeks.",
        self_cert_available=False,
    ),

    "FDNY": AgencyEdu(
        code="FDNY",
        what=(
            "The Fire Department of New York reviews plans and inspects buildings for fire safety compliance. "
            "It issues the Place of Assembly permit (required for spaces with > 74 occupants) and reviews "
            "sprinkler, alarm, and egress systems."
        ),
        why=(
            "FDNY review is required whenever: a change of use to assembly occupancy occurs, a new building "
            "exceeds 3 stories residential (sprinkler), or a Place of Assembly permit is needed (> 74 occupants). "
            "NYC Fire Code §FC 107.2 requires FDNY approval before CO is issued for these uses."
        ),
        how=(
            "File plans through DOB NOW — FDNY review is routed automatically for applicable filings. "
            "For Place of Assembly permits: file separately at FDNY (nycfirepa.com). "
            "FDNY inspects after construction is complete, before DOB sign-off."
        ),
        common_mistakes=[
            "Designing sprinkler system without FDNY-approved drawings — FDNY will require revision and re-inspection.",
            "Occupying a space for public assembly before the PA permit is issued — $10,000+ fine.",
            "Missing panic hardware requirements for assembly occupancy egress.",
            "Forgetting CO detector/alarm requirements when adding sleeping rooms.",
        ],
        law_citation="NYC Fire Code §FC 107.2; §FC 401.3.4 (PA permit); 3 RCNY (FDNY Rules); NYC BC §903 (sprinklers)",
        portal="https://www1.nyc.gov/site/fdny/index.page",
        filing_fee_note="PA permit: $340 base + occupant load fee. Sprinkler plan review: $175–$1,400 depending on system size.",
        timeline_note="FDNY plan review: 2–4 weeks after DOB accepts filing. Inspection: 1–2 weeks after completion.",
        self_cert_available=False,
    ),

    "NYC DOT": AgencyEdu(
        code="NYC DOT",
        what=(
            "The Department of Transportation manages streets, sidewalks, curbs, and the public right-of-way. "
            "For construction: DOT issues street opening permits, curb cut permits, sidewalk shed permits, "
            "and revocable consent for sidewalk cafés."
        ),
        why=(
            "Whenever construction requires: cutting into the street (for sewer/water connections), "
            "building a sidewalk shed (for FISP UNSAFE conditions), installing a curb cut, or placing "
            "outdoor seating in the public right-of-way — DOT is the approving agency. "
            "The public right-of-way is DOT's jurisdiction, full stop."
        ),
        how=(
            "Street openings: permit.nyc.gov (Permit FAQS portal). Sidewalk sheds: file through DOB (A2) "
            "then DOT for the sidewalk/curb permit. Sidewalk café: Revocable Consent application at "
            "nyc.gov/dot — Community Board review is automatically triggered within 5 days."
        ),
        common_mistakes=[
            "Opening the street without a permit — $5,000+ fine, required restoration at your cost.",
            "Building a sidewalk shed without the DOT construction fence/shed permit.",
            "Not accounting for Community Board review time in sidewalk café timeline (adds 3–6 months).",
            "Missing the 8-foot pedestrian clear path requirement for café siting.",
        ],
        law_citation="NYC Admin Code §19-141 (street openings); §19-226 (sidewalk cafés); 34 RCNY §2-02; Traffic Rules §4-06",
        portal="https://permit.nyc.gov",
        filing_fee_note="Street opening: $135 base + per-linear-foot fee. Sidewalk shed permit: $280. Revocable consent: $1,000 application fee.",
        timeline_note="Street opening: 3–5 business days. Sidewalk shed: 5–10 business days. Revocable consent (café): 4–6 months including CB review.",
        self_cert_available=False,
    ),

    "BSA": AgencyEdu(
        code="BSA",
        what=(
            "The Board of Standards and Appeals is the zoning appeals board — a quasi-judicial body that "
            "hears variance applications, special permit appeals, and appeals of DOB or DCP determinations. "
            "It has no supervisor in the City org chart; it is independent."
        ),
        why=(
            "BSA appears when a project requires: a use variance (ZR §72-21), an area variance, "
            "a special permit that BSA (not City Planning) grants, or an appeal of a DOB determination. "
            "If the Zoning Resolution says 'no' and you believe hardship applies, BSA is the path."
        ),
        how=(
            "Pre-Determination letter first (strongly recommended): BSA will tell you in 6–8 weeks whether "
            "your project has a viable case — BEFORE you spend $50K on a full variance application. "
            "Full application: file at BSA (nyc.gov/bsa), retain a land use attorney, prepare hardship "
            "findings per ZR §72-21.4, appear at public hearing, present to Community Board."
        ),
        common_mistakes=[
            "Filing a full variance application without first getting a Pre-Determination — wastes $50K+ if denied.",
            "Underestimating Community Board influence — CB recommendation is not binding but heavily weighted.",
            "Not meeting all four ZR §72-21 hardship findings — missing any one = automatic denial.",
            "Treating BSA as a negotiation — it is adjudicative; prepare the legal record.",
            "Assuming BSA will grant what Community Board opposes — extremely rare.",
        ],
        law_citation="NYC Charter §668 (BSA powers); Zoning Resolution §72-21 (use variance hardship findings); §73-00 (special permits)",
        portal="https://www.nyc.gov/bsa",
        filing_fee_note="Pre-Determination: $1,750. Variance application: $3,500–$6,000 filing fee. Professional costs (attorney, architect): $50K–$150K+.",
        timeline_note="Pre-Determination: 6–8 weeks. Full variance: 4–6 months typical. Contested: 9–18 months.",
        self_cert_available=False,
    ),

    "DCP": AgencyEdu(
        code="DCP",
        what=(
            "The Department of City Planning administers the Zoning Resolution and reviews land use actions "
            "that require City Planning Commission approval: rezonings, special permits, CEQR environmental "
            "review, and Uniform Land Use Review Procedure (ULURP) applications."
        ),
        why=(
            "DCP review is required for: new buildings on large sites (CEQR if > 20,000 sq ft or triggers "
            "significant environmental impact), City Map amendments, zoning map changes, or special permits "
            "that the ZR routes to the City Planning Commission rather than BSA."
        ),
        how=(
            "Pre-application conference: nyc.gov/dcp — free, strongly recommended before CEQR. "
            "CEQR: Environmental Assessment Statement (EAS) for smaller actions; Environmental Impact "
            "Statement (EIS) for significant impacts. "
            "ULURP: 60-day Community Board review → Borough President → CPC → City Council. Full cycle: 7–12 months."
        ),
        common_mistakes=[
            "Assuming CEQR doesn't apply to a mid-size project — any action that requires a discretionary approval gets screened.",
            "Skipping the pre-application conference — DCP staff can scope the EAS and save months of rework.",
            "Not running ULURP in parallel with design development — it is a 7-month minimum regardless of project readiness.",
        ],
        law_citation="NYC Charter §197-a (ULURP); 62 RCNY §§6-01 through 6-15 (CEQR); Zoning Resolution §11-00",
        portal="https://www.nyc.gov/dcp",
        filing_fee_note="EAS filing: $2,000–$6,000. EIS: $20,000–$500,000+ (consulting costs). ULURP application: $3,000–$10,000.",
        timeline_note="Pre-application: free, 2–4 weeks for meeting. CEQR EAS: 2–6 months. Full ULURP: 7–12 months minimum.",
        self_cert_available=False,
    ),

    "OATH": AgencyEdu(
        code="OATH",
        what=(
            "The Office of Administrative Trials and Hearings is the City's independent administrative "
            "court system. For building professionals: OATH hears Environmental Control Board (ECB) "
            "violation hearings — the tribunal where DOB, DEP, and FDNY violations are adjudicated."
        ),
        why=(
            "If your property has open ECB violations (issued by DOB, DEP, FDNY, or DSNY inspectors), "
            "they must be resolved at OATH before most DOB filings will be accepted. "
            "Violations accrue daily penalties. OATH is also where the Sidewalk Café revocable consent "
            "process routes contested applications."
        ),
        how=(
            "Log into ECB Online (ecbonline.nyc.gov) to see all open violations. "
            "Request a hearing at OATH (oath.nyc.gov). Appear with evidence of correction. "
            "If work was corrected: bring photos, contractor affidavits, and correction receipts. "
            "If violation was issued in error: bring documentation to contest. "
            "Stipulated agreements: resolve without a hearing if you admit and pay (faster)."
        ),
        common_mistakes=[
            "Ignoring open violations and trying to file a new DOB permit — DOB's system flags them and rejects the filing.",
            "Not appearing at the OATH hearing — default judgment, full penalty, no appeal.",
            "Paying the fine without getting a Certificate of Correction — the violation stays open on record.",
            "Missing that ECB and OATH are different entities: ECB issues the violation, OATH hears the case.",
        ],
        law_citation="NYC Admin Code §28-201 (ECB violations); §§1041–1049 (ECB hearing procedures); NYC Charter §1048 (OATH jurisdiction)",
        portal="https://www.nyc.gov/oath",
        filing_fee_note="Hearing: free. Violation penalties: $250–$25,000+ per violation, per day. Stipulated agreement: reduced penalty available.",
        timeline_note="Hearing scheduled: 4–8 weeks from request. Appear with evidence, same-day resolution if correction proven.",
        self_cert_available=False,
    ),

    "HPD": AgencyEdu(
        code="HPD",
        what=(
            "The Department of Housing Preservation and Development administers housing programs, "
            "enforces the Housing Maintenance Code, and oversees the ADU Pilot Program (Local Law 18/2024). "
            "It is the intake agency for basement apartment legalization under the pilot program."
        ),
        why=(
            "HPD appears when: (1) the project involves the ADU Pilot Program (informal basement unit "
            "occupied before April 20, 2024 in a 1–3 family home), or (2) the building is rent-stabilized "
            "and capital work triggers an MCI (Major Capital Improvement) rent increase application."
        ),
        how=(
            "ADU Pilot: apply at hpd.nyc.gov/adu — HPD reviews eligibility, coordinates with DOB. "
            "MCI: file at HPD's online portal. MCI approval takes 6–18 months; tenant notification required. "
            "Housing Maintenance Code violations (different from ECB): resolved at HPD, not OATH."
        ),
        common_mistakes=[
            "Applying for ADU pilot in a flood zone AE or VE — program is ineligible, full stop.",
            "Revealing informal occupancy history in a public filing without client consent — privacy issue (SHIELD Act).",
            "Confusing HPD Housing Maintenance Code violations (civil) with ECB violations (administrative). Different systems.",
            "Filing MCI without notifying tenants first — required, and failure invalidates the application.",
        ],
        law_citation="Local Law 18/2024 (ADU Pilot); Admin Code §§26-510–26-511 (MCI); Housing Maintenance Code §27-2000 et seq.",
        portal="https://www.nyc.gov/hpd",
        filing_fee_note="ADU Pilot intake: free. MCI application: $300 + per-unit fee. DOB A1 for ADU legalization: standard DOB fees.",
        timeline_note="ADU Pilot HPD intake: 30–60 days for eligibility determination. MCI: 6–18 months. ADU DOB A1: 60–90 days.",
        self_cert_available=False,
    ),

    "DSNY": AgencyEdu(
        code="DSNY",
        what=(
            "The Department of Sanitation manages solid waste collection, street cleaning, and "
            "construction waste regulations. For building work: DSNY permits are needed for "
            "temporary dumpsters (roll-offs) in the street and large construction waste removal."
        ),
        why=(
            "Any construction generating > 10 cubic yards of debris per day (or placing a dumpster "
            "in the street) requires a DSNY permit. Unlicensed debris removal = violation."
        ),
        how=(
            "Roll-off dumpster permit: nyc.gov/dsny — file for street use. "
            "Construction waste: use a licensed transfer station (DSNY-approved hauler required). "
            "No debris in blue recycling bins — separate streams required."
        ),
        common_mistakes=[
            "Placing a dumpster in the street without a DSNY street placement permit.",
            "Using an unlicensed hauler for construction debris — DSNY violation + cost of re-removal.",
        ],
        law_citation="Admin Code §16-119 (illegal disposal); §16-120.1 (construction waste); 16 RCNY §4-01",
        portal="https://www.nyc.gov/dsny",
        filing_fee_note="Roll-off street placement: $130/month. Licensed hauler: market rate ($400–$1,500/load depending on debris type).",
        timeline_note="Permit: 2–3 business days.",
        self_cert_available=False,
    ),

    "NYCEDC": AgencyEdu(
        code="NYCEDC",
        what=(
            "The NYC Economic Development Corporation manages City-owned properties and administers "
            "economic development programs. For building professionals: EDC is relevant when a project "
            "is on City-owned land, in an EDC-managed district, or seeking ICAP/ICIP tax benefits."
        ),
        why=(
            "EDC appears when: project is on City-owned or EDC-managed land (special leasehold rules), "
            "or developer is seeking Industrial Commercial Abatement Program (ICAP) tax abatement, "
            "or project is in an EDC special district (Flushing, Sunset Park, Brooklyn Navy Yard)."
        ),
        how=(
            "EDC projects are typically initiated through competitive RFP processes or direct developer "
            "engagement. ICAP: file with DOF, EDC assists with eligibility verification. "
            "No standard public portal — engage EDC project team directly."
        ),
        common_mistakes=[
            "Assuming ICAP applies automatically — must apply within 1 year of construction start.",
            "Not confirming City land lease terms before design — land use restrictions in EDC leases are binding.",
        ],
        law_citation="Admin Code §§11-258 through 11-270 (ICAP); §22-621 (ICAP eligibility); EDC lease terms vary by project",
        portal="https://edc.nyc",
        filing_fee_note="ICAP application: $600. EDC RFP processes: no fee. Tax abatement value: varies, can be substantial.",
        timeline_note="ICAP review: 3–6 months. EDC lease negotiation: 6–24 months.",
        self_cert_available=False,
    ),
}


# ---------------------------------------------------------------------------
# Accessor
# ---------------------------------------------------------------------------

def explain(code: str, verbose: bool = True) -> str:
    """Return educational text for agency code."""
    edu = AGENCY_EDU.get(code)
    if not edu:
        return (
            f"{code}: No educational entry in moswalk-kernel registry. "
            "This may be a T3 (unknown/provisional) agency. "
            "Run the t3_discovery skill to surface available information."
        )
    return edu.plain_text(verbose=verbose)


def explain_pathway(steps: list, verbose: bool = False) -> str:
    """
    Return educational text for every agency in an ordered step list.
    steps: list of AgencyStep or dict with 'code' key.
    """
    seen: set[str] = set()
    lines = []
    for step in steps:
        code = step.code if hasattr(step, "code") else step.get("code", "?")
        if code in seen:
            continue
        seen.add(code)
        lines.append(explain(code, verbose=verbose))
        lines.append("")
    return "\n".join(lines).strip()


def one_liner_index() -> str:
    """Return a compact index of all agencies in the educational registry."""
    return "\n".join(edu.one_liner() for edu in AGENCY_EDU.values())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else None
    if code:
        print(explain(code, verbose=True))
    else:
        print("moswalk-kernel educational registry — all agencies:\n")
        print(one_liner_index())
        print("\nUsage: python educational.py DOB")
