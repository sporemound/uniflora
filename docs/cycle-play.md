# Cycle play

A Position is a complete scenario. A cycle is one asynchronous collective attempt inside that
Position. A participant's accepted primary command is their primary contribution for the cycle;
players never need to announce the beginning or end of a turn.

## Player rules

- Each cycle needs an accepted observation or inspection before intervention begins.
- Each participant may make one primary contribution per cycle.
- A proposal requires at least three distinct primary contributors in Positions 0-5 and four in
  Position 6. A proposal author's unused primary contribution may satisfy that minimum.
- Once the minimum is present, an already-counted contributor may assemble the proposal without
  spending a second primary contribution or replacing their recorded one.
- A participant who has spent their primary contribution may still use free information and one
  eligible reaction.
- Each participant may add one reaction to the current proposal or public response stack.
- Proposal authors cannot confirm their own proposal.
- There is no response timer. The Discord channel is the public priority record.

`/interior position` and `/interior recall` show the current cycle and phase.
`/interior accessibility` gives a concise fallback: current action families, proposal direction,
and allowance rules. `/interior chart` shows the position flow and completion checks, while
Discord autocomplete exposes the exact fields for the selected slash command.

## Phases

1. **Renewal** refreshes allowances and applies position-defined persistent effects. It is
   automatic.
2. **Preparation** uses three interleavable activity labels:
   - **Orientation** covers observations, inspection, local orientation, and public summaries.
   - **Coordination** covers the Position's relationships, maintenance, movement, containment,
     and intervention commands.
   - **Calculation** covers quantities, comparisons, and audits without moving resources.
3. **Proposal assembly** submits a proposal or opens a stack, closes Preparation, and opens the
   exclusive Response window. It uses the author's primary contribution if still available; an
   already-counted contributor can instead assemble it without taking a second primary action.
4. **Response** keeps public priority open only for eligible reactions, branches, kickers,
   triggers, stack control, and non-author confirmation.
5. **Resolution** applies the position validator and stack entries deterministically.
6. **Reassessment** records the outcome, cleans up temporary state, and either completes the
   Position or opens the next cycle.

Orientation, Coordination, and Calculation are not one-way locks. Until a proposal or stack
opens, accepted preparation actions may move freely among them: a calculation can reveal a
missing observation, and players can return to observe or coordinate without administrative
help. The footer names Preparation and separately reports the latest activity; that activity does
not close the other Preparation families. Position-specific evidence and maintenance
prerequisites still apply. Response is the only exclusive player-facing phase.

Ordinary play never requires `/interior ops cycle-close`. Once the contributor minimum is met,
one of those contributors can assemble the proposal even though their primary contribution is
already recorded. The administrative command remains available only for exceptional facilitator
or technical recovery of an abandoned or manually constructed state; it is not a progression
step.

## Action classes

Primary orientation includes `observe` and `inspect`. Primary coordination includes relationship,
resource, maintenance, sampling, separation, inoculation, containment, reduction, redesign, and
documentation commands. A proposal or stack-opening command uses a primary contribution when the
author has not yet contributed. After the position's contributor minimum is met, an
already-counted contributor may assemble it without a second primary contribution.

Position, recall, and accessibility are always free because they do not enter the action engine.
The one-time Position 0 `awaken` event is also free and does not consume a primary contribution.
The first `orient` by a participant in a cycle is free; repeating it is an observational primary
contribution. Summaries, calculations, comparisons, audits, and other verification actions do not
consume the primary allowance.

Branches, stack reactions, kickers, triggers, and confirmations are reactions. `stack-resolve`
closes public priority but does not consume a reaction slot.

## Failure and persistence

A proposal that reaches deterministic validation but does not satisfy the current public state is
an accepted failed attempt rather than a lost Discord command. Hypha records the validator's
feedback, adds one instability, enters reassessment, and opens the next cycle. Discoveries remain
available, so the next attempt begins with more public information.

Cycle cleanup resets primary and reaction allowances, temporary connections, open offers and
support requests, temporary maintenance and mitigation, relays, branch drafts, calculations,
route reassessments, and stack state.

Confirmed observations, public archives and summaries, resources, strain, repair, coherence,
saturation, viability, containment, evidence, source reduction, throughput, burden, persistent
effects, the settlement scar, and the contribution and cycle histories remain. Position-specific
validators retain authority over which additional systems are temporary or established.

## Compatibility

Cycle data is additive JSON session state. No database migration is required. When an older active
session is encountered, reads synthesize its current cycle and the next accepted action persists
it. Existing contributions are assigned to the current cycle, discoveries satisfy the
observation-opening check, and a pending proposal or open stack restores the response phase.
