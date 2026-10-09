# The Missing Interior v2 — Phase 4C collaborative finding review and promotion

## Purpose

Phase 4C extends the Phase 4B investigation-room Durable Object with immutable finding
revisions, exact-revision peer review, typed relationships, deterministic promotion checks,
sanitized public conclusions, and explicit provenance. It extends the existing room authority
and version `4.2.0` WebSocket protocol; it does not create a second collaboration service.

Findings and promoted conclusions are advisory research output only. Promotion cannot advance
a game position, change resources or eligibility, resolve player actions, modify Discord roles,
invoke authoritative progression, or mutate the Python game engine.

## Data model

| Record | Purpose |
| --- | --- |
| `RoomFinding` | Current room-facing projection, including scientific selection, layers, creator, current revision, and lifecycle state. |
| `FindingRevision` | Immutable revision content: finding and revision IDs, previous revision, statement, optional interpretation, limitations, evidence and Milestone 6J analysis-artifact references, author, timestamp, reason, lifecycle, and addressed review IDs. |
| `FindingReview` | Stable review ID, exact finding revision, reviewer, `endorse`, `challenge`, or `request_revision` disposition, optional rationale, timestamp, client operation ID, and room/artifact/visualization context. |
| `FindingReviewResolution` | Immutable resolution of one blocking review, with `withdrawn`, `resolved`, or `addressed_by_revision` status, resolver, rationale, timestamp, operation ID, exact reviewed revision, and optional resulting revision. |
| `FindingRelationship` | Stable, exact-revision link between two findings with creator, optional rationale, timestamp, and operation ID. |
| `PublicConclusion` | Immutable, sanitized promotion of one exact revision, including public-safe references, investigation context, provenance summary, publication time, and forward supersession information. |
| `FindingReviewDomainEvent` | Replayable event containing its ID, source operation, event type, room revision, timestamp, private actor/rationale audit metadata, and a cloned state patch. |

Records are kept in null-prototype maps and exposed in deterministic sorted arrays. A snapshot
also includes a promotion assessment for every current finding.

Evidence references identify an observation or Activity artifact and declare
`available`, `incomplete`, or `unavailable`. Analysis references point to an existing
Milestone 6J analysis artifact and may include an analysis job ID and lowercase SHA-256 hash.
Phase 4C validates and displays these references; it does not execute analysis in TypeScript.

## Revision semantics

Creating a finding creates revision 1 in `draft`. Each subsequent `finding:revise` operation:

- must target the exact current revision;
- may be performed by the finding creator or current presenter;
- appends `currentRevision + 1` with a pointer to the prior revision;
- preserves every earlier revision and its reviews;
- records the actor as the new revision author;
- makes the new revision the current `draft`;
- does not inherit reviews, endorsements, review eligibility, or promotion eligibility; and
- may explicitly address selected unresolved `request_revision` reviews.

The compatible Phase 4B `finding:update` operation follows the same append-only rule. It carries
forward limitations and evidence/analysis references, but creates a new draft revision rather
than overwriting the old record. Editing a reviewed, promoted, superseded, or withdrawn finding
therefore creates a new unreviewed current revision while retaining the earlier record and any
already published conclusion.

An `addressedReviewIds` entry must name an unresolved `request_revision` review on the same
finding and on the current or an earlier revision. Each accepted link creates an
`addressed_by_revision` resolution that identifies the resulting revision. Challenges cannot be
implicitly addressed by editing.

## Review dispositions

- `endorse` supports the exact revision. An author may comment or endorse, but an endorsement
  from the revision author does not satisfy independent review.
- `challenge` is a promotion blocker for the exact revision until resolved or withdrawn.
- `request_revision` is a blocker until resolved, withdrawn, or explicitly linked from a newer
  revision.

Reviews may be submitted only for the exact current revision while its lifecycle is
`under_review`, `reviewed`, `challenged`, or `revision_requested`. Historical or nonexistent
targets receive structured stale-revision or nonexistent-record errors. Reviews remain attached
to their original revision permanently.

## Deterministic blocker resolution

The original review is never erased. One immutable resolution record closes a blocker:

- only the blocker reviewer may `withdraw` it;
- the blocker reviewer may `resolve` it;
- the current presenter may `resolve` it only when the presenter is not the reviewed revision's
  author; or
- a newer revision may mark an unresolved `request_revision` as
  `addressed_by_revision` by listing its review ID explicitly.

Resolve and withdraw actions require a rationale. An endorsement never resolves a challenge or
revision request. After a current-revision blocker is closed, lifecycle is recomputed from all
reviews and resolutions. Resolving a historical blocker preserves history and can remove a prior
revision-request promotion block without rewriting the historical revision.

## Lifecycle and transitions

The lifecycle states are `draft`, `under_review`, `revision_requested`, `challenged`,
`reviewed`, `promoted`, `superseded`, and `withdrawn`.

| From | Action | To | Rule |
| --- | --- | --- | --- |
| none | Create or migrate finding | `draft` | Creates immutable revision 1. |
| `draft` | Start review | `under_review` | Must target the exact current revision. |
| In-review state | Submit or resolve reviews | derived state | Unresolved challenge wins over unresolved revision request; otherwise an independent endorsement yields `reviewed`, and no independent endorsement yields `under_review`. |
| `under_review` or `reviewed` | Promote | `promoted` | All promotion checks below must pass for the exact current revision. |
| Any non-withdrawn state | Withdraw | `withdrawn` | Finding creator, current revision author, or presenter only. Phase 4B delete is treated as withdrawal. |
| Any state | Create a new revision | `draft` | Finding creator or presenter only; the prior lifecycle and revision remain in history. |
| Target's current non-withdrawn, non-superseded state | Create a `supersedes` relationship | `superseded` | The predecessor remains stored; the relationship does not delete it. |

Review submission is invalid from `draft`, `promoted`, `superseded`, or `withdrawn`; review must
first be started on a draft. A second withdrawal and all malformed or nonexistent transitions
return deterministic structured errors.

## Finding relationships

Supported relationship types are:

- `supports`
- `related_to`
- `conflicts_with`
- `supersedes`

Both source and target findings and their exact revisions must exist. A finding cannot link to
itself, even across revisions. IDs and relationship types are validated, while a rationale is
optional. `supersedes` must be created from the current, active successor before promotion by its
creator, revision author, or the presenter. This prevents an unrelated participant or a
post-publication relationship from silently changing conclusion metadata. It preserves the target
and all its history. When it targets the predecessor's current revision, that predecessor becomes
`superseded`; when the source is later promoted, its conclusion lists any already promoted
predecessor conclusions in `supersedesConclusionIds`.

## Promotion eligibility

`assessPromotion` evaluates the same seven ordered checks on the server and in snapshots.
Promotion is eligible only when all are satisfied:

1. The requested revision is the exact current revision.
2. Its lifecycle is `under_review` or `reviewed`.
3. The exact revision has at least one endorsement from a participant other than its author.
4. No unresolved challenge applies to the exact revision.
5. No unresolved `request_revision` applies to the exact revision or any earlier revision.
   Earlier requests stop blocking only after withdrawal, explicit resolution, or an
   `addressed_by_revision` link.
6. Every supplied evidence reference is structurally valid.
7. Every supplied Milestone 6J analysis-artifact reference is structurally valid.

Structural validation covers identifiers, coherent observation-versus-Activity-artifact source
linkage, availability, public-safety flag, label, optional job ID, and optional lowercase SHA-256
artifact hash. Activity-artifact evidence must match the room's server-validated artifact and
visualization scope. Milestone 6J references are not fabricated or executed. Empty reference
arrays are valid.

An ineligible request returns `promotion_blocked` with deterministic blocker codes and exact
revision details. Promotion creates at most one conclusion per finding revision. Repeating
promotion with a different operation ID returns the existing review state without creating a
second conclusion or advancing the room revision.

## Public sanitation

A conclusion is built field by field from an allowlist. It contains the conclusion and source
revision IDs, statement, optional interpretation, limitations, public-safe evidence and analysis
references, fixed institution context, artifact/visualization context, publication time,
`promoted` lifecycle, provenance summary, and supersession IDs.

Reference objects are copied into public types only when marked `publicSafe`; private reference
metadata is not copied into either the public reference arrays or provenance references. Reviews
are reduced to stable review IDs and aggregate counts, never identities or rationales.

After allowlist construction, recursive sanitation walks every nested object, array, and string.
Key names are normalized before checking forbidden identity, participant, session, room-ticket,
operation, client-instance, WebSocket, Durable Object, private-note, room-log, HMAC, secret, and
`.dev.vars` fragments. String checks reject Discord-sized snowflakes, credential-labelled
material, bearer-like tokens, `.dev.vars` references, and unlabelled SHA-256-shaped values outside
the explicitly permitted reference/hash paths. User-supplied public text and labels are also
compared against all private room participant IDs, display names, and client operation IDs known
to the Durable Object. Any violation aborts promotion. Public
conclusions therefore do not expose Discord user IDs, private participant or reviewer identities,
session tokens, tickets, client operation IDs, socket attachments, storage metadata, private
notes, logs, or environment secrets.

## Provenance

Every conclusion carries these ordered stages:

```text
observation
→ analysis_job
→ analysis_artifact
→ finding_revision
→ peer_review
→ promoted_conclusion
```

Each stage is explicitly:

- `available` when its supplied links are present and available;
- `incomplete` when links exist but some are partial or unavailable; or
- `unavailable` when no link was supplied.

Observation stages use observation evidence references. Analysis-job availability requires a
job ID for every supplied analysis artifact; analysis-artifact availability follows the supplied
artifact references. The exact finding revision and promoted conclusion are always available.
Peer review is available when the exact revision has reviews. `missingLinks` includes both
incomplete and unavailable stages, and the review summary reports exact-revision disposition and
resolved-blocker counts. Missing observation, job, artifact, or review links are represented
explicitly and are never invented.

## Durable Object persistence, events, and reconnect

The existing `phase4b-room-state` Durable Object key remains the room authority. Schema version 2
persists:

- the canonical room/publication binding and global room revision;
- presenter ownership, selection, and layers;
- findings, immutable revisions, reviews, resolutions, relationships, and public conclusions;
- the ordered finding-review event stream;
- the operation-id ledger; and
- used one-time room tickets.

Before a room ticket is signed, the Worker loads the active visualization and its declared
scientific dataset, derives the canonical waveform bounds and time bases, and rejects any
client-supplied scope that differs. The Durable Object therefore receives server-verified
selection constraints rather than trusting browser metadata.

Schema-v1 state migrates in place. Each Phase 4B finding becomes revision 1 in `draft`, retaining
its title, observation, creator, timestamps, selection, and layers. Migration adds an explicit
public-safe Activity-artifact evidence reference, leaves analysis references empty, and records a
deterministic migration event. Existing room revision, publication binding, controls, ticket
nonces, and legacy operation metadata are retained.

Finding-review mutations append one of `finding_created`, `finding_revised`, `review_started`,
`review_submitted`, `review_blocker_resolved`, `relationship_created`, `finding_promoted`,
`finding_superseded`, or `finding_withdrawn`. Each event stores the accepted patch after the room
revision advances and retains private actor/display-name/rationale audit metadata. Withdrawal
therefore keeps its rationale in the private event log; the compatible Phase 4B delete operation
records an explicit compatibility rationale. Selection, layer, and presenter operations remain
canonical room-state mutations rather than finding-review events.

Persistence completes before broadcast. Phase 4C mutations broadcast a complete, sorted
`room:review-state`; control changes use the existing `room:state` pattern. Schema-v2 loads first
validate unique event and operation IDs plus monotonic event room revisions, then use replay only
when its canonical result matches the materialized state. A partial or corrupt event log therefore
cannot silently discard the materialized records. A reconnect receives a full snapshot containing
all durable history, conclusions, and current assessments. Live
participant presence reflects current hibernating WebSocket attachments, while durable review
state remains identical across reconstruction.

## Idempotency and replay

Every accepted protocol message contains a client `operationId`. The server canonicalizes the
entire request by recursively sorting object keys and stores its SHA-256 fingerprint with the
participant ID, response type, and result room revision. Successful operations are retained up to
the room's explicit 512-operation safety cap; there is no silent eviction that would weaken
idempotency. Rejected operations and rejected no-op presenter claims do not consume durable ledger
capacity and are reevaluated deterministically on retry.

Reusing an operation ID with the same participant and fingerprint returns
`operation:duplicate` without mutating state. Reusing it with a different participant or payload
returns `operation_id_conflict`. Duplicate detection precedes global stale-room-revision
checking. Persisted event patches contain their generated IDs and timestamps, so ordered replay
reconstructs the same finding-review state without generating new values.

## Authority boundary

Phase 4C writes only investigation-room Activity collaboration state and its sanitized advisory
conclusions. It does not call the Milestone 6J Python workflow, modify its artifacts, write
authoritative game state, invoke progression, alter deterministic resources or eligibility, or
perform Discord administration. A conclusion is evidence for human research discussion, never
an authoritative game command.

## Local validation

On Windows PowerShell, use `npm.cmd` to avoid the PowerShell `npm.ps1` execution-policy shim:

```powershell
Set-Location "C:\path\to\uniflora\activity"
npm.cmd run validate:phase4
npm.cmd run validate:phase4b
npm.cmd run validate:phase4c
npm.cmd run check
npm.cmd run build
```

Then run the retained Milestone 6J acceptance test from the repository root:

```powershell
Set-Location "C:\path\to\uniflora"
& ".\.venv\Scripts\python.exe" `
    -m pytest `
    ".\tests\test_investigation_analysis_workflow_v2.py" `
    -q
```

These are local checks. Do not run `deploy`, publish to the live environment, or mutate live data.

## Known limitations

- Evidence and analysis references are structurally validated but are not dereferenced or
  cryptographically reverified by the Durable Object.
- Independent review is defined by private participant ID; Phase 4C does not externally attest
  that two participant identities represent different humans.
- State, events, and the bounded 512-operation ledger currently share one Durable Object value.
  The room deliberately stops accepting mutations at its capacity instead of silently losing
  idempotency history; long-lived or open-public rooms need an explicit rollover/compaction design.
- Edge throttles are defense in depth rather than a global distributed rate limiter. Phase 4C is
  approved only for a non-distributed, exact-user-allowlisted test Activity, not open public writes.
- Protocol `4.2.0` is exact on the wire. Persisted Phase 4B data migrates, but connected older
  protocol clients must reload the updated Activity.
- Public conclusions are room-scoped records; there is no automatic cross-room catalogue or
  authoritative publication workflow.
- Superseding conclusions list predecessor conclusion IDs, but existing predecessor records are
  immutable and their reverse `supersededByConclusionId` remains unset.
- Withdrawal rationale is retained in private event audit history and intentionally omitted from
  the sanitized public conclusion.
- Presence is intentionally ephemeral, so participant lists can differ after reconnect even when
  all durable finding-review state is identical.
