# The Missing Interior — strategic stochastic overhaul

The v2 investigation now treats each position as a shared operation board rather
than an unlimited checklist. Evidence reading, movement, role selection, and
status review remain free. Capability resolution spends operation capacity and
may change campaign tracks, position pressure, preparation conditions, local
resources, and the effective Markov weights used by later observations.

## Public loop

Each position begins with three operation-capacity points per round. The first
operation resolved by a participant adds Coordination. A second operation by the
same participant costs a surcharge. When capacity reaches zero—or participants
legally pass the remainder—the round closes and the position's hidden process
advances once through a recorded natural-drift resolution.

The public board exposes:

- Case Integrity and Institutional Trust across the campaign;
- round, capacity, Coordination, and Escalation;
- one position-specific resource;
- active preparation conditions and their duration;
- major-operation proposals and anonymous support counts;
- completed position grades and carryover assets or liabilities.

It never exposes Discord identities, entropy, or latent Markov-state IDs.

## Major operations

Every investigation position contains one optional major intervention. A player
opens it with `propose-action <action_id>`. Another participant must use
`support-action <proposal_id>`. Threshold-reaching support revalidates the
proposal and resolves the operation atomically; the support event and action are
not split across two mutable states.

## Randomness and replay

Ordinary stored-record analysis is emission-only: it samples what the current
regime reveals but does not rewrite the regime. Explicit interventions may alter
transition weights, and round closure may trigger natural drift. All effective
weight tables, draws, public outcomes, measurements, track changes, capacity
costs, and board state are recorded before persistence. Reducers never reroll.

## Fail-forward review

A position can complete as `controlled`, `compromised`, `incomplete`, or
`critical`. Completion routes never require a particular random outcome. Poor
resource or escalation management creates later carryover pressure instead of
making the campaign unwinnable.
