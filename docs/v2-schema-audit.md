# The Missing Interior v2 Schema Audit

Status: Draft 0.1

## Goal

Determine which existing content structures can support v2 unchanged, which
should be generalized, and which encode only the pre-v2 narrative.

## Current architecture

Primary schema:

- `src/uniflora/content/schema.py`
- `PuzzleDefinition`
- `PuzzleDefinition.initial_state()`

Loader:

- `src/uniflora/content/loader.py`

Primary position validator:

- `src/uniflora/engine/position_zero.py`
- `EnvironmentPositionValidator`

## Preliminary classification

### Retain

- `schema_version`
- `content_version`
- `title`
- `public_premise`
- `entities`
- `observations`
- `allowed_actions`
- `orientation`
- `accessibility`
- `completion`
- `world_flags`

### Restructure

- `key`
- `position`
- `resource_values`
- `relational_requirements`
- `response_profile_changes`
- `confirmation`
- `narration_keys`
- `vocabulary`
- `presentation`
- `triggered_presentations`

### Replace with generic rules and effects

- `circulation`
- `provision_arc`
- `provision_requirements`
- `translation`
- `reconstruction`
- `sustainability`
- `reinterpretation_rules`

### Investigate

- `status`
- `tactical`

## Central design question

Should v2 introduce a parallel `PuzzleDefinitionV2`, leaving the pre-v2 loader
intact during migration, or modify `PuzzleDefinition` in place?

The preferred default is a parallel v2 schema unless the audit demonstrates
that the existing schema can be generalized without destabilizing legacy
content.

## Architecture decision

The audit supports a parallel v2 schema.

Reasons:

1. `PuzzleRegistry` is parameterized directly with `PuzzleDefinition`.
2. The loader requires exactly seven integer positions.
3. `PuzzleDefinition` contains explicit position-number validation branches.
4. Initial-state construction knows about bespoke narrative mechanics.
5. Position validators are divided into legacy position-specific classes.
6. `GameService` directly reads legacy mechanic blocks and position numbers.

Modifying the existing model would combine content migration, engine migration,
saved-state migration, and narrative rewriting into one change.

V2 will therefore begin as an isolated loader and schema with a synthetic
fixture. No legacy YAML will be converted until that fixture passes.
## Canonical design correction

The goal of v2 is not to generalize every pre-v2 mechanic.

Legacy structures such as `circulation`, `translation`, `sustainability`,
`reconstruction`, and `provision_arc` should not automatically become generic
v2 rule types.

The investigation model instead requires first-class representations for:

- persistent locations;
- player presence;
- temporary roles;
- instruments;
- evidence provenance;
- observations;
- hypotheses;
- analysis artifacts;
- assessments;
- contradictions;
- information gaps.

The next schema addition should introduce a pack-level investigation definition
alongside the existing minimal position registry.

The current `V2PuzzleRegistry` remains a valid experimental vertical slice and
should not be connected to the legacy `GameService`.
