# Riverside Community: CSV Ingestion Design

## What the data looks like

45 rows across 5 patients (RC-001 to RC-005). Columns:
`patient_name, mrn, date_of_birth, test_name, test_code, value, unit, collection_date, accession_number`

## Data quality issues found

| Issue | Example | Decision |
|-------|---------|----------|
| Three date formats | `03/01/2026`, `2026-03-10`, `3/9/26` | Parse with ordered fallbacks: `%m/%d/%Y`, `%Y-%m-%d`, `%m/%d/%y` |
| Non-numeric value | `>200` for glucose | Store as-is; `value` is a `CharField` and `>200` is a valid lab notation |
| Unit case variants | `mg/dL`, `mg/dl`, `MG/DL` | Normalize to lowercase on ingest |
| Missing unit | Sodium row RC-2026-044828 | Store empty string; field allows `blank=True` |
| Two names for RC-002 | `Rodriguez, Maria` / `Rodriguez, Maria L.` | Same MRN + DOB, last-seen name wins via `update_or_create` |
| Test name abbreviation | `Glu` vs `Glucose` for LOINC `2339-0` | Use LOINC code as canonical; store the CSV's `test_name` as-is |

## Mapping to the existing model

**Patient** - keyed on `(team, mrn)`, upsert via `update_or_create`. Rows in the CSV are denormalized (one per lab row), so I derive each patient from the first row I encounter for that MRN. `patient_data` stores the raw CSV fields as a dict.

**LabResult** - keyed on `accession_number`, upsert via `update_or_create`. `collection_date` maps to `effective_date` (date only, stored at midnight UTC). `observation_data` stores the raw CSV row as a dict.

**PatientAllergy** - not present in the CSV; nothing to create.

## What I am not doing

- **No DOB cross-validation against existing records.** The seeded Riverside patients (RC-002 through RC-004) don't match the CSV. MRN is the identifier; conflicts should be resolved with the hospital, not silently merged.
- **No unit normalization beyond lowercasing.** `mEq/L` and `mg/dL` are clinically distinct. I normalize case to avoid duplicate display strings but don't attempt any unit conversion.
- **No test name canonicalization.** `Glu` and `Glucose` share a LOINC code and will be stored under their CSV names. Canonical display names should come from a LOINC lookup table, not free-text hospital exports.

## Implementation plan

1. Add a management command `ingest_riverside_csv` that accepts the CSV path.
2. Open the CSV, iterate rows; for each row:
   a. Parse and normalize `collection_date`.
   b. Normalize `unit` to lowercase.
   c. Upsert the `Patient` from `(team, mrn)`.
   d. Upsert the `LabResult` from `accession_number`.
3. Print a summary (rows processed, patients created/updated, errors).
4. Rows that fail (e.g., unparseable date) are logged and skipped; processing continues for the rest.
