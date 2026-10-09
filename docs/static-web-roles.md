# Permanent roles for the web campaign

The web campaign uses three roles for all seven positions. A participant chooses one role once; it remains attached to that player for the entire investigation. Multiple participants may hold the same role. All three roles have work at each of the six facilities.

| Role ID | Display name | Main responsibility | Gated actions |
| --- | --- | --- | ---: |
| `evidence_investigator` | Evidence Investigator | Gather records, operate instruments, preserve direct observations | 22 |
| `systems_analyst` | Systems Analyst | Compare measurements, model alternatives, reconstruct patterns | 21 |
| `independent_reviewer` | Independent Reviewer | Audit provenance, calibration, uncertainty, and claims | 20 |

The 38 old position functions remain useful as task names in descriptions and action titles. They map to permanent roles as follows:

| Facility | Evidence Investigator | Systems Analyst | Independent Reviewer |
| --- | --- | --- | --- |
| Boundary Array | Field Observer; Instrument Operator | Atmospheric Analyst; Signal Correlator | Protocol Auditor |
| Aeronautical Incident Center | Controller Records Analyst; Pilot Testimony Analyst; Operational Sensor Auditor; Navigation Records Examiner | Incident Reconstructor | Independent Verifier |
| Aerial Phenomena Archive | Records Custodian; Witness Analyst | Terminology Historian; Recurrence Cartographer | Provenance Auditor; Archive Independent Reviewer |
| Holography Laboratory | Reconstruction Technician; Phase Registration Analyst | Constraint Integration Analyst | Optical Systems Auditor; Artifact Validation Specialist; Independent Reconstruction Reviewer |
| Subsurface Resonance Station | Seismic Array Analyst; Borehole Acoustics Analyst; Hydrogeology and Infrastructure Examiner | Geological Context Specialist; Distributed Mode Analyst | Electromagnetic Coupling Auditor; Independent Geophysical Reviewer |
| Quantum State Institute | State Preparation Operator; Readout Calibration Auditor | Measurement Basis Analyst; Cross-Location Synthesis Analyst; Tomography Estimator | Uncertainty Quantification Analyst; Measurement Ethics Reviewer; Independent State Reviewer |

The engine still requires a person other than the author to confirm an assessment or review a finding. The six major operations each require a separate supporter. A crew with one participant in each permanent role can perform every role-gated action and satisfy those independent-person checks. The Reviewer role does not, by itself, replace the separate-person requirement.

## Stream compatibility

`load_missing_interior_pack()` still loads the original `missing_interior` 2.0 pack and its 38 temporary functions. Existing Discord streams retain their old role assignment, release, and position-completion events. `load_missing_interior_static_pack()` derives the 2.1 `missing_interior_static_roles` pack for new web streams. The distinct pack ID makes the existing application service reject opening a stream under the wrong role rules. An old stream must be finished under 2.0 or migrated through an explicit, audited conversion before it can continue with permanent roles. Do not change its pack ID or rewrite its event history in place.

For new streams, the three roles have arc scope and no facility restriction. Role selection is recorded as the existing `role_assigned` event. Normal release and reassignment are rejected; crossing a position boundary keeps the role. Investigative actions require a chosen role; joining and beginning the investigation remain available before selection. This gives every authenticated web participant a stable role while preserving event replay.
