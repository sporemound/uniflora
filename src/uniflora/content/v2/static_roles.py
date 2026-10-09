"""Whole-campaign roles for the web investigation.

The original position functions remain in the 2.0 pack for existing streams.
This module derives a separately identified 2.1 pack without rewriting that
content or its event history. The old function names remain action titles and
descriptions; only their mechanical prerequisites become permanent roles.
"""

from __future__ import annotations

from types import MappingProxyType

from uniflora.content.v2.investigation_schema import V2InvestigationPack, V2RoleDefinition

STATIC_ROLES_PACK_ID = "missing_interior_static_roles"
STATIC_ROLES_CONTENT_VERSION = "2.1.0-static-roles"

EVIDENCE_INVESTIGATOR = "evidence_investigator"
SYSTEMS_ANALYST = "systems_analyst"
INDEPENDENT_REVIEWER = "independent_reviewer"

_ROLE_GROUPS = {
    EVIDENCE_INVESTIGATOR: (
        "field_observer",
        "instrument_operator",
        "controller_records_analyst",
        "pilot_testimony_analyst",
        "operational_sensor_auditor",
        "navigation_records_examiner",
        "records_custodian",
        "witness_analyst",
        "reconstruction_technician",
        "phase_registration_analyst",
        "seismic_array_analyst",
        "borehole_acoustics_analyst",
        "hydrogeology_infrastructure_examiner",
        "state_preparation_operator",
        "readout_calibration_auditor",
    ),
    SYSTEMS_ANALYST: (
        "atmospheric_analyst",
        "signal_correlator",
        "incident_reconstructor",
        "terminology_historian",
        "recurrence_cartographer",
        "constraint_integration_analyst",
        "geological_context_specialist",
        "distributed_mode_analyst",
        "measurement_basis_analyst",
        "cross_location_synthesis_analyst",
        "tomography_estimator",
    ),
    INDEPENDENT_REVIEWER: (
        "protocol_auditor",
        "independent_verifier",
        "provenance_auditor",
        "archive_independent_reviewer",
        "optical_systems_auditor",
        "artifact_validation_specialist",
        "independent_reconstruction_reviewer",
        "electromagnetic_coupling_auditor",
        "independent_geophysical_reviewer",
        "uncertainty_quantification_analyst",
        "measurement_ethics_reviewer",
        "independent_state_reviewer",
    ),
}

LEGACY_FUNCTION_TO_STATIC_ROLE = MappingProxyType(
    {
        function_id: role_id
        for role_id, function_ids in _ROLE_GROUPS.items()
        for function_id in function_ids
    }
)

STATIC_ROLES = (
    V2RoleDefinition(
        id=EVIDENCE_INVESTIGATOR,
        name="Evidence Investigator",
        scope="arc",
        description=(
            "Collects direct records, maintains instruments, and documents what was observed."
        ),
        allow_player_defined_name=False,
        allow_player_defined_description=False,
    ),
    V2RoleDefinition(
        id=SYSTEMS_ANALYST,
        name="Systems Analyst",
        scope="arc",
        description=(
            "Compares measurements, models competing explanations, and reconstructs patterns."
        ),
        allow_player_defined_name=False,
        allow_player_defined_description=False,
    ),
    V2RoleDefinition(
        id=INDEPENDENT_REVIEWER,
        name="Independent Reviewer",
        scope="arc",
        description=(
            "Checks provenance, uncertainty, alternatives, and whether conclusions "
            "exceed the evidence."
        ),
        allow_player_defined_name=False,
        allow_player_defined_description=False,
    ),
)


def build_static_roles_pack(legacy_pack: V2InvestigationPack) -> V2InvestigationPack:
    """Derive the immutable-role pack while retaining every non-role rule."""

    legacy_ids = {role.id for role in legacy_pack.roles}
    if legacy_ids != set(LEGACY_FUNCTION_TO_STATIC_ROLE):
        missing = sorted(legacy_ids - set(LEGACY_FUNCTION_TO_STATIC_ROLE))
        extra = sorted(set(LEGACY_FUNCTION_TO_STATIC_ROLE) - legacy_ids)
        raise ValueError(f"static role mapping is incomplete: missing={missing}, extra={extra}")

    actions = []
    for action in legacy_pack.actions:
        prerequisites = action.prerequisites
        mapped_roles = tuple(
            dict.fromkeys(
                LEGACY_FUNCTION_TO_STATIC_ROLE[role_id]
                for role_id in prerequisites.required_role_ids
            )
        )
        actions.append(
            action.model_copy(
                update={
                    "prerequisites": prerequisites.model_copy(
                        update={"required_role_ids": mapped_roles}
                    )
                }
            )
        )

    static_pack = legacy_pack.model_copy(
        update={
            "pack": legacy_pack.pack.model_copy(
                update={
                    "id": STATIC_ROLES_PACK_ID,
                    "content_version": STATIC_ROLES_CONTENT_VERSION,
                }
            ),
            "roles": STATIC_ROLES,
            "actions": tuple(actions),
        }
    )
    return V2InvestigationPack.model_validate(static_pack.model_dump(mode="python"))
