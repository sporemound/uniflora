# The Missing Interior v2 Content Contract

Status: Draft 0.1  
Scope: v2 position content and its boundary with the reusable game engine.

## 1. Purpose

The v2 content contract defines what every playable position must provide, what the
shared engine may assume, and what must remain content-driven.

It is intended to prevent position narratives from becoming hard-coded engine
behavior.

The contract must support:

- complete replacement of all pre-v2 positions;
- deterministic and replayable state transitions;
- explicit commands and natural-language interpretation;
- multiplayer contribution requirements;
- spoiler-safe public information;
- accessible summaries and command guidance;
- content validation before deployment;
- future position packs without engine rewrites.

## 2. Core design principles

### 2.1 Content describes the world

Position content defines:

- entities;
- observations;
- public descriptions;
- resources and counters;
- available actions;
- prerequisites;
- effects;
- completion conditions;
- presentation assets;
- position-specific event material.

### 2.2 The engine enforces generic rules

The shared engine defines:

- action validation;
- state mutation;
- contribution accounting;
- proposal and confirmation behavior;
- cycle progression;
- event triggering;
- persistence;
- idempotency;
- authorization;
- replay and audit history.

Shared engine code must not contain branches such as:

```python
if position == 3:
## Canonical v2 reset

The pre-v2 Position 0–6 narrative is not canonical for v2.

Legacy settlement state, resources, characters, narrative revelations, and
bespoke mechanics will not be migrated merely because they already exist.

The reusable inheritance from the legacy project is limited to:

- deterministic runtime patterns;
- persistence infrastructure;
- Discord integration patterns;
- authorization and privacy behavior;
- audit and replay concepts;
- tested generic utilities.

V2 is an investigation world consisting of persistent locations, temporary
roles, evidence sources, observations, hypotheses, analyses, and assessments.

Positions establish investigative focus and progression. They do not contain or
own all location state.

Evidence provenance, uncertainty, processing history, and limitations are
required gameplay concepts rather than optional presentation metadata.

The canonical institutional network and revelation chain are documented in:

- `docs/adr/0002-investigation-world-model.md`
