# Evaluation plan

## 1. Functional (done — automated)
`cd backend && python -m pytest` covers: rule outcomes per scenario, accumulation and coverage, stale/offline/delayed/incomplete data, insufficient-data logic, site thresholds, API auth/RBAC/validation/pagination, alert dedup and state machine, audit immutability and chain verification, ingestion idempotency and range checks, production lock-down of demo endpoints, LLM grounding, ML harness mechanics.

## 2. Model evaluation (pending data)
1. Obtain an authorised event inventory for the pilot area (e.g. state/GSI inventories) with event times and locations; agree label definitions with geoscientists.
2. Assemble time-aligned rainfall (gauge and/or IMERG), soil-moisture, displacement and river-stage data for event and non-event windows.
3. Run `ml/evaluate.py` with temporal and geographic hold-outs; score the baseline rules on the same test set for comparison.
4. Report precision, recall, PR-AUC, false-alarm rate, missed-event rate, lead time; by site and season where sample sizes allow; document class balance and gaps.
5. Only display probabilities after calibration has been performed and evaluated.

## 3. Human usability (pending participants)
With district disaster-management staff and field teams, measure: time to locate the affected site; whether users can explain why an alert was raised; whether they distinguish stale data from low risk; completion of the review workflow; whether suggested steps match local SOPs.

## 4. Field validation (out of prototype scope)
Instrument calibration, communications testing, false-alarm and missed-event review under formal authorisation.
