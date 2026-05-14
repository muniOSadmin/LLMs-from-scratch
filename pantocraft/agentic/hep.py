# pantocraft // — Human Escalation Protocol (HEP)
#
# Every tier-2 and tier-3 escalation emits a versioned HEP payload.
# This is not a fallback — it is the product surface.
#
# NY S7263 / information_not_advice framing: a licensed professional (PE, RA,
# or attorney) must review and approve any tier-3 action before filing.
# The HEP payload is the handoff artifact.
#
# Blueprint reference:
#   "A system that emits a structured reviewable action card for 40% is vastly
#    more valuable than one that files 90% but cannot explain what it did."

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

class FilingMode(Enum):
    """
    Blueprint Layer 4 / Step 4 — voyage confidence classification.

    These are navigation states, not permission levels. The voyage always
    proceeds — the mode determines who is on deck and what instruments
    are active. Nothing is ever fully determined before departure.

    MODE_A: charted waters — voyage confidence ≥ 0.80
            Standard crew. Operator reviews before any submission.
    MODE_B: variable conditions — 0.40 ≤ confidence < 0.80
            Specialist navigator required. Operator and licensed professional together.
    MODE_C: uncharted — confidence < 0.40
            All hands. Operator takes the helm directly. HEP payload is the
            instrument reading; the operator decides the course from here.
            This is not a stop — it is the highest-attention state.
    """
    MODE_A = "A"
    MODE_B = "B"
    MODE_C = "C"


def classify_filing_mode(confidence: float) -> FilingMode:
    if confidence >= 0.80:
        return FilingMode.MODE_A
    elif confidence >= 0.40:
        return FilingMode.MODE_B
    else:
        return FilingMode.MODE_C


class HEPTier(Enum):
    TIER_1 = 1   # 0.60–0.80 confidence, moderate risk → team, 4h SLA
    TIER_2 = 2   # <0.60 or high blast radius → lead, 1h SLA
    TIER_3 = 3   # compliance/legal/landmark/BSA → counsel, 15min SLA + page


class HEPTriggerType(Enum):
    POLICY          = "policy"           # hard-stop list match
    CONFIDENCE      = "confidence"       # below threshold
    BEHAVIORAL      = "behavioral"       # loop repetition, scope creep
    ERROR           = "error"            # auth/validation/policy error
    EXTERNAL        = "external"         # captcha, MFA, ToS change
    LANDMARK        = "landmark"         # any action on landmarked property
    IRREVERSIBLE    = "irreversible"     # ACRIS recording, BSA variance, LPC CoA


# Hard-stop list — any proposed action matching these always → TIER_3
HARD_STOP_ACTIONS = frozenset({
    "acris_record_deed",
    "acris_record_mortgage",
    "bsa_file_variance",
    "bsa_file_special_permit",
    "lpc_file_coa",                  # Certificate of Appropriateness
    "lpc_file_cne",                  # Certificate of No Effect
    "dob_submit_filing",
    "dob_submit_permit",
    "hpd_submit_registration",
})

# Tier-3 always — regardless of confidence
ALWAYS_TIER_3 = frozenset({
    HEPTriggerType.POLICY,
    HEPTriggerType.LANDMARK,
    HEPTriggerType.IRREVERSIBLE,
})


# ---------------------------------------------------------------------------
# HEP payload (hep/v1 schema)
# ---------------------------------------------------------------------------

@dataclass
class HEPPayload:
    """
    Versioned HEP payload. Every tier-2 and tier-3 escalation emits one.
    Serialize with .to_json() for the reviewer UI and audit log.
    """
    # Identity
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    schema_version: str = "hep/v1"
    created_at: float = field(default_factory=time.time)

    # Escalation metadata
    tier: int = 2                           # 1 | 2 | 3
    trigger_type: str = "confidence"        # HEPTriggerType.value
    trigger_detail: str = ""               # human-readable why

    # Subject
    bbl: Optional[str] = None              # primary subject property
    address: Optional[str] = None
    engagement_id: Optional[str] = None   # ties to session_log SHA-256

    # Proposed action (what the agent wants to do)
    proposed_action: str = ""
    proposed_action_reversible: bool = True
    affects_landmark: bool = False

    # Context
    pathway_type: Optional[str] = None
    agency_steps: list[str] = field(default_factory=list)  # ["DOB", "LPC", ...]
    confidence: float = 0.0
    filing_mode: str = ""           # A | B | C (Blueprint Layer 4)
    conditions: list[str] = field(default_factory=list)    # trigger conditions

    # Options presented to reviewer
    options: list[str] = field(default_factory=list)
    default_on_timeout: str = "reject"     # always "reject" for tier 3

    # Audit
    agent_version: str = "moswalk-kernel/0.1"
    information_not_advice: bool = True    # always True — NY S7263
    licensed_professional_required: bool = True

    # SLA (seconds)
    sla_seconds: int = field(init=False)

    def __post_init__(self):
        self.sla_seconds = {1: 14400, 2: 3600, 3: 900}[self.tier]

    @property
    def sla_label(self) -> str:
        return {1: "4 hours", 2: "1 hour", 3: "15 minutes (page counsel)"}[self.tier]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["sla_label"] = self.sla_label
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def summary(self) -> str:
        mode_str = f"Mode:{self.filing_mode}" if self.filing_mode else ""
        return (
            f"HEP TIER-{self.tier} {mode_str} | {self.trigger_type} | {self.trigger_detail}\n"
            f"  BBL: {self.bbl or '—'}  |  Action: {self.proposed_action}\n"
            f"  Landmark: {self.affects_landmark}  |  Reversible: {self.proposed_action_reversible}\n"
            f"  Confidence: {self.confidence:.0%}  |  SLA: {self.sla_label}\n"
            f"  information_not_advice: {self.information_not_advice}"
        )


# ---------------------------------------------------------------------------
# HEP factory — builds the correct tier for a given situation
# ---------------------------------------------------------------------------

def build_hep(
    *,
    proposed_action: str,
    confidence: float,
    bbl: Optional[str] = None,
    address: Optional[str] = None,
    engagement_id: Optional[str] = None,
    pathway_type: Optional[str] = None,
    agency_steps: Optional[list[str]] = None,
    conditions: Optional[list[str]] = None,
    affects_landmark: bool = False,
    trigger_type: Optional[HEPTriggerType] = None,
    trigger_detail: str = "",
) -> HEPPayload:
    """
    Build the correct-tier HEP payload for a proposed agent action.
    Tier is assigned deterministically — never inferred from LLM output.
    """
    conditions = conditions or []
    agency_steps = agency_steps or []

    # Determine trigger type if not provided
    if trigger_type is None:
        if proposed_action in HARD_STOP_ACTIONS:
            trigger_type = HEPTriggerType.POLICY
        elif affects_landmark or any("landmark" in c.lower() for c in conditions):
            trigger_type = HEPTriggerType.LANDMARK
        else:
            trigger_type = HEPTriggerType.CONFIDENCE

    # Assign tier deterministically
    if trigger_type in ALWAYS_TIER_3:
        tier = 3
    elif confidence < 0.60:
        tier = 2
    elif confidence < 0.80:
        tier = 1
    else:
        tier = 1  # default minimum for any escalation

    # Irreversible actions are always at least tier 2
    irreversible = proposed_action in HARD_STOP_ACTIONS or not _is_reversible(proposed_action)
    if irreversible and tier < 2:
        tier = 2

    if trigger_detail == "" and trigger_type:
        trigger_detail = _default_detail(trigger_type, proposed_action, confidence, conditions)

    filing_mode = classify_filing_mode(confidence).value

    return HEPPayload(
        tier=tier,
        trigger_type=trigger_type.value,
        trigger_detail=trigger_detail,
        bbl=bbl,
        address=address,
        engagement_id=engagement_id,
        proposed_action=proposed_action,
        proposed_action_reversible=not irreversible,
        affects_landmark=affects_landmark,
        pathway_type=pathway_type,
        agency_steps=agency_steps,
        confidence=confidence,
        filing_mode=filing_mode,
        conditions=conditions,
        options=_default_options(tier, proposed_action),
        default_on_timeout="reject" if tier >= 2 else "defer",
        licensed_professional_required=tier >= 2 or affects_landmark,
    )


def _is_reversible(action: str) -> bool:
    return action not in HARD_STOP_ACTIONS


def _default_detail(
    trigger_type: HEPTriggerType,
    action: str,
    confidence: float,
    conditions: list[str],
) -> str:
    if trigger_type == HEPTriggerType.POLICY:
        return f"Action '{action}' is on the hard-stop list and requires human approval."
    if trigger_type == HEPTriggerType.LANDMARK:
        return f"Property is landmarked or within a historic district. LPC Certificate of Appropriateness required before any filing."
    if trigger_type == HEPTriggerType.CONFIDENCE:
        conds = ', '.join(conditions) if conditions else 'none logged'
        return f"Voyage confidence {confidence:.0%} — conditions flagged: {conds}. Operator navigates from here with full context."
    if trigger_type == HEPTriggerType.ERROR:
        return f"Action '{action}' encountered an auth/validation/policy error. Zero retries per policy."
    return f"Escalation triggered for '{action}'."


def _default_options(tier: int, action: str) -> list[str]:
    base = ["approve", "reject", "defer"]
    if tier == 3:
        base = ["approve (counsel sign-off required)", "reject", "request_more_info"]
    return base


# ---------------------------------------------------------------------------
# HEP write — appends to engagement's escalation log (separate from session_log)
# ---------------------------------------------------------------------------

_HEP_DIR = Path(__file__).parent / "escalations"


def write_hep(payload: HEPPayload) -> Path:
    """
    Persist HEP payload to pantocraft/agentic/escalations/<trace_id>.json
    File mode 600 — contains BBL, address, proposed action.
    """
    _HEP_DIR.mkdir(exist_ok=True)
    path = _HEP_DIR / f"{payload.trace_id}.json"
    path.write_text(payload.to_json())
    path.chmod(0o600)
    return path


# ---------------------------------------------------------------------------
# FieldAPI integration helper
# ---------------------------------------------------------------------------

def hep_from_pathway_result(
    result,   # PathwayResult from agency_navigator
    bbl: Optional[str] = None,
    address: Optional[str] = None,
    engagement_id: Optional[str] = None,
    proposed_action: str = "consult_output_delivery",
    conditions: Optional[list[str]] = None,  # trigger conditions (from trigger_scanner)
) -> Optional[HEPPayload]:
    """
    Given a PathwayResult, determine if HEP is required.
    Returns a HEPPayload if escalation is needed, None if safe to proceed.
    Pass conditions explicitly — PathwayResult does not carry them.
    """
    conditions = conditions or []
    affects_landmark = any("landmark" in c.lower() for c in conditions)
    # Fall back to checking step notes if no conditions supplied
    if not affects_landmark:
        affects_landmark = any(
            "landmark" in (getattr(s, "notes", "") or "").lower()
            for s in getattr(result, "steps", [])
        )
    confidence = getattr(result, "confidence", 1.0)
    has_blockers = getattr(result, "has_hard_blockers", False)

    filing_mode = classify_filing_mode(confidence)

    # Mode C — voyage confidence < 0.40: uncharted conditions, all hands on deck
    if filing_mode == FilingMode.MODE_C:
        return build_hep(
            proposed_action=proposed_action,
            confidence=confidence,
            bbl=bbl,
            address=address,
            engagement_id=engagement_id,
            pathway_type=getattr(result, "pathway_type", None),
            agency_steps=[s.code for s in getattr(result, "steps", [])],
            conditions=conditions,
            affects_landmark=affects_landmark,
            trigger_type=HEPTriggerType.CONFIDENCE,
            trigger_detail=f"Mode C: voyage confidence {confidence:.0%} — uncharted conditions. Operator takes the helm. HEP payload is the instrument reading; course is yours to set.",
        )

    # No escalation needed for clean Mode A, non-landmark pathways
    if filing_mode == FilingMode.MODE_A and not affects_landmark and not has_blockers:
        return None

    result_conditions = [str(c) for c in conditions]
    agency_codes = [s.code for s in getattr(result, "steps", [])]

    trigger = HEPTriggerType.LANDMARK if affects_landmark else HEPTriggerType.CONFIDENCE

    return build_hep(
        proposed_action=proposed_action,
        confidence=confidence,
        bbl=bbl,
        address=address,
        engagement_id=engagement_id,
        pathway_type=getattr(result, "pathway_type", None),
        agency_steps=agency_codes,
        conditions=conditions,
        affects_landmark=affects_landmark,
        trigger_type=trigger,
    )


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== HEP smoke test ===\n")

    # Landmark property — should be tier 3
    hep = build_hep(
        proposed_action="consult_output_delivery",
        confidence=0.95,
        bbl="3-07489-0001",
        address="123 Landmark St Brooklyn",
        affects_landmark=True,
        conditions=["Landmark building or within historic district"],
        pathway_type="alteration_type_1",
        agency_steps=["LPC", "DOB", "FDNY"],
    )
    print(hep.summary())
    print(f"\nTier: {hep.tier}  (expected 3)")
    assert hep.tier == 3

    # Low confidence, no landmark — should be tier 2
    hep2 = build_hep(
        proposed_action="pathway_recommendation",
        confidence=0.55,
        pathway_type="alteration_type_2",
    )
    print(f"\nTier: {hep2.tier}  (expected 2)")
    assert hep2.tier == 2

    # Hard stop action — should be tier 3
    hep3 = build_hep(
        proposed_action="lpc_file_coa",
        confidence=0.99,
    )
    print(f"Tier: {hep3.tier}  (expected 3, hard-stop)")
    assert hep3.tier == 3

    print("\nAll assertions passed.")
    print("\nSample JSON payload:")
    print(hep.to_json())
