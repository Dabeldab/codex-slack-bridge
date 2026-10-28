# Firestore durable state — one-time GCP setup

The command-center uses Firestore (native mode) as the durable store so the
kanban board and per-job token/cost history survive Cloud Run scale-to-zero
with **no always-on compute cost**. Firestore bills only what you use and the
workload (dozens to low-hundreds of docs/day) sits far inside the daily free
tier (50K reads / 20K writes / 1 GiB).

## Runtime service account

The Cloud Run service runs as:

    nova-command-center-shadow@gen-lang-client-0051653266.iam.gserviceaccount.com

It uses Application Default Credentials (ADC) at runtime — **no service-account
key file** is needed or stored.

## One-time steps (run once, before the Firestore backend is enabled)

### 1. Enable the Firestore API

    gcloud services enable firestore.googleapis.com \
      --project gen-lang-client-0051653266

### 2. Grant the runtime SA the datastore roles

Firestore native mode grants through the Cloud Datastore roles:

    gcloud projects add-iam-policy-binding gen-lang-client-0051653266 \
      --member="serviceAccount:nova-command-center-shadow@gen-lang-client-0051653266.iam.gserviceaccount.com" \
      --role="roles/datastore.user"

### 3. Set the Firestore database (if this is the first Firestore DB in the project)

If no Firestore database exists yet, create it in the deployment region:

    gcloud firestore databases create --database="(default)" \
      --location=us-central1 \
      --project gen-lang-client-0051653266

(If a default database already exists this returns an ALREADY_EXISTS error,
which is fine.)

## Enabling the backend at deploy time

Set these environment variables on the Cloud Run service (or via the Cloud
Build substitutions in `cloudbuild-cloud-run-chatgpt.yaml`):

    FIRESTORE_ENABLED=1
    FIRESTORE_PROJECT_ID=gen-lang-client-0051653266

The runtime reads them via ADC and the runtime SA's IAM binding. When
`FIRESTORE_ENABLED` is unset/off the store degrades to the existing ephemeral
JSON path and nothing breaks.

## Optional guardrails

    FIRESTORE_MAX_WRITES_PER_REFRESH=1000   # free-tier write-budget cap (default)

## Collections created

  * `tickets/{salesforceTicketId}` — the kanban board, upserted incrementally
    by the deterministic refresh (no full rewrite; staleness from
    `last_seen_at`).
  * `job_usage/{bridgeJobId}` — per-job token/cost history, written alongside
    the local usage record on every job completion.

## Verification

After a deploy with `FIRESTORE_ENABLED=1`:

    gcloud firestore collections list --project gen-lang-client-0051653266

and hit `GET /usage/history` (authenticated) to confirm `"source": "firestore"`
in the response.