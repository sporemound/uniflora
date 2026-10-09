# UFOSINT research sidequests

UFOSINT sidequests are optional, report-scoped public-source investigations in
the Discord Activity. They do not verify a source report, alter game state,
unlock content, award progress, identify witnesses, or authorize field work.

## User flow

1. A quality-gated UFOSINT report appears in Network Cartography.
2. `Investigate as sidequest` opens the report drawer. Discord bulletin buttons
   use an official `discord.com/activities/<application-id>` launch URL with a
   PII-free `custom_id=ufosint:<id>`; the embedded SDK converts that launch
   context into the cartography route.
3. The Worker re-reads the current server-side UFOSINT feed and freezes a
   privacy-reduced report snapshot. The snapshot and template version are
   immutable and SHA-256 pinned.
4. Investigators work a revisioned checklist: provenance, source independence,
   geographic and temporal envelopes, historical weather, aviation,
   astronomy, sensor/media limits, ordinary explanations, synthesis, and
   independent peer review.
5. Findings are immutable exact revisions. Reviews remain attached to the
   exact revision they assessed, and authors cannot review their own revision.
6. A conclusion is allowed only after required tasks are completed, waived, or
   explicitly unavailable with an audit note, and an unblocked current
   conclusion revision has an independent endorsement.

## Dynamical evidence

The browser does not treat Dynamical stores as map tiles. Cartography renders
declared catalog coverage plus public-report markers whose privacy-reduced
location and date overlap each dataset. GFS context is visible by default; the
other datasets can be enabled independently. These markers identify bounded
query opportunities, not weather observations. A signed Python worker performs
the actual report-window queries and publishes provenance-rich derived artifacts.

| Dataset | Role | Coverage | Time coverage | Important limitation |
| --- | --- | --- | --- | --- |
| ASOS/AWOS GeoParquet | Surface observations | Global stations | 1940-present, hourly | Experimental; station-dependent; no added interpolation or quality control; the experimental catalog page does not state a dataset license |
| NOAA GFS analysis | Model analysis | Global, ~20 km | 2021-05-01-present, hourly | Gridded reconstruction, not an observation at the witness location |
| NOAA HRRR analysis | Model analysis | CONUS, 3 km | 2014-10-01-present, hourly | Material missing source files before August 2018 and early variable gaps |
| NOAA MRMS hourly analysis | Radar/multisensor context | CONUS, ~1 km | 2014-11-01-present, hourly | Radar coverage and early-hour availability vary |
| NASA IMERG Late | Satellite precipitation estimate | Global, ~10 km | 1998-present, 30 minutes | Merged estimate; pre-GPM/high-latitude uncertainty is greater |

The report feed supplies an event date rather than an authoritative event time.
Planning therefore uses the full date with a one-day UTC buffer on both sides
and a 50 km envelope around the privacy-quantized city coordinate. Evidence is
context, not a causal determination. Missing values remain explicit.

Signed jobs include the required and already-completed dataset keys. The worker
uploads every available required dataset in a bounded cycle, advances the
optimistic revision after each accepted artifact, and records partial progress.
Retries skip accepted datasets and resume only the pending keys, so one failed
provider cannot erase or duplicate earlier evidence.

## Durable model

Migration `activity/migrations/0004_ufosint_sidequests.sql` adds:

- `ufosint_sidequests`
- `ufosint_sidequest_events`
- `ufosint_sidequest_tasks`
- `ufosint_sidequest_finding_revisions`
- `ufosint_sidequest_reviews`
- `ufosint_sidequest_artifacts`
- `ufosint_sidequest_artifact_provenance`

Database constraints and triggers enforce immutable source snapshots,
append-only events, one-step optimistic revisions, exact finding-review foreign
keys, immutable artifact provenance, bounded enumerations, and one sidequest per
environment/report. API operations add durable operation-ID idempotency.

## HTTP boundaries

Discord Activity session required:

- `GET /api/ufosint-sidequests?reportId=ufosint:<id>`
- `POST /api/ufosint-sidequests`
- `GET /api/ufosint-sidequests/<sidequest-id>`
- `GET /api/ufosint-sidequests/<sidequest-id>/events`
- `POST /api/ufosint-sidequests/<sidequest-id>/actions`
- `GET /api/ufosint-sidequests/<sidequest-id>/artifacts/<artifact-id>/content`

Replay-resistant Hypha HMAC required:

- `GET /api/hypha/ufosint-sidequests/jobs?limit=<1-25>`
- `POST /api/hypha/ufosint-sidequests/<sidequest-id>/artifacts`

The signed artifact endpoint accepts only `dynamical_analysis` envelopes. It
records a fixed worker identity and requires report-snapshot hash provenance.
Ordinary Activity sessions cannot self-assert weather or Dynamical artifacts.
Every artifact attachment carries bounded base64 content. The Worker decodes
and stores those exact bytes, computes SHA-256 and byte length server-side, and
serves them only through the authenticated content route; caller-supplied
metadata cannot attest to missing or different bytes. Before offering a saved
file, the Activity rechecks its immutable byte length and SHA-256 digest.

Any authenticated participant in the configured Activity channel can
collaborate on any test sidequest, including task and lifecycle changes. That
channel is the current authorization boundary; there are no per-sidequest
owner or role permissions.

## Runtime and deployment

The Python modules are deliberately fail-closed:

- `uniflora.dynamical_context` plans eligible/unavailable datasets and builds
  deterministic artifacts through injected provider handlers.
- `uniflora.ufosint_sidequest_sync` verifies job snapshots and hashes, signs
  requests using the existing Hypha protocol, converts weather artifacts to the
  Activity reproducibility contract, and processes one bounded work cycle.

Provider handlers and network access must be explicitly configured by the
runtime. An absent dependency or failed query produces no partial evidence.
The repository supplies the bounded planner, provenance projection, signed
transport, and resumable worker; it does not silently install Icechunk/Xarray
or make provider network requests during the bot process.

Before deploying the Worker, apply the D1 migration and then deploy the same
build so routes never run against the old schema:

```text
cd activity
npm run validate:ufosint-sidequests
npm run build
npm run db:migrate:remote
npm run deploy
```

The migration and deployment are intentionally separate operator actions; the
implementation does not apply remote migrations or publish automatically.

## Validation

```text
cd activity
npm run validate:ufosint-sidequests
npm run build

cd ..
pytest tests/test_dynamical_context.py tests/test_ufosint_sidequest_sync.py
pytest tests/test_ufo_sidequests.py tests/test_ufo_discord_reports.py
ruff check src/uniflora/dynamical_context.py src/uniflora/ufosint_sidequest_sync.py
```
