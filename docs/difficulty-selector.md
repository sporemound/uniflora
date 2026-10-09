# Private per-user difficulty selector

Hypha can post a persistent three-button selector in the exact configured Discord test channel:

```text
/v2 difficulty action:Open selector
```

Each click is a private presentation preference for the Discord account that clicked it:

- **Guided** adds proactive next-step cues, definitions, and command reminders.
- **Standard** preserves the current balanced presentation and is the default.
- **Expert** removes automatic phase scaffolding where the Discord transport can do so safely.

All three levels preserve the same evidence, scientific constraints, access policy, action costs,
cooldowns, peer-review independence, promotion policy, position prerequisites, and deterministic
outcomes. Difficulty is not an authoritative rules switch and never changes shared game state.
`/interior accessibility`, `/interior next`, `/v2 status`, and `/v2 guide` remain available.

## Discord workflow

The v2 test selector is administrator-only because the configured test channel is
administrator-only.

1. Run `/v2 difficulty action:Open selector`.
2. Click **Guided**, **Standard**, or **Expert** on the Hypha message.
3. Discord returns an ephemeral confirmation visible only to the clicking account.
4. Run `/v2 difficulty action:My selection` to inspect your effective setting.
5. Run `/v2 difficulty action:Selector status` for the open message ID and aggregate response
   count. Individual choices and identities are not displayed.
6. Run `/v2 difficulty action:Close selector confirm:true` when selection should stop. Closing
   does not erase saved preferences.

Only one selector may be open for the session. A new selector may be posted after the earlier one
is closed. Retained history and per-account change limits prevent unbounded component spam.

## Identity and persistence boundary

The callback derives identity from `interaction.user.id`; no user ID or simulated v2 seat is
accepted from a button value. The choice therefore belongs to the real Discord account even when
the sole tester switches between `investigator-a` and `reviewer-b`.

Every accepted change verifies the current guild, channel, and exact Hypha message ID against the
open database record. A copied, stale, closed, wrong-channel, or wrong-guild component cannot
change a preference. Changed selections append private audit rows with the Discord interaction ID
for idempotency. Re-clicking the same value is a no-op.

Preferences are stored in sidecar SQL tables and are deliberately excluded from:

- authoritative v2 event envelopes and snapshots;
- public Activity state and signed Hypha projections;
- investigation-room participants, findings, reviews, and conclusions; and
- public Discord tallies or voter lists.

The selector works without Message Content or native Discord Poll intents.

## Web Activity boundary

The web Activity does not yet write this preference. Adding a second unsynchronized store would
create conflicting choices, while the current v2 test runtime maps one real administrator to two
simulated seats. A future web control must use the existing server-attested Activity session and a
private, self-only preference endpoint; it must never accept a participant or Discord ID from the
browser or publish the preference in public state.

Until that authenticated synchronization path exists, Discord is the canonical difficulty
surface.
