# ADR 0002: Investigation world model

Status: Accepted

## Context

The Missing Interior v2 is a complete narrative and mechanical reset.

The legacy Position 0–6 story, settlement state, resources, characters, and
bespoke position mechanics are not canonical for v2. The legacy project remains
valuable as a deterministic runtime, persistence reference, Discord reference,
and compatibility boundary.

V2 is a deterministic multiplayer research mystery. Players reconstruct an
inaccessible phenomenon from incomplete observations gathered through different
locations, instruments, witnesses, processing chains, and scientific methods.

Its governing principle is:

> No position resolves from a single perspective.

## Decision

V2 will model an investigation world rather than a sequence of self-contained
puzzle documents.

The first-class concepts are:

- world;
- location;
- position;
- player presence;
- temporary operational role;
- instrument;
- evidence source;
- observation;
- hypothesis;
- analysis result;
- assessment.

## Canonical locations

The complete institutional network is:

1. Boundary Array
2. Aeronautical Incident Center
3. Aerial Phenomena Archive
4. Holography Laboratory
5. Subsurface Resonance Station
6. Quantum State Institute

Locations persist after they become available.

A position establishes the current investigative focus, but it does not own all
state belonging to its focus location.

The model must distinguish:

- `position_id`;
- `focus_location_id`;
- `available_location_ids`;
- `required_location_ids`;
- `player_current_location_id`.

## Player identity and roles

Players do not portray named fictional characters.

Players may receive temporary operational roles for a position or investigative
arc. Roles are released when their scope resolves.

Persistent player records may retain:

- completed assignments;
- demonstrated proficiencies;
- authored assessments;
- confirmed analyses;
- visited locations;
- contributions to discoveries.

The model must distinguish player identity, temporary role assignment,
proficiency, location access, and current location.

## Evidence

Evidence provenance and limitations are first-class state.

An evidence source or observation may record:

- source class;
- provenance;
- independence;
- instrument or witness;
- raw or derived status;
- processing history;
- uncertainty;
- known limitations;
- supported conclusions;
- unsupported extrapolations.

Contradictions must remain representable. The engine must not automatically
reconcile conflicting sources.

## Scientific analysis

Scientific processing runs through deterministic analysis jobs outside Discord
event handlers.

An analysis artifact must be able to record:

- input dataset hashes;
- method identifier and version;
- parameters;
- derived values;
- uncertainty;
- limitations;
- software versions;
- provenance.

A computed result is evidence. It is not automatically a narrative conclusion.

## Position progression

The canonical high-level sequence is:

1. An immense luminous phenomenon is observed.
2. No physical trajectory satisfies all records.
3. Historical cases form a distributed sampling pattern.
4. The combined pattern reconstructs an absent volume.
5. The absent volume behaves as a regional physical mode.
6. The institutional network temporarily forms an interior viewpoint.

This revelation remains content rather than engine logic.

## Next milestone

The next milestone is:

> V2 Milestone 2 — Deterministic Investigation Kernel

It must demonstrate:

1. content definition;
2. initialized investigation state;
3. player location;
4. temporary role assignment;
5. action prerequisite evaluation;
6. deterministic accepted or rejected results;
7. immutable effect application;
8. evidence or observation unlocking;
9. assessment requirement tracking;
10. position completion.

The milestone remains isolated from:

- Discord;
- SQLAlchemy;
- legacy `GameService`;
- natural-language interpretation;
- scientific worker processes;
- production story content.

## Consequences

The existing minimal v2 schema remains useful, but it is not yet the complete
world model.

The first synthetic investigation will use the Boundary Array and multiple
evidence sources rather than generic resource transfer.

Positions and locations must never become interchangeable concepts.
