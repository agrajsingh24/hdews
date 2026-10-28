# Model / rule card — `baseline-rules-v0.1-demo`

| | |
|---|---|
| Type | Deterministic, hazard-specific scoring rules (no machine learning) |
| Hazards | Rainfall-triggered landslide; flash flood |
| Code | `backend/app/services/risk_engine/` (`features.py`, `rules.py`, `engine.py`, `config.py`, `playbook.py`) |
| Threshold status | **EXPERIMENTAL_DEMO_SETTINGS_NOT_CALIBRATED** |
| Evaluation status | **Not evaluated.** No labelled, time-aligned event dataset is available for the pilot area. |
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
* POOR if any critical input is missing or stale; DEGRADED if any input is incomplete, delayed, suspect, or a non-critical input is missing.
* POOR + available evidence LOW → `INSUFFICIENT_DATA` (never LOW).
* POOR + available evidence ≥ ELEVATED → tier kept, `tier_is_lower_bound = true`.
* `max_possible_tier`: the tier reached if every missing/stale/incomplete indicator were at its high level.

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
