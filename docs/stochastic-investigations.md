# Authoring stochastic investigations

This document defines the implementation boundary for probabilistic mechanics in The Missing Interior v2.

## Safety invariant

Randomness is resolved before persistence and fully recorded in the accepted event. Reducers, serializers, Activity projection, and replay code must never reroll an outcome.

A stochastic action must therefore satisfy all ordinary deterministic prerequisites first:

1. the action belongs to the current position;
2. the player occupies the required location;
3. the player holds a permitted canonical role;
4. all hard and bounded-choice evidence gates are met;
5. all prerequisite capabilities and observation counts are met.

Only then may the stochastic resolver run.

## Process structure

A process contains:

- an algorithm identifier;
- an initial hidden state;
- a set of hidden states;
- integer transition weights from each state;
- one or more observation channels;
- weighted public outcomes for each channel;
- structured public measurements and uncertainty;
- competing model identifiers and likelihood weights;
- posterior learning rate and support floor;
- an optional latent-state disclosure flag.

All weights are non-negative integers. At least one transition and one emission must have positive weight. Weights do not need to sum to 100 or 10,000; the resolver samples proportionally and records the exact normalized context hash.

## Capability binding

An action can bind to a process using:

```yaml
stochastic_process_id: boundary_signal_regime
stochastic_channel_id: receiver_diagnostic
advance_stochastic_state: true
```

`advance_stochastic_state: false` samples an observation from the current hidden state without making a transition. This is suitable for repeated measurements of the same regime. A capability should normally be non-repeatable unless the position explicitly supports longitudinal sampling.

## Bounded-choice prerequisites

Linear prerequisite lists are still supported, but nonlinear positions should prefer bounded choices:

```yaml
prerequisites:
  candidate_examined_evidence_ids:
    - optical_record
    - radio_return
    - weather_record
  minimum_examined_evidence_count: 2
```

The equivalent capability gate is available for actions:

```yaml
prerequisites:
  candidate_completed_action_ids:
    - inspect_calibration_interferograms
    - validate_registration_reference_grid
    - audit_reconstruction_method
  minimum_completed_action_count: 2
```

Observation gates can require evidence from a process without requiring one exact capability:

```yaml
prerequisites:
  required_stochastic_process_ids:
    - holographic_phase_regime
  minimum_stochastic_observation_count: 2
```

## Completion routes

A position may define several legitimate routes. Completion succeeds when at least one route is satisfied in addition to the position-wide assessment and epistemic requirements.

```yaml
completion_routes:
  - id: sensitivity_route
    title: Reconstruction sensitivity route
    required_action_ids:
      - register_cross_location_constraints
      - test_inverse_reconstruction_artifacts
    candidate_action_ids:
      - inspect_calibration_interferograms
      - validate_registration_reference_grid
      - audit_reconstruction_method
    minimum_completed_action_count: 2
    required_stochastic_process_ids:
      - holographic_phase_regime
    minimum_stochastic_observation_count: 2
```

Routes must be genuinely distinct. Do not create two labels that ultimately require the same full action set.

## Model updates

The resolver starts from the current model-support distribution or an equal prior. For each observation:

1. multiply each model’s support by its outcome likelihood;
2. normalize the evidence-updated distribution;
3. blend it with the previous distribution using `posterior_learning_rate_basis_points`;
4. enforce `minimum_model_support_basis_points`;
5. normalize exactly to 10,000 basis points with deterministic remainder allocation.

Model support is an investigation aid. It must not be described as certainty, metaphysical truth, or a substitute for retained records.

## Public and private state

Private event/state fields may include hidden-state identifiers and raw draw metadata. The public Activity may include only:

- process public label;
- observation channel;
- public outcome label and summary;
- public measurements;
- uncertainty;
- sequence;
- model support;
- evidence unlocked by that observation.

The Activity projection checks the serialized snapshot for player IDs. Hidden state IDs are omitted unless `reveal_latent_state` is explicitly enabled in content.

## Testing requirements

Every stochastic process should have tests for:

- same seed, same event and state;
- different seeds can reach more than one outcome;
- serialized event and state round-trip;
- replay equality without a random source;
- model support sums to exactly 10,000;
- every public datum remains within its declared domain;
- hidden state does not enter public projection;
- every completion route can finish a full campaign;
- no valid route depends on an action from another position.

Use:

```powershell
python scripts/audit_stochastic_overhaul.py --chains 24 --steps 32
python scripts/verify_stochastic_campaign.py --route primary
python scripts/verify_stochastic_campaign.py --route alternate
```

Both tools are in-memory and do not open the live SQLite database.
