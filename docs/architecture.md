# Architecture

The target application has four one-way layers:

1. **Discord adapter** authenticates the surface and converts Discord data to internal input.
2. **Deterministic game engine** validates every action and exclusively owns progression.
3. **GPT interpretation and narration** may propose typed input or restate confirmed output.
4. **Persistent storage** records explicitly environment-scoped state and append-only events.

All four boundaries now exist for action interpretation and response transformation. The policy,
engine, interpretation, narration, and storage types have no dependency on Discord events, so
they are tested without a Discord connection.

## Request boundary

Every request is resolved from trusted numeric IDs:

```text
DM / other guild / other channel -> ignore
configured test channel          -> configured administrators only
configured live channel          -> administrators, or mycotroph role for player actions
live/test player action          -> additionally requires that environment to be running
```

Channel names are never security inputs. Discord's guild administrator permission alone does
not grant game administration; the user's ID must be present in `ADMIN_USER_IDS`.

Every repository operation requires a `SessionRef(session_id, environment)`. Every stateful row
stores that session ID and environment, and event rows additionally use a composite foreign key
to the matching session/environment. The current Discord channel is never durable evidence of
an event's environment.

PostgreSQL row locks and uniqueness constraints protect cross-process mutation; an asyncio lock
also serializes each session within one process. Each accepted engine action stores before/after
state in the append-only event log within the same transaction as its projection changes.
Duplicate message keys reuse the original event, and position-completion keys prevent repeated
completion.

Each accepted gameplay action also passes through the shared cycle controller before and after
its position validator. The controller classifies the action, enforces preparation/response and
participant allowances, and records cycle metadata in the same atomic state mutation. Position
validators remain independently testable so cycle policy does not duplicate or weaken their
deterministic resource, evidence, proposal, and completion checks.

Checkpoints and rollback append administrative events rather than deleting history. Session
exports identify their source environment; cross-environment imports fail unless an operator
explicitly opts into the unsafe path, which marks the destination modified.

## Content and progression authority

Seven YAML documents define identity, public premise, entities, observations, unlock metadata,
allowed actions, relational thresholds, resources, sustainability, reconstruction,
confirmation, completion effects, profiles, vocabulary, accessibility, and narration keys.
Pydantic rejects extra fields, ambiguous aliases, broken references, incomplete positions, invalid
compatibility matrices, noncanonical remediation hierarchy order, unknown counter targets,
contradictory culture declarations, unsafe biological eligibility, or missing positions. Every
position is complete, but YAML remains configuration rather than execution authority: an action
changes progression only through its registered typed model and ordinary-Python validator.

Positions 1 through 6 may carry a `provision_arc` definition. It declares broad fictional
contaminant classes, fungal cultures, compatibility pairs, treatment systems, non-reusable
substrates, public thresholds, climate records, action vocabularies, and initial counters. The
canonical hierarchy is ordered: refuse unnecessary production, reduce harmful inputs, redesign,
reuse only verified-safe material, separate flows, contain unavoidable waste, remediate compatible
contamination, monitor long-term effects, and manage spent substrate. Increasing treatment cannot
satisfy a missing source-reduction requirement.

Positions 3 through 6 also carry position-specific `provision_requirements`. These bind required
public observations, accepted actions, persistent effects, proposal fields, participant/function
minimums, and non-author confirmation to one proposal kind. Schema validation keeps those
requirements aligned with the position's action allowlist and relational rules.

Position 0 rules are ordinary Python. The validator computes donor and recipient results from
stored resources, requires a recorded pathway repair, counts distinct participant IDs and
temporary contribution functions, checks maintenance language against configured terms, and
requires non-author confirmation. YAML supplies data; it does not execute transitions.

## Public cycle state

Every Position begins at Cycle 1, Preparation, with Orientation as its latest activity. Cycle
state lives in the existing session JSON and therefore needs no relational migration. A
pre-cycle session gets a synthesized cycle view on
read and persists it with its next accepted action: existing contributions are scoped to the
current attempt, pending proposals or stacks reopen response, and no discovery or counter is
discarded.

The cycle controller applies these shared rules across Positions 0–6:

- an accepted observation or inspection opens intervention for that cycle;
- each participant receives one primary contribution;
- Orientation, Coordination, and Calculation are interleavable Preparation activity labels, not
  one-way phase locks;
- proposal creation requires three distinct primary contributors in Positions 0-5 and four in
  Position 6; a new author's primary contribution may satisfy the applicable minimum;
- after the minimum is met, an already-counted contributor may assemble the proposal without a
  second primary contribution or replacing the contribution already recorded;
- calculations, audits, summaries, and the first local orientation are free;
- proposal creation or stack opening closes Preparation and opens an exclusive public Response
  window;
- each participant receives one reaction per response window; stack resolution itself is a
  control action;
- a validator-rejected proposal is recorded as a failed collective attempt, adds instability,
  enters reassessment, and opens the next cycle;
- failed stack resolution also enters reassessment; successful confirmation completes the cycle
  and starts the next Position at Cycle 1.

Cycle cleanup clears temporary coordination records, open offers, calculations, mitigations,
route tests, stack state, and action allowances. Confirmed observations, contribution history,
resources, counters, established effects, archives, containment, and other position-defined
persistent records survive. Full terminology and phase behavior are documented in
[Cycle play](cycle-play.md).

These rules prevent ordinary phase-ordering or spent-primary deadlocks; player progression does
not depend on an operator closing a cycle. The guarded cycle-close command exists only for
exceptional facilitator or technical recovery of abandoned or manually constructed states.

Position 1 is also ordinary Python. The multi-position router atomically replaces completed
Position 0 data with a Circulation state derived from actual resource totals, counters, persistent
effects, unconsumed triggers, and prior confirmed records. Its validator distinguishes source
quantity from delivered quantity, applies route efficiency, requires public maintenance and a
conditional branch, distributes contribution functions, and completes only after non-author
confirmation. Optional public observations begin the Provision Works arc through unexplained
industrial allocation, changing climate baselines, altered return water, and a finite indicator
bed without requiring the full production system to be revealed immediately.

Position 2 derives its three record values from the confirmed Position 1 circulation. Its
ordinary-Python validator keeps source departure (`sent`), boundary arrival (`delivered`), and
the later remainder (`retained`) separately accurate. It requires public provenance, comparisons,
classification, an accurate relay, an explicitly preserved difference, three contributors, and
non-author confirmation. Additional records distinguish withdrawn from circulated, returned from
reusable, visually clarified from evidenced safety, and transformation from filtration,
immobilization, or accumulation.

Position 3 uses `ProvisionArcValidator` for Reciprocity. Players compare verified public benefit
with local water, heat, labor, waste, risk, and maintenance burdens, then establish source
reduction, disclosure, funded containment, worker protection, and public shutdown authority.

Position 4 requires a deterministic, multi-action remediation cycle. Public state separately
tracks compatibility, viability, contact time, paired evidence, saturation, flow separation,
rest/replacement, containment, source reduction, and archive duties. Unknown discharge cannot be
accepted by a biological bed, and visible clarification never proves safety.

Position 5 preserves versioned claims, later revisions, physical evidence, affected-region
observations, uncertainty, corrections, unresolved conflict, and the history of unsafe spent
substrate reuse. New versions append to public memory rather than replacing earlier records.

Position 6 accepts multiple reconstruction models but applies shared minimum constraints: four
participants and contribution functions, lower unnecessary throughput, protected public water,
livelihood transition, separated flows, source reduction before remediation, spent-substrate
custody, monitoring, maintenance, preserved history, public governance, and enforceable
reassessment or shutdown. Completion at Position 6 retains the final public state without trying
to advance to a nonexistent Position 7.

Each transition carries public history, counters, effects, records, resources, and unconsumed
triggers into a freshly validated position state. A content-version change runs an additive,
environment-scoped state upgrade. Provision Works data lives in the existing JSON session,
proposal, and event payloads, so this arc requires no Alembic/database-schema migration.

The optional tactical layer uses the same authority. One public stack may be open at a time;
its base proposal plus reactions is capped at four entries and resolves last-in, first-out.
Hypha posts the computed order before the base proposal is attempted. Confirmed events may add
single-use public reaction records, proposals may receive up to three distinct-participant
kickers, and visible counters can cross YAML-defined thresholds. Persistent effects, consumed
triggers, counters, and the stack are stored in the same environment-scoped state and event
transaction as ordinary actions. They are never inferred by GPT.

## Public-only behavior

The client requests message-content intent for natural-language actions. DMs, other guilds,
other channels, unauthorized users, and irrelevant discussion are silent. Relevant input and
all results remain in the appropriate shared channel. Test output receives a visible marker.
Generic ephemeral messages exist only to acknowledge invalid slash commands as Discord
requires; they contain no puzzle facts, clues, narration, or state.

## GPT interpretation boundary

The deterministic relevance gate admits only messages that mention the bot or directly reply to
one of its messages. Ordinary participant conversation remains silent even while a reconstruction
response is awaited. Slash commands use Discord interactions and do not pass through this message
gate. Once admitted, broad orientation and explicit confirmed-state summaries are resolved locally
before the API boundary.

For other admitted messages, the context builder sends only a temporary `participant_1` label,
allowed actions, public entity IDs/aliases and confirmed observations for the current position,
plus the sanitized current response. It sends no earlier channel messages. Discord text is quoted
as untrusted data. The Responses API must return the strict `StructuredInterpretation` Pydantic
schema.

The explicit slash-command surface is authoritative for all seven positions. Natural-language
interpretation is optional and intentionally narrower; an unsupported Provision Works action
falls back to public command guidance rather than acquiring inferred fields.

The interpretation is rejected before the engine for low confidence, malformed/unknown actions,
rule-change attempts, unconfirmed evidence keys, unknown entity/observation/proposal IDs, and
deterministically detected prompt injection. Accepted candidates still pass through the same
ordinary Python validator used by slash commands. GPT has no repository mutation capability.

Cooldown and aggregate usage records carry the durable session and environment; usage records do
not identify the participant. Prompts and participant messages are not persisted. Daily and
monthly hard caps and per-user/global cooldowns fail closed to explicit commands. Usage is recorded
even when the returned model structure is later rejected.

## GPT narration boundary

Only an accepted deterministic event with a stored event ID enters response transformation.
Rejected actions retain their engine feedback; duplicate events do not make a second narration
request. The provider request contains only the active response profile, event type/key, completion
flag, and explicit style allowlist. It includes no canonical outcome, prior narration, or
participant response.

Structured output contains only a short lead and closing. Lead and closing words must
come from a small profile-specific, non-factual vocabulary and cannot contain IDs, numbers,
mentions, links, or backticks. A guard failure, timeout, provider error, cooldown, context limit,
or hard budget cap returns deterministic profile-specific narration. The canonical outcome is
inserted locally after validation and is never sent to the narration model. Narration writes only
aggregate API-usage and final public-history records; it has no game-state
mutation path.

## Orientation reveal boundary

Generic atmospheric actions such as looking around, surveying the area, or getting one's
bearings map to a local-orientation intent. That intent returns only the position's configured
immediate sensory response and invitation to ask about one specific feature. It does not unlock
an observation, add a contribution function, confirm a fact, or satisfy a need, capacity,
structure, history, or risk inquiry.

Explicit requests for a recap, orientation or accessibility summary, map overview, or confirmed
public state are classified separately. Targeted inquiries are also separate and must pass their
ordinary deterministic observation rules. The natural-language interpreter applies this
classification before any API call; it may not promote a broad atmospheric phrase to a summary
or targeted inquiry.

## Scientific restraint boundary

Provision Works content uses broad fictional classes and categorical public thresholds. It does
not contain culturing instructions, exposure limits, chemical recipes, species-specific safety
claims, or permission to reuse treated material. Compatibility, treatment response, contaminant
removal, safety, and reuse eligibility remain separate propositions. Used treatment substrate is
contained unless public fictional rules explicitly establish otherwise; it never becomes compost
automatically.

## Process lifecycle

The HTTP health service starts before the Discord connection. `/healthz` is a liveness endpoint
and reports Discord connectivity plus both session modes. `/readyz` returns 503 until Discord is
connected. SIGINT and SIGTERM close Discord and the HTTP runner cleanly.

Logs are newline-delimited JSON on standard output. Relevant records include `environment` as
`live`, `test`, `system`, or `outside`; tokens and environment contents are never logged.

## Guarded rollout and recovery

Startup runs database integrity and complete packaged-content simulation checks before Discord
connects. A background backup service creates timestamped SQLite online backups or PostgreSQL
custom-format `pg_dump` files and records success/failure without putting database URLs in logs or
process arguments.

`live-readiness` is read-only. It requires distinct live, test, and diagnostic channel
configuration, database/content
health, a historical clean test completion, an unmodified current test state, pristine locked
live Position 0 state, available API hard-budget headroom, and a recent successful backup.
`start-live` repeats those checks and requires explicit confirmation before the locked-to-running
transition.

Runtime controls are session/environment scoped: model overrides, budget overrides, fallback
mode, consecutive API failures, and feature flags cannot cross between test and live. Repeated
provider failures activate deterministic fallback for only the affected environment. Budget
alerts are throttled and sent to the required configured administrator diagnostic channel.

Rollback and invalidation require scoped event IDs. Operational rollback is allowed only while
paused and rebuilds relational projections from restored deterministic state. Invalidation marks
the original event, restores its prior state, leaves the session paused, and permits a typed retry
under a new idempotency key. Deleted Discord messages are logged and alerted but never delete or
reverse durable events.

The administrator test surface also exposes checkpoints, paused checkpoint rollback, labeled
exports, same-environment paused imports, generated-narration clearing, and confirmed debug
overrides. Imports always mark test state modified and rebuild projections; cross-environment or
out-of-range documents fail before mutation. Clearing history deletes only test narration rows,
then appends an audit event—the durable event log and puzzle summaries remain.
Forced events, positions, and profiles are repository-guarded to the test environment and visibly
disqualify the current rehearsal from live-readiness.
