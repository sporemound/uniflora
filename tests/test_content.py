from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from uniflora.content.loader import ContentValidationError, PuzzleRegistry
from uniflora.content.schema import (
    CANONICAL_REMEDIATION_HIERARCHY,
    PositionStatus,
    PuzzleDefinition,
)
from uniflora.content.validation import validate_packaged_content
from uniflora.narration import FallbackNarrator
PUZZLES_ROOT = (
    Path(__file__).parents[1]
    / "src"
    / "uniflora"
    / "content"
    / "puzzles"
)

requires_legacy_puzzles = pytest.mark.skipif(
    not PUZZLES_ROOT.is_dir(),
    reason="Legacy v1 packaged puzzles are not included in this source-review distribution.",
)

CORE_PROVISION_COUNTERS = {
    "saturation",
    "viability",
    "containment",
    "evidence",
    "source_reduction",
    "throughput",
    "extraction",
    "public_benefit",
    "burden",
}
PROVISION_PROPOSAL_KINDS = {
    3: "reciprocity",
    4: "remediation_protocol",
    5: "memory_archive",
    6: "reconstruction",
}
POSITION_FOUR_CYCLE = (
    "inspect_discharge",
    "identify_contaminant_class",
    "verify_fungal_compatibility",
    "maintain_or_inoculate_bed",
    "regulate_flow_and_contact_time",
    "sample_upstream_and_downstream",
    "evaluate_evidence",
    "rest_or_replace_saturated_substrate",
    "contain_spent_material",
    "reassess_production_limits",
)

@requires_legacy_puzzles
def test_packaged_content_defines_complete_positions_zero_through_six() -> None:
    puzzles_root = (
        Path(__file__).parents[1]
        / "src"
        / "uniflora"
        / "content"
        / "puzzles"
    )

    if not puzzles_root.is_dir():
        pytest.skip(
            "Legacy v1 packaged puzzles are not included in this source-review distribution."
        )
    registry = PuzzleRegistry.load_packaged()
    definitions = registry.all()
    assert [item.position for item in definitions] == list(range(7))
    assert all(item.status is PositionStatus.COMPLETE for item in definitions)
    assert all(item.expansion is None for item in definitions)
    registry.validate_narration_keys(FallbackNarrator().templates)

@requires_legacy_puzzles
def test_complete_provision_arc_positions_preserve_public_safety_invariants() -> None:
    definitions = PuzzleRegistry.load_packaged().all()[3:]
    for definition in definitions:
        arc = definition.provision_arc
        requirements = definition.provision_requirements
        relational = definition.relational_requirements
        confirmation = definition.confirmation
        assert arc is not None
        assert requirements is not None
        assert relational is not None
        assert confirmation is not None
        assert requirements.proposal_kind == PROVISION_PROPOSAL_KINDS[definition.position]
        assert tuple(arc.remediation_hierarchy) == CANONICAL_REMEDIATION_HIERARCHY
        assert CORE_PROVISION_COUNTERS <= (
            set(arc.counter_defaults) | set(arc.target_counter_defaults)
        )
        assert set(requirements.required_actions) <= set(definition.allowed_actions)
        assert requirements.minimum_distinct_users >= 3
        assert requirements.minimum_distinct_functions >= 3
        assert requirements.non_author_confirmation
        assert relational.minimum_distinct_users == requirements.minimum_distinct_users
        assert relational.minimum_distinct_functions == requirements.minimum_distinct_functions
        assert relational.non_author_confirmation
        assert confirmation.non_author_required
        contaminants = {item.id: item for item in arc.contaminant_classes}
        cultures = {item.id: item for item in arc.fungal_cultures}
        assert contaminants
        assert cultures
        assert all(not item.visible_clarity_proves_safety for item in contaminants.values())
        declared_pairs = {
            (contaminant, culture.id)
            for culture in cultures.values()
            for contaminant in culture.compatible_contaminant_classes
        }
        compatible_pairs = {
            (rule.contaminant_class, rule.culture_id)
            for rule in arc.compatibility_rules
            if rule.compatible
        }
        assert compatible_pairs == declared_pairs
        assert all(contaminants[item[0]].biological_treatment_eligible for item in compatible_pairs)

    assert definitions[1].provision_requirements is not None
    assert definitions[1].provision_requirements.maintenance_cycle_steps == POSITION_FOUR_CYCLE


def test_position_zero_has_required_non_obvious_network_shape() -> None:
    definition = PuzzleRegistry.load_packaged().get(0)
    assert len(definition.entities) >= 5
    assert len(definition.observations) >= 5
    assert definition.relational_requirements is not None
    assert definition.relational_requirements.minimum_distinct_users == 3
    assert definition.sustainability is not None
    assert definition.sustainability.minimum_donor_reserve == 4
    assert definition.sustainability.minimum_recipient_viability == 6
    assert definition.confirmation is not None
    assert definition.confirmation.non_author_required
    assert definition.orientation is not None
    assert "full network layout" in definition.orientation.prohibited_automatic_reveals
    assert "awaken_vessel" in definition.allowed_actions
    assert "/interior act awaken" in definition.public_premise
    reveal = definition.triggered_presentations[0]
    assert reveal.id == "route_03_settlement_vista"
    assert reveal.condition.counter == "repair"
    assert reveal.condition.target == "damaged_circulation"
    assert reveal.condition.minimum == 1


def test_position_one_presentation_asset_and_introduction_are_packaged() -> None:
    definition = PuzzleRegistry.load_packaged().get(1)
    assert definition.presentation is not None
    assert (
        definition.presentation.image_asset
        == "assets/position_1_interrupted_current_atmosphere.png"
    )
    assert definition.presentation.additional_images == ()
    assert "## POSITION 1 — THE INTERRUPTED CURRENT" in definition.presentation.introduction
    assert "/interior accessibility" in definition.presentation.introduction
    assert "/interior chart" in definition.presentation.introduction

    command_help = definition.accessibility.explicit_command_help
    assert len(command_help) <= 6
    assert any("Discover:" in item for item in command_help)
    assert any("Coordinate:" in item for item in command_help)
    assert any("/interior chart" in item for item in command_help)
    assert set(definition.accessibility.accepted_input_modes) == {
        "natural_language",
        "explicit_command",
    }


def test_position_one_guide_art_covers_every_command_and_entity() -> None:
    root = Path(__file__).parents[1]
    guide_names = (
        "position_1_guide_1_discover",
        "position_1_guide_2_coordinate",
        "position_1_guide_3_propose",
        "position_1_guide_4_branch",
        "position_1_guide_5_tactical",
        "position_1_guide_6_aliases",
    )
    sources = []
    for page, name in enumerate(guide_names, start=1):
        source = (root / "design" / "sources" / f"{name}.svg").read_text(encoding="utf-8")
        assert f"page {page} of 6" in source
        sources.append(source)

        png = root / "src" / "uniflora" / "content" / "assets" / f"{name}.png"
        header = png.read_bytes()[:24]
        assert header[:8] == b"\x89PNG\r\n\x1a\n"
        assert int.from_bytes(header[16:20], "big") == 3200
        assert int.from_bytes(header[20:24], "big") == 2400

    combined = "\n".join(sources)
    proposal_guides = "\n".join(sources[2:5])
    assert "inspectable labels from the public map" in sources[0]
    assert "Shaded Planting Surface" in sources[0]
    assert "Inspection replaces each unresolved map cue" in sources[0]
    assert "revision_trigger" in proposal_guides
    assert "No maintenance, reassessment, or branch sentence is required" in proposal_guides
    assert "branch_condition:&lt;text&gt;" not in proposal_guides
    assert "maintenance:&lt;text&gt;" not in proposal_guides
    assert "reassessment:&lt;text&gt;" not in proposal_guides
    expected_command_paths = (
        "/interior position",
        "/interior recall",
        "/interior accessibility",
        "/interior act orient",
        "/interior act observe",
        "/interior act summarize",
        "/interior act connect",
        "/interior act offer",
        "/interior act request-support",
        "/interior act sustain",
        "/interior act relay",
        "/interior act mitigate",
        "/interior act calculate",
        "/interior propose circulation",
        "/interior act branch",
        "/interior act confirm",
        "/interior propose circulation-stack",
        "/interior act stack-react",
        "/interior act stack-resolve",
        "/interior act kicker",
        "/interior act trigger",
    )
    assert all(command in combined for command in expected_command_paths)

    alias_source = sources[-1]
    expected_entity_ids = (
        "northern_reservoir",
        "eastern_growth",
        "central_relay",
        "pale_nursery",
        "lower_archive_bed",
        "condensation_veil",
        "route_07",
        "route_11",
        "return_channel",
        "first_bloom_basin",
        "production_intake_channel",
        "warm_return_channel",
        "return_indicator_bed",
        "spent_indicator_hold",
    )
    assert all(entity_id in alias_source for entity_id in expected_entity_ids)


    @pytest.mark.legacy_content
    def test_all_positions_use_concise_inference_first_accessibility() -> None:
        registry = PuzzleRegistry.load_packaged()
        for position in range(7):
            definition = registry.get(position)
            accessibility = definition.accessibility
            assert set(accessibility.accepted_input_modes) == {
                "natural_language",
                "explicit_command",
            }
            assert len(accessibility.explicit_command_help) <= 6
            assert "recall" in accessibility.summary.lower()
            assert "chart" in accessibility.summary.lower()
            assert definition.orientation is not None
            assert any(
                cue in definition.orientation.specificity_invitation.lower()
                for cue in ("name", "ask", "inspect")
            )


def test_position_two_presentation_asset_and_introduction_are_packaged() -> None:
    definition = PuzzleRegistry.load_packaged().get(2)
    assert definition.content_version == "2.1.1"
    assert definition.presentation is not None
    assert definition.presentation.image_asset == "assets/position_2_translation.png"
    assert "## POSITION 2 — TRANSLATION" in definition.presentation.introduction
    assert "/interior accessibility" in definition.presentation.introduction


def test_provision_schema_rejects_noncanonical_remediation_hierarchy() -> None:
    raw = PuzzleRegistry.load_packaged().get(3).model_dump(mode="json")
    hierarchy = raw["provision_arc"]["remediation_hierarchy"]
    hierarchy[0], hierarchy[1] = hierarchy[1], hierarchy[0]
    with pytest.raises(ValidationError, match="canonical nine-layer order"):
        PuzzleDefinition.model_validate(raw)

    raw = PuzzleRegistry.load_packaged().get(3).model_dump(mode="json")
    raw["provision_arc"]["remediation_hierarchy"] = []
    with pytest.raises(ValidationError, match="canonical nine-layer order"):
        PuzzleDefinition.model_validate(raw)


def test_provision_schema_rejects_ineligible_or_mismatched_compatibility_rules() -> None:
    raw = PuzzleRegistry.load_packaged().get(4).model_dump(mode="json")
    mixed_rule = next(
        item
        for item in raw["provision_arc"]["compatibility_rules"]
        if item["contaminant_class"] == "mixed_unknown_discharge"
    )
    mixed_rule["compatible"] = True
    with pytest.raises(ValidationError, match="ineligible contaminants"):
        PuzzleDefinition.model_validate(raw)

    raw = PuzzleRegistry.load_packaged().get(4).model_dump(mode="json")
    compatible_rule = next(
        item for item in raw["provision_arc"]["compatibility_rules"] if item["compatible"]
    )
    compatible_rule["compatible"] = False
    with pytest.raises(ValidationError, match="compatibility must match"):
        PuzzleDefinition.model_validate(raw)

    raw = PuzzleRegistry.load_packaged().get(4).model_dump(mode="json")
    raw["provision_arc"]["compatibility_rules"].pop()
    with pytest.raises(ValidationError, match="explicitly cover every"):
        PuzzleDefinition.model_validate(raw)


def test_provision_schema_rejects_unknown_negative_or_missing_core_counters() -> None:
    raw = PuzzleRegistry.load_packaged().get(3).model_dump(mode="json")
    raw["provision_arc"]["counter_defaults"]["instant_cleanup"] = 1
    with pytest.raises(ValidationError, match="unknown Provision Works counters"):
        PuzzleDefinition.model_validate(raw)

    raw = PuzzleRegistry.load_packaged().get(3).model_dump(mode="json")
    raw["provision_arc"]["counter_defaults"]["burden"] = -1
    with pytest.raises(ValidationError, match="must be nonnegative"):
        PuzzleDefinition.model_validate(raw)

    raw = PuzzleRegistry.load_packaged().get(3).model_dump(mode="json")
    del raw["provision_arc"]["counter_defaults"]["burden"]
    with pytest.raises(ValidationError, match="initialize every core public counter"):
        PuzzleDefinition.model_validate(raw)

    raw = PuzzleRegistry.load_packaged().get(3).model_dump(mode="json")
    raw["provision_arc"]["target_counter_defaults"]["containment"] = {"white_rot_beds": 1}
    with pytest.raises(ValidationError, match="all other Provision Works counters must be scalar"):
        PuzzleDefinition.model_validate(raw)


def test_provision_schema_requires_required_actions_to_be_allowed() -> None:
    raw = PuzzleRegistry.load_packaged().get(3).model_dump(mode="json")
    required_action = raw["provision_requirements"]["required_actions"][0]
    raw["allowed_actions"].remove(required_action)
    with pytest.raises(ValidationError, match="required actions must be allowed"):
        PuzzleDefinition.model_validate(raw)


def test_position_four_schema_requires_exact_ordered_maintenance_cycle() -> None:
    raw = PuzzleRegistry.load_packaged().get(4).model_dump(mode="json")
    cycle = raw["provision_requirements"]["maintenance_cycle_steps"]
    cycle[2], cycle[3] = cycle[3], cycle[2]
    with pytest.raises(ValidationError, match="canonical ordered maintenance cycle"):
        PuzzleDefinition.model_validate(raw)


def test_schema_rejects_ambiguous_aliases() -> None:
    raw = PuzzleRegistry.load_packaged().get(0).model_dump(mode="json")
    raw["entities"][1]["aliases"].append("north")
    with pytest.raises(ValidationError, match="ambiguous"):
        PuzzleDefinition.model_validate(raw)

    raw = PuzzleRegistry.load_packaged().get(0).model_dump(mode="json")
    raw["entities"][1]["discovery_label"] = "north"
    with pytest.raises(ValidationError, match="ambiguous"):
        PuzzleDefinition.model_validate(raw)


def test_schema_requires_discovery_labels_for_every_observation_entity() -> None:
    raw = PuzzleRegistry.load_packaged().get(0).model_dump(mode="json")
    raw["entities"][0]["discovery_label"] = None

    with pytest.raises(ValidationError, match="require spoiler-safe discovery labels"):
        PuzzleDefinition.model_validate(raw)


def test_loader_rejects_malformed_yaml(tmp_path: Path) -> None:
    (tmp_path / "position_0.yaml").write_text("position: [not valid", encoding="utf-8")
    with pytest.raises(ContentValidationError, match="invalid puzzle file"):
        PuzzleRegistry.load_directory(tmp_path)


def test_loader_rejects_missing_position_presentation_asset(tmp_path: Path) -> None:
    content = Path(__file__).parents[1] / "src" / "uniflora" / "content"
    source = content / "puzzles"
    puzzles = tmp_path / "puzzles"
    puzzles.mkdir()
    for item in source.glob("*.yaml"):
        (puzzles / item.name).write_text(item.read_text(encoding="utf-8"), encoding="utf-8")
    assets = tmp_path / "assets"
    assets.mkdir()
    route_reveal = content / "assets" / "route_03_settlement_vista.png"
    (assets / route_reveal.name).write_bytes(route_reveal.read_bytes())
    with pytest.raises(ContentValidationError, match="missing Position 1 presentation asset"):
        PuzzleRegistry.load_directory(puzzles)


@pytest.mark.asyncio
async def test_content_validation_runs_isolated_complete_position_simulations() -> None:
    report = await validate_packaged_content()
    assert report.valid
    assert "positions 0-6 pass strict YAML schema validation" in report.checks
    assert "isolated three-participant Position 0 simulation completes" in report.checks
    assert "isolated four-participant slash-only Position 1 simulation completes" in report.checks
    assert "isolated slash-only Position 2 translation simulation completes" in report.checks
