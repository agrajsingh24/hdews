# Safety and limitations

## Operating boundary
* HDEWS is a **research prototype and decision-support demonstrator**. It is not a certified or official warning service and has no affiliation with, or endorsement from, any government agency.
* It never sends messages, sirens, SMS, CAP feeds or notifications to anyone. "Test notification" and "escalation" actions are **recorded only**.
* It does not issue evacuation, road-closure, rescue or emergency declarations. Decisions belong to authorised people following the responsible authority's approved SOPs.
* Do not use it as the basis for life-safety decisions.

## Built-in safeguards
| Risk | Safeguard |
|---|---|
| Demo mistaken for reality | Violet "Prototype / simulated" strip on every page; `SIMULATED` tags on every reading, assessment and alert; `[SYNTHETIC]` incident titles; demo notice on every alert |
| Missing data read as "safe" | `INSUFFICIENT_DATA` tier; lower-bound flag with worst-case tier; stale sensors shown struck-through and "not current"; data-gap alerts |
| False precision | Ordinal points labelled "not a probability"; thresholds labelled uncalibrated; evaluation page says "Not evaluated yet" |
| LLM hallucination | LLM only explains; its numbers must all appear in the evidence or the output is discarded; template fallback |
| Unauthorised changes | Role permissions on every mutating endpoint; demo endpoints disabled in production |
| Lost or altered history | Append-only audit table (DB triggers) + SHA-256 hash chain with verification |
| Alert fatigue | Deduplication per site/hazard/kind; condition persistence shown as a count instead of new alerts |
| Unaccountable closure | Resolution requires an outcome category and reason (supports false-alarm / missed-event review) |

## Known limitations
* All telemetry is simulated; coordinates are approximate locality points; the pilot area is a rectangle, not the district boundary; river lines are schematic.
* Thresholds and points are uncalibrated. No ML model is trained or validated.
* Public-report incidents are summaries of media / research sources and have not been cross-checked against an official inventory.
* No satellite, terrain, forecast or upstream-catchment inputs yet.
* Authentication uses demo accounts and bearer tokens in session storage; replace with an identity provider and harden before any real deployment.
* Single-node design; in-memory rate limiting.
* Offline operation, SMS/CAP integration and multi-language templates are not implemented.
