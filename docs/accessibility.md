# Accessibility and explicit play

Every required path through Positions 0-6 is public, asynchronous, deterministic, and available
through Discord slash commands. OpenAI, natural-language interpretation, voice chat, DMs, rapid
responses, manual arithmetic, and private clues are not required.

## Always-available support

- `/interior position` repeats the current public premise.
- `/interior recall` repeats confirmed discoveries, counters, effects, pending proposals,
  triggers, and prior-position summaries without revealing locked facts.
- `/interior accessibility` lists explicit actions for the current position.
- `/interior act summarize focus:<optional-text>` restates confirmed public information.
- `/interior act orient atmospheric_text:<optional-text>` gives a narrow local bearing without
  unlocking or enumerating the wider map.
- Discord's slash-command form exposes field names and numeric constraints before submission.
  The [command sheet](command-sheet.md) provides a copyable reference outside Discord.

All important numeric state is repeated after discovery. Position 1 provides
`/interior act calculate` so a player does not have to compute pathway delivery manually.
Position 0 offers short maintenance choices such as `monitor` or `reassess`; long prose is not
required where a configured short term is sufficient.

## Interaction guarantees

- There is no timing penalty. A player may leave and return to the same public state.
- No action depends on color, sound, animation, image interpretation, or an atmospheric artwork.
  Text, alt text, static narration, and commands carry the authoritative information.
- Presentation artwork is supplementary. It cannot reveal a required fact or count as an
  authoritative map.
- There are no fixed roles. Contribution functions are earned through accepted public actions,
  so participants may choose commands that match their comfort and available attention.
- Failed commands provide a public reason and do not wipe collective progress. A participant can
  use the response, recall, or accessibility help to try a different action later.
- Orientation, coordination, and calculation may be revisited in any order during Preparation.
  Only an open proposal or stack pauses those actions for its public Response window; ordinary
  play never depends on an administrator closing the cycle.
- The game preserves provenance and disagreement. It does not require players to collapse
  different measurement stages, erase minority records, or deliver one ideological speech.
- Explicit commands are authoritative. Optional natural-language interpretation covers only a
  subset and may fall back to a command without changing state.

## Optional audio layer

- Audio is off by default and starts only after a participant activates the visible audio
  control. The Activity never requests microphone access.
- Narration, interface cues, and scientific sonification are supplementary. Playing, stopping,
  muting, or never enabling them cannot examine evidence, submit an action, change a score,
  satisfy a review, unlock a position, or alter completion.
- Every narrated passage remains visible as text. Every interface cue has a simultaneous visible
  status, and every sonification retains its plotted data, numeric result, units, source-series
  labels, and a plain-language mapping legend.
- Presentation volume and analysis volume are independently adjustable, with a persistent mute
  and stop control. Audio stops when the Activity is hidden or the participant leaves the
  relevant analysis view.
- Silence is never left ambiguous: unavailable, missing, withheld, and measured zero values
  remain visibly distinguished.

## Public collaboration

Essential clues and decisions must remain in the game channel. If a participant wants help
entering a long proposal, the group may assemble its field values in public and another
participant may submit them. The proposal author still cannot supply the required confirmation,
and the distinct-participant/function rules still apply.

Operators should keep the test surface administrator-only and visibly marked `[TEST SURFACE]`.
Simulated test identities exist only in test and never satisfy live participation. See the
[operator guide](operator-guide.md) for rehearsal and recovery procedures.
