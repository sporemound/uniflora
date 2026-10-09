from __future__ import annotations

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _identifier(value: str) -> str:
    cleaned = value.strip()
    if not _IDENTIFIER_PATTERN.fullmatch(cleaned):
        raise ValueError(
            "identifiers must begin with a lowercase letter and contain "
            "only lowercase letters, numbers, and underscores"
        )
    return cleaned


def _nonblank(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("text must not be blank")
    return cleaned


def _normalized_alias(value: str) -> str:
    return re.sub(r"[\s_-]+", " ", value.casefold()).strip()


class V2EntityDefinition(BaseModel):
    """One stable entity exposed by a v2 position."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    label: str
    aliases: tuple[str, ...] = ()

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("aliases")
    @classmethod
    def validate_aliases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(_nonblank(alias) for alias in value)
        normalized = tuple(_normalized_alias(alias) for alias in cleaned)

        if len(normalized) != len(set(normalized)):
            raise ValueError("entity aliases must be unique")

        return cleaned


class V2ObservationDefinition(BaseModel):
    """A declarative public observation attached to an entity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    entity_id: str
    public_text: str
    counts_as_primary: bool = False

    @field_validator("id", "entity_id")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("public_text")
    @classmethod
    def validate_public_text(cls, value: str) -> str:
        return _nonblank(value)


class V2PositionDefinition(BaseModel):
    """Minimal v2 position contract for the first vertical slice."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[2]
    id: str
    ordinal: int = Field(ge=0)
    content_key: str
    content_version: str
    title: str
    public_premise: str

    entities: tuple[V2EntityDefinition, ...] = ()
    observations: tuple[V2ObservationDefinition, ...] = ()
    initial_visible_entity_ids: tuple[str, ...] = ()

    @field_validator("id", "content_key")
    @classmethod
    def validate_identifiers(cls, value: str) -> str:
        return _identifier(value)

    @field_validator("content_version", "title", "public_premise")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _nonblank(value)

    @field_validator("initial_visible_entity_ids")
    @classmethod
    def validate_visible_entity_ids(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        cleaned = tuple(_identifier(entity_id) for entity_id in value)

        if len(cleaned) != len(set(cleaned)):
            raise ValueError("initial visible entity IDs must be unique")

        return cleaned

    @model_validator(mode="after")
    def validate_internal_references(self) -> Self:
        entity_ids = tuple(entity.id for entity in self.entities)

        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("entity IDs must be unique within a position")

        observation_ids = tuple(observation.id for observation in self.observations)

        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("observation IDs must be unique within a position")

        known_entities = set(entity_ids)

        for observation in self.observations:
            if observation.entity_id not in known_entities:
                raise ValueError(
                    f"observation {observation.id!r} references unknown entity "
                    f"{observation.entity_id!r}"
                )

        unknown_visible = set(self.initial_visible_entity_ids) - known_entities
        if unknown_visible:
            raise ValueError(
                "initial visibility references unknown entities: "
                + ", ".join(sorted(unknown_visible))
            )

        alias_owners: dict[str, str] = {}

        for entity in self.entities:
            terms = (entity.id, entity.label, *entity.aliases)

            for term in terms:
                normalized = _normalized_alias(term)
                previous_owner = alias_owners.get(normalized)

                if previous_owner is not None and previous_owner != entity.id:
                    raise ValueError(
                        f"ambiguous entity alias {term!r} is shared by "
                        f"{previous_owner!r} and {entity.id!r}"
                    )

                alias_owners[normalized] = entity.id

        return self
