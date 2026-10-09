# The Missing Interior v2 — Phase 4B persistent collaborative findings

This is a cumulative Phase 4B Activity overlay for branch `v2-rewrite-foundation`.
Because the Phase 4A source archive was not supplied, the included `App.tsx`, scientific workspace,
styles, and Worker entry point replace the collaboration layer completely while preserving the
Phase 3B scientific publication APIs. It modifies only `activity/` and does not touch the Python
engine, Discord production configuration, production databases, or any prohibited legacy path.

Phase 4B adds:

- Durable Object persistence for room findings;
- owner and presenter edit/delete permissions;
- canonical artifact and visualization binding;
- synchronized finding creation, update, deletion, and restoration;
- deterministic room revisions and stale-revision rejection;
- operation-ID replay protection;
- selection bounds, text-length, and protocol validation;
- reconnect snapshots and room isolation;
- a findings editor and saved-findings panel in the scientific workspace.

## Prerequisite

First verify that the latest `test` publication returns:

```text
artifactId            : artifact-phase3-sr03
visualizationFilename : activity-visualization.json
dataFilename          : activity-data.json
```

Phase 4A must already provide the `INVESTIGATION_ROOMS` Durable Object binding and
`ROOM_TICKET_SECRET` local secret. The Durable Object class exported by this overlay is
`InvestigationRoom`.

## Apply

Extract the archive over:

```text
C:\path\to\uniflora
```

All ZIP entries are relative paths.

Register the npm validation command without replacing `package.json`:

```powershell
Set-Location "C:\path\to\uniflora\activity"
node ".\tools\register_phase4b_script.mjs"
```

Then run:

```powershell
npm run validate:phase4
npm run validate:phase4b
npm run check
npm audit
npm audit --omit=dev
```

## Manual acceptance

Open two windows using the same room ID, for example:

```text
http://127.0.0.1:5173/?room=phase4-lab
```

Verify synchronized range/layer behavior, presenter locking, finding creation, restoration,
ownership restrictions, refresh persistence, deletion, and isolation from a different room ID.

## Storage boundary

Findings are stored only in the room Durable Object. They are not written to D1 publication
records, the game database, the local research dashboard database, or artifact manifests.
