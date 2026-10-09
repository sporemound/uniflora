# Authoring strategic v2 investigations

Strategic content uses pack schema `3`; authoritative state with an initialized
board uses serialization schema `4`; the public Activity uses schema `2.4.0`.
Schemas 1–3 remain readable.

## Position rules

Each strategic position declares operation capacity, maximum rounds,
Coordination and Escalation bounds, one local resource, a natural-drift process,
and thresholds for a controlled outcome. The current pack uses three capacity
per round and eight maximum rounds.

## Action profiles

An action can declare:

- a strategic class and deterministic capacity/Coordination cost;
- campaign, position-track, and local-resource deltas;
- conditions to add or remove;
- `none`, `emit_only`, or `intervention_then_emit` stochastic behavior;
- ordered integer transition and emission modifiers;
- an independent supporter count and irreversible flag.

Actions without an explicit profile receive a deterministic default based on
their action type. Default stochastic actions are emission-only after strategic
initialization.

## Event invariants

1. Validate ordinary action prerequisites and strategic affordability before
   drawing randomness.
2. Rejected commands append no event, spend nothing, and consume no RNG draw.
3. A legacy stream initializes the board inside its first accepted strategic
   action event; prior actions are not charged retroactively.
4. A board preview is eventless.
5. Natural drift occurs at most once in the operation that closes a round.
6. Proposal support is independent and definition-hash checked.
7. Effective weights and every draw are persisted; replay only applies records.
8. Public projections omit player IDs, latent states, and raw entropy.

## Commands

```text
strategic-board
propose-action <action_id>
support-action <proposal_id>
pass-capacity
```

The same commands are available through `/v2 command`. `/v2 guide` displays
current board state, capability costs, route progress, and valid next actions.
