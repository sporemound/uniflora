# Puzzle authoring guide

Puzzle files live in `src/uniflora/content/puzzles`. Exactly one YAML file must define each
position from 0 through 6. The loader uses `yaml.safe_load`, then strict Pydantic validation;
unknown fields and broken references fail startup.

## Required shape

Every definition declares:

- schema/content version, numeric position, key, title, status, and public premise;
- completion effects and public accessibility summary.

A `complete` position additionally requires at least five entities and observations, allowed
actions, relational and confirmation requirements, deterministic narration keys, a tactical
configuration, and a local orientation definition. Position 0 supplies sustainability and
reconstruction rules; Position 1 supplies circulation rules; Position 2 supplies translation
rules; Positions 3-6 supply a validated `provision_arc` and position-specific
`provision_requirements`. All packaged positions are complete.

Complete positions also declare `tactical`: a stack depth from two through four, reaction and
kicker allowlists, plus strain, repair, and coherence thresholds. These values configure bounded
Python rules; adding a string to an allowlist does not implement new transition behavior.

## Provision Works content schema

`provision_arc` is reusable configuration for Positions 1-6. It may declare:

- stable entity-role references for the Works, intake and return flows, public water, workers,
  treatment systems, containment, monitoring, archives, and reclaimed spaces;
- broad fictional contaminant classes with an explicit biological-treatment eligibility flag;
- fungal cultures and a complete compatibility matrix that must agree exactly;
- remediation systems with distinct processes, compatible classes/cultures, containment
  destinations, and categorical moisture, temperature, and contact-time requirements;
- substrates that always require containment and never permit automatic contaminated reuse;
- public thresholds for saturation, viability, containment, evidence, and throughput;
- the historical baseline, current measurement, forecast, conditional projection, obsolete
  expectation, and unresolved climate discrepancy;
- explicit vocabularies for sampling, reduction, redesign, mitigation, maintenance, and records;
- public counter defaults for saturation, viability, containment, evidence, source reduction,
  throughput, extraction, public benefit, burden, remediation, and archival coherence.

Compatibility is deliberately conservative. An ineligible or mixed/unknown class cannot have a
compatible biological-treatment rule. Culture declarations and the rule matrix must match.
Visible-only measures such as color, odor, turbidity, or appearance never increment safety
evidence.

The remediation hierarchy must use this exact order:

1. refuse unnecessary production;
2. reduce harmful inputs;
3. redesign production;
4. reuse verified-safe material;
5. separate clean and contaminated flows;
6. contain unavoidable waste;
7. remediate compatible contamination;
8. monitor long-term effects;
9. manage spent substrate.

`provision_requirements` binds one position to its proposal kind, required observations and
actions, required proposal fields and persistent effects, completion effects, participant and
function minimums, and non-author confirmation. Position 3 uses `reciprocity`, Position 4 uses
`remediation_protocol`, Position 5 uses `memory_archive`, and Position 6 uses `reconstruction`.
Required actions must also appear in `allowed_actions`; the relational thresholds must agree.

Adding YAML never registers behavior by itself. Every action string must have a strict typed
action, Discord adapter path, deterministic validator branch, public event result, and tests.

Entities provide stable IDs, public aliases/descriptions, initial resources, and measurements.
Aliases must be unique across the position. Observations reference known entities and contain
only text safe to post publicly. `fact_key` is an internal stable label; `public_text` is what
recall may reveal after deterministic unlock. Use the configured fact classification to keep
historical baselines, current measurements, forecasts, conditional projections, obsolete
expectations, unresolved discrepancies, provenance, and preserved differences distinct.

## Position 0 invariants

Do not weaken these while editing content:

- Three distinct participant IDs and three temporary contribution functions are required.
- Simulated `test:*` IDs are accepted only in the test session.
- The proposal author cannot supply the required confirmation.
- Donor reserve and recipient viability are computed from stored resources.
- A resource offer or proposal cannot spend below donor reserve.
- Observing the damaged path is not equivalent to contributing its repair.
- A maintenance condition must include an allowed future reassessment term.
- Completion and response-profile changes occur only after valid non-author confirmation.
- A public stack contains one base action and at most three reactions, resolved in reverse.
- Each participant contributes at most one entry to a given stack.
- Kicker contributors are distinct non-authors; a proposal accepts at most three kickers.
- Three donor strain counters raise the maintained reserve requirement by the configured penalty.
- Two successful route tests create the persistent `route_reinforced` effect.

The initial tactical keywords are interface summaries rather than a separate command language:
route objection/repair/reassessment, Sustain through monitoring, and Mitigate through donor
protection. Natural-language play may use them, but every resulting action has the same explicit
typed representation as a slash command.

## Position 1 invariants

- Position 1 begins from actual confirmed Position 0 resources, counters, effects, and records.
- The ecological regions resolve as systems in a remote specialist workers' settlement; the
  dried First Bloom basin is public evidence of a future civic garden, not a supernatural reward.
- Pale Nursery demand is a deterministic forecast derived from inherited instability.
- Condensation output is unavailable until its collection surface is publicly sustained.
- Source and delivered quantities remain distinct until Route 07 is reassessed.
- Central Relay forwards within one resolution cycle and never becomes durable storage.
- Valid circulation strategies include loss-accounted Veil flow, maintained efficient flow, and
  combined flow with protected Northern or Archive support.
- Northern support preserves its strain-adjusted reserve, consumes stored water, and adds strain.
- Archive support preserves bed viability and records whether coherence becomes fragile.
- A combined inflow requires Central Relay maintenance and a calculation containing its support.
- A stack demand reassessment changes deterministic state before the base proposal resolves.
- A proposal requires a maintenance condition, reassessment condition, and public branch. The
  Discord command records their canonical text from one guided revision-trigger choice rather
  than asking players to guess validator vocabulary.
- At least one non-author supplies maintenance, mitigation, branching, or a qualifying safeguard.
- Completion requires at least three participants, three functions, and non-author confirmation.
- Early Provision Works observations remain staged: an unexplained allocation, altered return,
  changing climate baseline, and limited indicator bed do not reveal the entire system at once.
- The indicator bed may change visible condition but cannot prove safety or unlimited capacity.
- The complete path must work through slash commands with OpenAI disabled.

## Position 2 invariants

- Record totals are derived from the confirmed Position 1 source and delivery quantities.
- Sent, delivered, and retained identify distinct stages; an accurate record is never rewritten
  merely to match another stage.
- All three records, their glossary, provenance, and the minority note must become public.
- At least two comparisons must collectively include all three records.
- Completion requires the evidence-supported `different_stages` classification, an accurate
  relay, a three-term mapping, and a summary containing every stage and value.
- The proposal must explicitly preserve a difference or minority account.
- Withdrawn/circulated, returned/reusable, treated/visually clarified, and degradation,
  transformation, filtration, immobilization, or accumulation remain distinct material terms.
- Completion requires at least three participants, three functions, and non-author confirmation.
- The complete path must work through slash commands with OpenAI disabled.

## Position 3 invariants

- Verified public benefit never cancels local burden, extraction, control, or risk.
- The Works must reduce waste at source, disclose materials, fund maintenance and containment,
  protect workers and maintainers, and accept a public shutdown condition.
- Employment counts as one benefit only where its stability and conditions are public.
- Required effects include a public discharge ledger, source reduction, worker protection, and
  spent-substrate containment before a reciprocity proposal can complete.
- Completion requires three participants/functions and non-author confirmation.

## Position 4 invariants

- The public maintenance-cycle order is deterministic: inspect discharge; identify the
  contaminant class; verify fungal compatibility; maintain or inoculate the bed; regulate flow
  and contact time; sample upstream and downstream; evaluate evidence; rest or replace saturated
  substrate; contain spent material; and reassess production limits. The two `or` stages accept
  either branch, not both.
- Unknown/mixed discharge and incompatible cultures fail safely and create useful public records.
- Low viability, saturation, excessive throughput, missing separation, or insufficient
  containment prevents treatment even when infrastructure exists.
- A visual-only sample does not add evidence. Upstream/downstream comparison and repeated public
  measurement are separate requirements.
- Saturated substrate must be rested or replaced and routed to an approved containment entity.
- Source reduction precedes the final remediation protocol and treatment capacity never permits
  additional pollution.

## Position 5 invariants

- Original claims, later revisions, evidence, affected-region observations, uncertainty,
  corrections, and unresolved conflict remain versioned and public.
- A correction appends a version; it never overwrites or deletes an earlier record.
- The failed-treatment history includes visible clarification, accumulated substrate, unsuitable
  reuse, re-entry into the system, and the later omission.
- Spent material remains contained while its handling requirement is unresolved.
- Completion requires three participants/functions and non-author confirmation.

## Position 6 invariants

- Several reconstruction models are valid; no single ideological speech or final boss is needed.
- Completion requires four distinct participants and four contribution functions.
- Revised output must reduce unnecessary throughput and protect public water.
- The proposal must preserve livelihoods or supply a transition, separate flows, put source
  reduction before remediation, contain spent substrate, fund monitoring/maintenance, preserve
  history, establish public or worker-community control, and define reassessment/shutdown.
- Distant private accumulation cannot override local ecological viability.
- Final completion remains at Position 6 and is read-only afterward.

## Static narration and scientific restraint

All authoritative arc outcomes are static YAML or Python text derived from confirmed state. Do
not add practical culturing steps, exposure thresholds, chemical recipes, species-specific safety
claims, or instructions for real contaminated material. Broad fictional categories are required.
Never imply that visible clarity establishes safety or that spent fungal substrate is compost.

All clue text must remain public. Do not add secrets, private inventories, member-specific
vulnerabilities, permanent player classes, or YAML fields that assert a transition without a
Python validator.

## Orientation text

`orientation.local_response` must stay narrowly sensory and local. It must not contain the full
set of region names, network positions, routes, unrevealed measurements, or a public-state recap.
`specificity_invitation` should invite one more precise inquiry through the fiction without
asserting which inquiry category applies.

Treat generic attempts to get bearings as `orient_local`; they never unlock facts or count as a
need, capacity, structure, history, or risk contribution. Only an explicit recap, orientation or
accessibility summary, map overview, or confirmed-public-state request may enter a summary path,
and even that path may disclose only already-confirmed public information.

## Triggered presentations

Complete positions may declare `triggered_presentations` for one-time public artwork. Each entry
has a globally unique ID, a visible-counter condition, an image asset, alt text, and an
introduction. Delivery is recorded durably and retried after reconnect without intentionally
reposting a successful reveal. Triggered artwork is not pinned.

An atmospheric presentation must say when it is not an authoritative map. Its image, alt text,
and introduction must not confirm unrevealed region names, routes, measurements, or network
relations. Triggered presentations are consequences of deterministic public state; generic
orientation language never activates them.

## Validation workflow

```powershell
pytest tests/test_content.py tests/test_provision_arc.py
pytest tests/test_position_zero.py tests/test_position_one.py tests/test_position_two.py
pytest
ruff check .
```

`/interior validate-content` strict-loads all seven positions and performs an in-memory,
slash-only simulation through terminal Position 6, including the ordered remediation cycle and
test/live isolation check. It does not mutate either durable session.

Then reset `#test`, complete a clean run without force commands through Positions 0-6, use at
least four distinct identities/functions for final reconstruction, and verify the live session is
unchanged. Content validation does not start or unlock the live game.
