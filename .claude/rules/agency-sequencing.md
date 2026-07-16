# Rule: Agency Sequencing

Never assume agencies are parallel. Always check `sequential_after` in `agency_patterns.yaml`.

- If `blocking: true` and the agency is not resolved → halt all downstream agencies
- If `sequential_after: [LPC, DEP]` → do not launch DOB until both complete
- `confidence < 0.70` → surface stale flag to user, do not proceed silently
- No agency graph without BBL resolution first
- `ECB` violations → resolution path is **OATH**, not ECB itself
- When DOB (Housing DM) conflicts with DOT (Operations DM) → escalation requires two different Deputy Mayors; flag as `escalation_risk: high`
