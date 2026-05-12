# Webhook Ingestion: System Design

## Problem

Riverside Community currently sends lab data as a CSV batch export. They want
to move to real-time delivery: FHIR R4 Bundles pushed via HTTP webhook as
results are finalized. Other hospitals will follow the same pattern.

**Constraints:**
- Results must appear in the dashboard within 5 minutes of receipt
- Webhook endpoint must respond within 3 seconds (hospital's HTTP timeout)
- The hospital may retry on timeout (same payload delivered multiple times)
- The system must be observable
- Stack: Django, Celery, Redis, PostgreSQL

---

## Design overview

The core tension is between the 3-second response requirement and the work
required to process a bundle. The solution is to decouple receipt from
processing: the endpoint does the minimum work needed to safely accept the
payload, then hands off to a Celery worker.

```
Hospital
  POST /api/webhooks/<team_slug>/fhir/
        |
        | < 3 seconds
        v
  Django endpoint
    1. Authenticate (HMAC signature)
    2. Store raw payload -> WebhookDelivery row
    3. Enqueue Celery task (delivery_id)
    4. Return 202 Accepted
        |
        | async
        v
  Celery worker
    1. Load delivery from DB
    2. Call process_fhir_bundle() (existing logic)
    3. Mark delivery done / failed
```

With this split, the endpoint is doing three cheap operations (auth check, one
DB write, one Redis enqueue) and will comfortably return in well under 3
seconds. The worker has no response deadline and can take as long as needed.

---

## Idempotency and corrections

**Duplicate deliveries** (hospital retries the same payload): handled
automatically. `process_fhir_bundle()` already uses `update_or_create` keyed
on `accession_number`, so reprocessing the same payload produces the same
final state. No extra deduplication logic is needed for correctness.

**Corrections** (a result is amended after the fact): also handled by
`update_or_create`. The sample payload demonstrates this: `obs-101-corrected`
carries status `corrected` and the same accession number as the original
`obs-101`. When processed, it overwrites the original row with the corrected
value. This is the right behavior: we want the latest version of a result, not
the first.

The distinction matters: a duplicate is the same payload arriving twice; a
correction is a new payload with new data for the same accession. Both are
safe to process idempotently.

---

## Data model changes

Add one new model to track webhook deliveries:

```
WebhookDelivery
  team            FK -> Team
  received_at     DateTimeField (auto)
  payload         JSONField
  status          CharField  (pending, processing, done, failed)
  error           TextField (blank)
  processed_at    DateTimeField (null)
```

Storing the raw payload serves two purposes: it gives ops a record to inspect
when something goes wrong, and it enables replaying a delivery without asking
the hospital to resend.

No changes to the existing `Patient`, `LabResult`, or `PatientAllergy` models.

---

## Endpoint

```
POST /api/webhooks/<team_slug>/fhir/
```

One URL pattern handles all hospitals. `team_slug` identifies which team the
data belongs to, and the same authentication and processing logic applies to
all of them. Adding a new hospital is a matter of configuration, not code.

**Authentication:** each team has a shared secret stored in the database. The
hospital signs each request with HMAC-SHA256 over the raw request body, sent
as an `X-Webhook-Signature` header. The endpoint verifies the signature before
doing anything else. Requests that fail auth return 401 immediately and are not
stored.

**Response codes:**
- `202 Accepted`: payload received and queued
- `400 Bad Request`: payload is not valid JSON or missing required fields
- `401 Unauthorized`: signature invalid or team not found

The endpoint does not return `200 OK` because that would imply the data was
processed, which it has not been yet.

---

## Celery task

```python
@shared_task(bind=True, max_retries=3)
def process_webhook_delivery(self, delivery_id):
    ...
```

The task loads the `WebhookDelivery` row, calls the existing
`process_fhir_bundle()`, and updates the delivery status. On failure it retries
with exponential backoff (delays: 30s, 5m, 30m). After three failures the
delivery is marked `failed` and an alert fires.

Using `delivery_id` rather than embedding the payload in the task message keeps
the Celery queue lightweight and ensures the full payload lives in one
canonical place (the DB row).

---

## Observability

**Structured logging:** the task logs at the start (`delivery_id`, `team`,
`bundle_size`) and on completion (`patients_upserted`, `observations_upserted`,
`errors`, `duration_ms`). Errors include enough context to diagnose without
having to replay.

**Metrics to alert on:**

| Signal | Alert condition |
|--------|----------------|
| `WebhookDelivery.status = failed` | any failure |
| Queue depth (Celery/Redis) | > 100 pending tasks |
| Processing lag | `received_at` to `processed_at` > 5 minutes |
| Error rate | > 5% of deliveries in a 15-minute window |

**Delivery log:** the `WebhookDelivery` table is queryable by ops. For any
patient data question ("why is this result missing?") ops can find the relevant
delivery, inspect the raw payload, and replay it via a management command if
needed.

---

## What I'm not designing here

**Backpressure:** at 5,000 results/day the queue load is trivial. If volume
grows significantly, the worker pool size is the lever to pull with no
architectural changes needed.

**Payload validation beyond auth:** the endpoint accepts any valid JSON and
lets the worker surface parse errors. Strict schema validation at the endpoint
would be more defensive but adds latency on the critical path. Worth revisiting
if bad payloads become a common failure mode.

**Result history:** the existing model stores only the latest value per
accession. If an audit trail becomes a requirement, the model needs a
`LabResultHistory` table. Out of scope here.
