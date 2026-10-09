# The Missing Interior — Stochastic Investigation Overhaul

## Design statement

The Missing Interior is no longer a linear checklist with a single fixed path through each position. It is now a replayable multiplayer investigation in which instruments, institutions, and models evolve under uncertainty.

A legal player action always succeeds mechanically. What changes from one investigation to another is **what that action reveals**, how strongly it supports competing explanations, which secondary records become available, and which route through the position becomes most useful.

The central rule is:

> Outcomes may be stochastic when generated, but every generated outcome becomes an immutable event and replays exactly.

This preserves the project’s event-sourced audit trail while allowing genuinely different cases to emerge.

## The player loop

Every position now moves through four public phases.

### 1. Establish

Players secure enough independent source material to form an initial case. They choose among available facilities, records, and temporary investigative functions. A position no longer requires every opening action.

### 2. Perturb

Capabilities interrogate the current hidden process. A receiver diagnostic, reconstruction, archive audit, basis comparison, or resonance test produces a bounded but non-predetermined observation. The result can strengthen one explanation, complicate another, or unlock a new source.

### 3. Reconcile

Players compare observations across domains, test ordinary explanations, preserve contradictions, and document what the collection system could not observe. Competing models remain visible instead of collapsing into a single answer too early.

### 4. Review

A participant drafts the assessment and another participant independently confirms it. Completion requires a valid route, sufficient source diversity, the position’s required contradiction and information gap, and a confirmed assessment.

## Six evolving investigations

### Position 1 — First Return

The Boundary Array retains an optical record and independent radio return. The underlying signal regime evolves as optical inspection, receiver calibration, timing comparison, and atmospheric testing interrogate it.

Valid routes:

- **Receiver-led reconstruction** — establish the receiver state, then test timing and atmosphere.
- **Optical-environmental reconstruction** — establish the optical and weather record without requiring the receiver diagnostic.

### Position 2 — The Track That Will Not Close

Pilot testimony, controller communications, radar products, transponder records, and fusion logic define overlapping but non-identical airspace accounts.

Valid routes:

- **Testimony and geometry** — reconstruct relative bearings from human and operational records.
- **Sensor provenance** — audit retained plots, processing, and data lineage.

### Position 3 — A Pattern Without a Common Cause

The archive contains recurring forms whose similarity may come from recurrence, copying, vocabulary drift, selective retention, or genuinely related events.

Valid routes:

- **Provenance** — reconstruct custody, source dependence, and terminology.
- **Recurrence sampling** — build a controlled comparison across records and periods.

### Position 4 — The Volume Defined by Its Absence

Holographic reconstruction produces families of possible volumes under incomplete phase coverage and inverse-method artifacts.

Valid routes:

- **Reconstruction sensitivity** — compare calibration, registration, and algorithm families.
- **Absent volume** — reconstruct the missing volume directly, then test its dependence on method.

### Position 5 — A Mode Without a Source Point

Seismic, acoustic, electromagnetic, hydrological, and infrastructure records may describe a regional mode rather than a local source.

Valid routes:

- **Multiphysics coherence** — combine three or more independent measurement domains.
- **Infrastructure exclusion** — map local coupling and infrastructure before testing the regional model.

### Position 6 — The View From the Missing Interior

The final institute compares incompatible measurement bases, estimates an effective state, and reconstructs the difference between exterior and interior descriptions.

Valid routes:

- **State estimation** — begin from synchronized observables and estimate the effective density matrix.
- **Basis sensitivity** — begin from readout calibration and test how basis selection changes the reconstruction.

## Stochastic processes

Each facility has one content-defined process:

| Process | Algorithm | Mechanical role |
|---|---|---|
| Boundary signal regime | Hidden Markov model | Correlated optical, radio, timing, and environmental observations |
| Airspace track regime | Hidden Markov model | Evolving agreement and disagreement among testimony, plots, and fusion products |
| Archive provenance regime | Semi-Markov model | Persistence, delayed accession, copying, custody gaps, and vocabulary drift |
| Holographic phase regime | Hidden Markov model | Phase coverage, registration, inverse artifacts, and absent-volume stability |
| Subsurface mode regime | Hidden Markov model | Cross-domain bursts, local coupling, and regional coherence |
| Quantum observer regime | Hidden Markov model | Basis-dependent observations, preparation, readout, and state-estimation uncertainty |

Hidden states are never shown to players unless a future content pack explicitly permits disclosure. Players see only recorded outcomes, measurements, uncertainty, and model support.

## Competing models

Every stochastic observation updates a bounded distribution over several candidate models. Updates use integer likelihood weights, a tempered learning rate, and a minimum support floor. This prevents one lucky observation from declaring the case solved and prevents a model from becoming mathematically impossible too early.

The public Activity shows model support as an evolving investigative aid, not as a probability that any metaphysical explanation is true.

## Randomness and trust

The engine supports two sources of randomness:

- **Cryptographic runtime source** for live play.
- **Seeded HMAC source** for testing, balancing, and exact bug reproduction.

The generated event records:

- the process and channel;
- previous and next hidden-state identifiers in the private event stream;
- the bounded draw and selected outcome;
- a hash of the transition weights;
- public measurements and uncertainty;
- the resulting model-support distribution.

The reducer never draws again. Replaying an event stream produces byte-equivalent authoritative state.

## What remains deterministic

The following are never randomized:

- authorization;
- role and location requirements;
- parser behavior;
- whether a legal action is accepted;
- assessment confirmation rules;
- event ordering and integrity;
- whether the campaign remains completable;
- public/private information boundaries.

## Activity overhaul

The Activity public-state schema is now `2.3.0`. It exposes:

- authoritative game sequence;
- current case phase;
- evidence status;
- capability status and blockers;
- route progress;
- recent stochastic observations;
- competing-model support;
- position and facility state;
- the next collaborative requirement.

The Activity refreshes lightweight public state frequently while retaining a slower refresh for large scientific bundles. The scientific workspace receives the live snapshot, so a Discord capability can unlock or change the relevant workspace state rather than merely incrementing a counter.

## Compatibility

The overhaul preserves existing position, evidence, action, role, and stream identifiers. Existing schema-2 events remain readable. New stochastic fields begin appearing only in new action events. No SQLite migration is required.

The live sequence-9 Position 1 stream can continue after installation. Its next stochastic capability initializes the corresponding process from the content-defined initial state and records the first observation as a normal append-only event.
