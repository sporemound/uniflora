# V2 public Discord identities

This update changes the public `/v2` interface from the two simulated A/B seats
to real Discord participants.

## Public commands

- `/v2 command text:<strict command>` uses the invoking Discord account.
- `/v2 role role:<function> name:<optional title> description:<optional text>`
  exposes autocomplete for roles required by the current position.
- `/v2 status` hides internal `test:` and `system:` identities.
- `/v2 guide` presents the public case briefing rather than the complete
  sole-tester solution sequence.

The event stream records a new `player_joined` event the first time a Discord
member acts. Public participant IDs use `discord:<user-id>`. Independent review
therefore compares real Discord accounts.

The internal `investigator-a` and `reviewer-b` identities remain available to
automated tests and `/v2 begin`, but ordinary players cannot select them.
