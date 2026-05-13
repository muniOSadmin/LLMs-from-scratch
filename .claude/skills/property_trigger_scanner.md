# skill: property_trigger_scanner

Resolve a NYC property (by BBL or address) into the set of agency triggers
that apply to it, using PLUTO data and trigger_scanner.py.

## When to invoke

Use this skill whenever a user provides:
- A BBL (Borough-Block-Lot, e.g. "3-00783-0001" or "3007830001")
- A NYC address with enough information to identify the property
- A SimClient object from iphone-llm/sim/clients/

And wants to know: which agencies will be involved? What are the blockers?

## What this skill does

1. **Resolve BBL** — if address given, use python-geosupport (offline) or NYC
   Geoclient API to get the BBL. If BBL given directly, use as-is.

2. **Load PLUTO data** — read from local PLUTO v25v4 SQLite cache or CSV.
   Key fields: LandMarked, HistDist, FloodZone, YearBuilt, NumFloors,
   LotArea, ZoneDist1, BldgClass, OwnerType.

3. **Run trigger_scanner.scan()** — convert PLUTO row to flags dict via
   from_pluto_row(), then call scan() to produce TriggerResult.

4. **Surface results** — present TriggerResult.blocker_flags() prominently,
   then TriggerResult.educational_flags() as context.

## Output format

```
BBL: {bbl}
Address: {address}
Zoning: {zoning_district} | Built: {year_built} | Stories: {stories}

BLOCKERS (must resolve before filing):
  ⛔ {blocker_1}
  ⛔ {blocker_2}

CONDITIONS TRIGGERED:
  • {condition_1}
  • {condition_2}

EDUCATIONAL FLAGS:
  ℹ {flag_1}
  ℹ {flag_2}

Confidence: PLUTO v25v4 (April 2026 — verify LPC and flood map status annually)
```

## Code path

```python
from moswalk_kernel.property.trigger_scanner import scan, from_pluto_row

# If PLUTO row available:
flags = from_pluto_row(pluto_row)
result = scan(flags)

# Or build flags manually from known property data:
result = scan({
    "landmarked": True,
    "landmark_type": "historic_district",
    "flood_zone": None,
    "year_built": 1895,
    "open_violations": 2,
    "stories": 3,
    "lot_area_sqft": 2000,
    "zoning_district": "R6B",
})

print(result.blocker_flags())
print(result.educational_flags())
```

## Data sources

- **PLUTO v25v4** — nyc.gov/planning → PLUTO & MAPPLUTO (updated monthly)
  Key fields for trigger scanning: LandMarked, HistDist, FloodZone, YearBuilt,
  NumFloors, LotArea, ZoneDist1, BldgClass, OwnerType
- **FEMA FIRM panels** — msc.fema.gov — verify flood zone annually; PLUTO
  FloodZone field lags FEMA updates by up to 6 months
- **LPC designation data** — nyc.gov/lpc → Research → Databases
  Cross-check PLUTO LandMarked field against LPC official list
- **DOB NOW BIS** — dobnowasbuild.nyc.gov — for open violation count
  (PLUTO does not include violation data — must query DOB separately)
- **HPD HPDRP** — rent-stabilized building data; PLUTO OwnerType is a rough proxy

## Privacy

BBL is public record. Do not include client name, contact, or project description
in this lookup. Those belong in pantocraft/clients/ (encrypted).

Per NY SHIELD Act: property public data (BBL, PLUTO) and client PII must be
stored in separate data stores with separate access paths.

## Fallback if PLUTO unavailable

If the local PLUTO cache is not available (first run, offline, or iOS):
- Build flags dict from user-provided information (borough, approximate year built,
  whether the user reports it's landmarked or in a flood zone)
- Set confidence to 0.70 on all conditions (stale flag)
- Surface a warning: "PLUTO data not loaded — trigger scan is based on user
  input only. Verify against nyc.gov/planning before filing."

## Known limitations

1. PLUTO FloodZone lags FEMA updates. Always verify FEMA FIRM for flood-zone projects.
2. PLUTO LandMarked = "Y" for individual landmarks but HistDist is a separate field.
   Check both.
3. Open violations not in PLUTO — must query DOB NOW BIS separately.
4. Rent stabilization status: HPD HPDRP is authoritative; PLUTO OwnerType is a proxy.
5. ADU pilot eligibility (Local Law 18/2024): geography-based, requires HPD confirmation.
