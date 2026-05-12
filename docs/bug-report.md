# Bug Report: Lakewood Memorial Integration

**Date:** 2026-05-11
**Reported by:** Sarah RN, Dr. Chen, James Lab Tech

| # | Report | Root cause | File |
|---|--------|------------|------|
| 1 | Martinez's penicillin allergy not shown | Allergies with `null` criticality dropped by serializer | `labs/serializers.py` |
| 2 | Riverside patients visible in Lakewood list | Patient views not filtered by team slug | `labs/views.py` |
| 3 | Some lab dates show "Invalid Date" | Frontend reading absent FHIR field instead of normalized backend field | `frontend/src/utils/formatDate.ts` |

---

## Bug #1: Missing allergy

`get_allergies()` skipped any allergy where `criticality` is `None` via an explicit `if not criticality: continue` guard. That's a valid clinical state ("not assessed"), not a reason to hide the allergy. Martinez's Penicillin allergy was stored correctly; it just never reached the response.

**Fix:** Removed the guard. Added a null-criticality allergy to the test fixture so this case is now covered.

**Note:** A test fixture comment already said *"Only uses non-None criticality values so the test passes with the buggy serializer"*. This was a known issue worked around in tests rather than fixed.

---

## Bug #2: Cross-team patient leak

Both `PatientListView` and `PatientDetailView` used `queryset = Patient.objects.all()`. The team slug in the URL was never applied to the query, so every team saw every patient across all hospitals.

**Fix:** Replaced static querysets with `get_queryset()` filtering on `team__slug=self.kwargs["slug"]`.

**Note:** This is a data isolation failure, not just a UX issue. It likely violates the trust boundary between partner institutions and should be reviewed for HIPAA implications.

---

## Bug #3: "Invalid Date" on lab results

`formatDate()` read `observation.effectiveDateTime` from the raw FHIR JSON. FHIR allows `effectivePeriod` (a start/end window) as an alternative, and roughly 15% of observations use it with no `effectiveDateTime` key. `new Date(undefined)` renders as "Invalid Date".

The right fix was not a frontend fallback. The backend already normalizes all FHIR date variants into `effective_date` at ingest time.

**Fix:** `formatDate` now takes a plain date string; `PatientDetail` passes `result.effective_date`.

---

## Follow-up items

1. Audit other serializers for similar filters that could silently suppress clinical data.
2. Add team-isolation tests that assert one team cannot access another team's records.
3. Determine scope of Bug #2 exposure and whether a formal incident report is required.
