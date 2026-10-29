# Model / rule card — `baseline-rules-v0.1-demo`

| | |
|---|---|
| Type | Deterministic, hazard-specific scoring rules (no machine learning) |
| Hazards | Rainfall-triggered landslide; flash flood |
| Code | `backend/app/services/risk_engine/` (`features.py`, `rules.py`, `engine.py`, `config.py`, `playbook.py`) |
| Threshold status | **EXPERIMENTAL_DEMO_SETTINGS_NOT_CALIBRATED** |
| Evaluation status | **Not evaluated.** No labelled, time-aligned event dataset is available for the pilot area. |
| Verification | Threshold boundaries, safety invariants and 3,000 randomised cases tested — see docs/TEST_RESULTS.md. This is software verification, not validation of predictive skill. |
| Playbook | `demo-playbook-v0.1` — illustrative review steps, **not** an authority-approved SOP |

## Intended use
Demonstrating an explainable, human-reviewed decision-support workflow on simulated data. Producing *candidate* items for trained reviewers.

## Out of scope
Public warnings, evacuation or road-closure decisions, any life-safety decision, any claim of predictive skill or lead time.

## Inputs and features
| Feature | Built from | Notes |
|---|---|---|
| `rain_1h_mm`, `rain_3h_mm`, `rain_24h_mm` | Sum of rain-gauge samples in window | Coverage = samples / expected; < 75 % → *incomplete* (lower bound) |
| `soil_moisture_pct` | Latest good reading | Compared as excess over site baseline |
| `displacement_24h_mm` | Latest − reading nearest 24 h earlier (extensometer) | Not computed if no reading near the earlier time |
| `river_level_m` | Latest good stage | Compared with site warning / danger stage |
| `river_rise_1h_m` | Latest − reading nearest 1 h earlier | |

Readings flagged `bad` or `missing` are excluded. A sensor is *stale* after 3 reporting intervals and *offline* after 6 h; a reading is *delayed* if received > 2 intervals after it was observed.

## Scoring
Each indicator awards watch/high points (landslide: rain 24 h 1/2 ★, rain 1 h 1/2, soil excess 1/2 ★, displacement 2/4; flash flood: river stage 2/4 ★, 1 h rise 1/2, rain 1 h 1/2 ★, rain 3 h 1/2; ★ = critical). Score ≥ 4 → HIGH, ≥ 2 → ELEVATED, else LOW.

## Reliability and missing data
* **Effective criticality (since the 2026-10-28 audit, HDEWS-009):** a missing or stale input counts as critical if it is a
  documented critical input (★), *or* if its sensor is configured at the site and the unavailable data could change the tier.
  This enforces "a sensor outage must not lower apparent risk". Inputs with no sensor configured at a site are not outages
  and keep the documented DEGRADED treatment.
* POOR if any (effectively) critical input is missing or stale; DEGRADED if any input is incomplete, delayed, suspect,
  conflicting between sources, or not configured.
* POOR + available evidence LOW → `INSUFFICIENT_DATA` (never LOW).
* POOR + available evidence ≥ ELEVATED → tier kept.
* `max_possible_tier`: the tier reached if every missing/stale/incomplete indicator were at its high level.
  `tier_is_lower_bound` ("may understate") is true only when `max_possible_tier` is higher than the tier (HDEWS-011).
* Duplicate readings at one timestamp count once, preferring OBSERVED > IMPORTED > DERIVED > SIMULATED (HDEWS-003);
  non-finite values are unusable (HDEWS-010); freshness is judged from the newest *usable* reading (HDEWS-008).
* **One origin per sensor (HDEWS-033):** if a sensor has readings of several origins (e.g. a real gateway and the simulator),
  only the highest-precedence origin is used for every calculation of that sensor. Readings of different origins are
  never summed (rain) or differenced (24 h displacement, 1 h river rise); doing so produced meaningless values such as a
  19 mm "displacement" between a real extensometer and simulated data. The ignored readings are disclosed and
  reliability is at most DEGRADED.

## Alerting criteria
* Candidate **hazard** alert: tier HIGH.
* Candidate **data-gap** alert (never presented as a hazard alert): reliability POOR **and** either adverse conditions
  (observed 1 h rain ≥ the site setting, or available evidence ≥ ELEVATED) **or** the site's configured rain gauge is
  itself missing/stale, so adverse weather cannot be ruled out (HDEWS-036: previously a total blackout raised nothing).
* One open alert per site, hazard and kind; repeated confirmations are linked to it, not duplicated.
* None of these changes alter any threshold or point value.

## Outputs
Tier, reliability, ordinal score (with "not a probability" note), per-factor value/threshold/level/status/as-of/evidence ids, missing inputs, reliability notes, changes vs previous assessment, review steps, rule version, data origin (SIMULATED / OBSERVED / MIXED).

## Known limitations and failure modes
* Thresholds are invented for demonstration; real rainfall–landslide thresholds vary strongly by geology, slope and antecedent conditions.
* No terrain, geology, land-cover or forecast inputs yet.
* Point sensors represent only their location; a gauge may miss convective cells (cloudbursts) a few km away.
* Upstream conditions (e.g. glacial-lake outbursts, upstream rainfall) are not represented; a flash flood can arrive with little local rainfall.
* Additive points assume independent indicators; interactions are not modelled.
* Simulated data cannot reveal false-alarm or missed-event rates.

## Path to an ML model
`MLModelInterface.register()` refuses any model whose `validated` flag is false. Use `ml/evaluate.py` with an expert-labelled dataset, temporal and geographic hold-outs, and compare against this baseline before registering anything.
