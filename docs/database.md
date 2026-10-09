# Database migrations, backup, and restore

## Migrations

The service runs `alembic upgrade head` before opening Discord. Disable that only when a release
workflow runs migrations separately:

```powershell
$env:RUN_MIGRATIONS_ON_STARTUP = "false"
alembic upgrade head
python -m uniflora
```

Create future revisions after changing models with:

```powershell
alembic revision --autogenerate -m "describe the schema change"
alembic upgrade head
pytest
```

Review generated migrations before deployment. Never downgrade production without a verified
backup. The initial migration is frozen and does not import current application models.

## Provision Works content upgrades

The Position 1-6 Provision Works release does not change the relational schema and therefore
does not require a new Alembic revision. Its entities, counters, observations, proposal fields,
samples, containment records, versioned records, and other position state are stored in the
existing JSON state, proposal, and event payloads.

At startup, the service compares the current position's `content_key` and `content_version` with
the packaged definition separately for live and test. A complete position with an older content
version receives an additive, idempotent content upgrade. The upgrader retains existing public
progress, counters, resources, effects, proposals, triggers, records, and history while supplying
new defaults and recording a scoped `content.position_N.initialized` audit event. It does not
copy state between environments. `/interior test copy-live-content` reloads validated packaged
content into test and likewise does not copy live progress.

Treat YAML and content-version changes as application releases even though they need no database
migration:

1. Back up the database and record the running code/content version.
2. Validate the release and complete the arc in the isolated test environment.
3. Pause the affected live session for deployment.
4. Start the matched code and content together, then inspect the scoped state and audit event.
5. Resume only after `/interior validate-content` and readiness checks pass.

For rollback, pause the affected environment first. Use the event-scoped rollback/invalidation
tools when one gameplay event is wrong; they append audit history and rebuild the projection. If
the deployed code and YAML must both be rolled back, restore a matched release and a verified
backup in staging before applying it to production. Do not manufacture an Alembic downgrade for
a JSON content-version change, and do not replace a newer live JSON state with older YAML while
assuming the additive upgrader is reversible.

## SQLite backup and restore

Pause both game sessions before backup. With the service running, use SQLite's online backup
command if the `sqlite3` executable is available:

```powershell
New-Item -ItemType Directory -Force backups
sqlite3 data/interior.db ".backup 'backups/interior.db'"
```

Alternatively stop the service cleanly, verify no `interior.db-wal` file remains, then copy the
database. Keep backups outside an ephemeral container filesystem.

To restore: stop the service, preserve the damaged database separately, copy the selected backup
to `data/interior.db`, start the service, and inspect both environments through `/healthz` before
resuming either session.

## PostgreSQL backup and restore

Use provider snapshots plus a logical backup:

```powershell
pg_dump --format=custom --file=interior.dump $env:DATABASE_URL
pg_restore --clean --if-exists --no-owner --dbname=$env:DATABASE_URL interior.dump
```

Restore into staging first, run `alembic upgrade head`, and inspect live and test exports before
scheduling production restoration. Protect dumps as secrets because they contain Discord IDs
and public game history.

## Automated daily backup

`BACKUP_ENABLED=true` starts the non-blocking backup worker. `BACKUP_DIRECTORY` must point to
persistent storage and `BACKUP_INTERVAL_HOURS` defaults to 24. SQLite uses its online backup API.
PostgreSQL invokes `pg_dump --format=custom --no-owner` with the connection URL supplied through
the child process environment rather than command arguments. Standard output and error are not
logged because they may contain provider details.

Every attempt writes a `backup_records` row. `live-readiness` requires a successful backup no
older than the configured interval; disabling backup prevents a READY result. Back up before each
migration or content release in addition to the scheduled copy. Retention and off-site
replication remain an infrastructure responsibility: use provider snapshots or lifecycle rules
so timestamped files do not grow without bound.
