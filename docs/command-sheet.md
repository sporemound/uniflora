# Player command sheet

Discord displays the fields after a command is selected. Text in angle brackets below describes a
value; do not type the brackets. Only actions allowed by the current position are accepted.
Use public IDs or aliases from `/interior recall` and `/interior accessibility` rather than
inventing a new identifier.

## Public state

| Command | Purpose |
| --- | --- |
| `/interior position` | Show a compact current-position briefing, your recent contribution, and what is waiting. |
| `/interior next` | Show two or three useful actions available to you now, including their costs. |
| `/interior recall` | Show confirmed facts, records, counters, effects, proposals, and triggers. |
| `/interior accessibility` | Show the current position's explicit play alternatives. |
| `/interior intervene` | Slash-command fallback for an active Position 1 event; `brace`, `divert`, and `release` map to the event's three context-specific choices. |
| `/interior test settlement-event` | Open a no-deadline interactive event in the isolated test session. |

Action results end with `Recorded`, `Cost`, `Cycle effect`, `Available next`, and `Waiting on`.
Repeated observations do not consume a primary action when they add no new contribution.
The phase footer calls Orientation, Coordination, and Calculation the latest activity within
Preparation because they may interleave. A proposal opens the exclusive Response window. Once
the contributor minimum is met, an already-counted participant may assemble that proposal
without spending a second primary action; no operator command is part of normal progression.

## Core actions

| Command | Fields |
| --- | --- |
| `/interior act awaken` | `name`, `fate` (`plant`, `open`, or `keep`); available once at the opening |
| `/interior act orient` | `atmospheric_text` (optional) |
| `/interior act observe` | `entity` |
| `/interior act connect` | `source`, `target` |
| `/interior act offer` | `resource`, `amount`, `target` |
| `/interior act request-support` | `need`, `amount` (optional) |
| `/interior act summarize` | `focus` (optional); posts the textual summary with a fresh visual state-chart PNG |
| `/interior act sustain` | `target`, `condition` |
| `/interior act relay` | `source`, `via`, `target`, `resource`, `amount` |
| `/interior act mitigate` | `target`, `risk`, `detail` (optional) |
| `/interior act calculate` | `source_amount`, `pathway`, `support_amount` (optional) |
| `/interior act branch` | `proposal_id`, `condition`, `action` |
| `/interior act compare` | `record_a`, `record_b` |
| `/interior act clarify` | `record`, `term` |
| `/interior act classify` | `record_a`, `record_b`, `classification` |
| `/interior act relay-record` | `record`, `summary` |
| `/interior act annotate` | `record`, `note` |
| `/interior act confirm` | `proposal_id` from another participant's proposal |
| `/interior act trigger` | `trigger_id` |

Position 0 begins with a rootglass seed. The first accepted `/interior act awaken` names it and
irreversibly changes the settlement; later participants inherit that public scar. Position 0
uses `/interior act reconstruct` with `donor`, `recipient`, `resource`, `amount`,
`pathway`, `pathway_action`, and `maintenance`. Its bounded tactical commands are
`/interior act stack-open`, `/interior act stack-react`, `/interior act stack-resolve`, and
`/interior act kicker`. Use the reaction or kicker names printed by the current accessibility
response.

## Provision Works actions

These commands are under `/interior works`, not `/interior act`.

| Command | Fields |
| --- | --- |
| `/interior works inspect` | `target` |
| `/interior works sample` | `source`, `comparison`, `measure` |
| `/interior works separate` | `source`, `clean_target`, `contaminated_target` |
| `/interior works inoculate` | `target`, `culture`, `substrate` |
| `/interior works slow` | `target`, `condition` |
| `/interior works contain` | `target`, `destination`, `condition` |
| `/interior works rest` | `target`, `reassessment` |
| `/interior works replace` | `target`, `destination`, `replacement` |
| `/interior works refuse` | `target`, `basis` |
| `/interior works reduce` | `target`, `measure`, `amount` (optional), `condition` (optional) |
| `/interior works redesign` | `target`, `change`, `public_need` |
| `/interior works document` | `subject`, `record_type`, `reference` |
| `/interior works audit` | `target`, `claim`, `comparison` |

Important validation rules:

- Inspect a system before auditing it. Audits compare an exact configured public claim or record
  with an existing observation or sample ID.
- Samples use two distinct inspected public points and a configured measure. A visual-only
  measure does not add safety evidence.
- Reduction uses a configured measure plus a positive amount or an accepted confirmed condition.
- Redesign uses a configured change and a confirmed public-need observation ID.
- Documentation versions an existing public observation, failure, or record; `reference` is not
  an unrestricted evidence field.
- Inoculation succeeds only for characterized eligible material, a compatible available culture,
  suitable categorical conditions, adequate separation and containment, and capacity below the
  saturation and throughput limits.
- Containment and spent-substrate handling must use an approved public destination.

Position 4 follows a ten-stage public cycle: inspect discharge; identify its contaminant class;
verify fungal compatibility; maintain **or** inoculate the bed; regulate flow and contact time;
sample upstream and downstream; evaluate the evidence; rest **or** replace saturated substrate;
contain spent material; and reassess production limits. `sustain` and `inoculate` are alternative
ways to satisfy the bed-maintenance stage, while `rest` and `replace` are alternative ways to
satisfy the saturation stage. Separation and failure documentation remain required supporting
actions; the either/or choices do not remove those obligations.

## Position-specific proposals

Select the command first, then fill the named Discord fields. Every accepted proposal still
requires `/interior act confirm proposal_id:<id>` from a non-author.

For Positions 3-6, leave `open_stack` false to file the proposal directly, or set
`open_stack:true` to open the same typed proposal as a bounded response stack. Other participants
then use `/interior act stack-react`, and a participant resolves it with
`/interior act stack-resolve`.

### Position 1: circulation

`/interior propose circulation`

Required fields: `source_amount`, `delivered_amount`, and `revision_trigger`. Select the displayed
revision condition; do not write maintenance, reassessment, or branch prose. Hypha supplies the
only valid known path: Condensation Veil water through Route 07 and Central Relay to Pale Nursery.

Optional fields: `support_source` and `support_amount`. Leave the source blank and the amount at
`0` when the calculation uses no support; otherwise supply both.
`/interior propose circulation-stack` opens the same proposal as a bounded response stack.

### Position 2: translation

`/interior propose translation`

Fields: `record_a`, `record_b`, `record_c`, `classification`, `mapping`, `shared_summary`, and
`preserved_difference`. `/interior propose translation-stack` opens the same proposal as a
bounded response stack.

### Position 3: reciprocity

`/interior propose reciprocity`

Fields: `producer`, `public_benefit`, `local_burden`, `source_reduction_action`,
`material_disclosure`, `maintenance_obligation`, `containment_plan`, `worker_protection`, and
`shutdown_condition`; `open_stack` is optional.

### Position 4: remediation

`/interior propose remediation`

Fields: `source_discharge`, `contaminant_class`, `production_reduction_action`, `treatment_bed`,
`fungal_culture`, `flow_rate_condition`, `moisture_condition`, `monitoring_method`,
`upstream_sample`, `downstream_sample`, `evidence_requirement`, `saturation_limit`,
`spent_substrate_destination`, `maintenance_condition`, and `shutdown_condition`; `open_stack`
is optional.

### Position 5: memory

`/interior propose memory`

Fields: `original_claim`, `later_revision`, `physical_evidence`, `affected_observation`,
`uncertainty`, `correction`, `unresolved_conflict`, and `handling_requirement`; `open_stack` is
optional.

### Position 6: reconstruction

`/interior propose reconstruction`

Fields: `production_line`, `current_output`, `revised_output`, `public_need_served`, `water_cap`,
`waste_reduction`, `worker_transition`, `ownership_or_governance`, `remediation_obligation`,
`clean_flow_plan`, `spent_substrate_plan`, `monitoring`, `maintenance`, `historical_records`,
`reassessment`, and `shutdown_threshold`; `open_stack` is optional.

Final reconstruction needs four distinct participants and four contribution functions. The
revised output must be lower than the current output, the water cap must protect public water,
and the text fields must preserve livelihood transition, public governance, source reduction,
separated flows, spent-substrate custody, monitoring, maintenance, memory, reassessment, and
shutdown authority.

## Position quick reference

| Position | Main action families | Proposal |
| --- | --- | --- |
| 0 — The Dry Network | observe, connect, offer | `/interior act reconstruct` |
| 1 — The Interrupted Current | observe, sustain, calculate, relay, mitigate, branch | `/interior propose circulation` |
| 2 — Translation | observe, compare, clarify, classify, relay-record, annotate | `/interior propose translation` |
| 3 — The Provision Works | inspect, audit, reduce, mitigate, contain | `/interior propose reciprocity` |
| 4 — The Maintained Remediation Cycle | inspect, separate, sustain or inoculate, slow, sample, audit, rest or replace, contain, reduce, document | `/interior propose remediation` |
| 5 — Memory | inspect, audit, document, contain | `/interior propose memory` |
| 6 — Reconstruction | inspect, sample, audit, separate, reduce, redesign, contain, sustain, mitigate, document | `/interior propose reconstruction` |

The [player rules](player-rules.md) explain collaboration and completion requirements.
