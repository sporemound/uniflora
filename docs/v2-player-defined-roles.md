# V2 player-defined role titles

This feature lets a participant give an active investigation role a public title
and an optional public description. The title is mapped to one canonical role
function, which remains the value used for action prerequisites, audit logs, and
event replay.

## Discord use

The existing `/v2 command` signature is unchanged. In the sole-tester setup:

```text
/v2 command identity:investigator-a text:role set field_observer as "Sky Recorder"
```

With an optional description:

```text
/v2 command identity:investigator-a text:role set signal_correlator as "Night Radio Listener" --description "Compares optical and radio timing"
```

The equivalent explicit grammar is:

```text
assign-role <canonical_role_id> --name "Public title" --description "Optional description"
```

Run `/v2 status` to display the title together with its canonical function.
Release it with:

```text
/v2 command identity:investigator-a text:role clear
```

The original command remains valid:

```text
/v2 command identity:investigator-a text:assign-role field_observer
```

## Mechanical boundary

A player-defined title does not create a new permission. For example, a role
named `Night Radio Listener` mapped to `signal_correlator` satisfies only the
requirements that already accept `signal_correlator`. It does not satisfy
`field_observer`, bypass a location restriction, or alter scientific results.

This conservative mapping keeps the deterministic engine intact while allowing
players to use language that feels natural to them. Combining several canonical
functions into one player role would be a separate rules change and is not part
of this patch.

## Validation and moderation

- Role titles are limited to 48 characters.
- Descriptions are limited to 240 characters.
- Control characters and Discord mention forms are rejected.
- The canonical function must exist in the loaded pack.
- The role must be available at the player's authoritative location.
- The pack must explicitly permit player-defined text for that function.

All 38 role functions in the current Missing Interior pack permit custom titles
and descriptions.

## Persistence compatibility

The authoritative state stores:

- `active_role_id`: canonical mechanical function;
- `active_role_display_name`: optional public title;
- `active_role_description`: optional public description.

Legacy role events and ordinary role assignments omit the two new fields during
canonical serialization. Existing event hashes and snapshots therefore retain
their previous byte representation. New custom-role assignments store the extra
metadata in the `role_assigned` event and replay it deterministically.

No SQLite schema migration or Discord application-command resync is required by
this implementation because the `/v2 command` option shape is unchanged.
