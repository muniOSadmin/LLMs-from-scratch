# pantocraft // — NYC AEC Intake Pipeline Prompts
#
# 8 production Claude API prompts for the intake pipeline.
# Model: claude-sonnet-4-20250514, max_tokens: 1000 (Prompt 8: 1500)
#
# Usage pattern:
#   from pantocraft.prompts.intake_pipeline import build_prompt, Prompt
#   system, user = build_prompt(Prompt.ADDRESS_EXTRACTOR, raw_content="...", source_type="email")
#
# All prompts return JSON. Strip ```json fences before parsing.
# Claude API must use zero-retention mode (Anthropic account setting).
#
# Privacy: these prompts operate on raw content that may contain BBLs
# and property context. Never include client PII (owner names, contact
# info, financial data) as prompt variables — use engagement_id only.

from __future__ import annotations

from enum import Enum
from string import Template
from typing import Any


class Prompt(Enum):
    ADDRESS_EXTRACTOR       = "address_extractor"
    PROJECT_CLASSIFIER      = "project_classifier"
    PROPERTY_ENRICHMENT     = "property_enrichment"
    OPPORTUNITY_SCORER      = "opportunity_scorer"
    ROUTING_DECISION        = "routing_decision"
    OUTREACH_EMAIL          = "outreach_email"
    REGULATORY_CHANGE       = "regulatory_change"
    PROPERTY_BRIEF          = "property_brief"


# ---------------------------------------------------------------------------
# Prompt 1 — Address Extractor
# Runs first on every incoming item before any other processing.
# ---------------------------------------------------------------------------

_P1_SYSTEM = """\
You are an address extraction engine for a NYC property consulting practice.
Your only job: find every NYC address in the input and return structured JSON.
Return ONLY valid JSON. No explanation, no markdown, no preamble."""

_P1_USER = """\
Extract all NYC addresses from the following content.

SOURCE TYPE: $source_type
CONTENT:
$raw_content

Return JSON:
{
  "addresses": [
    {
      "raw": "string — address as it appears in the text",
      "normalized": "string — standard format: NUMBER STREET, BOROUGH",
      "borough": "Manhattan | Brooklyn | Queens | Bronx | Staten Island",
      "confidence": "high | medium | low"
    }
  ],
  "address_count": integer,
  "source_has_address": true | false
}

If no address found, return address_count: 0 and empty array."""


# ---------------------------------------------------------------------------
# Prompt 2 — Project Classifier
# Runs after Prompt 1 returns a confirmed address.
# ---------------------------------------------------------------------------

_P2_SYSTEM = """\
You are a senior NYC building expeditor with 25 years of experience.
You classify property inquiries by project type and required agency track.
Return ONLY valid JSON. No explanation, no preamble."""

_P2_USER = """\
Classify the project implied by the following inquiry.

ADDRESS: $normalized_address
SOURCE TYPE: $source_type
CONTENT:
$raw_content

PROPERTY DATA (if available):
- Open DOB violations: $dob_violations
- Open HPD violations: $hpd_violations
- Open ECB violations: $ecb_violations
- Last permit filed: $last_permit
- Zoning district: $zoning

Return JSON:
{
  "primary_project_type": "one of: new_building | alteration_alt1 | alteration_alt2 | alteration_alt3 | co_pursuit | violation_clearance | landmark_approval | bsa_variance | ulurp_rezoning | tax_incentive | dep_utility | dot_permit | ll97_compliance | hpd_clearance | dca_license | fisp_facade | adu_legalization | other",
  "secondary_project_types": ["array of additional types if multi-track"],
  "agency_cluster": ["array: DOB | LPC | BSA | DCP | DEP | NYC_DOT | FDNY | HPD | DOF | OATH | DOHMH"],
  "urgency": "immediate | high | standard | monitor",
  "urgency_reason": "string — one sentence",
  "client_type_inferred": "individual_owner | llc_entity | developer | architect | attorney | contractor | unknown",
  "confidence": "high | medium | low",
  "classifier_notes": "string or null"
}"""


# ---------------------------------------------------------------------------
# Prompt 3 — Property Enrichment Synthesizer
# Runs after all parallel API calls return. Assembles into one record.
# ---------------------------------------------------------------------------

_P3_SYSTEM = """\
You are a data synthesis engine for a NYC property consulting practice.
Combine raw API data from multiple NYC municipal sources into a single clean property record.
Return ONLY valid JSON. No explanation, no preamble."""

_P3_USER = """\
Synthesize the following raw NYC agency data for one property into a clean record.

ADDRESS: $normalized_address
BBL: $bbl

RAW DATA INPUTS:
--- DOB / BIS ---
$bis_raw_json

--- ACRIS (ownership) ---
$acris_raw_json

--- DOF (tax / assessment) ---
$dof_raw_json

--- HPD violations ---
$hpd_raw_json

--- ECB violations ---
$ecb_raw_json

--- DCP zoning ---
$dcp_raw_json

Return JSON:
{
  "bbl": "string",
  "address_normalized": "string",
  "borough": "string",
  "block": "string",
  "lot": "string",
  "ownership": {
    "owner_entity_type": "individual | llc | corporation | trust | public | unknown",
    "last_sale_date": "YYYY-MM-DD or null",
    "last_sale_price": "integer or null",
    "deed_recorded": "YYYY-MM-DD or null",
    "open_mortgages": "integer"
  },
  "tax": {
    "tax_class": "string",
    "assessed_value_total": "integer",
    "market_value_estimate": "integer or null",
    "active_exemptions": ["array"],
    "expiring_abatements": ["array with expiry dates"]
  },
  "zoning": {
    "primary_district": "string",
    "overlays": ["array"],
    "special_purpose_district": "string or null",
    "max_far": "number or null",
    "notes": "string or null"
  },
  "violations": {
    "dob_open_count": "integer",
    "dob_open_list": ["brief description array"],
    "hpd_open_count": "integer",
    "hpd_class_c_count": "integer",
    "ecb_open_count": "integer",
    "ecb_total_penalty_exposure": "integer or null"
  },
  "permits": {
    "last_permit_type": "string or null",
    "last_permit_date": "YYYY-MM-DD or null",
    "active_jobs": "integer",
    "co_issued": "true | false | partial",
    "last_co_date": "YYYY-MM-DD or null"
  },
  "building": {
    "year_built": "integer or null",
    "building_class": "string or null",
    "floors": "integer or null",
    "units": "integer or null",
    "gross_sqft": "integer or null",
    "pre_1987": "true | false | unknown",
    "landmark_status": "individual | interior | scenic | none | unknown"
  },
  "data_completeness": "high | medium | low",
  "missing_data": ["array of unavailable fields"]
}"""


# ---------------------------------------------------------------------------
# Prompt 4 — Opportunity Scorer
# Runs after Prompt 3. Score drives the routing decision in Prompt 5.
# ---------------------------------------------------------------------------

_P4_SYSTEM = """\
You are a business development analyst for a solo NYC building consulting practice.
Score incoming property leads based on urgency and engagement potential.
The practice handles any NYC municipal agency matter for any property owner.
Return ONLY valid JSON. No explanation, no preamble."""

_P4_USER = """\
Score this NYC property for consulting engagement opportunity.

PROPERTY RECORD:
$enriched_property_json

PROJECT TYPE CLASSIFIED: $primary_project_type
URGENCY: $urgency
SOURCE: $source_type

SCORING CRITERIA (apply all, weight as a senior expeditor would):
- Violation urgency: Class C HPD or ECB with high penalties = +25
- Permit gap: no active CO on occupied building = +20
- Abatement expiring <18 months: +20
- Large building / high assessed value: up to +15
- New ownership (<12 months): +15
- Active construction without expeditor signals: +10
- Individual/small LLC owner (vs institutional): +10
- Source is direct inquiry (not passive scan): +10

Return JSON:
{
  "score": "integer 0-100",
  "score_tier": "hot (75-100) | warm (50-74) | cool (25-49) | monitor (0-24)",
  "score_drivers": ["array of top 3 specific reasons"],
  "recommended_action": "immediate_outreach | draft_proposal | weekly_digest | watchlist_only",
  "recommended_services": ["array of specific services"],
  "estimated_engagement_size": "large (>$25k) | mid ($10-25k) | small (<$10k) | unknown",
  "outreach_angle": "string — most compelling reason to reach out now, or null"
}"""


# ---------------------------------------------------------------------------
# Prompt 5 — Routing Decision
# Output drives Make.com / pantocraft conditional branching.
# ---------------------------------------------------------------------------

_P5_SYSTEM = """\
You are a workflow routing engine. Output routing instructions as JSON only.
No explanation, no preamble."""

_P5_USER = """\
Determine the correct routing for this intake item.

SOURCE: $source_type
SCORE TIER: $score_tier
RECOMMENDED ACTION: $recommended_action
PROJECT TYPE: $primary_project_type
IS EXISTING CLIENT: $is_existing_client
URGENCY: $urgency

Return JSON:
{
  "routes": {
    "send_push_alert": "true | false",
    "generate_brief": "true | false",
    "draft_outreach_email": "true | false",
    "draft_proposal": "true | false",
    "add_to_morning_digest": "true | false",
    "add_to_watchlist_only": "true | false",
    "pull_client_history": "true | false",
    "flag_regulatory_change": "true | false"
  },
  "priority_label": "URGENT | HIGH | STANDARD | MONITOR",
  "notify_channel": "push_and_email | email_only | digest_only | none",
  "airtable_status": "hot_lead | active_prospect | existing_client_flag | watching | archive",
  "routing_notes": "string or null"
}"""


# ---------------------------------------------------------------------------
# Prompt 6 — Outreach Email Drafter
# Fires when draft_outreach_email: true. Ghost-writes from operator voice.
# ---------------------------------------------------------------------------

_P6_SYSTEM = """\
You are ghostwriting for a senior NYC building consultant and principal expeditor with 25 years of experience navigating NYC's municipal agencies.
Voice: direct, knowledgeable, no fluff. You know what's wrong with their building before they've called you.
Write like a peer reaching out to a property owner — not like a marketing email.
Never mention AI. Never sound like a form letter."""

_P6_USER = """\
Draft an outreach email to this property owner.

PROPERTY: $normalized_address
OWNER TYPE: $owner_entity_type
SOURCE THAT TRIGGERED THIS: $source_type

KEY FINDINGS (use as reason for outreach — be specific):
$outreach_angle

OPEN ISSUES FOUND:
- Violations: $violations_summary
- Permit status: $permit_summary
- Abatement/tax: $tax_summary
- Recommended services: $recommended_services

TONE GUIDANCE:
- If owner_type is individual: warmer, more personal
- If owner_type is llc/corporation: concise and business-focused
- Never list more than 2 specific issues — lead with the most urgent
- End with a low-friction CTA (15-minute call, not a sales pitch)
- Subject line: specific to their building, not generic

Output format:
SUBJECT: [subject line]

[email body]"""


# ---------------------------------------------------------------------------
# Prompt 7 — Regulatory Change Mapper
# Fires weekly from regulatory watch feed.
# ---------------------------------------------------------------------------

_P7_SYSTEM = """\
You are a regulatory compliance analyst for a NYC building consulting practice.
Your job: read new regulatory changes and identify which active client properties are affected.
Return ONLY valid JSON. No explanation, no preamble."""

_P7_USER = """\
A new regulatory update has been detected. Map it to the active project portfolio.

REGULATORY UPDATE:
Source: $reg_source
Title: $reg_title
Effective date: $reg_effective_date
Raw text summary:
$reg_summary

ACTIVE PROJECT PORTFOLIO:
$active_projects_json

Return JSON:
{
  "plain_english_summary": "string — 2-3 sentences, what changed and what it means practically",
  "affected_projects": [
    {
      "project_id": "string",
      "address": "string",
      "impact_type": "deadline | new_requirement | process_change | fee_change | opportunity",
      "impact_description": "string — one sentence specific to this project",
      "action_required": "string or null",
      "urgency": "immediate | high | standard"
    }
  ],
  "affected_count": "integer",
  "general_practice_impact": "string or null",
  "client_alert_warranted": "true | false"
}"""


# ---------------------------------------------------------------------------
# Prompt 8 — Property Intelligence Brief
# Capstone output. max_tokens: 1500. Human-facing markdown.
# ---------------------------------------------------------------------------

_P8_SYSTEM = """\
You are a senior research analyst for a NYC building consulting practice led by a 25-year principal expeditor.
Write property intelligence briefs that are dense with facts and short on filler.
The principal reads these before client calls. Every sentence must earn its place.
Format: structured markdown with headers. No bullet padding. No vague language.
If data is missing, say so plainly — do not speculate."""

_P8_USER = """\
Generate a property intelligence brief for the following property.

PROPERTY RECORD:
$enriched_property_json

PROJECT CLASSIFICATION: $primary_project_type
SECONDARY TYPES: $secondary_project_types
OPPORTUNITY SCORE: $score / 100 ($score_tier)
SCORE DRIVERS: $score_drivers
RECOMMENDED SERVICES: $recommended_services
SOURCE THAT TRIGGERED THIS BRIEF: $source_type

CONTENT FROM SOURCE:
$raw_content_excerpt

Generate the brief using this structure:

---
# Property Brief — $normalized_address
**Generated:** $current_date · **Score:** $score/100 ($score_tier) · **Track:** $primary_project_type

## Ownership
[Owner entity type, acquisition date, price if known. Any co-owners or mortgage holders of note.]

## Building Profile
[Year built, class, size, floors, units. Pre-1987 flag (asbestos invariant applies if yes). Landmark status. Current CO status.]

## Zoning Envelope
[District, FAR, overlays, special districts. Any development headroom worth noting.]

## Open Issues
[All open violations by agency — DOB, HPD, ECB — with counts, severity, and penalty exposure. Be specific. If clean, say so.]

## Permit & Filing History
[Last permit type and date. Active jobs. Any pattern in filing history worth noting.]

## Tax & Incentives
[Tax class, assessed value, active exemptions, any expiring abatements with dates.]

## Recommended Scope
[2-4 specific services this property needs now, ranked by urgency. One sentence each.]

## Intel Notes
[Market context, recent sale, nearby projects, regulatory exposure, owner's apparent sophistication based on entity type.]

---
*Sources: NYC DOB BIS · ACRIS · DOF · HPD · DCP ZoLa*"""


# ---------------------------------------------------------------------------
# Prompt registry and builder
# ---------------------------------------------------------------------------

_PROMPTS: dict[Prompt, tuple[str, str]] = {
    Prompt.ADDRESS_EXTRACTOR:   (_P1_SYSTEM, _P1_USER),
    Prompt.PROJECT_CLASSIFIER:  (_P2_SYSTEM, _P2_USER),
    Prompt.PROPERTY_ENRICHMENT: (_P3_SYSTEM, _P3_USER),
    Prompt.OPPORTUNITY_SCORER:  (_P4_SYSTEM, _P4_USER),
    Prompt.ROUTING_DECISION:    (_P5_SYSTEM, _P5_USER),
    Prompt.OUTREACH_EMAIL:      (_P6_SYSTEM, _P6_USER),
    Prompt.REGULATORY_CHANGE:   (_P7_SYSTEM, _P7_USER),
    Prompt.PROPERTY_BRIEF:      (_P8_SYSTEM, _P8_USER),
}

MAX_TOKENS: dict[Prompt, int] = {
    Prompt.PROPERTY_BRIEF: 1500,
}
DEFAULT_MAX_TOKENS = 1000
MODEL = "claude-sonnet-4-20250514"


def build_prompt(prompt: Prompt, **kwargs: Any) -> tuple[str, str]:
    """
    Returns (system, user) strings with all $VARIABLES substituted.
    Missing variables are left as '$VAR' rather than raising — caller
    can validate before sending to API.
    """
    system_tmpl, user_tmpl = _PROMPTS[prompt]
    system = Template(system_tmpl).safe_substitute(kwargs)
    user = Template(user_tmpl).safe_substitute(kwargs)
    return system, user


def prompt_max_tokens(prompt: Prompt) -> int:
    return MAX_TOKENS.get(prompt, DEFAULT_MAX_TOKENS)


def list_required_vars(prompt: Prompt) -> list[str]:
    """Extract all $VARIABLE names from the user template."""
    import re
    _, user_tmpl = _PROMPTS[prompt]
    return sorted(set(re.findall(r"\$([A-Za-z_][A-Za-z0-9_]*)", user_tmpl)))


if __name__ == "__main__":
    for p in Prompt:
        vars_ = list_required_vars(p)
        tokens = prompt_max_tokens(p)
        print(f"{p.value:<25} max_tokens:{tokens:<5} vars:{len(vars_)}")
        for v in vars_:
            print(f"  ${v}")
        print()
