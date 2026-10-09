from __future__ import annotations

import re
from collections.abc import Iterable, Mapping


def semantic_trigger_id(
    reactions: Iterable[Mapping[str, object]],
    kind: str,
    subject: str | None = None,
) -> str:
    """Return a stable, readable ID that remains unique in the public session state."""

    kind_tokens = _tokens(kind)
    subject_tokens = [token for token in _tokens(subject or "") if token not in kind_tokens]
    base = "-".join([*kind_tokens, *subject_tokens]) or "reaction"
    existing = {str(item.get("trigger_id", "")) for item in reactions}
    if base not in existing:
        return base

    suffix = 2
    while f"{base}-{suffix}" in existing:
        suffix += 1
    return f"{base}-{suffix}"


def semantic_trigger_aliases(
    reactions: Iterable[Mapping[str, object]],
    observation_entities: Mapping[str, str],
) -> dict[str, str]:
    """Map stored trigger IDs, including legacy hashes, to readable public aliases."""

    aliases: dict[str, str] = {}
    reserved: list[dict[str, str]] = []
    for reaction in reactions:
        stored_id = str(reaction.get("trigger_id", ""))
        if not stored_id:
            continue
        subject = _reaction_subject(reaction, observation_entities)
        preferred = str(reaction.get("public_trigger_id", ""))
        if not preferred and not re.fullmatch(r"t-[0-9a-f]{12}", stored_id):
            preferred = stored_id
        if not preferred or any(item["trigger_id"] == preferred for item in reserved):
            preferred = semantic_trigger_id(
                reserved, str(reaction.get("kind", "reaction")), subject
            )
        aliases[stored_id] = preferred
        reserved.append({"trigger_id": preferred})
    return aliases


def resolve_trigger_id(
    supplied_id: str,
    reactions: Iterable[Mapping[str, object]],
    observation_entities: Mapping[str, str],
) -> str:
    """Accept either a durable stored ID or its readable public alias."""

    reaction_list = list(reactions)
    if any(str(item.get("trigger_id", "")) == supplied_id for item in reaction_list):
        return supplied_id
    aliases = semantic_trigger_aliases(reaction_list, observation_entities)
    return next(
        (stored_id for stored_id, public_id in aliases.items() if public_id == supplied_id),
        supplied_id,
    )


def _tokens(value: str) -> list[str]:
    return [token for token in re.sub(r"[^a-z0-9]+", "-", value.casefold()).split("-") if token]


def _reaction_subject(
    reaction: Mapping[str, object], observation_entities: Mapping[str, str]
) -> str | None:
    observation_id = str(reaction.get("observation_id") or "")
    return (
        observation_entities.get(observation_id)
        or str(reaction.get("pathway_id") or "")
        or str(reaction.get("donor_id") or "")
        or str(reaction.get("subject") or "")
        or None
    )
