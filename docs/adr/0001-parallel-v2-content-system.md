# ADR 0001: Parallel v2 content system

Status: Accepted

## Context

The legacy content schema combines reusable position concepts with
position-specific structures including sustainability, reconstruction,
circulation, translation, provision arcs, and reinterpretation rules.

The legacy loader:

- loads only `PuzzleDefinition`;
- indexes content by integer position;
- requires exactly positions 0 through 6;
- performs legacy-wide validation after loading.

The legacy schema and game service contain direct position-number branches.

## Decision

V2 will introduce a parallel content system rather than modifying the legacy
schema in place.

Initial modules:

- `uniflora.content.v2.schema`
- `uniflora.content.v2.loader`
- `uniflora.content.v2.validation`

Legacy `PuzzleDefinition`, `PuzzleRegistry`, packaged YAML files, and validators
will remain unchanged during the initial v2 implementation.

## Consequences

Benefits:

- legacy behavior remains testable;
- v2 can use stable string IDs and arbitrary pack lengths;
- synthetic v2 content can be tested before rewriting Position 0;
- migration can occur one subsystem at a time.

Costs:

- both content systems will temporarily coexist;
- an engine-facing compatibility boundary will be required;
- legacy saved states will require an explicit migration policy.

## First milestone

Load and validate a synthetic one-position v2 content pack without invoking the
legacy registry or validators.